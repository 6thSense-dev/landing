import { test, expect } from '@playwright/test';

for (const scenario of ['missing', 'ambiguous', 'no-position', 'matched']) {
  test(`interval review ${scenario} never substitutes another recording`, async ({ page }) => {
    const review = { recording: 'recording-a', start_s: 0, end_s: 5, reason: 'fixture', clean_start_s: 0 };
    if (scenario === 'no-position') delete review.clean_start_s;
    const target = { role: 'recording_preview', recording: 'recording-a', key: 'clean/a.mp4', url: '/fixture-a.mp4' };
    const files = [{ role: 'joined_preview', key: 'clean/joined.mp4', url: '/fixture-joined.mp4' }];
    if (scenario !== 'missing') files.push(target);
    if (scenario === 'ambiguous') files.push({ ...target, key: 'clean/a-other.mp4' });
    let fileRequests = 0;
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data = {};
      if (path === '/api/auth/me') data = { id: 1, role: 'ops', email: 'fixture@example.test' };
      else if (path === '/api/ops/state') data = { episodes: [], wearers: [], tasks: [] };
      else if (path === '/api/ops/clean/state') data = { wearers: [], cameras: [], runs: [{
        run_id: 'fixture', device_id: 'ABC123', retained_seconds: 10, rejected_seconds: 0,
        source_seconds: 10, estimated_krw: null, rate_krw_hour: null, paid: false,
        recordings: [], recording_count: 1, review_intervals: [review], warnings: [],
      }] };
      else if (path.endsWith('/files')) { fileRequests++; data = { files }; }
      await route.fulfill({ json: data });
    });
    await page.route('**/fixture-*.mp4', route => route.abort());
    await page.goto('/portal/ops');
    await page.getByRole('button', { name: 'Clean', exact: true }).click();
    await page.getByText('Flagged footage to review (1)', { exact: true }).click();
    await page.getByRole('button', { name: 'Review interval', exact: true }).click();
    if (scenario === 'matched') {
      await expect(page.getByRole('dialog')).toBeVisible();
      await expect(page.locator('video')).toHaveAttribute('src', '/fixture-a.mp4');
    } else {
      await expect(page.getByRole('alert')).toContainText(scenario === 'no-position' ? 'no valid clean-video position' : 'No substitute video');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      expect(fileRequests).toBe(scenario === 'no-position' ? 0 : 1);
      await page.getByRole('button', { name: 'Watch joined footage' }).click();
      await expect(page.getByRole('dialog')).toBeVisible();
      await expect(page.locator('video')).toHaveAttribute('src', '/fixture-joined.mp4');
    }
  });
}

test('delayed link renewal cannot reopen a closed player', async ({ page }) => {
  let release;
  let renewalStarted;
  const started = new Promise(resolve => { renewalStarted = resolve; });
  let requests = 0;
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data = {};
    if (path === '/api/auth/me') data = { id: 1, role: 'ops', email: 'fixture@example.test' };
    else if (path === '/api/ops/state') data = {};
    else if (path === '/api/ops/clean/state') data = { runs: [{ run_id: 'fixture', recordings: [], retained_seconds: 10, rejected_seconds: 0 }] };
    else if (path.endsWith('/files')) {
      requests++;
      if (requests === 2) {
        const deferred = new Promise(resolve => { release = resolve; });
        renewalStarted();
        await deferred;
      }
      data = { files: [{ key: 'joined.mp4', role: 'joined_preview', url: `/fixture-${requests}.mp4` }] };
    }
    await route.fulfill({ json: data });
  });
  await page.route('**/fixture-*.mp4', route => route.abort());
  await page.goto('/portal/ops');
  await page.getByRole('button', { name: 'Clean', exact: true }).click();
  await page.getByRole('button', { name: 'Watch joined footage' }).click();
  await page.getByRole('button', { name: 'Reload video link' }).click();
  await started;
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  const response = page.waitForResponse(r => r.url().endsWith('/files'));
  release();
  await response;
  // Observe two animation frames after the fetch callback has processed.
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
