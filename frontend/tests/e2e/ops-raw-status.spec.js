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
  await expect(row('qa-review').locator('.ops-chip')).toHaveText('Scene review required');
  await expect(row('qa-rejected').locator('.ops-chip')).toHaveText('Rejected by scene QA');
  await expect(row('budget-collision').locator('.ops-chip')).toHaveText('Budget update interrupted');
  await expect(row('spot-interrupted').locator('.ops-chip')).toHaveText('Cloud worker interrupted');
  await expect(row('metadata-source')).toContainText('Metadata missing');
  await expect(row('metadata-source')).toContainText('Recover the original metadata');
  await expect(row('changed-source')).toContainText('Source files changed');
  await expect(row('changed-source')).toContainText('Compare the updated upload');
  await expect(row('pending-source').locator('.ops-chip')).toHaveText('Checking source match');
  await expect(row('pending-source')).toContainText('The Clean result is imported. Automatic scans check');
  await expect(row('matched-source')).toHaveCount(0);
  await expect(page.getByText('Needs attention', { exact: true })).toHaveCount(0);

  await page.getByLabel('Search raw sources', { exact: true }).fill('Metadata missing');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(row('metadata-source')).toBeVisible();
  await page.getByLabel('Search raw sources', { exact: true }).fill('');
  await page.getByLabel('Processing status', { exact: true }).selectOption('awaiting_verification');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(row('pending-source')).toBeVisible();
  await page.getByLabel('Show completed / rejected').check();
  await page.getByLabel('Processing status', { exact: true }).selectOption('clean');
  await expect(row('matched-source').locator('.ops-chip')).toHaveText('In Clean');
  await row('matched-source').getByText('Recorded status message', { exact: true }).click();
  await expect(row('matched-source')).toContainText('source receipts awaiting reconciliation');
  await expect(row('pending-source')).toHaveCount(0);
});
