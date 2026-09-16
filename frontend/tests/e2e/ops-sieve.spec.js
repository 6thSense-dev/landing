import { test, expect } from '@playwright/test';
import { expectNoHorizontalOverflow } from './helpers.js';

const group = (label, inherited = 3600) => ({ label, seconds: 3600, inherited_seconds: inherited, recordings: 1 });
async function setup(page) {
  const now = new Date().toISOString();
  const state = { expired: false, failing: false, pipelineFailing: false, requests: [], pipeline: {
    checked_at: now, cache: { stale: false }, errors: [],
    company: { available: true, source_groups: 55, archived: 44, clean_complete: 38, in_progress: 2, held: 9, deleted: 6, updated_at: now },
    delivery: { available: true, state: 'DELIVERED_CHECKSUMS_VERIFIED', recordings_processed: 34, recordings_expected: 34, prepared_hours: 6.03, packaged_assets: 325, uploaded_assets: 325, uploaded_files: 2600, total_files: 2600, uploaded_bytes: 240e9, total_bytes: 240e9, uploaded_hours: 6.03, complete: true, updated_at: now },
    validation: { available: true, state: 'IN_PROGRESS', clip_reports: 198, total_clips: 325, updated_at: now },
    supplement: { available: true, state: 'READY_FOR_REVIEW', recordings: 11, hours: 4.6966, bytes: 25394194367, external_delivery_performed: false, updated_at: now },
  }, data: {
    automatic_sync: true, updated_at: new Date().toISOString(), sync: { completed_at: new Date().toISOString() }, bucket: '6thsense-sieve', prefix: 'inherited/v1/',
    totals: { clean_seconds: 7200, inherited_seconds: 3600, recordings: 2, inherited_recordings: 1, copied_bytes: 1e9, countries: 2, entities: 2, cameras: 2, status_counts: { inherited: 1, blocked: 1 } },
    breakdowns: { country: [group('Korea'), group('India',0)], entity: [group('한규태 / 한그라픽스'), group('India contributor',0)], activity: [group('Print Removal'), group('Unclassified',0)], clean_date: [{...group('2026-09-15'), seconds:7200, recordings:2}] },
    recordings: [
      { run_id:'korea', recording:'ego_20260901_120000_ABC123', country:'Korea', entity:{name:'한규태 / 한그라픽스'}, activity:'Print Removal', camera:'ABC123', format:'Split stereo', retained_seconds:3600, status:'inherited' },
      { run_id:'india', recording:'ego_20260901_130000_DEF456', country:'India', entity:{name:'India contributor'}, activity:'Unclassified', camera:'DEF456', format:'Split stereo', retained_seconds:3600, status:'blocked', reason:'Clean artifact is missing' },
    ],
  }};
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    state.requests.push({ path, method:route.request().method() });
    if (path === '/api/auth/me') return route.fulfill({ json:{id:100,role:'ops',email:'ops@example.test'} });
    if (path === '/api/ops/sieve/availability') return route.fulfill({ json:{visible:!state.expired} });
    if (path === '/api/ops/sieve/state') return route.fulfill({ status:state.expired?410:state.failing?503:200, json:state.data });
    if (path === '/api/ops/sieve/pipeline') return route.fulfill({ status:state.expired?410:state.pipelineFailing?503:200, json:state.pipeline });
    if (path === '/api/ops/state') return route.fulfill({ json:{episodes:[],wearers:[],tasks:[],totals:{}} });
    if (path === '/api/ops/clean/state') return route.fulfill({ json:{runs:[],wearers:[],cameras:[],ledger:[],collections:[]} });
    return route.fulfill({status:404});
  });
  return state;
}

test('unique hours, diversity and provenance; filters and responsive layout', async ({page},testInfo) => {
  const state = await setup(page);
  await page.goto('/portal/ops?tab=sieve');
  await expect(page.getByRole('heading',{name:'Sieve',exact:true})).toBeVisible();
  await expect(page.locator('.sieve-stats')).toContainText('2.00');
  await expect(page.locator('.sieve-stats')).toContainText('1.00');
  await expect(page.locator('.sieve-deadline')).toContainText('Sep 22, 2026');
  await expect(page.locator('.sieve-deadline')).toContainText('Sep 25');
  await expect(page.locator('.sieve-progress')).toContainText('50% inherited');
  await expect(page.getByRole('region',{name:'Activity',exact:true})).toContainText('Unclassified');
  await expect(page.locator('.sieve-recording')).toHaveCount(2);
  await expectNoHorizontalOverflow(page);
  await page.screenshot({path:testInfo.outputPath('sieve-dashboard.png'),fullPage:true});
  await page.getByLabel('Filter recordings by country',{exact:true}).selectOption('India');
  await expect(page.locator('.sieve-recording')).toHaveCount(1);
  await page.locator('.sieve-recording summary').click();
  await expect(page.locator('.sieve-recording')).toContainText('Clean artifact is missing');
  await page.getByLabel('Filter recordings by status',{exact:true}).selectOption('inherited');
  await expect(page.getByText('No recordings match these filters.')).toBeVisible();
  await page.getByLabel('Filter recordings by country',{exact:true}).selectOption('');
  await page.getByLabel('Filter recordings by status',{exact:true}).selectOption('');
  await page.getByLabel('Search recordings',{exact:true}).fill('한규태');
  await expect(page.locator('.sieve-recording')).toHaveCount(1);
  await expectNoHorizontalOverflow(page);
  expect(state.requests.every(r=>r.method==='GET')).toBe(true);
});

test('refresh failure keeps previous totals and retry recovers', async ({page}) => {
  const state = await setup(page);
  await page.goto('/portal/ops?tab=sieve');
  await expect(page.locator('.sieve-stats')).toBeVisible();
  state.failing=true;
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.getByRole('alert')).toContainText('last loaded snapshot');
  await expect(page.locator('.sieve-stats')).toContainText('2.00');
  state.failing=false;
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('initial retry works; expiry removes tab and redirects to Clean', async ({page}) => {
  const state=await setup(page);state.failing=true;
  await page.goto('/portal/ops?tab=sieve');
  await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeVisible();
  state.failing=false;
  await page.getByRole('button',{name:'Retry',exact:true}).click();
  await expect(page.locator('.sieve-stats')).toBeVisible();
  state.expired=true;
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.getByRole('button',{name:'Sieve',exact:true})).toHaveCount(0);
  await expect(page).toHaveURL(/tab=clean/);
});

test('empty Clean shows zero and useful empty state', async ({page}) => {
  const state=await setup(page);state.data.recordings=[];
  for(const key of Object.keys(state.data.breakdowns))state.data.breakdowns[key]=[];
  state.data.totals={clean_seconds:0,inherited_seconds:0,recordings:0,inherited_recordings:0,copied_bytes:0,countries:0,entities:0,cameras:0,status_counts:{}};
  await page.goto('/portal/ops?tab=sieve');
  await expect(page.getByText('New recordings will appear after they enter Clean.')).toBeVisible();
  await expect(page.locator('.sieve-progress')).toContainText('0% inherited');
  await expectNoHorizontalOverflow(page);
});

test('pipeline separates processing, customer upload, validation and private hours', async ({page}, testInfo) => {
  const state = await setup(page);
  await page.goto('/portal/ops?tab=sieve');
  const panel = page.getByRole('region', { name: 'Live pipeline progress' });
  await expect(panel).toBeVisible();
  await expect(page.getByRole('article', {name: 'Company Raw → Clean'})).toContainText('All countries');
  await expect(page.getByRole('article', {name: 'Sieve preparation'})).toContainText('6.03 h');
  const uploaded = page.getByRole('article', {name: 'Uploaded to Sieve'});
  await expect(uploaded).toContainText('6.03 h');
  await expect(uploaded).toContainText('2,600 / 2,600');
  await expect(uploaded).toContainText('240 GB / 240 GB');
  await expect(uploaded).toContainText('Upload complete');
  await expect(uploaded.getByRole('progressbar')).toHaveAttribute('value', '2600');
  const validation = page.getByRole('article', {name: 'Independent validation'});
  await expect(validation).toContainText('198 / 325');
  await expect(validation.getByText('Passed', {exact: true})).toHaveCount(0);
  const supplement = page.getByRole('article', {name: 'Private originals supplement'});
  await expect(supplement).toContainText('4.70 h');
  await expect(supplement).toContainText('not uploaded to Sieve');
  await expect(page.getByText('Copied to internal Sieve storage', {exact:true})).toBeVisible();
  await expect(page.getByText('Hours inherited by Sieve', {exact:true})).toHaveCount(0);
  expect(await panel.evaluate(el => el.compareDocumentPosition(document.querySelector('.sieve-stats')) & Node.DOCUMENT_POSITION_FOLLOWING)).toBeTruthy();
  await expect(panel.getByRole('button')).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await page.screenshot({path:testInfo.outputPath('sieve-live-progress.png'), fullPage:true});
  expect(state.requests.every(r=>r.method==='GET')).toBe(true);
});

test('unavailable and partial pipeline never invent zero counts or passing validation', async ({page}) => {
  const state = await setup(page);
  state.pipeline.company = {available:false, source_groups:null};
  state.pipeline.delivery = {available:true, state:'RUNNING', prepared_hours:2.3, uploaded_hours:null, uploaded_files:16, total_files:null, uploaded_bytes:1e9, total_bytes:null, stale:true};
  state.pipeline.validation = {available:true, state:'COMPLETE', clip_reports:214, total_clips:214};
  state.pipeline.supplement = {available:false, hours:null};
  state.pipeline.errors = ['private-implementation-error-not-for-display'];
  await page.goto('/portal/ops?tab=sieve');
  await expect(page.getByRole('article', {name:'Company Raw → Clean'})).toContainText('Status unavailable. No count is assumed.');
  const uploaded = page.getByRole('article', {name:'Uploaded to Sieve'});
  await expect(page.getByRole('article', {name:'Sieve preparation'})).toContainText('2.30 h');
  await expect(uploaded).toContainText('Not reported');
  await expect(uploaded).toContainText('16 / —');
  await expect(uploaded).toContainText('Stale snapshot');
  await expect(uploaded.getByRole('progressbar')).toHaveCount(0);
  await expect(page.getByRole('article',{name:'Independent validation'})).toContainText('Result not yet reported');
  await expect(page.getByRole('region',{name:'Live pipeline progress'})).not.toContainText('0.00');
  await expect(page.getByRole('region',{name:'Live pipeline progress'})).not.toContainText('private-implementation');
  await expect(page.locator('.sieve-stats')).toContainText('2.00');
  await expectNoHorizontalOverflow(page);
});

test('pipeline refresh fails independently and only explicit PASS marks validation passed', async ({page}) => {
  const state = await setup(page);
  await page.goto('/portal/ops?tab=sieve');
  await expect(page.getByRole('article',{name:'Uploaded to Sieve'})).toContainText('6.03 h');
  state.pipelineFailing = true;
  state.data.totals.clean_seconds = 10800;
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.getByRole('region',{name:'Live pipeline progress'})).toContainText('Showing the last loaded pipeline snapshot');
  await expect(page.getByRole('article',{name:'Uploaded to Sieve'})).toContainText('6.03 h');
  await expect(page.locator('.sieve-stats')).toContainText('3.00');
  state.pipelineFailing = false;
  state.pipeline.validation.state = 'PASS';
  state.pipeline.cache.stale = true;
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.getByRole('article',{name:'Independent validation'}).locator('.sieve-pipeline-verdict')).toHaveText('Passed');
  await expect(page.getByRole('region',{name:'Live pipeline progress'})).toContainText('Pipeline updates are delayed');
  await expect(page.getByRole('region',{name:'Live pipeline progress'})).not.toContainText('Live update failed');
});

test('pipeline works when collection is unavailable and both endpoints poll', async ({page}) => {
  await page.clock.install();
  const state = await setup(page);
  state.failing = true;
  Object.assign(state.pipeline.delivery, {state:'TRANSFERRING', complete:false, uploaded_hours:null, uploaded_files:1656, uploaded_assets:207, uploaded_bytes:150e9});
  await page.goto('/portal/ops?tab=sieve');
  await expect(page.getByRole('article',{name:'Uploaded to Sieve'})).toContainText('Uploaded hours are not yet confirmed');
  await expect(page.getByRole('button',{name:'Retry',exact:true})).toBeVisible();
  const before = state.requests.filter(r=>r.path==='/api/ops/sieve/pipeline').length;
  state.pipeline.delivery.uploaded_files = 1700;
  await page.clock.fastForward(30001);
  await expect(page.getByRole('article',{name:'Uploaded to Sieve'})).toContainText('1,700 / 2,600');
  expect(state.requests.filter(r=>r.path==='/api/ops/sieve/pipeline').length).toBeGreaterThan(before);
  expect(state.requests.filter(r=>r.path==='/api/ops/sieve/state').length).toBeGreaterThan(1);
});

test('initial pipeline error leaves collection usable', async ({page}) => {
  const state = await setup(page);
  state.pipelineFailing = true;
  await page.goto('/portal/ops?tab=sieve');
  const panel = page.getByRole('region',{name:'Live pipeline progress'});
  await expect(panel).toContainText('Live pipeline status is unavailable');
  await expect(panel.getByRole('progressbar')).toHaveCount(0);
  await expect(panel).not.toContainText('0.00');
  await expect(page.locator('.sieve-recording')).toHaveCount(2);
  state.pipelineFailing = false;
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.getByRole('article',{name:'Uploaded to Sieve'})).toContainText('6.03 h');
});
