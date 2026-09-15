import { test, expect } from '@playwright/test';
import { expectNoHorizontalOverflow } from './helpers.js';

test('Raw monitors sources, Clean records review, and Payment requires explicit approval', async ({ page }, testInfo) => {
  const person = { id: 1, name: '한규태', workplace: '한그라픽스', is_active: true, rate_krw_hour: 11000 };
  const recording = 'ego_20260907_180803_16A4A5';
  const entry = { run_id: 'run', recording, wearer_id: 1, manifest_sha256: 'a'.repeat(64), source_seconds: 20000, retained_seconds: 18000, rejected_seconds: 2000, rejection_reasons: { 'Computer use': 2000 }, review_status: 'needs_review', review_intervals: [], date_basis: 'Operator-confirmed', collection_date: '2026-09-07', payment_status: 'unapproved' };
  const requests = [];
  entry.artifact_status = 'complete';
  let reviewed = false, approved = false;
  const payment = () => ({
    configuration: { threshold_basis: 'accumulated', wise_configured: true, wise_environment: 'sandbox', source_currency: 'USD', automatic_funding_enabled: false },
    scheduled_for: '2026-09-18T09:00:00Z', collection_week: ['2026-09-07', '2026-09-14'],
    contributors: [{ ...person, wearer_id: 1, entries: [{ ...entry, review_status: reviewed ? 'reviewed' : 'needs_review' }], due_krw: approved ? 0 : 55000, qualifying_seconds: reviewed && !approved ? 18000 : 0, eligible_krw: reviewed && !approved ? 55000 : 0, eligible_entries: reviewed && !approved ? [{ run_id: 'run', recording, manifest_sha256: entry.manifest_sha256 }] : [], recipient: { id: '123', name: person.name } }],
    payouts: approved ? [{ id: 'payout', wearer_id: 1, amount_krw: 55000, scheduled_for: '2026-09-18T09:00:00Z', status: 'approved', approved_by: 'ops@example.test' }] : [],
  });
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    requests.push({ path, method: req.method(), body: req.postDataJSON() });
    let data;
    if (path === '/api/auth/me') data = { id: 100, email: 'ops@example.test', role: 'ops' };
    else if (path === '/api/ops/state') data = { wearers: [person], cameras: [{ device_id: '16A4A5', wearer_id: 1 }], tasks: [], contributor_stats: [], episodes: [
      { recording: 'new-source', device_id: '16A4A5', wearer_id: 1, raw: { status: 'pending', pending_files: 1 }, processing: { state: 'recovering', reason: 'Recover missing metadata' } },
      { recording, device_id: '16A4A5', wearer_id: 1, raw: { status: 'processed' }, processing: { state: 'clean' } },
    ] };
    else if (path === '/api/ops/clean/state') data = { wearers: [person], cameras: [], collections: [], ledger: [{ ...entry, review_status: reviewed ? 'reviewed' : 'needs_review' }], runs: [{ run_id: 'run', device_id: '16A4A5', wearer_id: 1, source_seconds: 20000, retained_seconds: 18000, rejected_seconds: 2000, recordings: [], recording_count: 1 }] };
    else if (path === '/api/ops/clean/runs/run/files') data = { files: [{ key: 'left.mp4', url: '/test-left.mp4', role: 'left_video', recording }, { key: 'right.mp4', url: '/test-right.mp4', role: 'right_video', recording }] };
    else if (path === '/api/ops/payments/review') { reviewed = true; data = { ok: true }; }
    else if (path === '/api/ops/payments/state') data = payment();
    else if (path === '/api/ops/payments/approve') { approved = true; data = payment(); }
    else return route.fulfill({ status: 404 });
    return route.fulfill({ json: data });
  });
  await page.goto('/portal/ops');
  await expect(page.getByRole('cell', { name: /^new-source EGO-/ })).toBeVisible();
  await expect(page.getByRole('cell', { name: new RegExp(recording) })).toHaveCount(0);
  await expect(page.getByRole('columnheader', { name: 'Paid', exact: true })).toHaveCount(0);
  await expect(page.getByRole('columnheader', { name: 'Approved', exact: true })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await page.getByRole('button', { name: 'Users', exact: true }).click();
  await expect(page.getByText(/these contributor records do not establish an app account/)).toBeVisible();
  await page.locator('summary').filter({ hasText: 'Camera assignments' }).click();
  await expect(page.getByRole('button', { name: 'Save camera assignment' })).toBeVisible();
  await page.getByRole('button', { name: 'Clean', exact: true }).click();
  await page.locator('.ops-footage-review > summary').click();
  await expect(page.getByText('Both eye videos, full frame sequences and IMU are verified.')).toBeVisible();
  await page.getByRole('button', { name: 'Watch this recording' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.locator('.ops-clean-modal video')).toHaveAttribute('src', '/test-left.mp4');
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Mark reviewed' })).toBeDisabled();
  await page.getByLabel('I reviewed all retained footage and flagged intervals.').check();
  await page.getByRole('button', { name: 'Mark reviewed' }).click();
  await expect(page.locator('.ops-footage-review > summary')).toContainText('reviewed');
  expect(requests.find(r => r.path.endsWith('/review')).body.watched_all).toBe(true);
  await page.getByRole('button', { name: 'Payment', exact: true }).click();
  await expect(page.getByText('Sandbox — test transfers only', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve Payment' })).toBeDisabled();
  await page.getByLabel(/I approve ₩55,000 for this reviewed footage/).check();
  await page.getByRole('button', { name: 'Approve Payment' }).click();
  await expect(page.getByRole('cell', { name: 'approved', exact: true })).toBeVisible();
  const payload = requests.find(r => r.path.endsWith('/approve')).body;
  expect(payload.expected_amount_krw).toBe(55000);
  expect(payload.entries).toEqual([{ run_id: 'run', recording, manifest_sha256: entry.manifest_sha256 }]);
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath('payment.png'), fullPage: true });
});
