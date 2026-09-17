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
test('spreadsheet formulas are escaped while names remain readable',()=>{
 const c=context();for(const value of ['=IMPORTXML("https://bad")','+821012345678','@evil','-1','\tcmd'])assert.equal(c.safeCell(value),"'"+value);
 assert.equal(c.safeCell('한규태'),'한규태');
});
test('bridge uses signed receipt phone, ignores edited register phone and authenticates exact bytes',()=>{
 const receipt={form_id:'form',response_id:'r',version:'v',terms_sha256:'a'.repeat(64),signature:'Test',signed_at:'2026-09-18T00:00:00Z',accepted:{adult:true},answers:{phoneItem:'+82 10 1234 5678'}};
 const text=JSON.stringify(receipt),hash=createHash('sha256').update(text).digest('hex');
 const row=['id','Test','+821099998888','','Contracted','','','','','file',hash,'',null];
 const props={CONTRACT_SYNC_SECRET:'secret',CONTRACT_SYNC_URL:'https://example.invalid/sync',CONTRACT_ITEM_IDS:'{"phone":"phoneItem"}'};
 let request;
 const c=context({PropertiesService:{getScriptProperties:()=>({getProperty:k=>props[k]})},DriveApp:{getFileById:()=>({getBlob:()=>({getDataAsString:()=>text})})},
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
