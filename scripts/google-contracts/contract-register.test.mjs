import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import { createHash, createHmac } from 'node:crypto';
const source=readFileSync(new URL('./ContractRegister.gs',import.meta.url),'utf8');
function context(extra={}){
 const ctx=vm.createContext({Utilities:{DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},
 computeDigest:(_,text)=>[...createHash('sha256').update(text).digest()],
 computeHmacSha256Signature:(text,key)=>[...createHmac('sha256',key).update(text).digest()]},...extra});
 vm.runInContext(source,ctx);return ctx;
}
const sha=text=>createHash('sha256').update(text).digest('hex');
function releaseFixture(){
 const formShape={title:'Signed terms',description:'Company offer',items:[]};
 const source={format:'6thsense-contract-release-v1',form_id:'form',version:'v',terms_sha256:'a'.repeat(64),
  shape_sha256:sha(JSON.stringify(formShape)),form_shape:formShape,spec:{version:'v',termsSha256:'a'.repeat(64),sections:[]},item_ids:{phone:'phoneItem'}};
 const sourceText=JSON.stringify(source),metadata={source_file_id:'source',source_sha256:sha(sourceText),form_id:source.form_id,version:source.version,terms_sha256:source.terms_sha256,shape_sha256:source.shape_sha256};
 const receipt={contract_id:sha('form:r'),form_id:'form',response_id:'r',version:'v',terms_sha256:source.terms_sha256,shape_sha256:source.shape_sha256,
  source_file_id:'source',source_sha256:metadata.source_sha256,signature:'Test',signed_at:'2026-09-18T00:00:00Z',accepted:{adult:true},answers:{phoneItem:'+82 10 1234 5678'}};
 const text=JSON.stringify(receipt),row=[receipt.contract_id,'Test','+821099998888','','Contracted',receipt.signed_at,'v','r','form','file',sha(text),'',null];
 return {source,sourceText,metadata,receipt,text,row,drive:{getFileById:id=>({getBlob:()=>({getDataAsString:()=>id==='source'?sourceText:text})})}};
}
test('spreadsheet formulas are escaped while names remain readable',()=>{
 const c=context();for(const value of ['=IMPORTXML("https://bad")','+821012345678','@evil','-1','\tcmd'])assert.equal(c.safeCell(value),"'"+value);
 assert.equal(c.safeCell('한규태'),'한규태');
});
test('bridge uses signed receipt phone, ignores edited register phone and authenticates exact bytes',()=>{
 const {row,drive}=releaseFixture();
 const props={CONTRACT_SYNC_SECRET:'secret',CONTRACT_SYNC_URL:'https://example.invalid/sync',CONTRACT_ITEM_IDS:'{"phone":"phoneItem"}'};
 let request;
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k]})},DriveApp:drive,
 UrlFetchApp:{fetch:(url,payload)=>{request=payload;return{getResponseCode:()=>200,getContentText:()=>'{"linked":false}'}}}});
 const sheet={getRange:()=>({getValues:()=>[row],setValue:()=>{},setValues:()=>{}})};
 c.syncContractRow(sheet,2);
 const payload=JSON.parse(request.payload);assert.equal(payload.phone,'+821012345678');assert.ok(!('password' in payload));
 assert.equal(request.headers['X-Form-Signature'],createHmac('sha256','secret').update(request.headers['X-Form-Timestamp']+'.'+request.payload).digest('hex'));
 row[10]='f'.repeat(64);assert.throws(()=>c.syncContractRow(sheet,2),/integrity/);
});
test('unreleased forms cannot create signed rows or publish unfinished terms',()=>{
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:()=>null})},CONTRACT_SPEC:{reviewIssues:['recipient details incomplete']}});
 assert.throws(()=>c.recordContractSubmission({}),/not released/);
 assert.throws(()=>c.releaseReviewedContractForm(),/final contract decisions/);
});
test('a published form cannot be rebuilt even when setup completion flag is missing',()=>{
 let deleted=false;
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:k=>k==='CONTRACT_FORM_ID'?'existing':null})},FormApp:{openById:()=>({isPublished:()=>true,deleteItem:()=>{deleted=true}})}});
 assert.throws(()=>c.prepareContractRegisterDraft(),/published or signed/);assert.equal(deleted,false);
});

test('signed submission uses frozen terms despite mutable live spec, saves once, and rejects changed form or missing acceptance',()=>{
 const required=['participation','collection','privacy','international_transfer','adult'];
 const ids=Object.fromEntries([...required,'phone','signature','email'].map(id=>[id,id]));
 const answers=Object.fromEntries(required.map(id=>[id,['I agree']]));
 Object.assign(answers,{phone:'+82 10 1234 5678',signature:'  Contractor  ',email:'test@example.invalid'});
 const rows=[[]], receipts=[];
 const props={CONTRACT_RELEASED:'true',CONTRACT_FORM_ID:'form',CONTRACT_ITEM_IDS:JSON.stringify(ids),
  CONTRACT_FORM_SHAPE_SHA256:createHash('sha256').update('{}').digest('hex'),CONTRACT_RECEIPT_FOLDER:'folder',CONTRACT_SOURCE_FILE:'source'};
 const sheet={getDataRange:()=>({getValues:()=>rows}),appendRow:r=>rows.push(r),getLastRow:()=>rows.length};
 const frozenSource={form_id:'form',version:'v1',terms_sha256:'a'.repeat(64),shape_sha256:sha('{}'),item_ids:ids,
  spec:{sections:[{questions:required.map(id=>({id,options:['I agree']}))}]}};
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k]})},
  CONTRACT_SPEC:{version:'changed-live-version',termsSha256:'f'.repeat(64),sections:[]},
  MimeType:{PLAIN_TEXT:'text/plain'},DriveApp:{getFolderById:()=>({createFile:(name,text)=>{receipts.push(JSON.parse(text));return {getId:()=> 'receipt'}}})}});
 c.contractRegister=()=>sheet;c.formShape=()=>({});c.syncContractRow=()=>{};
 c.activeContractRelease=()=>({source:frozenSource,metadata:{source_file_id:'released-source',source_sha256:'c'.repeat(64)}});
 const event={source:{getId:()=> 'form'},response:{getId:()=> 'response',getTimestamp:()=>new Date('2026-09-18T00:00:00Z'),
  getItemResponses:()=>Object.entries(answers).map(([id,value])=>({getItem:()=>({getId:()=>id}),getResponse:()=>value}))}};
 c.recordContractSubmission(event);c.recordContractSubmission(event);
 assert.equal(rows.length,2);assert.equal(receipts.length,1);assert.equal(rows[1][4],'Contracted');
 assert.equal(receipts[0].signature,'Contractor');assert.equal(receipts[0].answers.phone,answers.phone);
 assert.equal(receipts[0].version,'v1');assert.equal(receipts[0].terms_sha256,'a'.repeat(64));assert.equal(receipts[0].source_file_id,'released-source');
 assert.equal(rows[1][10],createHash('sha256').update(JSON.stringify(receipts[0])).digest('hex'));
 c.formShape=()=>({changed:true});assert.throws(()=>c.recordContractSubmission(event),/form changed/);
 c.formShape=()=>({});answers.adult=[];
 assert.throws(()=>c.recordContractSubmission(event),/acceptance missing/);assert.equal(receipts.length,1);
});

test('missed triggers are recovered while legacy applications are never synced',()=>{
 const rows=[[],['old','','','','Application only','','','legacy'],['known','','','','Contracted','','','known-response']];
 const calls=[],saved=[];let released=false;
 const sheet={getDataRange:()=>({getValues:()=>rows}),getLastRow:()=>rows.length,getRange:(row,col)=>({setValue:value=>saved.push({row,col,value})})};
 const responses=['known-response','new-response'].map(id=>({getId:()=>id}));
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:k=>k==='CONTRACT_RELEASED'?'true':'form'})},
  FormApp:{openById:()=>({getResponses:()=>responses})},LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{released=true}})}});
 c.contractRegister=()=>sheet;
 c.recordContractSubmission=event=>{calls.push(event.response.getId());rows.push(['new','','','','Contracted','','','new-response']);};
 c.syncContractRow=(sheet,row)=>{if(row===3)throw Error('Corrupt receipt');};
 c.retryContractSync();
 assert.deepEqual(calls,['new-response']);assert.equal(released,true);
 assert.deepEqual(saved,[{row:3,col:19,value:'Receipt needs staff review'}]);
});

test('bridge network failure leaves signed state intact for automatic retry',()=>{
 const {row,drive}=releaseFixture();
 const writes=[];
 const props={CONTRACT_SYNC_SECRET:'test-secret',CONTRACT_SYNC_URL:'https://example.invalid',CONTRACT_ITEM_IDS:'{"phone":"phoneItem"}'};
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k]})},
  DriveApp:drive,UrlFetchApp:{fetch:()=>{throw Error('network')}}});
 c.syncContractRow({getRange:(r,col)=>({getValues:()=>[row],setValue:value=>writes.push({col,value})})},2);
 assert.equal(row[4],'Contracted');assert.deepEqual(writes,[{col:19,value:'Sync pending; automatic retry'}]);
 row[4]='Application only';writes.length=0;c.syncContractRow({getRange:()=>({getValues:()=>[row]})},2);assert.equal(writes.length,0);
});

test('valid receipts cannot be swapped into another register row to apply staff identity or withdrawal',()=>{
 const {row,drive}=releaseFixture();let requests=0;
 const props={CONTRACT_SYNC_SECRET:'test-secret',CONTRACT_SYNC_URL:'https://example.invalid'};
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k]})},DriveApp:drive,UrlFetchApp:{fetch:()=>{requests++;}}});
 for(const [column,value] of [[0,'wrong-contract'],[5,'2026-09-19T00:00:00Z'],[6,'wrong-version'],[7,'wrong-response'],[8,'wrong-form']]){
  const altered=[...row];altered[column]=value;altered[4]='Withdrawn';altered[12]=999;
  assert.throws(()=>c.syncContractRow({getRange:()=>({getValues:()=>[altered]})},2),/does not belong/);
 }
 assert.equal(requests,0);
});

test('released source and metadata must both match persisted hashes and full form shape',()=>{
 const f=releaseFixture(),props={CONTRACT_RELEASE_METADATA:JSON.stringify(f.metadata)};
 let stored=f.sourceText;
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k]})},DriveApp:{getFileById:()=>({getBlob:()=>({getDataAsString:()=>stored})})}});
 assert.equal(c.activeContractRelease().source.form_shape.description,'Company offer');
 stored+=' ';assert.throws(()=>c.activeContractRelease(),/integrity/);
 stored=f.sourceText;props.CONTRACT_RELEASE_METADATA=JSON.stringify({...f.metadata,version:'changed'});
 assert.throws(()=>c.activeContractRelease(),/metadata mismatch/);
 stored=JSON.stringify({...f.source,form_shape:{...f.source.form_shape,description:'changed'}});
 assert.throws(()=>c.readContractRelease('source',sha(stored)),/source mismatch/);
});

test('publication persists full participant-visible form before enabling responses and cannot replace release evidence',()=>{
 const props={CONTRACT_FORM_ID:'form',CONTRACT_SYNC_SECRET:'test-secret',CONTRACT_SYNC_URL:'https://example.invalid',CONTRACT_ITEM_IDS:'{"privacy":"privacy-question"}',CONTRACT_RECEIPT_FOLDER:'folder'};
 const saved=[];let published=false,accepting=false;
 const checkbox={getId:()=> 'privacy-question',getType:()=> 'CHECKBOX',getTitle:()=> 'Privacy acceptance',getHelpText:()=> 'Full notice here',
  asCheckboxItem:()=>({isRequired:()=>true,getChoices:()=>[{getValue:()=> 'I agree'}]})};
 const form={getId:()=> 'form',getTitle:()=> 'Contract',getDescription:()=> 'Company standing offer',getItems:()=>[checkbox],getResponses:()=>[],
  isPublished:()=>published,setPublished:value=>{assert.equal(saved.length,1);assert.ok(props.CONTRACT_RELEASE_METADATA);published=value;},setAcceptingResponses:value=>{accepting=value;},getPublishedUrl:()=> 'https://example.invalid/form'};
 const spec={version:'v1',termsSha256:'a'.repeat(64),reviewIssues:[],sections:[{questions:[{id:'privacy',options:['I agree']}]}]};
 const c=context({CONTRACT_SPEC:spec,console:{log:()=>{}},MimeType:{PLAIN_TEXT:'text/plain'},
  PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k],setProperty:(k,v)=>{props[k]=v;},setProperties:p=>Object.assign(props,p)})},
  FormApp:{openById:()=>form},DriveApp:{getFolderById:()=>({createFile:(name,text)=>{saved.push({name,text});return {getId:()=> 'released-source'};}}),getFileById:()=>({getBlob:()=>({getDataAsString:()=>saved[0].text})})},
  ScriptApp:{getProjectTriggers:()=>['receiveContractSubmission','retryContractSync'].map(name=>({getHandlerFunction:()=>name}))}});
 c.releaseReviewedContractForm();
 assert.equal(published,true);assert.equal(accepting,true);assert.equal(props.CONTRACT_RELEASED,'true');
 const stored=JSON.parse(saved[0].text),metadata=JSON.parse(props.CONTRACT_RELEASE_METADATA);
 assert.deepEqual(stored.form_shape,{title:'Contract',description:'Company standing offer',items:[{id:'privacy-question',type:'CHECKBOX',title:'Privacy acceptance',help:'Full notice here',required:true,choices:['I agree']}]});
 assert.deepEqual(stored.spec,spec);assert.equal(metadata.source_sha256,sha(saved[0].text));assert.equal(stored.shape_sha256,sha(JSON.stringify(stored.form_shape)));
 c.releaseReviewedContractForm();assert.equal(saved.length,1);
 spec.version='changed';assert.throws(()=>c.releaseReviewedContractForm(),/cannot be replaced/);assert.equal(saved.length,1);
});

test('one malformed missed response cannot block other imports or an existing withdrawal sync',()=>{
 const rows=[[],['withdrawn','','','','Withdrawn','','','withdrawn-response']];
 const imported=[],synced=[],props={CONTRACT_RELEASED:'true',CONTRACT_FORM_ID:'form'};let unlocked=false;
 const sheet={getDataRange:()=>({getValues:()=>rows}),getLastRow:()=>rows.length,getRange:()=>({setValue:()=>{}})};
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k],setProperty:(k,v)=>{props[k]=v;}})},
  FormApp:{openById:()=>({getResponses:()=>['bad-response','good-response'].map(id=>({getId:()=>id}))})},
  LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{unlocked=true;}})},console:{log:()=>{},warn:()=>{},error:()=>{}}});
 c.contractRegister=()=>sheet;
 c.recordContractSubmission=event=>{const id=event.response.getId();imported.push(id);if(id==='bad-response')throw Error('bad response');rows.push(['new','','','','Contracted','','',id]);};
 c.syncContractRow=(sheet,row)=>synced.push(rows[row-1][4]);
 c.retryContractSync();
 assert.deepEqual(imported,['bad-response','good-response']);
 assert.deepEqual(synced,['Withdrawn','Contracted']);assert.equal(unlocked,true);
});

test('draft refresh distinguishes a consent question from a section with the same title',()=>{
 for(const savedIds of [{international_transfer:'question'},{}]){
  const props={CONTRACT_FORM_ID:'form',CONTRACT_ITEM_IDS:JSON.stringify(savedIds),CONTRACT_RECEIPT_FOLDER:'folder'};
  let questionUpdated=false,reads=0;
  const heading={getId:()=> 'section',getTitle:()=> 'Transfer consent',getType:()=> 'PAGE_BREAK',setHelpText:()=>{}};
  const question={getId:()=> 'question',getTitle:()=> 'Transfer consent',getType:()=> 'CHECKBOX',setTitle:()=>{questionUpdated=true;},setHelpText:()=>{}};
  const form={isPublished:()=>false,getResponses:()=>[],getItems:()=>{reads++;return [heading,question];},setTitle:()=>form,setDescription:()=>form,setConfirmationMessage:()=>form};
  const c=context({CONTRACT_SPEC:{title:'Contract',version:'v1',sections:[{title:'Transfer consent',questions:[{id:'international_transfer',title:'Transfer consent'}]}]},
   PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k],setProperty:(k,v)=>{props[k]=v;},setProperties:p=>Object.assign(props,p)})},FormApp:{openById:()=>form},
   MimeType:{PLAIN_TEXT:'text/plain'},DriveApp:{getFolderById:()=>({createFile:()=>({getId:()=> 'source'})})},SpreadsheetApp:{openById:()=>({getSheetByName:()=>({})})}});
  c.contractRegister=()=>({});c.importLegacyApplicationsToRegister=()=>{};c.auditContractDraft=()=>{};
  c.finishContractRegisterDraft();assert.equal(questionUpdated,true);assert.equal(reads,1);assert.equal(JSON.parse(props.CONTRACT_ITEM_IDS).international_transfer,'question');
 }
});
