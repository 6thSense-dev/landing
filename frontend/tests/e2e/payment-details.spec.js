import { test, expect } from '@playwright/test';

const choices = {
  collects_details: 'I agree to collection and use of my payment details.',
  shares_details: 'I agree to sharing details for payment.',
  international_transfer: 'I agree to the international transfer.',
  owns_account: 'This is my own bank account.',
};
const notice = {
  version: 'KR-PAYMENT-TEST-1', sha256: 'a'.repeat(64),
  locales: {
    en: { title: 'How we use your payment details', paragraphs: ['6thSense uses your details to verify your bank account and pay your earnings. Full account numbers are not stored in the contractor Sheet.'], choices },
    ko: { title: '지급정보 이용 안내', paragraphs: ['보수 지급을 위해 본인 명의 계좌정보를 입력해 주세요. 전체 계좌번호는 계약자 Sheet에 저장하지 않습니다.'], choices: { collects_details: '수집·이용에 동의합니다.', shares_details: '정보 제공에 동의합니다.', international_transfer: '국외 이전에 동의합니다.', owns_account: '본인 명의 계좌입니다.' } },
  },
  privacy_url: 'https://wise.com/gb/legal/privacy-notice-business-en',
  guide_url: 'https://wise.com/help/articles/2932331/guide-to-krw-transfers',
};
const fields = [
  { key: 'accountHolderName', required: true, minLength: 2, maxLength: 140 },
  { key: 'bankCode', required: true, options: [{ value: 'SHINHAN_088', label: 'Shinhan Bank (신한은행)' }] },
  { key: 'accountNumber', required: true, minLength: 10, maxLength: 16 },
  { key: 'dateOfBirth', required: true }, { key: 'email', required: true }, { key: 'phoneNumber', required: true },
  { key: 'address.country', required: true, refresh: true, options: [{ value: 'KR', label: 'South Korea' }, { value: 'US', label: 'United States' }] },
  { key: 'address.city', required: true }, { key: 'address.firstLine', required: true }, { key: 'address.postCode', required: true },
];

async function mock(page, { approved = true, bank = null } = {}) {
  const state = { bank, notice, writes: [], checks: [], failWrite: false, failRefresh: false, staleNotice: false };
  await page.addInitScript(() => sessionStorage.setItem('6thsense-contributor-session', JSON.stringify({ access: 'test-access', refresh: 'test-refresh', expires: Date.now() + 900000 })));
  await page.route('**/api/contributor/configuration', r => r.fulfill({ json: { identity: { region: 'us-west-2', clientId: 'testclient1234' } } }));
  await page.route('https://cognito-idp.us-west-2.amazonaws.com/**', r => r.fulfill({ json: {} }));
  await page.route('**/api/form-contracts/configuration', r => r.fulfill({ status: 503, json: {} }));
  await page.route('**/api/uploads/info', r => r.fulfill(approved
    ? { json: { name: 'Test Contributor', remaining_bytes: 1000, batches: [] } }
    : { status: 403, json: { detail: 'camera_approval_required' } }));
  await page.route('**/api/contributor/bank/**', route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    expect(request.headers().authorization).toBe('Bearer test-access');
    if (path.endsWith('/setup')) return route.fulfill({ json: { country: 'KR', notice: state.notice, bank: state.bank } });
    const body = request.postDataJSON();
    expect(body.notice_version).toBe(notice.version);
    expect(body.notice_sha256).toBe(notice.sha256);
    for (const key of Object.keys(choices)) expect(body[key]).toBe(true);
    if (path.endsWith('/requirements')) {
      state.checks.push(body);
      if (state.failRefresh) return route.fulfill({ status: 503, json: { detail: 'bank_requirements_unavailable' } });
      return route.fulfill({ json: { country: 'KR', currency: 'KRW', fields } });
    }
    state.writes.push(body);
    if (state.staleNotice) {
      state.notice = { ...notice, version: 'changed', sha256: 'b'.repeat(64) };
      return route.fulfill({ status: 409, json: { detail: 'payment_notice_changed' } });
    }
    state.bank = { status: state.failWrite ? 'needs_reconciliation' : 'needs_review', accountHolderName: 'Test Recipient', bankLabel: 'Shinhan Bank', maskedAccount: '•••• 7890' };
    if (state.failWrite) return route.abort('failed');
    return route.fulfill({ json: { status: state.bank.status } });
  });
  return state;
}

async function enter(page) {
  await page.getByRole('button', { name: 'Add bank details', exact: true }).click();
  for (const label of Object.values(choices)) await page.getByRole('checkbox', { name: label, exact: true }).check();
  await page.getByRole('button', { name: 'Continue to bank details', exact: true }).click();
  await page.getByLabel('Legal name in Latin letters', { exact: true }).fill('Test Recipient');
  await page.getByLabel('Bank', { exact: true }).selectOption('SHINHAN_088');
  await page.getByLabel('Account number', { exact: true }).fill('001234567890');
  await page.getByLabel('Date of birth', { exact: true }).fill('1990-01-02');
  await page.getByLabel('Email', { exact: true }).fill('recipient@example.invalid');
  await page.getByLabel('Phone number', { exact: true }).fill('+821012345678');
  await page.getByLabel('City', { exact: true }).fill('Seoul');
  await page.getByLabel('Street address', { exact: true }).fill('1 Test Street');
  await page.getByLabel('Postal code', { exact: true }).fill('01234');
}

test('payment setup works before camera approval with explicit consent and masked receipt', async ({ page }, info) => {
  const state = await mock(page, { approved: false });
  await page.goto('/upload#payment-details');
  await page.getByRole('button', { name: 'Add bank details', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Continue to bank details' })).toBeDisabled();
  expect(state.checks).toHaveLength(0);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await enter(page);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('payment-fields.png'), fullPage: true });
  await page.getByRole('button', { name: 'Submit payment details', exact: true }).click();
  await expect(page.getByText('Details received — awaiting verification', { exact: true })).toBeVisible();
  await expect(page.getByText(/•••• 7890/)).toBeVisible();
  expect(state.writes).toHaveLength(1);
  expect(state.writes[0].values.accountNumber).toBe('001234567890');
  expect(state.writes[0].operation_id).toMatch(/^[a-f0-9-]{36}$/);
  expect(await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }))).not.toContain('001234567890');
  await expect(page.getByLabel('Account number', { exact: true })).toHaveCount(0);
  await expect(page.locator('input[type=file]')).toHaveCount(0);
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await expect(page.getByText(/•••• 7890/)).toHaveCount(0);
});

test('ambiguous submission is not automatically retried and uploads stay available', async ({ page }) => {
  const state = await mock(page); state.failWrite = true;
  await page.goto('/upload'); await enter(page);
  await page.getByRole('button', { name: 'Submit payment details', exact: true }).click();
  await expect(page.getByText('Checking your submission', { exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(1);
  await expect(page.locator('input[type=file]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
  await expect(page.getByText(/•••• 7890/)).toBeVisible();
  expect(state.writes).toHaveLength(1);
  await expect(page.getByRole('button', { name: 'Add bank details' })).toHaveCount(0);
});

test('failed dynamic requirements block submission until refreshed', async ({ page }) => {
  const state = await mock(page);
  await page.goto('/upload'); await enter(page);
  state.failRefresh = true;
  await page.getByLabel('Country of residence', { exact: true }).selectOption('US');
  await expect(page.getByRole('alert')).toContainText('temporarily unavailable');
  await expect(page.getByRole('button', { name: 'Submit payment details', exact: true })).toBeDisabled();
  state.failRefresh = false;
  await page.getByRole('button', { name: 'Reload bank fields', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Submit payment details', exact: true })).toBeEnabled();
  expect(state.checks.at(-1).values['address.country']).toBe('US');
  expect(state.writes).toHaveLength(0);
});

test('existing verified recipient is not asked to resubmit and Korean status is readable', async ({ page }, info) => {
  const state = await mock(page, { bank: { status: 'ready', accountHolderName: 'Test Recipient' } });
  await page.goto('/upload');
  await expect(page.getByText('Payment account verified', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Add bank details' })).toHaveCount(0);
  await page.getByRole('button', { name: '한국어', exact: true }).click();
  await expect(page.getByText('지급 계좌 확인 완료', { exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: info.outputPath('payment-ready-ko.png'), fullPage: true });
});

test('operator-confirmed no-create permits a fresh operation after status refresh', async ({ page }) => {
  const state = await mock(page); state.failWrite = true;
  await page.goto('/upload'); await enter(page);
  await page.getByRole('button', { name: 'Submit payment details', exact: true }).click();
  await expect(page.getByText('Checking your submission', { exact: true })).toBeVisible();
  state.bank = null; state.failWrite = false;
  await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
  await enter(page);
  await page.getByRole('button', { name: 'Submit payment details', exact: true }).click();
  await expect(page.getByText('Details received — awaiting verification', { exact: true })).toBeVisible();
  expect(state.writes).toHaveLength(2);
  expect(state.writes[0].operation_id).not.toBe(state.writes[1].operation_id);
});

test('changed notice requires fresh acknowledgment after refresh', async ({ page }) => {
  const state = await mock(page); state.staleNotice = true;
  await page.goto('/upload'); await enter(page);
  await page.getByRole('button', { name: 'Submit payment details', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('payment notice has changed');
  await page.getByRole('button', { name: 'Refresh status', exact: true }).click();
  await expect(page.getByLabel('Account number', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Add bank details', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Continue to bank details', exact: true })).toBeDisabled();
  expect(await page.getByRole('checkbox', { checked: true }).count()).toBe(0);
});
