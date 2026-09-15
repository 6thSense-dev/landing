import { test, expect } from '@playwright/test';

test('switching source clears old counts and denied access stays unknown', async ({ page }) => {
  let lists = 0, checks = 0;
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let status = 200, data = {};
    if (url.pathname === '/api/auth/me') data = { id: 1, role: 'ops', email: 'fixture@example.test' };
    else if (url.pathname === '/api/ops/state') data = {};
    else if (url.pathname === '/api/ops/inventory-sources') {
      lists++;
      if (lists === 1) status = 503;
      else data = { sources: [
        { id: 'operations', label: 'Operations raw', bucket: 'fixture-first', prefix: '', expected_owner: null },
        { id: 'company', label: 'Company legacy', bucket: 'fixture-second', prefix: 'recordings/', expected_owner: '111111111111' },
        { id: 'nested', label: 'Nested recording', bucket: 'fixture-second', prefix: 'recordings/take/chunks/', expected_owner: '111111111111' },
      ] };
    } else if (url.pathname === '/api/ops/inventory-coverage') {
      checks++;
      const id = url.searchParams.get('source_id');
      data = { source_id: id, bucket: id === 'operations' ? 'fixture-first' : 'fixture-second', scope_prefix: id === 'nested' ? 'recordings/take/chunks/' : id === 'company' ? 'recordings/' : '',
        listing_complete: id !== 'company', stop_reason: id === 'company' ? 'read_error' : null,
        objects_observed: id === 'company' ? 0 : 97, recognized_recording_prefixes: 0,
        recordings_missing_metadata: 0, unrecognized_objects: 0, collision_recording_names: 0,
        examples: {}, limitations: [],
      };
      if (id === 'nested') Object.assign(data, { objects_observed: 1, recognized_recording_prefixes: 1, recordings_metadata_outside_scope: 1, metadata_scope_complete: false });
    }
    expect(route.request().method()).toBe('GET');
    await route.fulfill({ status, json: data });
  });
  await page.goto('/portal/ops');
  expect(lists).toBe(0);
  await page.getByText('Which recordings does this board cover?', { exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Coverage is unknown');
  await expect(page.getByRole('button', { name: 'Check inventory coverage' })).toBeDisabled();
  expect(checks).toBe(0);
  await page.getByRole('button', { name: 'Retry source list' }).click();
  await page.getByRole('button', { name: 'Check inventory coverage' }).click();
  const report = page.getByRole('region', { name: 'Inventory coverage result' });
  await expect(report).toContainText('97');
  await page.getByLabel('Recording source').selectOption('company');
  await expect(report).toHaveCount(0);
  expect(checks).toBe(1);
  await page.getByRole('button', { name: 'Check inventory coverage' }).click();
  await expect(report).toContainText('Full totals are unknown');
  await expect(report).toContainText('s3://fixture-second/recordings/');
  await expect(report).not.toContainText('97');
  expect(checks).toBe(2);
  await page.getByLabel('Recording source').selectOption('nested');
  await page.getByRole('button', { name: 'Check inventory coverage' }).click();
  await expect(report).toContainText('Listing completed for the selected source prefix');
  await expect(report).toContainText('Metadata outside checked prefix · unknown');
  await expect(report.locator('div').filter({ has: page.locator('dt', { hasText: 'Folders without metadata.json' }) }).last().locator('dd')).toHaveText('0');
});
