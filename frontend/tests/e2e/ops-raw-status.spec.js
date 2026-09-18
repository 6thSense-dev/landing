import { test, expect } from '@playwright/test';

test('Raw explains blocked causes and requires matched receipts before displaying Clean', async ({ page }) => {
  const episode = (recording, state, reason, raw = { status: 'pending', pending_files: 1 }) => ({
    recording, device_id: 'ABC123', session: 'korea', wearer_id: 1,
    processing: { state, reason, result_run_id: 'imported-result' }, raw,
  });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 100, role: 'ops', email: 'ops@example.test' } });
    if (path === '/api/ops/state') return route.fulfill({ json: {
      wearers: [{ id: 1, name: 'Example contributor' }], cameras: [], tasks: [], contributor_stats: [],
      episodes: [
        episode('metadata-source', 'blocked', 'Original metadata missing'),
        episode('qa-review', 'blocked', 'QA review required: no frames retained (uncertain_scene).'),
        episode('qa-rejected', 'blocked', 'QA rejected: no frames retained (phone_use).'),
        episode('budget-collision', 'blocked', 'Clean extraction failed: Inference reservation contention'),
        episode('spot-interrupted', 'blocked', 'Source conversion failed: Host EC2 (instance) terminated.'),
        episode('changed-source', 'blocked', 'New source versions arrived during processing; review before supersession'),
        episode('pending-source', 'awaiting_verification', 'QC output imported; awaiting exact source receipt reconciliation.', { status: 'partial', pending_files: 2 }),
        episode('matched-source', 'awaiting_verification', 'Cloud pipeline imported verified Clean; source receipts awaiting reconciliation.', { status: 'processed', pending_files: 0 }),
      ],
    } });
    return route.fulfill({ status: 404 });
  });
  await page.goto('/portal/ops');
  const row = name => page.getByRole('row').filter({ hasText: name });
  await expect(row('pending-source').locator('.ops-chip')).toHaveText('Checking source match');
  await expect(row('pending-source')).toContainText('The Clean result is imported. Automatic scans check');
  await page.getByRole('button', { name: 'Needs action', exact: true }).click();
  await expect(row('qa-review').locator('.ops-chip')).toHaveText('Scene review required');
  await expect(row('qa-rejected').locator('.ops-chip')).toHaveText('Rejected by scene QA');
  await expect(row('budget-collision').locator('.ops-chip')).toHaveText('Budget update interrupted');
  await expect(row('spot-interrupted').locator('.ops-chip')).toHaveText('Cloud worker interrupted');
  await expect(row('metadata-source')).toContainText('Metadata missing');
  await expect(row('metadata-source')).toContainText('Recover the original metadata');
  await expect(row('changed-source')).toContainText('Source files changed');
  await expect(row('changed-source')).toContainText('Compare the updated upload');
  await expect(row('matched-source')).toHaveCount(0);
  await expect(page.getByText('Needs attention', { exact: true })).toHaveCount(0);

  await page.getByLabel('Search raw sources', { exact: true }).fill('Metadata missing');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(row('metadata-source')).toBeVisible();
  await page.getByLabel('Search raw sources', { exact: true }).fill('');
  await page.getByRole('button', { name: 'Processing queue', exact: true }).click();
  await page.getByLabel('Processing status', { exact: true }).selectOption('awaiting_verification');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(row('pending-source')).toBeVisible();
  await page.getByRole('button', { name: 'Completed / rejected', exact: true }).click();
  await page.getByLabel('Processing status', { exact: true }).selectOption('clean');
  await expect(row('matched-source').locator('.ops-chip')).toHaveText('In Clean');
  await row('matched-source').getByText('Recorded status message', { exact: true }).click();
  await expect(row('matched-source')).toContainText('source receipts awaiting reconciliation');
  await expect(row('pending-source')).toHaveCount(0);
});

test('Raw separates missing footage, paginates work and resets filters safely', async ({ page }) => {
  const episodes = Array.from({ length: 61 }, (_, i) => ({ recording: `queued-${String(i).padStart(3, '0')}`,
    device_id: 'ABC123', processing: { state: 'queued', reason: 'Validate source' }, raw: { pending_files: 1 } }));
  episodes.push({ recording: 'missing-video', processing: { state: 'blocked', reason: 'Source media missing' }, raw: { pending_files: 0 } });
  episodes.push({ recording: 'real-failure', processing: { state: 'blocked', reason: 'Source conversion failed' }, raw: { pending_files: 1 } });
  episodes.push({ recording: 'new-media-arrived', processing: { state: 'blocked', reason: 'Source media missing' }, raw: { pending_files: 1 } });
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 100, role: 'ops', email: 'ops@example.test' } });
    if (path === '/api/ops/state') return route.fulfill({ json: { episodes, wearers: [], cameras: [], tasks: [], contributor_stats: [] } });
    return route.fulfill({ status: 404 });
  });
  await page.goto('/portal/ops');
  await expect(page.locator('tbody tr')).toHaveCount(25);
  await expect(page.getByLabel('Raw pagination')).toContainText('1–25 of 61');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByLabel('Raw pagination')).toContainText('26–50 of 61');
  await expect(page.getByRole('row').filter({ hasText: 'queued-025' })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(11);
  await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeDisabled();
  await page.getByLabel('Search raw sources').fill('queued-000');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.getByLabel('Raw pagination')).toContainText('Page 1 of 1');
  await page.getByLabel('Search raw sources').fill('');
  await page.getByLabel('Rows per page').selectOption('50');
  await expect(page.locator('tbody tr')).toHaveCount(50);
  await page.getByRole('button', { name: 'Waiting for upload', exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody')).toContainText('missing-video');
  await expect(page.locator('tbody').getByRole('button', { name: 'Preview' })).toBeDisabled();
  await page.getByRole('button', { name: 'Needs action', exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(2);
  await expect(page.locator('tbody')).not.toContainText('missing-video');
  await expect(page.getByText('Recovery and QC worker connection is not configured.')).toHaveCount(0);
});
