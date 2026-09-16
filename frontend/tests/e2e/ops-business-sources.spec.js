import { test, expect } from '@playwright/test';

test('Raw shows registered Trial footage as China business and filters it separately from people', async ({ page }) => {
  const business = { kind: 'business', id: 'factory-example', name: 'Example factory', country: 'china', payment_model: 'b2b_contract' };
  const source = (recording, overrides) => ({ recording, device_id: 'ABC123', session: '2026-09-01_Trial',
    wearer_id: null, raw: { status: 'pending', pending_files: 1 }, processing: { state: 'queued', reason: 'Ready for processing.' }, ...overrides });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 100, email: 'ops@example.test', role: 'ops' } });
    if (path === '/api/ops/state') return route.fulfill({ json: {
      wearers: [{ id: 1, name: 'Individual contributor' }], cameras: [], tasks: [], contributor_stats: [],
      episodes: [source('business-source', { counterparty: business }), source('personal-source', { wearer_id: 1 })],
    } });
    return route.fulfill({ status: 404 });
  });
  await page.goto('/portal/ops');
  const businessRow = page.getByRole('row').filter({ hasText: 'business-source' });
  await expect(businessRow).toContainText('China');
  await expect(businessRow).toContainText('Example factory');
  await expect(businessRow).toContainText('B2B');
  await expect(businessRow).not.toContainText('Unassigned');
  await page.getByLabel('Raw source', { exact: true }).selectOption('business:factory-example');
  await expect(businessRow).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: 'personal-source' })).toHaveCount(0);
  await page.getByLabel('Raw source', { exact: true }).selectOption('wearer:1');
  await expect(businessRow).toHaveCount(0);
  await expect(page.getByRole('row').filter({ hasText: 'personal-source' })).toBeVisible();
});

test('Raw refresh replaces Unassigned with PSDN for every attributed upload and filters them together', async ({ page }) => {
  await page.clock.install();
  const psdn = { kind: 'business', id: 'psdn', name: 'PSDN', country: 'korea', payment_model: 'b2b_contract' };
  const recordings = ['ego_20260911_171333_4A57B4', 'ego_20260911_162622_4A5700', 'ego_20260916_120915_4A5728'];
  let attributed = false;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 100, email: 'ops@example.test', role: 'ops' } });
    if (path === '/api/ops/state') return route.fulfill({ json: {
      wearers: [], cameras: [], tasks: [], contributor_stats: [],
      episodes: [...recordings.map(recording => ({ recording, device_id: recording.split('_')[3],
        session: 'psdn-korea', wearer_id: null, counterparty: attributed ? psdn : null,
        raw: { status: 'pending', pending_files: 1 }, processing: { state: 'queued' } })),
        { recording: 'unrelated-upload', device_id: '4A57B4', wearer_id: null,
          raw: { status: 'pending', pending_files: 1 }, processing: { state: 'queued' } }],
    } });
    return route.fulfill({ status: 404 });
  });
  await page.goto('/portal/ops');
  for (const recording of recordings) {
    await expect(page.getByRole('row').filter({ hasText: recording })).toContainText('Unassigned');
  }
  attributed = true;
  await page.clock.fastForward(30_001);
  for (const recording of recordings) {
    const row = page.getByRole('row').filter({ hasText: recording });
    await expect(row).toContainText('PSDN');
    await expect(row).toContainText('B2B');
    await expect(row).not.toContainText('Unassigned');
  }
  await expect(page.getByRole('row').filter({ hasText: 'unrelated-upload' })).toContainText('Unassigned');
  await page.getByLabel('Raw source', { exact: true }).selectOption('business:psdn');
  await expect(page.locator('tbody tr')).toHaveCount(recordings.length);
  await expect(page.getByRole('row').filter({ hasText: 'unrelated-upload' })).toHaveCount(0);
  await page.getByLabel('Raw source', { exact: true }).selectOption('');
  await page.getByLabel('Search raw sources', { exact: true }).fill('PSDN');
  await expect(page.locator('tbody tr')).toHaveCount(recordings.length);
});
