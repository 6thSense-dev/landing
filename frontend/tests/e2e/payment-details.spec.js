import { test, expect } from '@playwright/test';
const choices = { collects_details:'Collect my details', shares_details:'Store in the private spreadsheet', international_transfer:'Process overseas', owns_account:'My own account' };
const notice = { version:'TEST-SHEET-1', sha256:'a'.repeat(64), locales:{
  en:{title:'How we store payment details',paragraphs:['Full details are stored in the private payment spreadsheet.'],choices},
  ko:{title:'지급정보 저장 안내',paragraphs:['비공개 지급정보 스프레드시트에 저장됩니다.'],choices},
}};
const fields = [{key:'accountHolderName',required:true,maxLength:100},{key:'bankName',required:true,maxLength:100},{key:'accountNumber',required:true,minLength:6,maxLength:50}];
async function mock(page) {
  const state={bank:null,writes:[],fail:false,saveDespiteFailure:false,notice};
  await page.addInitScript(()=>sessionStorage.setItem('6thsense-contributor-session',JSON.stringify({access:'test-access',refresh:'test-refresh',expires:Date.now()+900000})));
  await page.route('**/api/contributor/configuration',r=>r.fulfill({json:{identity:{region:'us-west-2',clientId:'testclient1234'}}}));
  await page.route('https://cognito-idp.us-west-2.amazonaws.com/**',r=>r.fulfill({json:{}}));
  await page.route('**/api/form-contracts/configuration',r=>r.fulfill({status:503,json:{}}));
  await page.route('**/api/uploads/info',r=>r.fulfill({status:403,json:{detail:'camera_approval_required'}}));
  await page.route('**/api/contributor/bank/**',route=>{
    const req=route.request(),path=new URL(req.url()).pathname;
    expect(req.headers().authorization).toBe('Bearer test-access');
    if(path.endsWith('/setup')) return route.fulfill({json:{country:'KR',notice:state.notice,bank:state.bank}});
    const body=req.postDataJSON();
    for(const key of Object.keys(choices)) expect(body[key]).toBe(true);
    if(path.endsWith('/requirements')) return route.fulfill({json:{country:'KR',currency:'KRW',fields}});
    state.writes.push(body);
    if(!state.fail||state.saveDespiteFailure) state.bank={status:'sheet_saved',submissionId:body.operation_id,submittedAt:'2026-09-19T10:00:00Z',accountHolderName:body.values.accountHolderName,bankLabel:body.values.bankName,maskedAccount:'•••• 7890'};
    if(state.fail) return route.abort('failed');
    return route.fulfill({json:state.bank});
  });
  return state;
}
async function enter(page) {
  await page.goto('/upload#payment-details');
  await page.getByRole('button',{name:'Add bank details',exact:true}).click();
  await expect(page.getByRole('button',{name:'Continue to bank details',exact:true})).toBeDisabled();
  for(const label of Object.values(choices)) await page.getByRole('checkbox',{name:label,exact:true}).check();
  await page.getByRole('button',{name:'Continue to bank details',exact:true}).click();
  await page.getByLabel('Account holder name',{exact:true}).fill('테스트');
  await page.getByLabel('Bank name',{exact:true}).fill('신한은행');
  await page.getByLabel('Account number',{exact:true}).fill('001234567890');
}
test('saves three fields with consent and shows the masked receipt before camera approval',async({page})=>{
  const state=await mock(page);await enter(page);
  await page.getByRole('button',{name:'Save bank details',exact:true}).click();
  await expect(page.getByText('Bank details saved',{exact:true})).toBeVisible();
  expect(Object.keys(state.writes[0].values).sort()).toEqual(['accountHolderName','accountNumber','bankName']);
  await expect(page.getByText('테스트 · 신한은행 · •••• 7890',{exact:true})).toBeVisible();
  await expect(page.locator('#payment-details')).not.toContainText('001234567890');
});
test('failed request retains input, allows safe retry, and makes no false success claim',async({page})=>{
  const state=await mock(page);state.fail=true;await enter(page);
  await page.getByRole('button',{name:'Save bank details',exact:true}).click();
  await expect(page.getByText('Save not confirmed',{exact:true})).toBeVisible();
  await expect(page.getByLabel('Account number',{exact:true})).toHaveValue('001234567890');
  await expect(page.getByText('Bank details saved',{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Check saved status',exact:true}).click();
  await expect(page.getByLabel('Account number',{exact:true})).toHaveValue('001234567890');
  state.fail=false;
  await page.getByRole('button',{name:'Save bank details',exact:true}).click();
  await expect(page.getByText('Bank details saved',{exact:true})).toBeVisible();
  expect(state.writes[0].operation_id).toBe(state.writes[1].operation_id);
});
test('refresh recovers a successful save after a lost response without resubmitting',async({page})=>{
  const state=await mock(page);state.fail=true;state.saveDespiteFailure=true;await enter(page);
  await page.getByRole('button',{name:'Save bank details',exact:true}).click();
  await expect(page.getByText('Save not confirmed',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Check saved status',exact:true}).click();
  await expect(page.getByText('Bank details saved',{exact:true})).toBeVisible();
  expect(state.writes).toHaveLength(1);
});
test('changing language keeps all entered details',async({page})=>{
  await mock(page);await enter(page);
  await page.getByRole('button',{name:'한국어',exact:true}).click();
  await expect(page.getByLabel('예금주명',{exact:true})).toHaveValue('테스트');
  await expect(page.getByLabel('계좌번호',{exact:true})).toHaveValue('001234567890');
  await page.getByRole('button',{name:'계좌정보 저장하기',exact:true}).click();
  await expect(page.getByText('계좌정보 저장 완료',{exact:true})).toBeVisible();
});
