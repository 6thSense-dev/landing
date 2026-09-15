import { test, expect } from '@playwright/test';
import { expectNoHorizontalOverflow } from './helpers.js';

const person = { id: 7, name: '한규태', workplace: '한그라픽스', is_active: true, rate_krw_hour: 11000 };
const subject = '11111111-1111-1111-1111-111111111111';
const claimId = '22222222-2222-2222-2222-222222222222';
const attemptId = '33333333-3333-3333-3333-333333333333';

async function openRequests(page, { unknown = false, failLoad = false, cameraError = false } = {}) {
  const requests = [];
  const claims = [{ id: claimId, subject, device_id: 'ABC123', status: 'pending', ended_at: null }];
  const attempt = { id: attemptId, subject, status: unknown ? 'needs_reconciliation' : 'needs_review',
    recipient_id: unknown ? null : '456', summary: { accountHolderName: '한규태', bankLabel: 'Test Bank',
      maskedAccount: '•••• 7890', country: 'KR', currency: 'KRW' } };
  const state = { failLoad, cameraError };
  let linked = null;
  const payments = () => ({ contributors: [{ ...person, wearer_id: person.id, recipient: linked }] });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    requests.push({ path, method: request.method(), body: request.postDataJSON() });
    let data;
    if (path === '/api/auth/me') data = { id: 100, email: 'ops@example.test', role: 'ops' };
    else if (path === '/api/ops/state') data = { wearers: [person], episodes: [], cameras: [], tasks: [], contributor_stats: [] };
    else if (path === '/api/ops/contributors') {
      if (state.failLoad) return route.fulfill({ status: 503, json: { detail: 'Requests temporarily unavailable.' } });
      data = { accounts: [{ subject, wearer_id: person.id }], claims, recipients: [attempt] };
    } else if (path === '/api/ops/payments/state') data = payments();
    else if (path === `/api/ops/contributors/cameras/${claimId}/approve`) {
      if (state.cameraError) return route.fulfill({ status: 409, json: { detail: 'Current agreements must be accepted first.' } });
      claims[0].status = 'approved'; data = { id: claimId, status: 'approved' };
    } else if (path === '/api/ops/payments/recipient') {
      linked = { id: String(request.postDataJSON().recipient_id), name: person.name }; data = payments();
    } else if (path === `/api/ops/contributors/recipients/${attemptId}/resolve`) {
      const body = request.postDataJSON();
      if (body.resolution === 'found') {
        attempt.recipient_id = String(body.recipient_id); attempt.status = 'needs_review';
      } else attempt.status = 'retry_allowed';
      data = { id: attemptId, status: attempt.status };
    } else return route.fulfill({ status: 404 });
    return route.fulfill({ json: data });
  });
  await page.goto('/portal/ops');
  await page.getByRole('button', { name: 'Users', exact: true }).click();
  const panel = page.getByRole('region', { name: 'Mobile contributor requests' });
  await expect(panel).toBeVisible();
  await expect(panel.getByText('Loading contributor requests…')).toHaveCount(0);
  return { panel, requests, state };
}

test('camera and bank approvals require separate confirmations and keep server failures visible', async ({ page }, testInfo) => {
  const { panel, requests, state } = await openRequests(page, { cameraError: true });
  const camera = panel.getByRole('article', { name: 'Camera EGO-ABC123' });
  const bank = panel.getByRole('article', { name: 'Bank review for 한규태' });
  await expect(camera).toContainText('contributor #7');
  await expect(bank).toContainText('Test Bank · •••• 7890');
  await expect(bank).toContainText('ID 456');
  expect(requests.every(request => request.method === 'GET')).toBe(true);
  await expect(camera.getByRole('button', { name: 'Approve camera' })).toBeDisabled();
  await expect(bank.getByRole('button', { name: 'Verify and link recipient' })).toBeDisabled();
  await camera.getByRole('checkbox').check();
  await bank.getByRole('checkbox').check();
  await panel.getByRole('button', { name: 'Refresh requests' }).click();
  await expect(camera.getByRole('checkbox')).not.toBeChecked();
  await expect(bank.getByRole('checkbox')).not.toBeChecked();
  await camera.getByRole('checkbox').check();
  await camera.getByRole('button', { name: 'Approve camera' }).click();
  await expect(panel.getByRole('alert')).toHaveText('Current agreements must be accepted first.');
  await expect(camera).toBeVisible();
  state.cameraError = false;
  await camera.getByRole('button', { name: 'Approve camera' }).click();
  await expect(camera).toHaveCount(0);
  expect(requests.find(request => request.path.endsWith('/approve')).body).toEqual({ physically_verified: true });
  await expect(bank.getByRole('checkbox')).not.toBeChecked();
  await bank.getByRole('checkbox').check();
  await expectNoHorizontalOverflow(page);
  await panel.screenshot({ path: testInfo.outputPath('mobile-requests.png') });
  await bank.getByRole('button', { name: 'Verify and link recipient' }).click();
  await expect(bank).toHaveCount(0);
  await expect(panel).toContainText('No bank submissions awaiting review.');
  expect(requests.find(request => request.path === '/api/ops/payments/recipient').body)
    .toEqual({ wearer_id: 7, recipient_id: 456, confirm_recipient: true });
  expect(requests.filter(request => request.path === '/api/ops/payments/approve')).toEqual([]);
  await expect(page.getByRole('heading', { name: 'People who carry cameras' })).toBeVisible();
});

test('a found recipient needs evidence before recovery and another confirmation before linking', async ({ page }, testInfo) => {
  const { panel, requests } = await openRequests(page, { unknown: true });
  const bank = panel.getByRole('article', { name: 'Bank review for 한규태' });
  await expect(bank.getByLabel('Verified outcome')).toHaveValue('');
  await expect(bank.getByRole('button')).toHaveCount(0);
  expect(requests.every(request => request.method === 'GET')).toBe(true);
  await bank.getByLabel('Verified outcome').selectOption('found');
  await bank.getByLabel('Found Wise recipient ID').fill('789');
  await bank.getByLabel('Verification note').fill('Matched the recipient with Wise and the contributor.');
  await expect(bank.getByRole('button', { name: 'Record found recipient' })).toBeDisabled();
  await bank.getByRole('checkbox').check();
  await bank.getByLabel('Found Wise recipient ID').fill('790');
  await expect(bank.getByRole('checkbox')).not.toBeChecked();
  await bank.getByRole('checkbox').check();
  await expectNoHorizontalOverflow(page);
  await panel.screenshot({ path: testInfo.outputPath('recipient-recovery.png') });
  await bank.getByRole('button', { name: 'Record found recipient' }).click();
  await expect(bank).toContainText('ID 790');
  expect(requests.find(request => request.path.endsWith('/resolve')).body).toEqual({ resolution: 'found',
    recipient_id: 790, verified_owner: true, note: 'Matched the recipient with Wise and the contributor.' });
  expect(requests.filter(request => request.path === '/api/ops/payments/recipient')).toEqual([]);
  await expect(bank.getByRole('button', { name: 'Verify and link recipient' })).toBeDisabled();
});

test('only an explicit no-create confirmation releases an unknown bank submission', async ({ page }) => {
  const { panel, requests } = await openRequests(page, { unknown: true });
  const bank = panel.getByRole('article', { name: 'Bank review for 한규태' });
  await bank.getByLabel('Verified outcome').selectOption('not_created');
  await bank.getByLabel('Verification note').fill('   short  ');
  await bank.getByRole('checkbox').check();
  await expect(bank.getByRole('button', { name: 'Allow a new bank submission' })).toBeDisabled();
  await bank.getByLabel('Verification note').fill('Wise confirmed that no recipient was created.');
  await bank.getByRole('button', { name: 'Allow a new bank submission' }).click();
  await expect(bank).toHaveCount(0);
  await expect(panel.getByRole('status')).toContainText('The contributor can submit their bank details again.');
  expect(requests.find(request => request.path.endsWith('/resolve')).body).toEqual({ resolution: 'not_created',
    confirmed_not_created: true, note: 'Wise confirmed that no recipient was created.' });
  expect(requests.filter(request => request.path === '/api/ops/payments/recipient')).toEqual([]);
});

test('failed request loading leaves the existing Users screen usable and can be retried', async ({ page }) => {
  const { panel, requests, state } = await openRequests(page, { failLoad: true });
  await expect(panel.getByRole('alert')).toHaveText('Requests temporarily unavailable.');
  await expect(panel.getByRole('article')).toHaveCount(0);
  await expect(page.getByRole('heading', { name: 'People who carry cameras' })).toBeVisible();
  await page.locator('summary').filter({ hasText: 'Camera assignments' }).click();
  await expect(page.getByRole('button', { name: 'Save camera assignment' })).toBeVisible();
  state.failLoad = false;
  await panel.getByRole('button', { name: 'Refresh requests' }).click();
  await expect(panel.getByRole('alert')).toHaveCount(0);
  await expect(panel.getByRole('article', { name: 'Camera EGO-ABC123' })).toBeVisible();
  expect(requests.every(request => request.method === 'GET')).toBe(true);
});
