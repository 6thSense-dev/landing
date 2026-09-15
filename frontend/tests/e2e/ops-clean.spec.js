import { test, expect } from '@playwright/test';
import { expectNoHorizontalOverflow } from './helpers.js';

const person = { id: 1, name: '한규태', workplace: '한그라픽스', location: 'Korea', rate_krw_hour: 11000, is_active: true };
const run = (id, retained, excluded, estimate) => ({ region: { key: 'korea', label: 'Korea' }, run_id: id, wearer_id: 1, device_id: '16A4A5', retained_seconds: retained, rejected_seconds: excluded, source_seconds: retained + excluded, estimated_krw: estimate, rate_krw_hour: 11000, paid: false, recording_count: 1, recordings: [{ recording: `${id}-recording`, source_seconds: retained + excluded, retained_seconds: retained, status: 'completed' }], review_intervals: [], warnings: [] });
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
  await expect(page.getByRole('heading', { name: 'Clean footage by region' })).toBeVisible();
  await expect(page.locator('.ops-clean-card')).toHaveCount(0);
  await page.getByRole('button', { name: 'View Korea', exact: true }).click();
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
  await expect(page.getByLabel('Video', { exact: true })).toHaveValue('1');
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

test('region navigation separates people, hours, playback and review entries', async ({ page }, testInfo) => {
  const china = { ...run('china', 3600, 600, 11000), region: { key: 'china', label: 'China' } };
  const other = { ...run('other', 1800, 300, 5500), wearer_id: 2, device_id: 'ABC123' };
  const ledger = [first, china].map(r => ({ run_id: r.run_id, recording: `${r.run_id}-recording`, wearer_id: 1, source_seconds: r.source_seconds, retained_seconds: r.retained_seconds, rejected_seconds: r.rejected_seconds, review_status: 'needs_review', rejection_reasons: {}, review_intervals: [] }));
  const mixed = { ...collection, source_runs: [{ run_id: 'first' }, { run_id: 'china' }] };
  await openClean(page, { runs: [first, other, china], collections: [mixed], ledger, wearers: [person, { id: 2, name: 'Second contributor' }], cameras: [] });
  await expect(page.locator('.ops-clean-card')).toHaveCount(2);
  await expect(page.locator('.ops-footage-review')).toHaveCount(1);
  await expect(page.locator('.ops-footage-review')).toContainText('first-recording');
  await expect(page.getByRole('button', { name: 'Watch all clean footage' })).toHaveCount(0);
  await expect(page.getByLabel('Korea hour totals')).toContainText('6h 08m 18s');
  await page.getByLabel('Filter footage by source').selectOption('wearer:2');
  await expect(page.locator('.ops-clean-card')).toHaveCount(1);
  await expect(page.getByLabel('Korea hour totals')).toContainText('6h 08m 18s');
  await page.getByRole('button', { name: 'All regions', exact: true }).click();
  await expect(page.getByRole('button', { name: 'View Korea', exact: true })).toContainText('2 contributors');
  await expect(page.getByRole('button', { name: 'View China', exact: true })).toContainText('1h 00m 00s');
  await expect(page.getByRole('button', { name: 'View Vietnam', exact: true })).toContainText('No clean footage yet');
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath('clean-regions.png'), fullPage: true });
  await page.getByRole('button', { name: 'View China', exact: true }).click();
  await expect(page.locator('.ops-clean-card')).toHaveCount(1);
  await expect(page.locator('.ops-footage-review')).toHaveCount(1);
  await expect(page.locator('.ops-footage-review')).toContainText('china-recording');
  await page.getByLabel('Region', { exact: true }).selectOption('vietnam');
  await expect(page.getByRole('heading', { name: 'No clean footage in Vietnam yet' })).toBeVisible();
  await expect(page.locator('.ops-clean-card')).toHaveCount(0);
});

test('late playback from the previous region cannot reopen its player', async ({ page }) => {
  await openClean(page, { runs: [first], collections: [], wearers: [person], cameras: [] });
  let release;
  const pending = new Promise(resolve => { release = resolve; });
  let started = false;
  await page.route('**/api/ops/clean/runs/first/files', async route => {
    started = true;
    await pending;
    await route.fulfill({ json: { files: [{ key: 'late.mp4', url: '/test-late.mp4', role: 'joined_preview' }] } });
  });
  await page.getByRole('button', { name: 'Watch footage', exact: true }).click();
  await expect.poll(() => started).toBe(true);
  await page.getByLabel('Region', { exact: true }).selectOption('china');
  const received = page.waitForResponse('**/api/ops/clean/runs/first/files');
  release();
  await (await received).finished();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.getByRole('heading', { name: 'China · Clean footage' })).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('business factory batches group in China with their own playback and no contributor payout prompt', async ({ page }) => {
  const business = { kind: 'business', id: 'factory-example', name: 'Example factory', country: 'china', payment_model: 'b2b_contract' };
  const factory = id => ({ ...run(id, 60, 40, null), wearer_id: null, counterparty: business,
    region: { key: 'china', label: 'China' }, rate_krw_hour: null });
  const ledger = [{ run_id: 'factory-first', recording: 'factory-first-recording', counterparty: business, wearer_id: null,
    review_status: 'needs_review', artifact_status: 'complete', retained_seconds: 60, source_seconds: 100, rejected_seconds: 40,
    review_intervals: [], rejection_reasons: {}, date_basis: 'Camera NTP', collection_date: '2026-09-01', payment_status: 'b2b_contract' }];
  const requests = await openClean(page, { runs: [first, factory('factory-first'), factory('factory-second')], collections: [], ledger, wearers: [person], cameras: [] });
  await page.getByLabel('Region', { exact: true }).selectOption('china');
  const card = page.locator('.ops-clean-card');
  await expect(card).toHaveCount(1);
  await expect(card.getByRole('heading', { name: 'Example factory', exact: true })).toBeVisible();
  await expect(card).toContainText('B2B factory contract');
  await expect(card).toContainText('Settlement is managed separately from individual contributor payouts.');
  await expect(card).not.toContainText(person.name);
  await expect(card).not.toContainText('Unassigned contributor');
  await expect(card).not.toContainText('approve the payout in Payment');
  await card.locator('.ops-footage-review > summary').click();
  await expect(card.getByLabel('Collection date (China)')).toBeVisible();
  await expect(card.getByRole('button', { name: 'Hold for review', exact: true })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Withhold from payment', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('China hour totals')).toContainText('0h 02m 00s');
  await card.locator('summary').filter({ hasText: 'Batch details' }).click();
  await card.getByRole('button', { name: 'Watch batch 2', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(requests.some(r => r.path === '/api/ops/clean/runs/factory-second/files')).toBe(true);
  expect(requests.every(r => r.method === 'GET')).toBe(true);
});
