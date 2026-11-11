import test from 'node:test';
import assert from 'node:assert/strict';
import { runQueue, runScheduled } from './worker.mjs';

const env = { REINK_API_ORIGIN: 'https://api.example.test', REINK_WORKER_TOKEN: 'w'.repeat(32), LANDINGAI_PARSE_MODEL: 'parse-v1', LANDINGAI_EXTRACT_MODEL: 'extract-v1' };
const dispatch = { schema_version: '1', operation: 'extract_reinsurance_contract', job_id: 'job-1', attempt_id: 'attempt-1', capability: 'signed' };
const json = value => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } });
const options = { sleep: async () => {} };
const message = () => ({ body: dispatch, acked: false, retried: false, ack() { this.acked = true; }, retry() { this.retried = true; } });

test('processes a queue delivery through authenticated backend and LandingAI without exposing the key in the event', async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init]);
    if (url.endsWith('/protocol')) return json({ protocol_version: '2' });
    if (url.endsWith('/claim')) return json({ decision: 'start', checkpoint_token: 'claim-token' });
    if (url.endsWith('/credential')) return json({ api_key: 'customer-secret' });
    if (url.endsWith('/provider-start')) return json({ authorized: true });
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
    if (url.endsWith('/protocol')) return json({ protocol_version: '2' });
    if (url.endsWith('/claim')) return json({ decision: 'start', checkpoint_token: 'claim-token' });
    if (url.endsWith('/credential')) return json({ api_key: 'customer-secret' });
    if (url.endsWith('/provider-start')) return json({ authorized: true });
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
  assert.equal(calls.every(([, init]) => init.redirect === 'manual'), true);
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

function backend(overrides = {}) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init]);
    for (const [suffix, handler] of Object.entries(overrides)) if (url.endsWith(suffix)) { const r = await handler(calls.filter(([u]) => u.endsWith(suffix)).length, init); if (r) return r; }
    if (url.endsWith('/protocol')) return json({ protocol_version: '2' });
    if (url.endsWith('/claim')) return json({ decision: 'start', checkpoint_token: 'claim-token' });
    if (url.endsWith('/credential')) return json({ api_key: 'customer-secret' });
    if (url.endsWith('/provider-start')) return json({ authorized: true });
    if (url.endsWith('/document')) return new Response('%PDF-fake', { headers: { 'content-type': 'application/pdf' } });
    if (url.endsWith('/ade/parse')) return json({ markdown: 'Treaty', chunks: [], grounding: {}, metadata: { version: 'parse-v1' } });
    if (url.endsWith('/ade/extract')) return json({ extraction: { contract_name: 'Treaty', contract_type: 'Treaty', cedant_name: 'Cedant', reinsurer_name: 'Reinsurer' }, metadata: { version: 'extract-v1' } });
    if (url.endsWith('/checkpoint')) return json({ stored: true });
    if (url.endsWith('/deliver')) return json({ schema_version: '1', event_id: 'terminal', status: 'acknowledged' });
    throw new Error('unexpected URL');
  };
  const count = suffix => calls.filter(([url]) => url.endsWith(suffix)).length;
  const checkpointed = () => JSON.parse(calls.find(([url]) => url.endsWith('/checkpoint'))[1].body);
  return { calls, fetchImpl, count, checkpointed };
}

test('every queue-path request carries a timeout signal', async () => {
  const { calls, fetchImpl } = backend();
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl, options);
  assert.equal(item.acked, true);
  assert.equal(calls.length, 9);
  for (const [url, init] of calls) assert.ok(init.signal instanceof AbortSignal, url);
});

test('transient credential and document failures are retried before the single provider call', async () => {
  const { fetchImpl, count, checkpointed } = backend({
    '/credential': n => n === 1 ? new Response('busy', { status: 503 }) : null,
    '/document': n => { if (n === 1) throw new TypeError('network connection lost'); return null; },
  });
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl, options);
  assert.equal(count('/credential'), 2);
  assert.equal(count('/document'), 2);
  assert.equal(count('/ade/parse'), 1);
  assert.equal(checkpointed().status, 'completed');
  assert.equal(item.acked, true);
});

test('a persistent pre-provider outage records a retryable failure without calling the provider', async () => {
  const { calls, fetchImpl, count, checkpointed } = backend({
    '/document': () => { throw new DOMException('timed out', 'TimeoutError'); },
  });
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl, options);
  assert.equal(count('/document'), 3);
  assert.equal(calls.some(([url]) => url.startsWith('https://api.va.landing.ai/')), false);
  assert.deepEqual(checkpointed().error, { code: 'PREPARATION_FAILED', message: 'Document preparation failed before provider processing.', retryable: true });
  assert.equal(item.acked, true);
});

test('a rejected credential request is not retried and is not retryable', async () => {
  const { fetchImpl, count, checkpointed } = backend({ '/credential': () => new Response('gone', { status: 409 }) });
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl, options);
  assert.equal(count('/credential'), 1);
  assert.equal(checkpointed().error.retryable, false);
});

test('provider failures are never retried by the worker', async () => {
  const { fetchImpl, count, checkpointed } = backend({ '/ade/parse': () => new Response('busy', { status: 503 }) });
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl, options);
  assert.equal(count('/ade/parse'), 1);
  assert.equal(count('/ade/extract'), 0);
  assert.deepEqual(checkpointed().error, { code: 'EXTRACTION_FAILED', message: 'Document extraction failed.', retryable: false });
  assert.equal(item.acked, true);
});

test('a transient checkpoint failure is retried with the same token and event', async () => {
  const { calls, fetchImpl, count } = backend({ '/checkpoint': n => n === 1 ? new Response('busy', { status: 502 }) : null });
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl, options);
  const checkpoints = calls.filter(([url]) => url.endsWith('/checkpoint'));
  assert.equal(checkpoints.length, 2);
  assert.equal(checkpoints[0][1].body, checkpoints[1][1].body);
  assert.equal(checkpoints[1][1].headers['X-Checkpoint-Token'], 'claim-token');
  assert.equal(count('/ade/parse'), 1);
  assert.equal(item.acked, true);
});

test('scheduled maintenance logs which route failed with status or error type only', async () => {
  const config = { REINK_API_ORIGIN: env.REINK_API_ORIGIN, REINK_DISPATCH_SCHEDULER_TOKEN: 'd'.repeat(32), REINK_EXPIRY_SCHEDULER_TOKEN: 'e'.repeat(32), REINK_CLEANUP_SCHEDULER_TOKEN: 'c'.repeat(32) };
  const lines = [];
  await assert.rejects(runScheduled(config, async (url) => {
    if (url.endsWith('/cloudflare-dispatch')) throw new TypeError('private backend detail');
    if (url.endsWith('/expiry')) return new Response('{"detail":"nope"}', { status: 401 });
    return json({ processed: 0 });
  }, line => lines.push(line)), /MAINTENANCE_FAILED/);
  assert.deepEqual(lines.map(line => JSON.parse(line)), [
    { event: 'maintenance_failed', route: 'cloudflare-dispatch', error: 'TypeError' },
    { event: 'maintenance_failed', route: 'expiry', status: 401 },
  ]);
  assert.equal(lines.some(line => line.includes('private') || line.includes('d'.repeat(32)) || line.includes('nope')), false);
});

test('scheduled maintenance logs configuration failures without values', async () => {
  const lines = [];
  const config = { REINK_API_ORIGIN: env.REINK_API_ORIGIN, REINK_DISPATCH_SCHEDULER_TOKEN: 'short', REINK_EXPIRY_SCHEDULER_TOKEN: 'e'.repeat(32), REINK_CLEANUP_SCHEDULER_TOKEN: 'c'.repeat(32) };
  await assert.rejects(runScheduled(config, async () => json({}), line => lines.push(line)), /MAINTENANCE_FAILED/);
  assert.deepEqual(lines.map(line => JSON.parse(line)), [{ event: 'maintenance_failed', reason: 'INVALID_SECRETS' }]);
});

test('scheduled maintenance works under the Workers fetch, which rejects redirect "error"', async () => {
  const config = { REINK_API_ORIGIN: env.REINK_API_ORIGIN, REINK_DISPATCH_SCHEDULER_TOKEN: 'd'.repeat(32), REINK_EXPIRY_SCHEDULER_TOKEN: 'e'.repeat(32), REINK_CLEANUP_SCHEDULER_TOKEN: 'c'.repeat(32) };
  const workersFetch = async (url, init) => {
    if (init.redirect === 'error') throw new TypeError('Invalid redirect value');
    return json(url.endsWith('/cloudflare-dispatch') ? { attempted: 0 } : { processed: 0 });
  };
  await runScheduled(config, workersFetch, () => {});
});

test('scheduled maintenance treats a redirect as failure instead of following it', async () => {
  const config = { REINK_API_ORIGIN: env.REINK_API_ORIGIN, REINK_DISPATCH_SCHEDULER_TOKEN: 'd'.repeat(32), REINK_EXPIRY_SCHEDULER_TOKEN: 'e'.repeat(32), REINK_CLEANUP_SCHEDULER_TOKEN: 'c'.repeat(32) };
  const lines = [];
  await assert.rejects(runScheduled(config, async (url) => url.endsWith('/expiry')
    ? new Response(null, { status: 302, headers: { Location: 'https://elsewhere.example/' } })
    : json(url.endsWith('/cloudflare-dispatch') ? { attempted: 0 } : { processed: 0 }), line => lines.push(line)), /MAINTENANCE_FAILED/);
  assert.deepEqual(lines.map(line => JSON.parse(line)), [{ event: 'maintenance_failed', route: 'expiry', status: 302 }]);
});


test('provider authorization happens after preparation and before any provider request', async () => {
  const { calls, fetchImpl, count } = backend({ '/provider-start': () => json({ authorized: true }) });
  await runQueue({ messages: [message()] }, env, fetchImpl, options);
  assert.equal(count('/provider-start'), 1);
  const urls = calls.map(([url]) => url);
  assert.ok(urls.findIndex(url => url.endsWith('/document')) < urls.findIndex(url => url.endsWith('/provider-start')));
  assert.ok(urls.findIndex(url => url.endsWith('/provider-start')) < urls.findIndex(url => url.endsWith('/ade/parse')));
});

test('ambiguous provider authorization is never retried and checkpoints a terminal failure', async () => {
  const { fetchImpl, count, checkpointed } = backend({ '/provider-start': () => { throw new TypeError('lost authorization response'); } });
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl, options);
  assert.equal(count('/provider-start'), 1);
  assert.equal(count('/ade/parse'), 0);
  assert.equal(checkpointed().error.retryable, false);
  assert.equal(item.acked, true);
});

for (const response of [() => new Response('missing', { status: 404 }), () => json({ protocol_version: '1' })]) {
  test('incompatible backend refuses work before claim or provider calls', async () => {
    const { fetchImpl, count } = backend({ '/protocol': response });
    const item = message();
    await runQueue({ messages: [item] }, env, fetchImpl, options);
    assert.equal(count('/claim'), 0);
    assert.equal(count('/provider-start'), 0);
    assert.equal(count('/ade/parse'), 0);
    assert.equal(item.retried, true);
  });
}

test('trial capacity denial is a retryable pre-provider failure', async () => {
  const { fetchImpl, count, checkpointed } = backend({ '/provider-start': () => new Response('capacity', { status: 429 }) });
  const item = message();
  await runQueue({ messages: [item] }, env, fetchImpl, options);
  assert.equal(count('/provider-start'), 1);
  assert.equal(count('/ade/parse'), 0);
  assert.deepEqual(checkpointed().error, { code: 'TRIAL_CAPACITY_UNAVAILABLE', message: 'Free extractions are temporarily unavailable. Add a LandingAI key or try again later.', retryable: true });
  assert.equal(item.acked, true);
});
