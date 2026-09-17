import { test, expect } from '@playwright/test';
async function mock(page,{resume=false}={}) {
  const calls=[];
  await page.route('**/api/form-contracts/configuration',r=>r.fulfill({json:{url:'https://docs.google.com/forms/d/e/test/viewform',version:'test',rate_krw_hour:11000}}));
  await page.route('**/api/contributor/configuration',r=>r.fulfill({json:{identity:{region:'us-west-2',clientId:'testclient1234'}}}));
  await page.route('https://cognito-idp.us-west-2.amazonaws.com/**',r=>{
    const action=r.request().headers()['x-amz-target'].split('.').pop(),body=r.request().postDataJSON();calls.push({action,body});
    if(action==='SignUp'&&resume)return r.fulfill({status:400,json:{__type:'UsernameExistsException'}});
    if(action==='ConfirmSignUp'&&body.ConfirmationCode==='000000')return r.fulfill({status:400,json:{__type:'CodeMismatchException'}});
    return r.fulfill({json:action==='InitiateAuth'?{AuthenticationResult:{AccessToken:'access',RefreshToken:'refresh',ExpiresIn:900}}:{}});
  });
  await page.route('**/api/form-contracts/activate',r=>{
    expect(r.request().headers().authorization).toBe('Bearer access');expect(r.request().postData()).toBe(null);
    return r.fulfill({json:{activated:true}});
  });
  await page.route('**/api/uploads/info',r=>r.fulfill({status:403,json:{detail:'camera_approval_required'}}));
  return calls;
}
test('form signup, wrong SMS code, resend, confirmation and camera handover gate',async({page},info)=>{
  const calls=await mock(page);await page.goto('/upload?activate=1');
  await page.getByLabel('Phone number',{exact:true}).fill('+821012345678');
  await page.getByLabel('Choose a password',{exact:false}).fill('ExamplePassword1');
  await page.getByRole('button',{name:'Sign up',exact:true}).click();
  await expect(page.locator('input[type=password]')).toHaveCount(0);
  await page.getByLabel('SMS verification code').fill('000000');
  await page.getByRole('button',{name:'Verify and continue'}).click();
  await expect(page.getByRole('alert')).toHaveText('The verification code does not match. Try again.');
  await page.getByRole('button',{name:'Resend code',exact:true}).click();
  await page.getByLabel('SMS verification code').fill('123456');
  await page.getByRole('button',{name:'Verify and continue'}).click();
  await expect(page.getByText('Phone verified. You can now sign in with your password.')).toBeVisible();
  await page.getByLabel('Phone number',{exact:false}).fill('+821012345678');
  await page.getByLabel('Password',{exact:true}).fill('ExamplePassword1');
  await page.getByRole('button',{name:'Sign in to upload'}).click();
  await expect(page.getByRole('heading',{name:/camera assignment is waiting/})).toBeVisible();
  await expect(page.locator('input[type=file]')).toHaveCount(0);
  expect(calls[0].body.ClientMetadata).toEqual({area_code:'korea666'});
  expect(calls.map(c=>c.action)).toEqual(['SignUp','ConfirmSignUp','ResendConfirmationCode','ConfirmSignUp','InitiateAuth']);
  expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('ExamplePassword1');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:info.outputPath('contract-camera-handover.png'),fullPage:true});
});
test('unfinished phone verification resumes after reload without password collection',async({page})=>{
  const calls=await mock(page,{resume:true});await page.goto('/upload?activate=1');
  await page.getByLabel('Phone number',{exact:true}).fill('+821012345678');
  await page.getByLabel('Choose a password',{exact:false}).fill('ExamplePassword1');
  await page.getByRole('button',{name:'Sign up',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('already has an account');
  await page.reload();
  await page.getByRole('button',{name:'Finish phone verification'}).click();
  await expect(page.locator('input[type=password]')).toHaveCount(0);
  await page.getByLabel('Phone number',{exact:true}).fill('+821012345678');
  await page.getByRole('button',{name:'Send verification code',exact:true}).click();
  await expect(page.getByLabel('SMS verification code')).toBeVisible();
  expect(calls.map(c=>c.action)).toEqual(['SignUp','ResendConfirmationCode']);
  expect(calls[1].body).not.toHaveProperty('Password');
});

for (const detail of ['contract_not_found', 'contract_region_mismatch']) {
  test(`existing contributor keeps upload access when form activation reports ${detail}`, async ({page}) => {
    await mock(page);
    await page.addInitScript(() => sessionStorage.setItem('6thsense-contributor-session', JSON.stringify({
      access: 'access', refresh: 'refresh', expires: Date.now() + 900000,
    })));
    await page.route('**/api/form-contracts/activate', r => r.fulfill({status: detail === 'contract_region_mismatch' ? 403 : 409, json: {detail}}));
    await page.route('**/api/uploads/info', r => r.fulfill({json: {name: 'Existing contributor', remaining_bytes: 1000, batches: []}}));
    await page.goto('/upload');
    await expect(page.getByText('Existing contributor', {exact: true})).toBeVisible();
    await expect(page.locator('input[type=file]')).toHaveCount(1);
  });
}

test('identity conflicts stop before upload access and show a recovery contact', async ({page}) => {
  await mock(page);
  await page.addInitScript(() => sessionStorage.setItem('6thsense-contributor-session', JSON.stringify({
    access: 'access', refresh: 'refresh', expires: Date.now() + 900000,
  })));
  let infoCalls = 0;
  await page.route('**/api/form-contracts/activate', r => r.fulfill({status: 409, json: {detail: 'contract_identity_review_required'}}));
  await page.route('**/api/uploads/info', r => {infoCalls++;return r.fulfill({json: {name: 'Should not load'}});});
  await page.goto('/upload');
  await expect(page.getByRole('alert')).toContainText('confirm your contributor record');
  await expect(page.getByRole('alert').getByRole('link', {name: /alex@6thsense.dev/})).toBeVisible();
  expect(infoCalls).toBe(0);
  await expect(page.locator('input[type=file]')).toHaveCount(0);
});

test('withdrawn contract blocks upload before legacy access in both languages', async ({page}) => {
  await mock(page);
  await page.addInitScript(() => sessionStorage.setItem('6thsense-contributor-session', JSON.stringify({
    access: 'access', refresh: 'refresh', expires: Date.now() + 900000,
  })));
  let infoCalls = 0;
  await page.route('**/api/form-contracts/activate', r => r.fulfill({status: 409, json: {detail: 'contract_withdrawn'}}));
  await page.route('**/api/uploads/info', r => {infoCalls++;return r.fulfill({json: {name: 'Should not load'}});});
  await page.goto('/upload');
  await expect(page.getByRole('alert')).toContainText('Your contract was withdrawn.');
  await page.getByRole('button', {name: '한국어', exact: true}).click();
  await expect(page.getByRole('alert')).toContainText('계약이 철회되었습니다.');
  expect(infoCalls).toBe(0);
  await expect(page.locator('input[type=file]')).toHaveCount(0);
});
