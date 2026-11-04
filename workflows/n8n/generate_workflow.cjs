'use strict';
const fs=require('node:fs'),path=require('node:path');
const dir=__dirname;
const schema=JSON.parse(fs.readFileSync(path.join(dir,'generated/business-schema.json')));
const config=JSON.parse(fs.readFileSync(path.join(dir,'config.json')));
const lib=fs.readFileSync(path.join(dir,'normalizers.cjs'),'utf8').replace(/module\.exports=\{[^;]+;/,'');
const nodes=[],connections={};
function node(name,type,version,parameters,extra={}) {
  nodes.push({parameters,id:name.toLowerCase().replace(/\W+/g,'-'),name,type:'n8n-nodes-base.'+type,typeVersion:version,position:[nodes.length%6*260,Math.floor(nodes.length/6)*220],...extra});
}
function code(name,js,helpers=false){node(name,'code',2,{jsCode:(helpers ? lib+'\n' : '')+js,mode:'runOnceForAllItems'});}
function edge(a,b,output=0){connections[a]??={main:[]}; while(connections[a].main.length<=output)connections[a].main.push([]); connections[a].main[output].push({node:b,type:'main',index:0});}
function iff(name,expr){node(name,'if',2.3,{conditions:{options:{caseSensitive:true,leftValue:'',typeValidation:'strict',version:2},conditions:[{id:name,leftValue:expr,rightValue:true,operator:{type:'boolean',operation:'true',singleValue:true}}],combinator:'and'},options:{}});}
const full={response:{response:{fullResponse:true,neverError:true,responseFormat:'json'}},redirect:{redirect:{followRedirects:false}},timeout:30000};
const deadlineTimeout="={{ Math.max(1,Math.min(300000,Date.parse($('Claim gate').first().json.deadline_at)-Date.now())) }}";
function http(name,parameters){node(name,'httpRequest',4.5,{authentication:'genericCredentialType',genericAuthType:'httpHeaderAuth',...parameters}, {retryOnFail:false,onError:'continueRegularOutput'});}
function postJson(name,url,body,options=full){http(name,{method:'POST',url,sendBody:true,specifyBody:'json',jsonBody:body,options});}
node('Extraction webhook','webhook',2.2,{httpMethod:'POST',path:'reink-extraction-v1',authentication:'headerAuth',responseMode:'responseNode',options:{}},{webhookId:'reink-extraction-v1'});
code('Entry',`const config=${JSON.stringify(config)};
const body=$input.first().json.body;
const valid=validateDispatch(body);
const origin=new RegExp('^https://([a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[0-9]{1,5})?$','i').exec(config.backendOrigin);
const selectedModels=config.provider==='landingai' ? [config.landingParseModel,config.landingExtractModel] : [config.openaiModel];
const configured=!!origin && !origin[1].toLowerCase().endsWith('.invalid') && ['landingai','openai'].includes(config.provider) && selectedModels.every(model=>typeof model==='string' && model.trim() && !model.startsWith('SET_'));
return [{json:{valid,configured,dispatch: valid ? body : null,config,schema:${JSON.stringify(schema)},execution_key:'n8n-'+String($execution.id),response_code:valid ? (configured ? 202 : 503) : 422}}];`,true);
iff('Dispatch permitted','={{ $json.valid && $json.configured }}');
node('Reject dispatch','respondToWebhook',1.5,{respondWith:'json',responseBody:'={{ {error: $json.valid ? "Workflow configuration unavailable" : "Invalid dispatch"} }}',options:{responseCode:'={{ $json.response_code }}'}});
node('Accept dispatch','respondToWebhook',1.5,{respondWith:'json',responseBody:'={{ {schema_version:"1",job_id:$json.dispatch.job_id,attempt_id:$json.dispatch.attempt_id,status:"accepted",workflow_execution_id:null} }}',options:{responseCode:202}});
postJson('Claim attempt',"={{ $('Entry').first().json.config.backendOrigin + '/api/workflows/extraction/jobs/' + encodeURIComponent($('Entry').first().json.dispatch.job_id) + '/attempts/' + encodeURIComponent($('Entry').first().json.dispatch.attempt_id) + '/claim' }}","={{ {schema_version:'1',execution_key:$('Entry').first().json.execution_key} }}");
code('Claim gate',"return [{json:claimDecision($input.first().json,$('Entry').first().json.dispatch)}];",true);
iff('Owned active attempt','={{ $json.run }}');
http('Fetch original',{method:'GET',url:"={{ $('Entry').first().json.config.backendOrigin + '/api/workflows/extraction/jobs/' + encodeURIComponent($('Entry').first().json.dispatch.job_id) + '/document?attempt_id=' + encodeURIComponent($('Entry').first().json.dispatch.attempt_id) }}",options:{...full,response:{response:{fullResponse:true,neverError:true,responseFormat:'file',outputPropertyName:'document'}},timeout:deadlineTimeout}});
code('Prepare document',`const input=$input.first(), ctx=$('Entry').first().json;
try {
  if(Date.now()>=Date.parse($('Claim gate').first().json.deadline_at)) return [];
  if(input.json.error || (input.json.statusCode && input.json.statusCode!==200) || !input.binary?.document) fail('DOCUMENT_UNAVAILABLE');
  const doc=input.binary.document, mime=doc.mimeType?.split(';')[0];
  if(!['application/pdf','application/vnd.openxmlformats-officedocument.wordprocessingml.document'].includes(mime)) fail('UNSUPPORTED_INPUT');
  const bytes=await this.helpers.getBinaryDataBuffer(0,'document');
  if(bytes.length>50*1024*1024) fail('INPUT_LIMIT');
  if(ctx.config.provider==='openai' && bytes.length>=50000000) fail('INPUT_LIMIT');
  const filename=mime==='application/pdf' ? 'original.pdf' : 'original.docx';
  const request=ctx.config.provider==='openai' ? {model:ctx.config.openaiModel,store:false,input:[{role:'user',content:[{type:'input_file',filename,file_data:'data:'+mime+';base64,'+bytes.toString('base64')},{type:'input_text',text:ctx.config.prompt}]}],text:{format:{type:'json_schema',name:'reinsurance_contract',strict:true,schema:ctx.schema}}} : null;
  return [{json:{ready:true,mime,request,provider:ctx.config.provider},binary:input.binary}];
} catch(e) {return [{json:{ready:false,failure:e.code ?? 'NORMALIZATION_FAILED'}}];}`,true);
iff('Document ready','={{ $json.ready }}');
iff('LandingAI selected',"={{ $json.provider === 'landingai' }}");
http('LandingAI Parse',{method:'POST',url:'https://api.va.landing.ai/v1/ade/parse',sendBody:true,contentType:'multipart-form-data',bodyParameters:{parameters:[{parameterType:'formBinaryData',name:'document',inputDataFieldName:'document'},{name:'model',value:"={{ $('Entry').first().json.config.landingParseModel }}"}]},options:{...full,timeout:deadlineTimeout}});
code('Prepare markdown',`try {
  if(Date.now()>=Date.parse($('Claim gate').first().json.deadline_at)) return [];
  const parse=parseLanding($input.first().json,$('Entry').first().json.config);
  const markdown=await this.helpers.prepareBinaryData(Buffer.from(parse.markdown,'utf8'),'parsed.md','text/markdown');
  return [{json:{ready:true,parse},binary:{markdown}}];
} catch(e) {return [{json:{ready:false,failure:e.code ?? 'NORMALIZATION_FAILED'}}];}`,true);
iff('Markdown ready','={{ $json.ready }}');
http('LandingAI Extract',{method:'POST',url:'https://api.va.landing.ai/v1/ade/extract',sendBody:true,contentType:'multipart-form-data',bodyParameters:{parameters:[{parameterType:'formBinaryData',name:'markdown',inputDataFieldName:'markdown'},{name:'schema',value:"={{ JSON.stringify($('Entry').first().json.schema) }}"},{name:'model',value:"={{ $('Entry').first().json.config.landingExtractModel }}"},{name:'strict',value:'true'}]},options:{...full,timeout:deadlineTimeout}});
code('Normalize LandingAI',`try { const e=$('Entry').first().json; return [{json:{result:normalizeLanding($input.first().json,$('Prepare markdown').first().json.parse,$('Prepare document').first().json.mime,e.config,e.schema)}}]; } catch(e) {return [{json:{failure:e.code ?? 'NORMALIZATION_FAILED'}}];}`,true);
postJson('OpenAI Responses','https://api.openai.com/v1/responses','={{ $json.request }}',{...full,timeout:deadlineTimeout});
code('Normalize OpenAI',`try {const e=$('Entry').first().json; return [{json:{result:normalizeOpenAI($input.first().json,e.config,e.schema)}}];} catch(e) {return [{json:{failure:e.code ?? 'NORMALIZATION_FAILED'}}];}`,true);
code('Freeze event',`const input=$input.first().json,ctx=$('Entry').first().json;
const deadline_at=$('Claim gate').first().json.deadline_at;
if(Date.now()>=Date.parse(deadline_at)) return [];
const event={schema_version:'1',...{job_id:ctx.dispatch.job_id,attempt_id:ctx.dispatch.attempt_id},event_id:ctx.execution_key+'-terminal',workflow_execution_id:String($execution.id)};
const safe={NO_CONTRACT_DATA:'No useful contract data was found.',UNREADABLE_DOCUMENT:'The document could not be read.',UNSUPPORTED_INPUT:'The document format is unsupported.',INPUT_LIMIT:'The document exceeds the provider input limit.',DOCUMENT_UNAVAILABLE:'The original could not be retrieved.',PROVIDER_UNAVAILABLE:'The extraction provider is unavailable.',PROVIDER_REFUSAL:'The provider declined extraction.',PROVIDER_INCOMPLETE:'The provider did not complete extraction.',PROVIDER_VERSION_MISMATCH:'The provider configuration changed unexpectedly.',NORMALIZATION_FAILED:'The extracted data could not be normalized.',OUTPUT_LIMIT:'The extracted result exceeds the callback limit.'};
if(input.result){event.status='completed';event.result=input.result;} else {event.status='failed';const code=Object.hasOwn(safe,input.failure)?input.failure:'NORMALIZATION_FAILED';event.error={code,message:safe[code],retryable:false};}
if(Buffer.byteLength(JSON.stringify(event),'utf8')>5*1024*1024){delete event.result;event.status='failed';event.error={code:'OUTPUT_LIMIT',message:safe.OUTPUT_LIMIT,retryable:false};}
return [{json:{event,deadline_at,retry_count:0}}];`);
// Freeze event is the sole authority for terminal payload. Delivery never creates failures.
code('Delivery context',"const c=$input.first().json;if(Date.now()>=Date.parse(c.deadline_at))return [];return [{json:c}];");
postJson('Deliver event',"={{ $('Entry').first().json.config.backendOrigin + '/api/workflows/extraction/events' }}",'={{ $json.event }}',{...full,timeout:"={{ Math.max(1,Math.min(30000,Date.parse($json.deadline_at)-Date.now())) }}"});
code('Check acknowledgement',`const context=$('Delivery context').item.json;
const decision=callbackDecision($input.first().json,context,context.retry_count);
return [{json:{...context,...decision}}];`,true);
iff('Retry callback','={{ $json.retry }}');
node('Callback backoff','wait',1.1,{resume:'timeInterval',amount:'={{ $json.delaySeconds }}',unit:'seconds'},{webhookId:'reink-callback-backoff'});
edge('Extraction webhook','Entry');edge('Entry','Dispatch permitted');edge('Dispatch permitted','Accept dispatch');edge('Dispatch permitted','Reject dispatch',1);edge('Accept dispatch','Claim attempt');edge('Claim attempt','Claim gate');edge('Claim gate','Owned active attempt');edge('Owned active attempt','Fetch original');edge('Fetch original','Prepare document');edge('Prepare document','Document ready');edge('Document ready','LandingAI selected');edge('Document ready','Freeze event',1);edge('LandingAI selected','LandingAI Parse');edge('LandingAI selected','OpenAI Responses',1);edge('LandingAI Parse','Prepare markdown');edge('Prepare markdown','Markdown ready');edge('Markdown ready','LandingAI Extract');edge('Markdown ready','Freeze event',1);edge('LandingAI Extract','Normalize LandingAI');edge('Normalize LandingAI','Freeze event');edge('OpenAI Responses','Normalize OpenAI');edge('Normalize OpenAI','Freeze event');edge('Freeze event','Delivery context');edge('Delivery context','Deliver event');edge('Deliver event','Check acknowledgement');edge('Check acknowledgement','Retry callback');edge('Retry callback','Callback backoff');edge('Callback backoff','Delivery context');
const workflow={name:'re-ink extraction v1 (bind credentials before activation)',active:false,nodes,connections,settings:{executionOrder:'v1',saveDataErrorExecution:'all',saveDataSuccessExecution:'none',saveManualExecutions:false,saveExecutionProgress:false,executionTimeout:660},pinData:{},tags:[]};
fs.writeFileSync(path.join(dir,'reink-extraction-v1.json'),JSON.stringify(workflow,null,2)+'\n');
