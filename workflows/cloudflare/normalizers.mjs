'use strict';
// Pure, dependency-free helpers for normalizing LandingAI responses.
function fail(code = 'NORMALIZATION_FAILED') { const e = new Error(code); e.code = code; throw e; }
function object(x) { return x !== null && typeof x === 'object' && !Array.isArray(x); }
function checkSchema(value, schema) {
  if (schema.anyOf) { if (!schema.anyOf.some(s => { try { checkSchema(value,s); return true; } catch { return false; } })) fail(); return; }
  if (schema.enum && !schema.enum.includes(value)) fail();
  if (schema.type === 'null') { if (value !== null) fail(); return; }
  if (schema.type === 'object') {
    if (!object(value) || Object.keys(value).some(k => !Object.hasOwn(schema.properties,k))) fail();
    // Nullable facts may be omitted at the canonical boundary, even though model requests require all keys.
    for (const [k,v] of Object.entries(value)) checkSchema(v,schema.properties[k]);
  } else if (schema.type === 'array') {
    if (!Array.isArray(value) || value.length > (schema.maxItems ?? Infinity)) fail();
    value.forEach(v => checkSchema(v,schema.items));
  } else if (schema.type === 'number') { if (typeof value !== 'number' || !Number.isFinite(value)) fail(); }
  else if (schema.type === 'string') { if (typeof value !== 'string' || value.length > (schema.maxLength ?? Infinity)) fail(); }
}
function business(raw, schema) {
  if (!object(raw) || !object(raw.contract_data) || !Array.isArray(raw.parties_data)) fail();
  const pending=[raw];
  while(pending.length) { const value=pending.pop(); if(typeof value==='number' && !Number.isFinite(value)) fail(); if(value && typeof value==='object')pending.push(...Object.values(value)); }
  const result = JSON.parse(JSON.stringify(raw));
  const aliases = { 'quota share':'quota_share', 'quota-share':'quota_share', 'excess of loss':'xol', 'stop loss':'stop_loss', 'non proportional':'non-proportional', 'non_proportional':'non-proportional', 'facultative obligatory':'facultative_obligatory', 'facultative optional':'facultative_optional', 'cedent':'cedant' };
  for (const facts of [result.contract_data,...result.parties_data]) {
    for (const key of ['contract_type','contract_sub_type','contract_nature','role']) {
      if (typeof facts[key] === 'string') { const label = facts[key].trim().toLowerCase(); facts[key] = aliases[label] ?? label; }
    }
  }
  checkSchema(result,schema);
  for (const k of ['effective_date','expiration_date','inception_date']) {
    const v = result.contract_data[k];
    if (v != null && (!/^\d{4}-\d{2}-\d{2}$/.test(v) || !Number.isFinite(Date.parse(v)) || new Date(v).toISOString().slice(0,10) !== v)) fail();
  }
  for (const p of result.parties_data) if (typeof p.name !== 'string' || !p.name.trim() || /[\x00-\x1f\x7f]/.test(p.name)) fail();
  if (!result.parties_data.length && !Object.values(result.contract_data).some(v => v != null && (typeof v !== 'string' || v.trim()))) fail('NO_CONTRACT_DATA');
  return result;
}
function usableHttp(response) { if (response?.statusCode !== 200 || !object(response.body)) fail('PROVIDER_UNAVAILABLE'); return response.body; }
function safeVersion(v) { return typeof v === 'string' && v.length <= 256 && /^[A-Za-z0-9._:/-]+$/.test(v) ? v : undefined; }
function metadata(config, provider, resolved) {
  const m = {workflow_version:config.workflowVersion,provider,api_version:'ade-v1',model:config.landingExtractModel};
  const version = safeVersion(resolved); if (version) m.model_version=version;
  return m;
}
function parseLanding(response, config) {
  const body = usableHttp(response), m=body.metadata ?? {};
  if (!body.markdown?.trim() || !Array.isArray(body.chunks) || !object(body.grounding) || (m.failed_pages?.length ?? 0) || (m.warnings?.length ?? 0) || (m.page_count ?? 0) > 100) fail('UNREADABLE_DOCUMENT');
  if (m.version && m.version !== config.landingParseModel) fail('PROVIDER_VERSION_MISMATCH');
  return body;
}
function plainText(html) {
  return html.replace(/<[^>]*>/g,' ').replace(/^[ \t]{0,3}#{1,6}[ \t]+/gm,'').replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos|nbsp);/gi, (s,v) => {
    const named={amp:'&',lt:'<',gt:'>',quot:'"',apos:"'",nbsp:' '};
    if (named[v]) return named[v];
    const code=v.startsWith('#x') ? parseInt(v.slice(2),16) : parseInt(v.slice(1),10);
    return code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : s;
  }).replace(/\s+/g,' ').trim();
}
function referenceSource(parse, id, mime) {
  if (typeof id !== 'string' || !id.trim() || id.length > 128 || /[\x00-\x1f\x7f]/.test(id)) return undefined;
  const location=parse.grounding[id]; if (!location) return undefined;
  const chunk=parse.chunks.find(c => c.id === id);
  if (chunk?.type === 'figure' || /Figure|Logo|ScanCode/.test(location.type ?? '')) return undefined;
  let quote;
  if (chunk) quote=plainText(chunk.markdown ?? '');
  else {
    // Only actual element content; never use the extracted value as a quote.
    const escaped=id.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    const match=(parse.markdown ?? '').match(new RegExp('<([a-z][\\w:-]*)\\b[^>]*\\bid=["\\\']'+escaped+'["\\\'][^>]*>([\\s\\S]*?)<\\/\\1>','i'));
    if (match && match[1].toLowerCase() !== 'a') quote=plainText(match[2]);
    const parent=parse.chunks.find(c => c.id === location.position?.chunk_id);
    if (parent?.type === 'figure') return undefined;
  }
  if (!quote || quote.length > 8000) return undefined;
  const source={source_text:quote,chunk_id:id};
  if (mime === 'application/pdf') {
    if (!Number.isInteger(location.page) || location.page < 0) fail();
    source.page_number=location.page+1;
    if (location.box != null) {
      const b=location.box;
      if (!object(b) || Object.keys(b).sort().join() !== 'bottom,left,right,top' || !Object.values(b).every(v => typeof v === 'number' && Number.isFinite(v) && v>=0 && v<=1) || b.left>=b.right || b.top>=b.bottom) fail();
      source.bbox={...b};
    }
  }
  return source;
}
// Translate the provider schema used by production's LandingAI integration
// into the stable, review-facing machine contract.
function mapFlatExtraction(extraction, fieldMetadata, schema) {
  if (!object(extraction)) fail();
  const contract = {}, contractMeta = {}, parties = [], partyMeta = [];
  const names = { premium_text:'premium_description', retention_text:'retention_description', limit_text:'limit_description', commission_text:'commission_description' };
  for (const [key, value] of Object.entries(extraction)) {
    if (key === 'cedant_name' || key === 'reinsurer_name') {
      if (value != null && value !== '') {
        parties.push({ name:value, role:key === 'cedant_name' ? 'cedant' : 'reinsurer' });
        partyMeta.push({ name:fieldMetadata?.[key] });
      }
      continue;
    }
    const target = names[key] ?? key;
    if (!Object.hasOwn(schema.properties.contract_data.properties, target)) fail();
    contract[target] = target === 'currency' && typeof value === 'string' ? value.trim().toUpperCase() : value;
    if (fieldMetadata?.[key]) contractMeta[target] = fieldMetadata[key];
  }
  return { extraction:{ contract_data:contract, parties_data:parties }, metadata:{ contract_data:contractMeta, parties_data:partyMeta } };
}
function normalizeLanding(response, parse, mime, config, schema) {
  const body=usableHttp(response), m=body.metadata ?? {};
  if (m.schema_violation_error || (m.warnings?.length ?? 0)) fail();
  if (m.fallback_model_version || (m.version && m.version !== config.landingExtractModel)) fail('PROVIDER_VERSION_MISMATCH');
  const inputMeta=body.extraction_metadata?.data ?? body.extraction_metadata ?? {};
  const mapped=object(body.extraction?.contract_data) ? {extraction:body.extraction, metadata:inputMeta} : mapFlatExtraction(body.extraction,inputMeta,schema);
  const result=business(mapped.extraction,schema), meta=mapped.metadata;
  const refs=(facts,fields) => {
    if (!object(fields)) return {};
    const sources={};
    for (const [key,field] of Object.entries(fields)) {
      if (!object(field) || !Array.isArray(field.references) || !field.references.length) continue;
      if (!Object.hasOwn(facts,key) || facts[key] == null) fail();
      for (const id of field.references) { const s=referenceSource(parse,id,mime); if(s) { sources[key]=s; break; } }
    }
    return sources;
  };
  if (meta.parties_data != null && (!Array.isArray(meta.parties_data) || meta.parties_data.length !== result.parties_data.length)) fail();
  result.field_sources={contract:refs(result.contract_data,meta.contract_data), parties:result.parties_data.map((p,i) => refs(p,meta.parties_data?.[i]))};
  result.extraction_metadata=metadata(config,'landingai',m.version);
  result.extraction_metadata.provider_version=safeVersion(parse.metadata?.version) ?? config.landingParseModel;
  return result;
}

export { parseLanding, normalizeLanding };
