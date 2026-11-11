import test from 'node:test';
import assert from 'node:assert/strict';
import { runQueue, runScheduled } from './worker.mjs';

const env = { REINK_API_ORIGIN: 'https://api.example.test', REINK_WORKER_TOKEN: 'w'.repeat(32), LANDINGAI_PARSE_MODEL: 'parse-v1', LANDINGAI_EXTRACT_MODEL: 'extract-v1' };
const dispatch = { schema_version: '1', operation: 'extract_reinsurance_contract', job_id: 'job-1', attempt_id: 'attempt-1', capability: 'signed' };
const json = value => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } });
const message = () => ({ body: dispatch, acked: false, retried: false, ack() { this.acked = true; }, retry() { this.retried = true; } });

test('processes a queue delivery through authenticated backend and LandingAI without exposing the key in the event', async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init]);
    if (url.endsWith('/claim')) return json({ decision: 'start', checkpoint_token: 'claim-token' });
    if (url.endsWith('/credential')) return json({ api_key: 'customer-secret' });
    if (url.endsWith('/document')) return new Response('%PDF-fake', { headers: { 'content-type': 'application/pdf' } });
    if (url.endsWith('/ade/parse')) return json({ markdown: 'Treaty', chunks: [], grounding: {}, metadata: { version: 'parse-v1' } });
    if (url.endsWith('/ade/extract')) {
      const schema = JSON.parse(init.body.get('schema'));
      assert.ok(schema.properties.cedant_name);
      assert.equal(schema.properties.contract_data, undefined);
      return json({ extraction: { contract_name: 'Treaty', contract_type: 'Treaty', cedant_name: 'Cedant', reinsurer_name: 'Reinsurer' }, metadata: { version: 'extract-v1' } });
    }
    if (url.endsWith('/checkpoint')) {
      assert.equal(init.headers['X-Checkpoint-Token'], 'claim-token');
      assert.equal(JSON.stringify(init.body).includes('customer-secret'), false);
      assert.equal(JSON.parse(init.body).result.contract_data.contract_name, 'Treaty');
      return json({ stored: true });
    }
    if (url.endsWith('/deliver')) return json({ schema_version: '1', event_id: 'terminal', status: 'acknowledged' });
    throw new Error('unexpected URL');
  };
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl);
  assert.equal(item.acked, true);
  assert.equal(item.retried, false);
  assert.equal(calls.filter(([url]) => url.endsWith('/ade/parse')).length, 1);
  for (const [url, init] of calls.filter(([url]) => url.startsWith(env.REINK_API_ORIGIN))) {
    assert.equal(init.headers['X-Dispatch-Capability'], 'signed');
    assert.equal(init.headers.Authorization, `Bearer ${env.REINK_WORKER_TOKEN}`);
  }
});

test('worker retries instead of acknowledging when configuration is missing', async () => {
  const item = message();
  await runQueue({ messages: [item] }, {}, async () => { throw new Error('should not call'); });
  assert.equal(item.retried, true);
  assert.equal(item.acked, false);
});

test('an oversized document is rejected before any provider call', async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init]);
    if (url.endsWith('/claim')) return json({ decision: 'start', checkpoint_token: 'claim-token' });
    if (url.endsWith('/credential')) return json({ api_key: 'customer-secret' });
    if (url.endsWith('/document')) return new Response('x', { headers: { 'content-type': 'application/pdf', 'content-length': String(6 * 1024 * 1024) } });
    if (url.endsWith('/checkpoint')) { assert.equal(JSON.parse(init.body).status, 'failed'); return json({ stored: true }); }
    if (url.endsWith('/deliver')) return json({ schema_version: '1', event_id: 'terminal', status: 'acknowledged' });
    throw new Error('unexpected URL');
  };
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl);
  assert.equal(item.acked, true);
  assert.equal(calls.some(([url]) => url.startsWith('https://api.va.landing.ai/')), false);
});

test('scheduled maintenance calls three fixed backend endpoints with separate credentials', async () => {
  const calls = [];
  const config = { REINK_API_ORIGIN: env.REINK_API_ORIGIN, REINK_DISPATCH_SCHEDULER_TOKEN: 'd'.repeat(32), REINK_EXPIRY_SCHEDULER_TOKEN: 'e'.repeat(32), REINK_CLEANUP_SCHEDULER_TOKEN: 'c'.repeat(32) };
  await runScheduled(config, async (url, init) => {
    calls.push([url, init]);
    return json(url.endsWith('/cloudflare-dispatch') ? { attempted: 1 } : { processed: 2 });
  });
  assert.deepEqual(calls.map(([url]) => url), ['https://api.example.test/api/maintenance/cloudflare-dispatch', 'https://api.example.test/api/maintenance/expiry', 'https://api.example.test/api/maintenance/cleanup']);
  assert.equal(calls[0][1].headers.Authorization, `Bearer ${config.REINK_DISPATCH_SCHEDULER_TOKEN}`);
  assert.equal(calls[1][1].headers.Authorization, `Bearer ${config.REINK_EXPIRY_SCHEDULER_TOKEN}`);
  assert.equal(calls[2][1].headers.Authorization, `Bearer ${config.REINK_CLEANUP_SCHEDULER_TOKEN}`);
  assert.equal(calls.every(([, init]) => init.redirect === 'error'), true);
});

test('scheduled maintenance tries expiry and cleanup even if dispatch fails and reports generic failure', async () => {
  const calls = [];
  const config = { REINK_API_ORIGIN: env.REINK_API_ORIGIN, REINK_DISPATCH_SCHEDULER_TOKEN: 'd'.repeat(32), REINK_EXPIRY_SCHEDULER_TOKEN: 'e'.repeat(32), REINK_CLEANUP_SCHEDULER_TOKEN: 'c'.repeat(32) };
  await assert.rejects(runScheduled(config, async (url) => {
    calls.push(url);
    if (url.endsWith('/cloudflare-dispatch')) throw new Error('private backend detail');
    return json({ processed: 0 });
  }), error => error.message === 'MAINTENANCE_FAILED');
  assert.equal(calls.length, 3);
});

test('scheduled maintenance rejects shared scheduler secrets before making requests', async () => {
  const config = { REINK_API_ORIGIN: env.REINK_API_ORIGIN, REINK_DISPATCH_SCHEDULER_TOKEN: 'd'.repeat(32), REINK_EXPIRY_SCHEDULER_TOKEN: 'e'.repeat(32), REINK_CLEANUP_SCHEDULER_TOKEN: 'e'.repeat(32) };
  let calls = 0;
  await assert.rejects(runScheduled(config, async () => { calls++; }), /MAINTENANCE_FAILED/);
  assert.equal(calls, 0);
});
