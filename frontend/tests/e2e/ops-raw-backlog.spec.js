import { test, expect } from '@playwright/test';

async function mockState(page, raw_backlog) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me') return route.fulfill({ json: { id: 100, role: 'ops', email: 'ops@example.test' } });
    if (path === '/api/ops/state') return route.fulfill({ json: {
      raw_backlog, wearers: [], cameras: [], tasks: [], contributor_stats: [],
      episodes: Array.from({ length: 30 }, (_, i) => ({
        recording: `episode-${i}`, duration_s: 999999, device_id: 'ABC123',
        processing: { state: 'queued' }, raw: { status: 'pending', pending_files: 2 },
      })),
    } });
    return route.fulfill({ status: 404 });
  });
  await page.goto('/portal/ops');
  return page.getByRole('region', { name: 'Footage awaiting processing', exact: true });
}

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
