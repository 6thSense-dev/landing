import { test, expect } from '@playwright/test';

test('task declaration preserves exact time and conflict draft without payment writes', async ({ page }) => {
  const posts = [];
  let conflict = true;
  const projection = {
    run_id: 'fixture', task_id: 'manipulation', manifest_sha256: 'a'.repeat(64), revision: 0, review: null,
    recordings: [{ recording: 'recording-a', source_duration_ns: '2000000000', sources: [], accepted_ns: null, excluded_ns: null, unknown_ns: '2000000000' }],
    unique_usable_ns: null, limitations: [],
  };
  await page.route('**/api/**', async route => {
    const req = route.request(), path = new URL(req.url()).pathname;
    let data = {}, status = 200;
    if (path === '/api/auth/me') data = { id: 1, role: 'ops', email: 'fixture@example.test' };
    else if (path === '/api/ops/state') data = {};
    else if (path === '/api/ops/clean/state') data = { runs: [{ run_id: 'fixture', recordings: [], retained_seconds: 2, rejected_seconds: 0 }] };
    else if (path.endsWith('/activity-review')) {
      if (req.method() === 'POST') {
        const body = req.postDataJSON(); posts.push({ path, body });
        if (conflict) { status = 409; data = { detail: 'Stale revision' }; }
        else data = { ...projection, revision: 1, review: { ...body, reviewer_email: 'fixture@example.test', reviewed_at: 'synthetic-time' }, recordings: [{ ...projection.recordings[0], accepted_ns: '999999999', excluded_ns: '0', unknown_ns: '1000000001' }] };
      } else data = projection;
    }
    await route.fulfill({ status, json: data });
  });
  await page.goto('/portal/ops');
  await page.getByRole('button', { name: 'Clean', exact: true }).click();
  await page.getByRole('button', { name: 'Review task activity' }).click();
  const review = page.getByRole('region', { name: 'Task activity review' });
  await review.getByLabel('Task ID', { exact: true }).fill('manipulation');
  await review.getByRole('button', { name: 'Load task review' }).click();
  await expect(review.getByRole('cell', { name: 'Unknown', exact: true })).toHaveCount(2);
  await review.getByLabel('Criteria version').fill('v1');
  await review.getByLabel('Explicit task criteria').fill('Synthetic criterion: annotate deliberate object manipulation; preserve failed attempts.');
  await review.getByRole('button', { name: 'Add interval' }).click();
  await review.getByLabel('Start seconds 1', { exact: true }).fill('0.000000001');
  await review.getByLabel('End seconds 1', { exact: true }).fill('1');
  await review.getByLabel('Judgment 1', { exact: true }).selectOption('accepted');
  await review.getByLabel('Reason 1', { exact: true }).fill('Synthetic reviewed attempt');
  await review.getByLabel('Start seconds 1', { exact: true }).fill('0.0000000001');
  await review.getByRole('button', { name: 'Save review declaration' }).click();
  await expect(review.getByRole('alert')).toContainText('at most nine decimal places');
  expect(posts).toHaveLength(0);
  await review.getByLabel('Start seconds 1', { exact: true }).fill('0.000000001');
  await review.getByRole('button', { name: 'Save review declaration' }).click();
  await expect(review.getByRole('alert')).toContainText('Your draft is preserved');
  await expect(review.getByLabel('Start seconds 1', { exact: true })).toHaveValue('0.000000001');
  expect(posts[0].body.intervals[0]).toMatchObject({ start_ns: '1', end_ns: '1000000000', judgment: 'accepted' });
  expect(posts[0].body).not.toHaveProperty('reviewer_id');
  conflict = false;
  await review.getByRole('button', { name: 'Save review declaration' }).click();
  await expect(review).toContainText('Saved review declaration revision 1');
  await expect(review.getByRole('cell', { name: '0.999999999', exact: true })).toBeVisible();
  await review.getByLabel('Task ID', { exact: true }).fill('different_task');
  await expect(review.getByRole('button', { name: 'Save review declaration' })).toBeDisabled();
  expect(posts).toHaveLength(2);
  expect(posts.every(p => p.path.endsWith('/activity-review'))).toBe(true);
});
