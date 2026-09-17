/* Google Form is the contract source; Sheet is its staff register.
 * This file never accepts, stores or forwards a password and never sends email.
 * CONTRACT_SPEC is generated separately from the exact reviewed legal text.
 */
const CONTRACT_SHEET_ID = '1ZJZ_H4ZIWRl_c6QngmsDTfcAhQnbN6vrLbUnpPd_CPg';
const LEGACY_FORM_ID = '1nPiJ463QKCwJy5HDYaR063eZpFDrI_Ad-iLS6Imiyh0';
const REGISTER_HEADERS = ['Contract ID','Full name','Phone','Email','Status','Signed at','Contract version','Form response ID','Form ID','Receipt file ID','Receipt SHA-256','Website status','Existing Ops contributor ID','Camera ID','Camera handed over at','Camera returned at','Permissions status','Last sync','Sync issue'];

function contractHash(text) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,text,Utilities.Charset.UTF_8)
    .map(b=>('0'+((b+256)%256).toString(16)).slice(-2)).join('');
}
function safeCell(text) {
  const value=String(text===undefined||text===null?'':text);
  return /^[=+\-@\t\r]/.test(value)?"'"+value:value;
}
function contractRegister() {
  const book=SpreadsheetApp.openById(CONTRACT_SHEET_ID);
  let sheet=book.getSheetByName('Contractors');
  if(!sheet){sheet=book.insertSheet('Contractors');sheet.appendRow(REGISTER_HEADERS);sheet.setFrozenRows(1);sheet.getRange(1,1,1,REGISTER_HEADERS.length).setFontWeight('bold');sheet.getRange('C:C').setNumberFormat('@');}
  if(JSON.stringify(sheet.getRange(1,1,1,REGISTER_HEADERS.length).getValues()[0])!==JSON.stringify(REGISTER_HEADERS))throw Error('Register columns changed; review before writing');
  return sheet;
}
function formShape(form) {
  return {title:form.getTitle(),description:form.getDescription(),items:form.getItems().map(raw=>{
    const methods={TEXT:'asTextItem',CHECKBOX:'asCheckboxItem',MULTIPLE_CHOICE:'asMultipleChoiceItem',PARAGRAPH_TEXT:'asParagraphTextItem'};
    const type=String(raw.getType()),item=methods[type]?raw[methods[type]]():raw;
    return {id:String(raw.getId()),type:type,title:raw.getTitle(),help:raw.getHelpText(),required:item.isRequired?item.isRequired():false,choices:item.getChoices?item.getChoices().map(c=>c.getValue()):[]};
  })};
}
function prepareContractRegisterDraft() {
  const p=PropertiesService.getScriptProperties();
  if(p.getProperty('CONTRACT_DRAFT_COMPLETE')==='true'){
    console.log(JSON.stringify({form:FormApp.openById(p.getProperty('CONTRACT_FORM_ID')).getEditUrl(),sheet:'https://docs.google.com/spreadsheets/d/'+CONTRACT_SHEET_ID+'/edit',published:false}));return;
  }
  const existing=p.getProperty('CONTRACT_FORM_ID');
  const form=existing?FormApp.openById(existing):FormApp.create(CONTRACT_SPEC.title,false);
  if(form.isPublished()||form.getResponses().length)throw Error('Cannot rebuild a published or signed form');
  // Resume an interrupted draft without creating another form.
  if(existing)while(form.getItems().length)form.deleteItem(form.getItems().length-1);
  p.setProperty('CONTRACT_FORM_ID',form.getId());
  form.setDescription(CONTRACT_SPEC.description).setProgressBar(true).setAllowResponseEdits(false)
    .setPublishingSummary(false).setLimitOneResponsePerUser(false).setCollectEmail(false)
    .setConfirmationMessage(CONTRACT_SPEC.confirmation);
  const ids={};
  CONTRACT_SPEC.sections.forEach((s,index)=>{
    const header=index===0?form.addSectionHeaderItem():form.addPageBreakItem();
    header.setTitle(s.title).setHelpText(s.description||'');
    (s.blocks||[]).forEach(b=>form.addSectionHeaderItem().setTitle(b.title).setHelpText(b.text));
    (s.questions||[]).forEach(q=>{
      let item;
      if(q.type==='checkbox')item=form.addCheckboxItem().setChoiceValues(q.options);
      else if(q.type==='choice')item=form.addMultipleChoiceItem().setChoiceValues(q.options);
      else if(q.type==='paragraph')item=form.addParagraphTextItem();
      else{
        item=form.addTextItem();
        if(q.pattern)item.setValidation(FormApp.createTextValidation().requireTextMatchesPattern(q.pattern).setHelpText(q.validationHelp||'형식을 확인해 주세요. / Check the format.').build());
        else if(q.type==='email')item.setValidation(FormApp.createTextValidation().requireTextIsEmail().build());
      }
      item.setTitle(q.title).setRequired(q.required!==false);if(q.help)item.setHelpText(q.help);
      ids[q.id]=String(item.getId());
    });
  });
  form.setDestination(FormApp.DestinationType.SPREADSHEET,CONTRACT_SHEET_ID);
  const folder=DriveApp.createFolder('6thSense Contractor Agreements — private source records');
  const source=folder.createFile('contract-review-'+CONTRACT_SPEC.version+'.json',JSON.stringify(CONTRACT_SPEC,null,2),MimeType.PLAIN_TEXT);
  p.setProperties({CONTRACT_ITEM_IDS:JSON.stringify(ids),CONTRACT_RECEIPT_FOLDER:folder.getId(),CONTRACT_SOURCE_FILE:source.getId(),CONTRACT_DRAFT_COMPLETE:'true'});
  const sheet=contractRegister();
  if(!SpreadsheetApp.openById(CONTRACT_SHEET_ID).getSheetByName('Camera assignments')){
    const cams=SpreadsheetApp.openById(CONTRACT_SHEET_ID).insertSheet('Camera assignments');
    cams.appendRow(['Assignment ID','Contract ID','Camera ID','Effective start','Effective end','Handover checked by','Return checked by','Permission record','Notes']);cams.setFrozenRows(1);
  }
  // Prior application responses are not contract acceptances. No existing rows change.
  const known=new Set(sheet.getDataRange().getValues().slice(1).map(r=>String(r[7])));
  FormApp.openById(LEGACY_FORM_ID).getResponses().forEach(response=>{
    if(known.has(response.getId()))return;
    const answers={};response.getItemResponses().forEach(r=>answers[r.getItem().getTitle()]=r.getResponse());
    const get=pattern=>{const key=Object.keys(answers).find(k=>pattern.test(k));return key?String(answers[key]):'';};
    const row=Array(REGISTER_HEADERS.length).fill('');
    row[0]='APP-'+contractHash(LEGACY_FORM_ID+':'+response.getId()).slice(0,16);
    row[1]=safeCell(get(/^성명 \/ Full legal name$/));row[2]=safeCell(get(/Mobile number/));row[3]=safeCell(get(/^이메일/));
    row[4]='Application only — contract not signed';row[5]=response.getTimestamp().toISOString();row[6]='Application-2026-09-17';row[7]=response.getId();row[8]=LEGACY_FORM_ID;row[11]='Not activated';
    sheet.appendRow(row);
  });
  console.log(JSON.stringify({form:form.getEditUrl(),preview:form.getPublishedUrl(),sheet:'https://docs.google.com/spreadsheets/d/'+CONTRACT_SHEET_ID+'/edit',source:source.getUrl(),published:form.isPublished(),legacyApplicationCount:FormApp.openById(LEGACY_FORM_ID).getResponses().length}));
}

function receiveContractSubmission(event) {
  const lock=LockService.getScriptLock();lock.waitLock(30000);
  try {recordContractSubmission(event);} finally {lock.releaseLock();}
}
function recordContractSubmission(event) {
    const p=PropertiesService.getScriptProperties();
    if(p.getProperty('CONTRACT_RELEASED')!=='true')throw Error('Contract is not released');
    if(!event||!event.response||event.source.getId()!==p.getProperty('CONTRACT_FORM_ID'))throw Error('Unexpected form event');
    const shapeHash=contractHash(JSON.stringify(formShape(event.source)));
    if(shapeHash!==p.getProperty('CONTRACT_FORM_SHAPE_SHA256'))throw Error('Signed form changed; preserve responses and review');
    const ids=JSON.parse(p.getProperty('CONTRACT_ITEM_IDS')),answer={};
    event.response.getItemResponses().forEach(r=>answer[String(r.getItem().getId())]=r.getResponse());
    const value=id=>answer[ids[id]];
    const accepted={};
    for(const id of ['participation','collection','privacy','international_transfer','adult']){
      const expected=CONTRACT_SPEC.sections.flatMap(s=>s.questions||[]).find(q=>q.id===id).options[0];
      accepted[id]=Array.isArray(value(id))&&value(id).length===1&&value(id)[0]===expected;
      if(!accepted[id])throw Error('Required acceptance missing');
    }
    const phone=String(value('phone')).replace(/[\s()-]/g,'');
    if(!/^\+8210[0-9]{8}$/.test(phone))throw Error('Invalid Korean phone');
    const name=String(value('signature')||'').trim();if(!name)throw Error('Signature missing');
    const responseId=event.response.getId(),formId=event.source.getId();
    const contractId=contractHash(formId+':'+responseId);
    const sheet=contractRegister(),rows=sheet.getDataRange().getValues();
    if(rows.slice(1).some(r=>r[0]===contractId))return; // idempotent duplicate event
    const receipt={contract_id:contractId,form_id:formId,response_id:responseId,signed_at:event.response.getTimestamp().toISOString(),version:CONTRACT_SPEC.version,terms_sha256:CONTRACT_SPEC.termsSha256,signature:name,accepted:accepted,answers:answer,source_file_id:p.getProperty('CONTRACT_SOURCE_FILE'),shape_sha256:shapeHash};
    const receiptText=JSON.stringify(receipt),digest=contractHash(receiptText);
    const folder=DriveApp.getFolderById(p.getProperty('CONTRACT_RECEIPT_FOLDER'));
    const file=folder.createFile(contractId+'.json',receiptText,MimeType.PLAIN_TEXT);
    const row=Array(REGISTER_HEADERS.length).fill('');
    row[0]=contractId;row[1]=safeCell(name);row[2]=safeCell(phone);row[3]=safeCell(value('email'));row[4]='Contracted';row[5]=receipt.signed_at;row[6]=CONTRACT_SPEC.version;row[7]=responseId;row[8]=formId;row[9]=file.getId();row[10]=digest;row[11]='Password and phone verification pending';row[16]='Needs physical handover and permission check';
    sheet.appendRow(row);
    // Network failure does not undo the contract: the retry task catches up.
    syncContractRow(sheet,sheet.getLastRow());
}

function syncContractRow(sheet,rowNumber) {
  const p=PropertiesService.getScriptProperties(),row=sheet.getRange(rowNumber,1,1,REGISTER_HEADERS.length).getValues()[0];
  if(row[4]!=='Contracted'&&row[4]!=='Withdrawn')return;
  const secret=p.getProperty('CONTRACT_SYNC_SECRET'),endpoint=p.getProperty('CONTRACT_SYNC_URL');
  if(!secret||!endpoint){sheet.getRange(rowNumber,19).setValue('Website bridge not configured');return;}
  const receipt=JSON.parse(DriveApp.getFileById(row[9]).getBlob().getDataAsString());
  if(contractHash(JSON.stringify(receipt))!==row[10])throw Error('Receipt integrity failure');
  const payload={response_id:receipt.response_id,form_id:receipt.form_id,version:receipt.version,terms_sha256:receipt.terms_sha256,receipt_sha256:row[10],phone:String(receipt.answers[JSON.parse(p.getProperty('CONTRACT_ITEM_IDS')).phone]).replace(/[\s()-]/g,''),name:receipt.signature,signature:receipt.signature,signed_at:receipt.signed_at,accepted:receipt.accepted,wearer_id:row[12]?Number(row[12]):null,state:row[4]==='Withdrawn'?'withdrawn':'signed'};
  const body=JSON.stringify(payload),timestamp=String(Math.floor(Date.now()/1000));
  const signature=Utilities.computeHmacSha256Signature(timestamp+'.'+body,secret,Utilities.Charset.UTF_8).map(b=>('0'+((b+256)%256).toString(16)).slice(-2)).join('');
  try{
    const response=UrlFetchApp.fetch(endpoint,{method:'post',contentType:'application/json',payload:body,headers:{'X-Form-Timestamp':timestamp,'X-Form-Signature':signature},muteHttpExceptions:true});
    if(response.getResponseCode()===200){const result=JSON.parse(response.getContentText());sheet.getRange(rowNumber,12).setValue(result.linked?'Login linked':'Ready for secure password setup');sheet.getRange(rowNumber,18,1,2).setValues([[new Date().toISOString(),'']]);}
    else sheet.getRange(rowNumber,19).setValue('Sync needs review (HTTP '+response.getResponseCode()+')');
  }catch(e){sheet.getRange(rowNumber,19).setValue('Sync pending; automatic retry');}
}
function retryContractSync() {
  const lock=LockService.getScriptLock();if(!lock.tryLock(1000))return;
  try{
    const p=PropertiesService.getScriptProperties();
    if(p.getProperty('CONTRACT_RELEASED')!=='true')return;
    const form=FormApp.openById(p.getProperty('CONTRACT_FORM_ID'));
    // Recover missed triggers as well as failed network calls. Each response is idempotent.
    const sheet=contractRegister(),known=new Set(sheet.getDataRange().getValues().slice(1).map(r=>String(r[7])));
    form.getResponses().forEach(response=>{if(!known.has(response.getId()))recordContractSubmission({source:form,response:response});});
    for(let r=2;r<=sheet.getLastRow();r++){
      try{syncContractRow(sheet,r);}catch(e){sheet.getRange(r,19).setValue('Receipt needs staff review');}
    }
  }finally{lock.releaseLock();}
}

function auditContractDraft() {
  const p=PropertiesService.getScriptProperties(),f=FormApp.openById(p.getProperty('CONTRACT_FORM_ID'));
  console.log(JSON.stringify({form:f.getEditUrl(),published:f.isPublished(),responses:f.getResponses().length,questions:Object.keys(JSON.parse(p.getProperty('CONTRACT_ITEM_IDS'))).length,hasPasswordQuestion:f.getItems().some(i=>/^(password|비밀번호)/i.test(i.getTitle())),sourceSaved:!!p.getProperty('CONTRACT_SOURCE_FILE'),reviewIssues:CONTRACT_SPEC.reviewIssues,registerRows:contractRegister().getLastRow()-1}));
}

function releaseReviewedContractForm() {
  // Publishing is a separate concrete step after all text and provider schedules are final.
  if(CONTRACT_SPEC.reviewIssues.length)throw Error('Complete final contract decisions before publication');
  const p=PropertiesService.getScriptProperties(),f=FormApp.openById(p.getProperty('CONTRACT_FORM_ID'));
  if(!p.getProperty('CONTRACT_SYNC_SECRET')||!p.getProperty('CONTRACT_SYNC_URL'))throw Error('Website bridge is not ready');
  if(f.getResponses().length)throw Error('New version required after responses');
  p.setProperty('CONTRACT_FORM_SHAPE_SHA256',contractHash(JSON.stringify(formShape(f))));
  const handlers=ScriptApp.getProjectTriggers().map(t=>t.getHandlerFunction());
  if(!handlers.includes('receiveContractSubmission'))ScriptApp.newTrigger('receiveContractSubmission').forForm(f).onFormSubmit().create();
  if(!handlers.includes('retryContractSync'))ScriptApp.newTrigger('retryContractSync').timeBased().everyMinutes(5).create();
  p.setProperty('CONTRACT_RELEASED','true');
  f.setPublished(true);f.setAcceptingResponses(true);
  console.log(JSON.stringify({published:f.isPublished(),form:f.getPublishedUrl(),version:CONTRACT_SPEC.version}));
}

// Repairs an interrupted draft using its existing questions; never changes a signed form.
function finishContractRegisterDraft() {
  const p=PropertiesService.getScriptProperties(),form=FormApp.openById(p.getProperty('CONTRACT_FORM_ID'));
  if(form.isPublished()||form.getResponses().length)throw Error('Cannot change a published or signed form');
  const questions=CONTRACT_SPEC.sections.flatMap(s=>s.questions||[]),ids={};
  questions.forEach(q=>{
    const match=form.getItems().filter(i=>i.getTitle()===q.title);
    if(match.length!==1)throw Error('Draft question missing or duplicated: '+q.id);
    ids[q.id]=String(match[0].getId());
  });
  // The source is private; original Form responses stay in their existing linked tab.
  let folder;
  if(p.getProperty('CONTRACT_RECEIPT_FOLDER'))folder=DriveApp.getFolderById(p.getProperty('CONTRACT_RECEIPT_FOLDER'));
  else{folder=DriveApp.createFolder('6thSense Contractor Agreements — private source records');p.setProperty('CONTRACT_RECEIPT_FOLDER',folder.getId());}
  const source=folder.createFile('contract-review-'+CONTRACT_SPEC.version+'.json',JSON.stringify(CONTRACT_SPEC,null,2),MimeType.PLAIN_TEXT);
  p.setProperties({CONTRACT_ITEM_IDS:JSON.stringify(ids),CONTRACT_SOURCE_FILE:source.getId()});
  const book=SpreadsheetApp.openById(CONTRACT_SHEET_ID);contractRegister();
  if(!book.getSheetByName('Camera assignments')){
    const cams=book.insertSheet('Camera assignments');
    cams.appendRow(['Assignment ID','Contract ID','Camera ID','Effective start','Effective end','Handover checked by','Return checked by','Permission record','Notes']);cams.setFrozenRows(1);
  }
  form.setDescription(CONTRACT_SPEC.description).setConfirmationMessage(CONTRACT_SPEC.confirmation);
  for(const section of CONTRACT_SPEC.sections)for(const block of section.blocks||[]){
    const item=form.getItems().find(i=>i.getTitle()===block.title);
    if(!item)throw Error('Draft clause missing: '+block.title);
    item.asSectionHeaderItem().setHelpText(block.text);
  }
  p.setProperty('CONTRACT_DRAFT_COMPLETE','true');
  auditContractDraft();
}
