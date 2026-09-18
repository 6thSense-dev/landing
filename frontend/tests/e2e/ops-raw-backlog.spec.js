import { test, expect } from '@playwright/test';

async function mockState(page, raw_backlog, extraState = {}) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 100, role: 'ops', email: 'ops@example.test' } });
    if (path === '/api/ops/state') return route.fulfill({ json: {
      raw_backlog, wearers: [], cameras: [], tasks: [], contributor_stats: [],
      episodes: Array.from({ length: 30 }, (_, i) => ({
        recording: `episode-${i}`, duration_s: 999999, device_id: 'ABC123',
        processing: { state: 'queued' }, raw: { status: 'pending', pending_files: 2 },
      })),
      ...extraState,
    } });
    return route.fulfill({ status: 404 });
  });
  await page.goto('/portal/ops');
  return page.getByRole('region', { name: 'Footage awaiting processing', exact: true });
}

test('Raw breaks down time by business, contributor and unassigned source', async ({ page }) => {
  const sources = [
    { key: 'business:mtl', name: 'MTL', kind: 'business', country: 'india', known_seconds: 7200, known_episodes: 2, pending_episodes: 3, unknown_episodes: 1, partial_episodes: 1 },
    { key: 'wearer:null', name: 'Unassigned', kind: 'unassigned', known_seconds: 5400, known_episodes: 1, pending_episodes: 1, unknown_episodes: 0 },
    { key: 'wearer:1', name: 'MTL', kind: 'contributor', known_seconds: 3600, known_episodes: 1, pending_episodes: 1, unknown_episodes: 0 },
    { key: 'wearer:2', name: 'Unknown duration', kind: 'contributor', known_seconds: 0, known_episodes: 0, pending_episodes: 1, unknown_episodes: 1 },
  ];
  const summary = await mockState(page, {
    known_seconds: 16200, known_episodes: 4, pending_episodes: 6, unknown_episodes: 2, partial_episodes: 1, sources,
  }, { wearers: [{ id: 1, name: 'MTL' }, { id: 2, name: 'Unknown duration' }] });
  const breakdown = page.getByRole('region', { name: 'Footage awaiting processing by source', exact: true });
  const rows = breakdown.getByRole('listitem');
  await expect(rows).toHaveCount(4);
  await expect(rows.filter({ hasText: 'B2B · India' })).toContainText('2 h 0 m');
  await expect(rows.filter({ hasText: 'B2B · India' })).toContainText('1 awaiting duration (including 1 partially processed)');
  await expect(rows.filter({ hasText: 'MTL' }).filter({ hasText: 'Contributor' })).toContainText('1 h 0 m');
  await expect(rows.filter({ hasText: 'Unassigned' })).toContainText('1 h 30 m');
  await expect(rows.filter({ hasText: 'Unknown duration' })).toContainText('Awaiting duration');
  await expect(summary).toContainText('4 h 30 m');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await page.getByLabel('Raw source', { exact: true }).selectOption('wearer:1');
  await page.getByLabel('Search raw sources').fill('no-match');
  await page.getByRole('button', { name: 'Needs action', exact: true }).click();
  await expect(rows).toHaveCount(4);
  await expect(rows.filter({ hasText: 'B2B · India' })).toContainText('2 h 0 m');
  for (const row of await rows.all()) {
    const box = await row.boundingBox();
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize().width);
  }
});

test('Raw shows an empty source breakdown after a scan with no pending footage', async ({ page }) => {
  await mockState(page, { known_seconds: 0, known_episodes: 0, pending_episodes: 0, unknown_episodes: 0, sources: [] });
  await expect(page.getByRole('region', { name: 'Footage awaiting processing by source', exact: true })).toContainText('No sources have pending footage.');
});

test('Raw shows known backlog and unknown durations across filters and pages', async ({ page }) => {
  const summary = await mockState(page, {
    known_seconds: 702750, known_episodes: 26, unknown_episodes: 4, partial_episodes: 2, pending_episodes: 30,
  });
  await expect(summary).toContainText('195 h 12 m');
  await expect(summary).toContainText('26 of 30 episodes timed');
  await expect(summary).toContainText('4 awaiting duration (including 2 partially processed)');
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.locator('tbody tr')).toHaveCount(5);
  await expect(summary).toContainText('195 h 12 m');
  await page.getByLabel('Search raw sources').fill('episode-0');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(summary).toContainText('26 of 30 episodes timed');
  await page.getByRole('button', { name: 'Needs action', exact: true }).click();
  await expect(summary).toContainText('195 h 12 m');
  const box = await summary.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize().width);
});

for (const [label, data, expected] of [
  ['no scan', null, 'Awaiting bucket scan'],
  ['empty', { known_seconds: 0, known_episodes: 0, pending_episodes: 0, unknown_episodes: 0 }, '0 h 0 m'],
  ['unknown', { known_seconds: 0, known_episodes: 0, pending_episodes: 4, unknown_episodes: 4 }, 'Awaiting duration'],
  ['short', { known_seconds: 6.6, known_episodes: 1, pending_episodes: 1, unknown_episodes: 0 }, 'Less than 1 min'],
]) {
  test(`Raw duration handles ${label}`, async ({ page }) => {
    const summary = await mockState(page, data);
    await expect(summary).toContainText(expected);
    await expect(summary).not.toContainText('NaN');
    await expect(summary).not.toContainText('undefined');
  });
}
