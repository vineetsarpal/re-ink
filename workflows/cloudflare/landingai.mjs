// Isolated compatibility probe; this is not a queue consumer or production adapter.
const API = 'https://api.va.landing.ai/v1/ade';
// Parse + extract must finish inside the backend's 600s processing deadline.
export const PARSE_TIMEOUT_MS = 180000;
export const EXTRACT_TIMEOUT_MS = 120000;

export async function probeLandingAI({ document, filename, apiKey, parseModel, extractModel, schema, fetchImpl = fetch }) {
  if (!(document instanceof Blob) || !filename || !apiKey || !parseModel || !extractModel || !schema) {
    throw new Error('INVALID_CONFIGURATION');
  }
  const headers = { Authorization: `Bearer ${apiKey}` };
  const parseForm = new FormData();
  parseForm.append('document', document, filename);
  parseForm.append('model', parseModel);
  const parsedResponse = await fetchImpl(`${API}/parse`, {
    method: 'POST', headers, body: parseForm, redirect: 'manual', signal: AbortSignal.timeout(PARSE_TIMEOUT_MS),
  });
  if (parsedResponse.status !== 200) throw new Error('PARSE_FAILED');
  const parsed = await parsedResponse.json();
  if (typeof parsed.markdown !== 'string' || !parsed.markdown.trim() ||
      !Array.isArray(parsed.chunks) || !parsed.grounding ||
      parsed.metadata?.failed_pages?.length || parsed.metadata?.warnings?.length) {
    throw new Error('INVALID_PARSE_RESULT');
  }
  const extractForm = new FormData();
  extractForm.append('markdown', new Blob([parsed.markdown], { type: 'text/markdown' }), 'document.md');
  extractForm.append('schema', JSON.stringify(schema));
  extractForm.append('model', extractModel);
  const extractResponse = await fetchImpl(`${API}/extract`, {
    method: 'POST', headers, body: extractForm, redirect: 'manual', signal: AbortSignal.timeout(EXTRACT_TIMEOUT_MS),
  });
  if (extractResponse.status !== 200) throw new Error('EXTRACT_FAILED');
  const extracted = await extractResponse.json();
  if (!extracted.extraction || extracted.metadata?.schema_violation_error ||
      extracted.metadata?.warnings?.length || extracted.metadata?.fallback_model_version) {
    throw new Error('INVALID_EXTRACTION_RESULT');
  }
  return { parsed, extracted };
}
