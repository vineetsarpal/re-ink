import test from 'node:test';
import assert from 'node:assert/strict';
import { probeLandingAI } from './landingai.mjs';

const input = { document: new Blob(['fixture'], { type: 'application/pdf' }), filename: 'test.pdf', apiKey: 'test-secret', parseModel: 'parse-model', extractModel: 'extract-model', schema: { type: 'object' } };
const response = (status, body) => new Response(JSON.stringify(body), { status });
const parse = { markdown: '# fixture', chunks: [], grounding: {} };

test('sends document and parse markdown to the two fixed LandingAI endpoints', async () => {
  const requests = [];
  const result = await probeLandingAI({ ...input, fetchImpl: async (url, init) => {
    requests.push({ url, init });
    return requests.length === 1 ? response(200, parse) : response(200, { extraction: { contract_data: {} } });
  } });
  assert.equal(result.parsed.markdown, '# fixture');
  assert.deepEqual(requests.map(r => r.url), ['https://api.va.landing.ai/v1/ade/parse', 'https://api.va.landing.ai/v1/ade/extract']);
  assert.equal(requests[0].init.redirect, 'error');
  assert.equal(requests[0].init.headers.Authorization, 'Bearer test-secret');
  assert.equal(await requests[1].init.body.get('markdown').text(), '# fixture');
  assert.equal(requests[1].init.body.get('strict'), null);
});

test('rejects partial parse responses without sending to extraction', async () => {
  let calls = 0;
  await assert.rejects(probeLandingAI({ ...input, fetchImpl: async () => { calls++; return response(206, parse); } }), /PARSE_FAILED/);
  assert.equal(calls, 1);
});

test('rejects incomplete parse and fallback extraction without exposing provider errors', async () => {
  await assert.rejects(probeLandingAI({ ...input, fetchImpl: async () => response(200, { ...parse, metadata: { failed_pages: [1] } }) }), /INVALID_PARSE_RESULT/);
  let calls = 0;
  await assert.rejects(probeLandingAI({ ...input, fetchImpl: async () => ++calls === 1 ? response(200, parse) : response(200, { extraction: {}, metadata: { fallback_model_version: 'other' } }) }), /INVALID_EXTRACTION_RESULT/);
});
