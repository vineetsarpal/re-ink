'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),{execFileSync}=require('node:child_process'),path=require('node:path');
const workflow=require('../reink-extraction-v1.json');
const nodes=Object.fromEntries(workflow.nodes.map(n=>[n.name,n]));
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
async function run(name,input,upstream={},helpers={}) {
  const fn=new AsyncFunction('$input','$','$execution',nodes[name].parameters.jsCode);
  const lookup=name=>({first:()=>upstream[name],item:upstream[name]});
  return fn.call({helpers}, {first:()=>input},lookup,{id:'synthetic-execution'});
}
test('inactive sanitized export with stable authenticated webhook and pinned core versions',()=>{
  assert.equal(workflow.active,false);assert.deepEqual(workflow.pinData,{});
  const pins={webhook:2.2,respondToWebhook:1.5,httpRequest:4.5,wait:1.1,code:2,if:2.3};
  for(const node of workflow.nodes){assert.equal(node.typeVersion,pins[node.type.split('.').at(-1)]);assert.equal(node.credentials,undefined);if(node.type.endsWith('.httpRequest')){assert.equal(node.retryOnFail,false);assert.equal(node.parameters.authentication,'genericCredentialType');assert.equal(node.parameters.options.redirect.redirect.followRedirects,false);}}
  assert.equal(nodes['Extraction webhook'].parameters.path,'reink-extraction-v1');assert.equal(nodes['Extraction webhook'].parameters.authentication,'headerAuth');assert.equal(nodes['Accept dispatch'].parameters.options.responseCode,202);
  assert.deepEqual(workflow.connections['Owned active attempt'].main[0],[{node:'Fetch original',type:'main',index:0}]);
  assert.equal(workflow.connections['Owned active attempt'].main[1],undefined);
  assert.equal(workflow.connections['Retry callback'].main[1],undefined);
  for(const node of workflow.nodes.filter(n=>n.type.endsWith('.code')))new AsyncFunction('$input','$','$execution',node.parameters.jsCode);
});
test('Entry refuses unconfigured models/origin and validates dispatch before accepting',async()=>{
  const body={schema_version:'1',operation:'extract_reinsurance_contract',job_id:'synthetic-job',attempt_id:'synthetic-attempt'};
  assert.equal((await run('Entry',{json:{body}}))[0].json.response_code,503);
  assert.equal((await run('Entry',{json:{body:{...body,extra:true}}}))[0].json.response_code,422);
  const original=nodes.Entry.parameters.jsCode;
  try {
    for(const provider of ['landingai','openai']) {
      const config={...require('../config.json'),backendOrigin:'https://reink.synthetic.example',provider,landingParseModel:'synthetic-parse',landingExtractModel:'synthetic-extract',openaiModel:'synthetic-model'};
      nodes.Entry.parameters.jsCode=original.replace(/const config=.*?;\n/, 'const config='+JSON.stringify(config)+';\n');
      const [entry]=await run('Entry',{json:{body}});assert.equal(entry.json.response_code,202);assert.equal(entry.json.config.provider,provider);
    }
  } finally {nodes.Entry.parameters.jsCode=original;}
});
test('document binary survives into ADE; OpenAI inline PDF/DOCX request store=false and strict schema',async()=>{
  for(const mime of ['application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document']) {
    for(const provider of ['landingai','openai']) {
      const entry={json:{config:{...require('../config.json'),provider,openaiModel:'synthetic-fixture-model'},schema:require('../generated/business-schema.json')}};
      const result=await run('Prepare document',{json:{statusCode:200},binary:{document:{mimeType:mime}}},{Entry:entry,'Claim gate':{json:{deadline_at:'2030-01-01T00:00:00Z'}}},{getBinaryDataBuffer:async()=>Buffer.from('synthetic')});
      assert.equal(result[0].json.ready,true);assert.ok(result[0].binary.document);
      if(provider==='openai'){const request=result[0].json.request;assert.equal(request.store,false);assert.equal(request.text.format.strict,true);assert.ok(request.input[0].content[0].file_data.startsWith('data:'+mime+';base64,'));}
    }
  }
});
test('unsupported format/input bound and expired deadline stop provider work',async()=>{
  const entry={json:{config:{...require('../config.json'),provider:'openai'},schema:require('../generated/business-schema.json')}};
  const upstream={Entry:entry,'Claim gate':{json:{deadline_at:'2030-01-01T00:00:00Z'}}};
  const input={json:{statusCode:200},binary:{document:{mimeType:'image/png'}}};
  assert.equal((await run('Prepare document',input,upstream))[0].json.failure,'UNSUPPORTED_INPUT');
  input.binary.document.mimeType='application/pdf';
  assert.equal((await run('Prepare document',input,upstream,{getBinaryDataBuffer:async()=>({length:50000000})}))[0].json.failure,'INPUT_LIMIT');
  upstream['Claim gate'].json.deadline_at='2000-01-01T00:00:00Z';assert.deepEqual(await run('Prepare document',input,upstream),[]);
});
test('normalization failure becomes bounded static error, delivery ambiguity retains completed payload',async()=>{
  const entry={json:{dispatch:{job_id:'synthetic-job',attempt_id:'synthetic-attempt'},execution_key:'n8n-synthetic'}};
  const upstream={Entry:entry,'Claim gate':{json:{deadline_at:'2030-01-01T00:00:00Z'}}};
  const [failed]=await run('Freeze event',{json:{failure:'PRIVATE TRACE'}},upstream);
  assert.equal(failed.json.event.status,'failed');assert.equal(failed.json.event.error.code,'NORMALIZATION_FAILED');assert.ok(!JSON.stringify(failed).includes('PRIVATE TRACE'));
  const [completed]=await run('Freeze event',{json:{result:{contract_data:{contract_name:'Synthetic'},parties_data:[]}}},upstream);
  const [retry]=await run('Check acknowledgement',{json:{error:'network'}},{'Delivery context':completed});
  assert.equal(retry.json.retry,true);assert.equal(retry.json.event.status,'completed');assert.deepEqual(retry.json.event,completed.json.event);
});
test('generation deterministic and canonical outputs accepted by backend authority',()=>{
  const root=path.resolve(__dirname,'../../..'),python=path.join(root,'backend/.venv/bin/python');
  const paths=['generated/business-schema.json','generated/limits.json','reink-extraction-v1.json'].map(p=>path.resolve(__dirname,'..',p));
  const before=paths.map(p=>fs.readFileSync(p,'utf8'));
  execFileSync(python,[path.resolve(__dirname,'../generate_schema.py')],{cwd:root});execFileSync(process.execPath,[path.resolve(__dirname,'../generate_workflow.cjs')],{cwd:root});
  paths.forEach((p,i)=>assert.equal(fs.readFileSync(p,'utf8'),before[i]));
  const output=path.join(require('node:os').tmpdir(),'reink-canonical-'+process.pid+'.json');
  try {
    execFileSync(process.execPath,[path.join(__dirname,'normalizers.test.cjs')],{env:{...process.env,WRITE_CANONICAL_FIXTURES:output}});
    execFileSync(python,['-c',"import json,sys; from app.schemas.workflow import NormalizedExtractionResult; [NormalizedExtractionResult.model_validate(x) for x in json.load(open(sys.argv[1]))]",output],{cwd:path.join(root,'backend')});
  } finally {fs.rmSync(output,{force:true});}
});
