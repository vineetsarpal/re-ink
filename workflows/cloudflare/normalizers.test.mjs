import test from 'node:test';
import assert from 'node:assert/strict';
import schema from './business-schema.json' with { type: 'json' };
import { parseLanding, normalizeLanding } from './normalizers.mjs';

test('maps the production flat LandingAI schema to reviewer fields', () => {
  const config = { workflowVersion: 'test', landingParseModel: 'parse-v1', landingExtractModel: 'extract-v1' };
  const parsed = parseLanding({ statusCode: 200, body: {
    markdown: 'Example treaty', chunks: [{ id: '0-1', type: 'text', markdown: 'Premium $1,000' }, { id: '0-2', type: 'text', markdown: 'Acme Insurance' }],
    grounding: { '0-1': { page: 0 }, '0-2': { page: 1 } }, metadata: { version: 'parse-v1' },
  } }, config);
  const result = normalizeLanding({ statusCode: 200, body: {
    extraction: { contract_name: 'Example treaty', contract_type: 'Treaty', contract_sub_type: 'Stop Loss', premium_text: 'Premium $1,000', premium_amount: 1000, cedant_name: 'Acme Insurance', reinsurer_name: 'Re Co' },
    extraction_metadata: { premium_text: { references: ['0-1'] }, cedant_name: { references: ['0-2'] } },
    metadata: { version: 'extract-v1' },
  } }, parsed, 'application/pdf', config, schema);
  assert.equal(result.contract_data.contract_type, 'treaty');
  assert.equal(result.contract_data.contract_sub_type, 'stop_loss');
  assert.equal(result.contract_data.premium_description, 'Premium $1,000');
  assert.deepEqual(result.parties_data, [{ name: 'Acme Insurance', role: 'cedant' }, { name: 'Re Co', role: 'reinsurer' }]);
  assert.equal(result.field_sources.contract.premium_description.source_text, 'Premium $1,000');
  assert.equal(result.field_sources.parties[0].name.page_number, 2);
});

test('produces reviewer field names and aligned source evidence', () => {
  const config = { workflowVersion: 'test', landingParseModel: 'parse-v1', landingExtractModel: 'extract-v1' };
  const parsed = parseLanding({ statusCode: 200, body: {
    markdown: 'Example treaty',
    chunks: [{ id: '0-1', type: 'text', markdown: 'Premium $1,000' }, { id: '0-2', type: 'text', markdown: 'Acme Insurance' }],
    grounding: { '0-1': { page: 0, box: { left: 0.1, top: 0.2, right: 0.5, bottom: 0.3 } }, '0-2': { page: 1 } },
    metadata: { version: 'parse-v1' },
  } }, config);
  const result = normalizeLanding({ statusCode: 200, body: {
    extraction: { contract_data: { contract_name: 'Example treaty', premium_description: 'Premium $1,000', premium_amount: 1000 }, parties_data: [{ name: 'Acme Insurance', role: 'cedant' }] },
    extraction_metadata: { contract_data: { premium_description: { references: ['0-1'] } }, parties_data: [{ name: { references: ['0-2'] } }] },
    metadata: { version: 'extract-v1' },
  } }, parsed, 'application/pdf', config, schema);

  assert.equal(result.contract_data.premium_amount, 1000);
  assert.equal(result.parties_data[0].role, 'cedant');
  assert.deepEqual(result.field_sources.contract.premium_description, { source_text: 'Premium $1,000', chunk_id: '0-1', page_number: 1, bbox: { left: 0.1, top: 0.2, right: 0.5, bottom: 0.3 } });
  assert.deepEqual(result.field_sources.parties[0].name, { source_text: 'Acme Insurance', chunk_id: '0-2', page_number: 2 });
});
