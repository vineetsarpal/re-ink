// This module requires a durable coordinator; it is not wired to a deployment.
export const MAX_EVENT = 5 * 1024 * 1024;
// Bounded backoff (4 attempts, ~4.25s of waiting) for idempotent backend calls.
export const RETRY_DELAYS = [250, 1000, 3000];
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

async function confirmed(operation, sleep, delays) {
  for (let attempt = 0; ; attempt++) {
    try { if (await operation() === true) return true; } catch {}
    if (attempt >= delays.length) return false;
    await sleep(delays[attempt]);
  }
}

function validDispatch(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) &&
    Object.keys(value).sort().join() === 'attempt_id,capability,job_id,operation,schema_version' &&
    typeof value.capability === 'string' && value.capability.length > 0 && value.capability.length <= 4096 &&
    value.schema_version === '1' && value.operation === 'extract_reinsurance_contract' &&
    ['job_id', 'attempt_id'].every(key => typeof value[key] === 'string' &&
      value[key].trim() && value[key].length <= 128 && !/[\x00-\x1f\x7f]/.test(value[key]));
}

export async function consumeBatch(batch, services, { sleep = wait, delays = RETRY_DELAYS } = {}) {
  const deliver = (event, body) => confirmed(() => services.deliver(event, body), sleep, delays);
  for (const message of batch.messages) {
    if (!validDispatch(message.body)) {
      message.ack();
      continue;
    }
    try {
      const claim = await services.claim(message.body);
      if (claim?.decision === 'closed') {
        message.ack();
        continue;
      }
      if (claim?.decision === 'terminal') {
        const event = claim.event;
        if (!event || event.schema_version !== '1' || event.job_id !== message.body.job_id ||
            event.attempt_id !== message.body.attempt_id || event.event_id !== 'terminal' ||
            !['completed', 'failed'].includes(event.status)) {
          message.retry();
          continue;
        }
        if (await deliver(event, message.body)) message.ack();
        else message.retry();
        continue;
      }
      if (claim?.decision !== 'start' || typeof claim.checkpoint_token !== 'string' || !claim.checkpoint_token) {
        message.retry();
        continue;
      }
      let event = { schema_version: '1', job_id: message.body.job_id,
        attempt_id: message.body.attempt_id, event_id: 'terminal' };
      try {
        const result = await services.extract(message.body, claim.checkpoint_token);
        event = { ...event, status: 'completed', result };
        if (new TextEncoder().encode(JSON.stringify(event)).byteLength > MAX_EVENT) {
          throw new Error('RESULT_TOO_LARGE');
        }
      } catch (error) {
        // The one-shot claim is spent, so a pre-provider failure is recorded rather than redelivered.
        event = { ...event, status: 'failed', error: error?.preProvider === true
          ? { code: 'PREPARATION_FAILED', message: 'Document preparation failed before provider processing.', retryable: error.retryable === true }
          : { code: 'EXTRACTION_FAILED', message: 'Document extraction failed.', retryable: false } };
      }
      if (!await confirmed(() => services.checkpoint(message.body, claim.checkpoint_token, event), sleep, delays)) {
        message.retry();
        continue;
      }
      if (await deliver(event, message.body)) message.ack();
      else message.retry();
    } catch {
      message.retry();
    }
  }
}
