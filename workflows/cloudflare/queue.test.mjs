import test from 'node:test';
import assert from 'node:assert/strict';
import { consumeBatch, RETRY_DELAYS } from './queue.mjs';

function message(body) {
  return { body, acknowledged: false, retried: false,
    ack() { this.acknowledged = true; },
    retry() { this.retried = true; } };
}
const dispatch = { schema_version: '1', operation: 'extract_reinsurance_contract', job_id: 'job-1', attempt_id: 'attempt-1', capability: 'signed-capability' };
const sleeps = [];
const options = { sleep: async ms => { sleeps.push(ms); } };
const start = async () => ({ decision: 'start', checkpoint_token: 'one-time-secret' });
const result = async () => ({ contract_data: { contract_name: 'Treaty' }, parties_data: [] });

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
    deliver: async () => ++deliveries > RETRY_DELAYS.length + 1,
  };
  const first = message(dispatch);
  await consumeBatch({ messages: [first] }, services, options);
  assert.equal(first.retried, true);
  const second = message(dispatch);
  await consumeBatch({ messages: [second] }, services, options);
  assert.equal(second.acknowledged, true);
  assert.equal(extractions, 1);
  assert.equal(deliveries, RETRY_DELAYS.length + 2);
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
  }, options);
  assert.equal(deliveries, 0);
  assert.equal(item.retried, true);
});

test('retry backoff is bounded well within the processing deadline', () => {
  assert.ok(RETRY_DELAYS.length >= 2 && RETRY_DELAYS.length <= 4);
  assert.ok(RETRY_DELAYS.reduce((a, b) => a + b, 0) <= 10000);
});

test('a transient checkpoint failure is retried in the same invocation without repeating provider work', async () => {
  const item = message(dispatch);
  let extractions = 0;
  let checkpoints = 0;
  const delivered = [];
  sleeps.length = 0;
  await consumeBatch({ messages: [item] }, {
    claim: start,
    extract: async () => { extractions++; return result(); },
    checkpoint: async (_, token) => {
      assert.equal(token, 'one-time-secret');
      if (++checkpoints === 1) throw new TypeError('network');
      return checkpoints === 3;
    },
    deliver: async event => { delivered.push(event); return true; },
  }, options);
  assert.equal(extractions, 1);
  assert.equal(checkpoints, 3);
  assert.equal(delivered.length, 1);
  assert.deepEqual(sleeps, RETRY_DELAYS.slice(0, 2));
  assert.equal(item.acknowledged, true);
  assert.equal(item.retried, false);
});

test('checkpoint retries are bounded and then fall back to message retry', async () => {
  const item = message(dispatch);
  let checkpoints = 0;
  let deliveries = 0;
  let extractions = 0;
  await consumeBatch({ messages: [item] }, {
    claim: start,
    extract: async () => { extractions++; return result(); },
    checkpoint: async () => { checkpoints++; throw new Error('503'); },
    deliver: async () => { deliveries++; return true; },
  }, options);
  assert.equal(checkpoints, RETRY_DELAYS.length + 1);
  assert.equal(extractions, 1);
  assert.equal(deliveries, 0);
  assert.equal(item.retried, true);
});

test('a transient delivery failure is retried before acknowledging', async () => {
  const item = message(dispatch);
  let deliveries = 0;
  await consumeBatch({ messages: [item] }, {
    claim: start, extract: result,
    checkpoint: async () => true,
    deliver: async () => { if (++deliveries === 1) throw new Error('timeout'); return true; },
  }, options);
  assert.equal(deliveries, 2);
  assert.equal(item.acknowledged, true);
  assert.equal(item.retried, false);
});

test('a replayed terminal checkpoint retries delivery in the same invocation', async () => {
  const item = message(dispatch);
  let deliveries = 0;
  const event = { schema_version: '1', job_id: 'job-1', attempt_id: 'attempt-1', event_id: 'terminal', status: 'failed', error: { code: 'X', message: 'x', retryable: false } };
  await consumeBatch({ messages: [item] }, {
    claim: async () => ({ decision: 'terminal', event }),
    deliver: async () => ++deliveries === 2,
  }, options);
  assert.equal(deliveries, 2);
  assert.equal(item.acknowledged, true);
});

test('a transient failure before the provider call is checkpointed as retryable instead of stranding the claim', async () => {
  const item = message(dispatch);
  let saved;
  await consumeBatch({ messages: [item] }, {
    claim: start,
    extract: async () => { throw Object.assign(new Error('private detail'), { preProvider: true, retryable: true }); },
    checkpoint: async (_, _token, event) => { saved = event; return true; },
    deliver: async () => true,
  }, options);
  assert.equal(saved.status, 'failed');
  assert.deepEqual(saved.error, { code: 'PREPARATION_FAILED', message: 'Document preparation failed before provider processing.', retryable: true });
  assert.equal(item.acknowledged, true);
  assert.equal(item.retried, false);
});

test('a permanent failure before the provider call is not marked retryable', async () => {
  const item = message(dispatch);
  let saved;
  await consumeBatch({ messages: [item] }, {
    claim: start,
    extract: async () => { throw Object.assign(new Error('UNSUPPORTED_DOCUMENT'), { preProvider: true, retryable: false }); },
    checkpoint: async (_, _token, event) => { saved = event; return true; },
    deliver: async () => true,
  }, options);
  assert.equal(saved.error.code, 'PREPARATION_FAILED');
  assert.equal(saved.error.retryable, false);
});
