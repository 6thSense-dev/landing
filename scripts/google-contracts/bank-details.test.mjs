import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHmac} from 'node:crypto';
import vm from 'node:vm';
const source=readFileSync(new URL('./BankDetails.gs',import.meta.url),'utf8');
const secret='test-only-secret-'.repeat(3);
function fixture() {
  const rows=[['Contributor ID','Contributor name','Account holder','Bank','Account number','Submitted at (UTC)','Submission ID','Status','Notice version','Notice SHA-256','Consent receipt']];
  let sharing='PRIVATE',locked=false,flushes=0;
  const properties={BANK_DETAILS_SECRET:secret};
  const range=(row=1,col=1,height=rows.length,width=11)=>({setNumberFormat(){return this;},setValues(values){values.forEach((r,i)=>rows[row-1+i]=r);return this;},getValues:()=>rows.slice(row-1,row-1+height).map(r=>r.slice(col-1,col-1+width)),getDisplayValues:()=>rows.slice(row-1,row-1+height).map(r=>r.map(String))});
  const tab={getRange:range,getDataRange:()=>range(),getLastRow:()=>rows.length,getSheetId:()=>123,deleteRow:i=>rows.splice(i-1,1)};
  const ctx=vm.createContext({Date,PropertiesService:{getScriptProperties:()=>({getProperty:key=>properties[key],setProperty:(key,value)=>{properties[key]=value;}})},
    Utilities:{Charset:{UTF_8:'utf8'},computeHmacSha256Signature:(data,key)=>[...createHmac('sha256',key).update(data).digest()]},
    DriveApp:{Access:{PRIVATE:'PRIVATE'},getFileById:()=>({getSharingAccess:()=>sharing})},
    SpreadsheetApp:{openById:()=>({getSheetByName:()=>tab}),flush:()=>{flushes++;}},
    LockService:{getScriptLock:()=>({tryLock:()=>!locked,releaseLock:()=>{}})}});
  vm.runInContext(source,ctx);
  const signed=(data,timestamp=String(Math.floor(Date.now()/1000)))=>{const payload=JSON.stringify(data);return{timestamp,payload,signature:createHmac('sha256',secret).update(timestamp+'.'+payload).digest('hex')};};
  return {ctx,rows,signed,setSharing:v=>sharing=v,setLocked:v=>locked=v,getFlushes:()=>flushes};
}
const submission=()=>({action:'submit',contributorId:8,contributorName:'테스트',operationId:'a1a1a1a1-1234-4567-8123-a1a1a1a1a1a1',values:{accountHolderName:'테스트',bankName:'Test Bank',accountNumber:'001234567890'},consent:{notice:{version:'test',sha256:'a'.repeat(64)},choices:{collects_details:true,shares_details:true,international_transfer:true,owns_account:true}}});
test('writes once, preserves leading zeros and returns a masked read-back receipt',()=>{
  const f=fixture(),data=submission();
  const saved=f.ctx.bankRequest(f.signed(data));
  assert.equal(saved.ok,true);assert.equal(saved.bank.maskedAccount,'•••• 7890');
  assert.equal(f.rows[1][4],'001234567890');assert.equal(f.getFlushes(),1);
  data.operationId='b1b1b1b1-1234-4567-8123-b1b1b1b1b1b1';data.values.accountNumber='999999999999';
  assert.equal(f.ctx.bankRequest(f.signed(data)).bank.submissionId,saved.bank.submissionId);
  assert.equal(f.rows.length,2);assert.equal(f.rows[1][4],'001234567890');
  assert.equal(f.ctx.bankRequest(f.signed({action:'lookup',contributorId:8})).bank.maskedAccount,'•••• 7890');
  assert.equal(f.ctx.bankRequest(f.signed({action:'lookup',contributorId:9})).bank,null);
  assert.ok(!JSON.stringify(saved).includes('001234567890'));
});
test('rejects tampered, expired and missing authentication before writing',()=>{
  const f=fixture(),e=f.signed(submission());e.payload=e.payload.replace('Test Bank','Other Bank');
  assert.equal(f.ctx.bankRequest(e).ok,false);
  assert.equal(f.ctx.bankRequest(f.signed(submission(),'1000000000')).ok,false);
  assert.equal(f.ctx.bankRequest({}).ok,false);assert.equal(f.rows.length,1);
});
test('private workbook, consent, schema and lock failures never write',()=>{
  const f=fixture();f.setSharing('ANYONE');assert.throws(()=>f.ctx.bankRequest(f.signed(submission())));
  f.setSharing('PRIVATE');f.setLocked(true);assert.equal(f.ctx.bankRequest(f.signed(submission())).ok,false);
  f.setLocked(false);const data=submission();data.consent.choices.owns_account=false;
  assert.equal(f.ctx.bankRequest(f.signed(data)).ok,false);
  assert.equal(f.rows.length,1);f.rows[0][0]='renamed';assert.throws(()=>f.ctx.bankRequest(f.signed(submission())));
});
test('formula-like labels are escaped and duplicate contributor rows fail closed',()=>{
  const f=fixture(),data=submission();data.values.accountHolderName='=IMPORTXML("bad")';
  f.ctx.bankRequest(f.signed(data));assert.equal(f.rows[1][2][0],"'");
  f.rows.push([...f.rows[1]]);assert.throws(()=>f.ctx.bankRequest(f.signed(data)),/duplicate/);
});

test('deletion removes full rows and tombstones both existing and missing submissions',()=>{
  for(const savedFirst of [true,false]) {
    const f=fixture(),data=submission();
    if(savedFirst) f.ctx.bankRequest(f.signed(data));
    const result=f.ctx.bankRequest(f.signed({action:'delete',contributorId:8}));
    assert.equal(result.deleted,true);assert.equal(f.rows.length,1);
    assert.equal(f.ctx.bankRequest(f.signed(data)).ok,false);
    assert.equal(f.ctx.bankRequest(f.signed({action:'lookup',contributorId:8})).bank,null);
    assert.equal(f.ctx.bankRequest(f.signed({action:'delete',contributorId:8})).deleted,true);
  }
});
