// Disabled by default: no deployment configuration or backend route is enabled.
// Secrets must be supplied only as Cloudflare Worker secrets, never queue data.
import schema from './business-schema.json' with { type: 'json' };
import providerSchema from './provider-schema.json' with { type: 'json' };
import { consumeBatch, MAX_EVENT } from './queue.mjs';
import { probeLandingAI } from './landingai.mjs';
import { parseLanding, normalizeLanding } from './normalizers.mjs';

const MAX_DOCUMENT = 5 * 1024 * 1024;
const MAX_RESPONSE = 8 * 1024 * 1024;

async function boundedBytes(response, limit) {
  const declared = response.headers.get('content-length');
  if (declared && (!/^\d+$/.test(declared) || Number(declared) > limit)) throw new Error('RESPONSE_TOO_LARGE');
  if (!response.body) return new Uint8Array();
  const reader = response.body.getReader();
  const parts = [];
  let size = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) { await reader.cancel(); throw new Error('RESPONSE_TOO_LARGE'); }
      parts.push(value);
    }
  } finally { reader.releaseLock(); }
  const data = new Uint8Array(size);
  let offset = 0;
  for (const part of parts) { data.set(part, offset); offset += part.byteLength; }
  return data;
}

async function readJson(response, limit = MAX_RESPONSE) {
  if (response.status !== 200) throw new Error('REMOTE_REQUEST_FAILED');
  return JSON.parse(new TextDecoder().decode(await boundedBytes(response, limit)));
}

function trustedOrigin(value) {
  let origin;
  try { origin = new URL(value); } catch { throw new Error('INVALID_CONFIG'); }
  if (origin.protocol !== 'https:' || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash) throw new Error('INVALID_CONFIG');
  return origin.origin;
}

function settings(env) {
  const origin = trustedOrigin(env.REINK_API_ORIGIN);
  if (typeof env.REINK_WORKER_TOKEN !== 'string' || env.REINK_WORKER_TOKEN.length < 32 ||
      !env.LANDINGAI_PARSE_MODEL || !env.LANDINGAI_EXTRACT_MODEL) throw new Error('INVALID_CONFIG');
  return { origin, token: env.REINK_WORKER_TOKEN, parseModel: env.LANDINGAI_PARSE_MODEL, extractModel: env.LANDINGAI_EXTRACT_MODEL };
}

function services(env, fetchImpl) {
  const config = settings(env);
  const endpoint = (dispatch, action) => `${config.origin}/api/cloudflare/jobs/${encodeURIComponent(dispatch.job_id)}/attempts/${encodeURIComponent(dispatch.attempt_id)}/${action}`;
  const call = (dispatch, action, options = {}) => fetchImpl(endpoint(dispatch, action), {
    ...options, redirect: 'error', headers: { Authorization: `Bearer ${config.token}`, 'X-Dispatch-Capability': dispatch.capability, ...options.headers },
  });
  return {
    async claim(dispatch) { return readJson(await call(dispatch, 'claim', { method: 'POST' }), 16384); },
    async extract(dispatch, checkpointToken) {
      const headers = { 'X-Checkpoint-Token': checkpointToken };
      const credential = await readJson(await call(dispatch, 'credential', { headers }), 16384);
      if (typeof credential.api_key !== 'string' || !credential.api_key) throw new Error('INVALID_CREDENTIAL');
      const document = await call(dispatch, 'document', { headers });
      if (document.status !== 200) throw new Error('DOCUMENT_UNAVAILABLE');
      const mime = (document.headers.get('content-type') ?? '').split(';')[0].trim();
      const extensions = { 'application/pdf': 'pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx' };
      if (!extensions[mime]) throw new Error('UNSUPPORTED_DOCUMENT');
      const blob = new Blob([await boundedBytes(document, MAX_DOCUMENT)], { type: mime });
      // Bound provider JSON before the probe parses it; never log remote bodies.
      const providerFetch = async (url, options) => {
        const response = await fetchImpl(url, options);
        const bytes = await boundedBytes(response, MAX_RESPONSE);
        return new Response(bytes, { status: response.status, headers: { 'content-type': 'application/json' } });
      };
      const { parsed, extracted } = await probeLandingAI({ document: blob, filename: `document.${extensions[mime]}`, apiKey: credential.api_key,
        parseModel: config.parseModel, extractModel: config.extractModel, schema: providerSchema, fetchImpl: providerFetch });
      const normalizerConfig = { workflowVersion: 'cloudflare-prototype-v1', landingParseModel: config.parseModel, landingExtractModel: config.extractModel };
      const safeParse = parseLanding({ statusCode: 200, body: parsed }, normalizerConfig);
      return normalizeLanding({ statusCode: 200, body: extracted }, safeParse, mime, normalizerConfig, schema);
    },
    async checkpoint(dispatch, token, event) {
      const body = JSON.stringify(event);
      if (new TextEncoder().encode(body).byteLength > MAX_EVENT) throw new Error('RESULT_TOO_LARGE');
      const result = await readJson(await call(dispatch, 'checkpoint', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Checkpoint-Token': token }, body }), 16384);
      return result.stored === true;
    },
    async deliver(event, dispatch) {
      const ack = await readJson(await call(dispatch, 'deliver', { method: 'POST' }), 16384);
      return ack.schema_version === '1' && ack.event_id === event.event_id && ack.status === 'acknowledged';
    },
  };
}

export async function runQueue(batch, env, fetchImpl = fetch) {
  let adapter;
  try { adapter = services(env, fetchImpl); }
  catch { for (const message of batch.messages) message.retry(); return; }
  await consumeBatch(batch, adapter);
}

export async function runScheduled(env, fetchImpl = fetch) {
  let origin;
  try { origin = trustedOrigin(env.REINK_API_ORIGIN); } catch { throw new Error('MAINTENANCE_FAILED'); }
  const dispatch = env.REINK_DISPATCH_SCHEDULER_TOKEN;
  const expiry = env.REINK_EXPIRY_SCHEDULER_TOKEN;
  const cleanup = env.REINK_CLEANUP_SCHEDULER_TOKEN;
  if ([dispatch, expiry, cleanup].some(value => typeof value !== 'string' || value.length < 32) || new Set([dispatch, expiry, cleanup]).size !== 3) throw new Error('MAINTENANCE_FAILED');
  const requests = [
    ['/api/maintenance/cloudflare-dispatch', dispatch, 'attempted'],
    ['/api/maintenance/expiry', expiry, 'processed'],
    ['/api/maintenance/cleanup', cleanup, 'processed'],
  ];
  const results = await Promise.allSettled(requests.map(async ([path, token, field]) => {
    const response = await fetchImpl(origin + path, { method: 'POST', redirect: 'error', signal: AbortSignal.timeout(45000), headers: { Authorization: `Bearer ${token}` } });
    const result = await readJson(response, 16384);
    if (!Number.isSafeInteger(result[field]) || result[field] < 0) throw new Error('INVALID_RESPONSE');
  }));
  if (results.some(result => result.status === 'rejected')) throw new Error('MAINTENANCE_FAILED');
}

export default {
  async queue(batch, env) { await runQueue(batch, env); },
  async scheduled(_controller, env) { await runScheduled(env); },
};
