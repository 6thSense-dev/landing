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

for (const scenario of ['stereo', 'duplicate-left', 'changed-pin', 'switch-during-renewal']) {
  test(`current recording playback ${scenario} preserves contextual source`, async ({ page }) => {
    let release, renewalStarted;
    const started = new Promise(resolve => { renewalStarted = resolve; });
    let requests = 0;
    const files = [
      { key: 'left.mp4', role: 'left_video', recording: 'recording-a', version_id: 'v1', sha256: 'a'.repeat(64), url: '/fixture-left.mp4' },
      { key: 'right.mp4', role: 'right_video', recording: 'recording-a', version_id: 'v1', sha256: 'b'.repeat(64), url: '/fixture-right.mp4' },
      { key: 'other.mp4', role: 'left_video', recording: 'recording-b', url: '/fixture-other.mp4' },
    ];
    if (scenario === 'duplicate-left') files.push({ ...files[0], key: 'duplicate.mp4' });
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let data = {};
      if (path === '/api/auth/me') data = { id: 1, role: 'ops', email: 'fixture@example.test' };
      else if (path === '/api/ops/clean/state') data = {
        runs: [{ run_id: 'fixture', wearer_id: 1, recordings: [], source_seconds: 10, retained_seconds: 10, rejected_seconds: 0 }],
        ledger: [{ run_id: 'fixture', wearer_id: 1, recording: 'recording-a', retained_seconds: 10, review_status: 'needs_review', review_intervals: [] }],
      };
      else if (path.endsWith('/files')) {
        requests++;
        if (scenario === 'switch-during-renewal' && requests === 2) {
          const deferred = new Promise(resolve => { release = resolve; });
          renewalStarted(); await deferred;
        }
        data = { files: files.map(f => scenario === 'changed-pin' && requests === 2 && f.key === 'left.mp4' ? { ...f, version_id: 'v2', url: '/fixture-replaced.mp4' } : f) };
      }
      await route.fulfill({ json: data });
    });
    await page.route('**/fixture-*.mp4', route => route.abort());
    await page.goto('/portal/ops');
    await page.getByRole('button', { name: 'Clean', exact: true }).click();
    await page.locator('.ops-footage-review > summary').click();
    await page.getByRole('button', { name: 'Watch this recording' }).click();
    if (scenario === 'duplicate-left') {
      await expect(page.getByRole('alert')).toContainText('No substitute video');
      await expect(page.getByRole('dialog')).toHaveCount(0);
      return;
    }
    await expect(page.locator('video')).toHaveAttribute('src', '/fixture-left.mp4');
    await expect(page.getByLabel('Video', { exact: true }).locator('option')).toHaveCount(2);
    await page.locator('video').dispatchEvent('ended');
    await expect(page.locator('video')).toHaveAttribute('src', '/fixture-left.mp4');
    if (scenario === 'stereo') {
      await page.getByLabel('Video', { exact: true }).selectOption('1');
      await expect(page.locator('video')).toHaveAttribute('src', '/fixture-right.mp4');
    } else if (scenario === 'changed-pin') {
      const response = page.waitForResponse(r => r.url().endsWith('/files'));
      await page.getByRole('button', { name: 'Reload video link' }).click();
      await response;
      await expect(page.locator('video')).toHaveAttribute('src', '/fixture-left.mp4');
      await expect(page.getByRole('dialog').getByRole('alert')).toBeVisible();
    } else {
      await page.getByRole('button', { name: 'Reload video link' }).click();
      await started;
      await page.getByLabel('Video', { exact: true }).selectOption('1');
      const response = page.waitForResponse(r => r.url().endsWith('/files'));
      release(); await response;
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
      await expect(page.locator('video')).toHaveAttribute('src', '/fixture-right.mp4');
    }
  });
}

test('late batch response cannot replace selected collection playback', async ({ page }) => {
  let release, firstStarted;
  const started = new Promise(resolve => { firstStarted = resolve; });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data = {};
    if (path === '/api/auth/me') data = { id: 1, role: 'ops', email: 'fixture@example.test' };
    else if (path === '/api/ops/clean/state') data = {
      runs: [{ run_id: 'fixture', wearer_id: 1, recordings: [], source_seconds: 10, retained_seconds: 10, rejected_seconds: 0 }],
      collections: [{ collection_id: 'combined', wearer_id: 1, source_runs: [{ run_id: 'fixture' }], retained_seconds: 10, recordings: ['recording-a'] }],
    };
    else if (path.endsWith('/runs/fixture/files')) {
      const deferred = new Promise(resolve => { release = resolve; });
      firstStarted(); await deferred;
      data = { files: [{ key: 'old.mp4', role: 'joined_preview', url: '/fixture-old.mp4' }] };
    } else if (path.endsWith('/collections/combined/files')) {
      data = { files: [{ key: 'combined.mp4', role: 'joined_preview', url: '/fixture-combined.mp4' }] };
    }
    await route.fulfill({ json: data });
  });
  await page.route('**/fixture-*.mp4', route => route.abort());
  await page.goto('/portal/ops');
  await page.getByRole('button', { name: 'Clean', exact: true }).click();
  await page.getByText('Batch details & source recordings (1)', { exact: true }).click();
  await page.getByRole('button', { name: 'Watch batch 1', exact: true }).click();
  await started;
  await page.getByRole('button', { name: 'Watch all clean footage' }).click();
  await expect(page.locator('video')).toHaveAttribute('src', '/fixture-combined.mp4');
  const response = page.waitForResponse(r => r.url().endsWith('/runs/fixture/files'));
  release(); await response;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator('video')).toHaveAttribute('src', '/fixture-combined.mp4');
});
