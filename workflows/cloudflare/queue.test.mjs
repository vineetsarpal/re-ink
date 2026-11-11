import test from 'node:test';
import assert from 'node:assert/strict';
import { consumeBatch } from './queue.mjs';

function message(body) {
  return { body, acknowledged: false, retried: false,
    ack() { this.acknowledged = true; },
    retry() { this.retried = true; } };
}
const dispatch = { schema_version: '1', operation: 'extract_reinsurance_contract', job_id: 'job-1', attempt_id: 'attempt-1', capability: 'signed-capability' };

test('invalid queue messages are acknowledged without running extraction', async () => {
  const item = message({ job_id: 'job', api_key: 'secret' });
  let calls = 0;
  await consumeBatch({ messages: [item] }, { claim: async () => { calls++; } });
  assert.equal(calls, 0);
  assert.equal(item.acknowledged, true);
  assert.equal(item.retried, false);
});

test('a claimed extraction is checkpointed before delivery and acknowledged after delivery', async () => {
  const item = message(dispatch);
  const calls = [];
  await consumeBatch({ messages: [item] }, {
    claim: async () => ({ decision: 'start', checkpoint_token: 'one-time-secret' }),
    extract: async (_, token) => { assert.equal(token, 'one-time-secret'); return { contract_data: { contract_name: 'Treaty' }, parties_data: [] }; },
    checkpoint: async (_, token, event) => { assert.equal(token, 'one-time-secret'); calls.push(['checkpoint', event]); return true; },
    deliver: async (event, incoming) => { assert.equal(incoming.capability, 'signed-capability'); calls.push(['deliver', event]); return true; },
  });
  assert.deepEqual(calls.map(c => c[0]), ['checkpoint', 'deliver']);
  assert.equal(calls[0][1].status, 'completed');
  assert.equal(calls[0][1].event_id, 'terminal');
  assert.deepEqual(calls[0][1], calls[1][1]);
  assert.equal(item.acknowledged, true);
});

test('redelivery after callback failure delivers the checkpoint without repeating provider work', async () => {
  let saved;
  let extractions = 0;
  let deliveries = 0;
  const services = {
    claim: async () => saved ? { decision: 'terminal', event: saved } : { decision: 'start', checkpoint_token: 'one-time-secret' },
    extract: async () => { extractions++; return { contract_data: { contract_name: 'Treaty' }, parties_data: [] }; },
    checkpoint: async (_, token, event) => { assert.equal(token, 'one-time-secret'); saved = event; return true; },
    deliver: async () => ++deliveries > 1,
  };
  const first = message(dispatch);
  await consumeBatch({ messages: [first] }, services);
  assert.equal(first.retried, true);
  const second = message(dispatch);
  await consumeBatch({ messages: [second] }, services);
  assert.equal(second.acknowledged, true);
  assert.equal(extractions, 1);
  assert.equal(deliveries, 2);
});

test('an in-progress claim never starts another provider call', async () => {
  const item = message(dispatch);
  let calls = 0;
  await consumeBatch({ messages: [item] }, {
    claim: async () => ({ decision: 'in_progress' }),
    extract: async () => { calls++; },
  });
  assert.equal(calls, 0);
  assert.equal(item.retried, true);
});

test('closed attempts are acknowledged without a provider call', async () => {
  const item = message(dispatch);
  let calls = 0;
  await consumeBatch({ messages: [item] }, {
    claim: async () => ({ decision: 'closed' }),
    extract: async () => { calls++; },
  });
  assert.equal(calls, 0);
  assert.equal(item.acknowledged, true);
});

test('provider errors produce a safe failure rather than leaking error details', async () => {
  const item = message(dispatch);
  let received;
  await consumeBatch({ messages: [item] }, {
    claim: async () => ({ decision: 'start', checkpoint_token: 'one-time-secret' }),
    extract: async () => { throw new Error('private secret and document text'); },
    checkpoint: async (_, token, event) => { assert.equal(token, 'one-time-secret'); received = event; return true; },
    deliver: async () => true,
  });
  assert.equal(received.status, 'failed');
  assert.equal(received.error.code, 'EXTRACTION_FAILED');
  assert.equal(JSON.stringify(received).includes('private secret'), false);
  assert.equal(item.acknowledged, true);
});

test('an oversized extraction is checkpointed and delivered as a safe failure', async () => {
  const item = message(dispatch);
  let saved;
  await consumeBatch({ messages: [item] }, {
    claim: async () => ({ decision: 'start', checkpoint_token: 'one-time-secret' }),
    extract: async () => ({ text: 'x'.repeat(5 * 1024 * 1024) }),
    checkpoint: async (_, _token, event) => { saved = event; return true; },
    deliver: async event => { assert.deepEqual(event, saved); return true; },
  });
  assert.equal(saved.status, 'failed');
  assert.equal(saved.error.code, 'EXTRACTION_FAILED');
  assert.equal(item.acknowledged, true);
});

test('an unconfirmed checkpoint does not deliver or acknowledge a result', async () => {
  const item = message(dispatch);
  let deliveries = 0;
  await consumeBatch({ messages: [item] }, {
    claim: async () => ({ decision: 'start', checkpoint_token: 'one-time-secret' }),
    extract: async () => ({ contract_data: { contract_name: 'Treaty' }, parties_data: [] }),
    checkpoint: async () => false,
    deliver: async () => { deliveries++; return true; },
  });
  assert.equal(deliveries, 0);
  assert.equal(item.retried, true);
});
