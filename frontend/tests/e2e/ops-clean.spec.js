import { test, expect } from '@playwright/test';
import { expectNoHorizontalOverflow } from './helpers.js';

const person = { id: 1, name: '한규태', workplace: '한그라픽스', location: 'Korea', rate_krw_hour: 11000, is_active: true };
const run = (id, retained, excluded, estimate) => ({ run_id: id, wearer_id: 1, device_id: '16A4A5', retained_seconds: retained, rejected_seconds: excluded, source_seconds: retained + excluded, estimated_krw: estimate, rate_krw_hour: 11000, paid: false, recording_count: 1, recordings: [{ recording: `${id}-recording`, source_seconds: retained + excluded, retained_seconds: retained, status: 'completed' }], review_intervals: [], warnings: [] });
const first = run('first', 20297.806709, 9746.833299666667, 62021);
const second = run('second', 7975, 3266.9, 24368);
const collection = { collection_id: 'complete', wearer_id: 1, label: '한규태 · 전체 Clean', retained_seconds: 28272.8, recordings: Array.from({ length: 35 }, (_, i) => ({ recording: `recording-${i}` })), source_runs: [{ run_id: 'first' }, { run_id: 'second' }] };

async function openClean(page, state) {
  const requests = [];
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push({ path, method: request.method() });
    let data;
    if (path === '/api/auth/me') data = { id: 100, email: 'ops@example.test', role: 'ops' };
    else if (path === '/api/ops/state') data = { episodes: [], wearers: [person], tasks: [], totals: {} };
    else if (path === '/api/ops/clean/state') data = state;
    else if (path.endsWith('/files')) data = { files: [{ key: 'joined.mp4', url: '/test-video.mp4', role: 'joined_preview', label: 'Combined video' }, { key: 'recording.mp4', url: '/test-recording.mp4', role: 'recording_preview', recording: 'first-recording', label: 'Recording preview' }] };
    else return route.fulfill({ status: 404 });
    await route.fulfill({ json: data });
  });
  await page.route('**/test-*.mp4', route => route.fulfill({ status: 200, contentType: 'video/mp4', body: '' }));
  await page.goto('/portal/ops');
  await page.getByRole('button', { name: 'Clean', exact: true }).click();
  await expect(page.locator('.ops-clean-card')).not.toHaveCount(0);
  return requests;
}

test('one contributor card combines totals and playback while preserving batch review', async ({ page }, testInfo) => {
  const reviewed = { ...first, review_intervals: [{ recording: 'first-recording', start_s: 1, end_s: 10, clean_start_s: 1, reason: 'Paperwork to review' }], warnings: ['Recovered footage'] };
  const requests = await openClean(page, { runs: [reviewed, second], collections: [collection], wearers: [person], cameras: [] });
  const card = page.locator('.ops-clean-card');
  await expect(card).toHaveCount(1);
  await expect(card.getByRole('heading', { name: '한규태', exact: true })).toHaveCount(1);
  await expect(card.locator('.ops-clean-metrics')).not.toContainText('₩');
  await expect(card.locator('.ops-clean-metrics')).toContainText('7h 51m 13s');
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath('clean-collapsed.png'), fullPage: true });
  await card.getByRole('button', { name: 'Watch all clean footage' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(requests.some(r => r.path === '/api/ops/clean/collections/complete/files')).toBe(true);
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await card.locator('summary').filter({ hasText: 'Batch details' }).click();
  await expect(card.getByRole('region', { name: 'Batch 1', exact: true })).toBeVisible();
  await expect(card.getByRole('region', { name: 'Batch 2', exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Watch batch 2' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(requests.some(r => r.path === '/api/ops/clean/runs/second/files')).toBe(true);
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await card.locator('summary').filter({ hasText: 'Flagged footage' }).click();
  await card.getByRole('button', { name: 'Review interval' }).click();
  await expect(page.getByLabel('Video', { exact: true }).locator('option')).toHaveCount(1);
  await expect(page.locator('.ops-clean-modal video')).toHaveAttribute('src', '/test-recording.mp4');
  expect(requests.some(r => r.path === '/api/ops/clean/runs/first/files')).toBe(true);
  await page.getByRole('button', { name: 'Close', exact: true }).click();
  await expectNoHorizontalOverflow(page);
  expect(requests.every(r => r.method === 'GET')).toBe(true);
});

test('missing combined video keeps one contributor, batch access, and footage-only state', async ({ page }) => {
  await openClean(page, { runs: [{ ...first, paid: true }, second], collections: [], collection_errors: 1, wearers: [person], cameras: [] });
  const card = page.locator('.ops-clean-card');
  await expect(card).toHaveCount(1);
  await expect(card.locator('.ops-clean-status')).toHaveText('Footage ledger');
  await expect(card.locator('.ops-clean-metrics')).not.toContainText('₩');
  await expect(page.getByRole('alert')).toContainText('could not be verified');
  await card.locator('summary').filter({ hasText: 'Batch details' }).click();
  await expect(card.getByRole('button', { name: 'Watch batch 1' })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Watch batch 2' })).toBeVisible();
});

test('new batch outside the joined video remains accessible without claiming full playback coverage', async ({ page }) => {
  await openClean(page, { runs: [first, second, run('third', 3600, 60, 11000)], collections: [collection], wearers: [person], cameras: [] });
  const card = page.locator('.ops-clean-card');
  await expect(card).toHaveCount(1);
  await expect(card.getByRole('button', { name: 'Watch all clean footage' })).toHaveCount(0);
  await expect(card.getByRole('button', { name: 'Watch combined footage' })).toBeVisible();
  await expect(card.locator('.ops-clean-metrics')).toContainText('8h 51m 13s');
  await card.locator('summary').filter({ hasText: 'Batch details' }).click();
  await expect(card.getByRole('button', { name: 'Watch batch 3' })).toBeVisible();
});
