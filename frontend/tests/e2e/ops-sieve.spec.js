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

const summary = (page, name) => page.locator('summary').filter({hasText:name});
const metric = (page, name) => page.getByRole('article',{name,exact:true});

test('delivery overview is compact and keeps totals separate', async ({page}, info) => {
  const state = await setup(page);
  await page.goto('/portal/ops?tab=sieve');
  await expect(metric(page,'Uploaded to Sieve')).toContainText('6.03 h');
  await expect(metric(page,'Uploaded to Sieve')).toContainText('of 10 h delivery target');
  await expect(metric(page,'Available in Clean')).toContainText('2.00 h');
  await expect(metric(page,'Originals transfer')).toContainText('4.70 h');
  await expect(metric(page,'Uploaded to Sieve').getByRole('progressbar')).toHaveAttribute('value','6.03');
  await expect(page.getByRole('region',{name:'Delivery overview'})).not.toContainText('10.73');
  await expect(page.getByLabel('What happens next')).toContainText('Technical checks: in progress');
  await expect(page.getByRole('link',{name:'Review footage'})).toHaveAttribute('href','/portal/ops?tab=clean');
  await expect(page.getByLabel('Company processing')).toContainText('38 processed');
  await expect(page.getByLabel('Company processing')).toContainText('2 in progress');
  await expect(page.getByLabel('Company processing')).toContainText('9 held');
  await expect(page.locator('.sieve-processing')).not.toHaveAttribute('open','');
  await expect(page.locator('.sieve-breakdown')).not.toHaveAttribute('open','');
  if(info.project.name==='desktop-1280') expect((await page.getByRole('heading',{name:'Browse footage'}).boundingBox()).y).toBeLessThan(750);
  await expectNoHorizontalOverflow(page);
  await page.screenshot({path:info.outputPath('sieve-overview.png'),fullPage:true});
  expect(state.requests.every(r=>r.method==='GET')).toBe(true);
});

test('all original statistics and technical details remain accessible', async ({page},info) => {
  await setup(page);
  await page.goto('/portal/ops?tab=sieve');
  await summary(page,'Processing details').focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('region',{name:'Sieve preparation',exact:true})).toContainText('34 / 34 recordings');
  await expect(page.getByRole('region',{name:'Sieve preparation',exact:true})).toContainText('325 clips');
  const upload=page.getByRole('region',{name:'Customer upload',exact:true});
  await expect(upload).toContainText('2,600 / 2,600');
  await expect(upload).toContainText('240 GB / 240 GB');
  await expect(upload).toContainText('325 / 325 clips');
  await expect(page.getByRole('region',{name:'Independent validation',exact:true})).toContainText('198 / 325');
  await expect(page.getByRole('region',{name:'Private extra footage',exact:true})).toContainText('25.39 GB');
  await expect(page.getByRole('region',{name:'Originals archive',exact:true})).toContainText('44 archived / 55 upload groups · 6 deleted');
  const copies=page.getByRole('region',{name:'Internal Sieve copies',exact:true});
  await expect(copies).toContainText('1.00 h copied · 1 recordings');
  await expect(copies).toContainText('1 GB · 50% of Clean copied');
  await expect(copies).toContainText('0 copy pending · 1 copy blocked');
  await expect(copies).toContainText('Original codecs are preserved');
  await summary(page,'Collection breakdown').click();
  for(const name of ['Country','Contributor / business','Activity','Clean intake by day']) await expect(page.getByRole('region',{name,exact:true})).toBeVisible();
  await expect(page.getByRole('region',{name:'Activity',exact:true})).toContainText('Unclassified');
  await expect(page.locator('.sieve-breakdown')).toContainText('2 countries · 2 contributors · 2 cameras');
  await expect(page.locator('.sieve-deadline')).toContainText('Sep 22, 2026');
  await expect(page.locator('.sieve-footer')).toContainText('Sep 25');
  await expectNoHorizontalOverflow(page);
  await page.screenshot({path:info.outputPath('sieve-expanded.png'),fullPage:true});
});

test('recordings paginate and filters search the entire collection', async ({page}) => {
  const state=await setup(page);
  state.data.recordings=Array.from({length:24},(_,i)=>({...state.data.recordings[i%2],run_id:`run-${i}`,recording:`recording-${String(i).padStart(2,'0')}`}));
  await page.goto('/portal/ops?tab=sieve');
  await expect(page.locator('.sieve-recording')).toHaveCount(10);
  await expect(page.getByRole('navigation',{name:'Recording pages'})).toContainText('1–10 of 24');
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await expect(page.locator('.sieve-recording').first()).toContainText('recording-10');
  await page.getByLabel('Search recordings',{exact:true}).fill('recording-23');
  await expect(page.locator('.sieve-recording')).toHaveCount(1);
  await page.locator('.sieve-recording summary').click();
  await expect(page.locator('.sieve-recording')).toContainText('Clean artifact is missing');
  await expect(page.getByRole('navigation',{name:'Recording pages'})).toHaveCount(0);
  await page.getByLabel('Search recordings',{exact:true}).fill('');
  await page.getByLabel('Filter recordings by country',{exact:true}).selectOption('India');
  await expect(page.getByRole('navigation',{name:'Recording pages'})).toContainText('1–10 of 12');
  await page.getByLabel('Filter recordings by status',{exact:true}).selectOption('inherited');
  await expect(page.getByText('No recordings match these filters.')).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test('unavailable or partial figures never become zero or passed', async ({page}) => {
  const state=await setup(page);
  state.pipeline.company={available:false};state.pipeline.supplement={available:false};
  Object.assign(state.pipeline.delivery,{state:'TRANSFERRING',complete:false,uploaded_hours:null,uploaded_files:16,total_files:null,stale:true});
  state.pipeline.validation={available:true,state:'COMPLETE',clip_reports:325,total_clips:325};
  await page.goto('/portal/ops?tab=sieve');
  await expect(metric(page,'Uploaded to Sieve')).toContainText('Not reported');
  await expect(metric(page,'Uploaded to Sieve').getByRole('progressbar')).toHaveCount(0);
  await expect(metric(page,'Originals transfer')).toContainText('Not reported');
  await expect(page.getByLabel('What happens next')).toContainText('Technical checks: result pending');
  await expect(page.getByLabel('Company processing')).toContainText('status unavailable');
  await expect(page.getByRole('status')).toContainText('Last known figures');
  await summary(page,'Processing details').click();
  await expect(page.getByRole('region',{name:'Customer upload',exact:true})).toContainText('16 / —');
  await expect(page.getByRole('region',{name:'Customer upload',exact:true})).toContainText('Stale snapshot');
});

test('refresh failures preserve snapshots and both sources recover independently', async ({page}) => {
  const state=await setup(page);
  await page.goto('/portal/ops?tab=sieve');
  await expect(metric(page,'Uploaded to Sieve')).toContainText('6.03 h');
  state.pipelineFailing=true;state.data.totals.clean_seconds=10800;
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.getByRole('status')).toContainText('last loaded delivery snapshot');
  await expect(metric(page,'Uploaded to Sieve')).toContainText('6.03 h');
  await expect(metric(page,'Available in Clean')).toContainText('3.00 h');
  state.pipelineFailing=false;state.failing=true;state.pipeline.validation.state='PASS';
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.getByRole('alert')).toContainText('last loaded snapshot');
  await expect(page.getByLabel('What happens next')).toContainText('Technical checks: passed');
  await expect(metric(page,'Uploaded to Sieve')).toContainText('customer acceptance not recorded');
  state.failing=false;
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
});

test('initial failure leaves the other source useful and expiry redirects', async ({page}) => {
  const state=await setup(page);state.failing=true;
  await page.goto('/portal/ops?tab=sieve');
  await expect(metric(page,'Uploaded to Sieve')).toContainText('6.03 h');
  await expect(metric(page,'Available in Clean')).toContainText('Not reported');
  state.failing=false;
  await page.getByRole('button',{name:'Retry',exact:true}).click();
  await expect(page.locator('.sieve-recording')).toHaveCount(2);
  state.expired=true;
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(page).toHaveURL(/tab=clean/);
});

test('empty collection and initial pipeline failure stay honest', async ({page}) => {
  const state=await setup(page);state.pipelineFailing=true;state.data.recordings=[];
  for(const key of Object.keys(state.data.breakdowns))state.data.breakdowns[key]=[];
  state.data.totals={clean_seconds:0,inherited_seconds:0,recordings:0,inherited_recordings:0,copied_bytes:0,countries:0,entities:0,cameras:0,status_counts:{}};
  await page.goto('/portal/ops?tab=sieve');
  await expect(metric(page,'Available in Clean')).toContainText('0.00 h');
  await expect(metric(page,'Uploaded to Sieve')).toContainText('Not reported');
  await expect(page.getByText('New recordings will appear after they enter Clean.')).toBeVisible();
  await expect(page.getByRole('status')).toContainText('Delivery status is unavailable');
  await expectNoHorizontalOverflow(page);
});

test('automatic refresh updates counts without collapsing open details', async ({page}) => {
  await page.clock.install();const state=await setup(page);
  await page.goto('/portal/ops?tab=sieve');
  await summary(page,'Processing details').click();
  await summary(page,'Collection breakdown').click();
  const before=state.requests.length;
  state.pipeline.company.in_progress=1;state.pipeline.validation.clip_reports=222;
  await page.clock.fastForward(30001);
  await expect(page.getByLabel('Company processing')).toContainText('1 in progress');
  await expect(page.getByRole('region',{name:'Independent validation',exact:true})).toContainText('222 / 325');
  await expect(page.locator('.sieve-processing')).toHaveAttribute('open','');
  await expect(page.locator('.sieve-breakdown')).toHaveAttribute('open','');
  expect(state.requests.slice(before).some(r=>r.path==='/api/ops/sieve/pipeline')).toBeTruthy();
  expect(state.requests.slice(before).some(r=>r.path==='/api/ops/sieve/state')).toBeTruthy();
});


test('polling shrink does not restore an obsolete page when new footage arrives', async ({page}) => {
  await page.clock.install();
  const state=await setup(page);
  const all=Array.from({length:24},(_,i)=>({...state.data.recordings[0],run_id:`run-${i}`,recording:`recording-${String(i).padStart(2,'0')}`}));
  state.data.recordings=all;
  await page.goto('/portal/ops?tab=sieve');
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await expect(page.getByRole('navigation',{name:'Recording pages'})).toContainText('21–24 of 24');
  state.data.recordings=all.slice(0,8);
  await page.clock.fastForward(30001);
  await expect(page.locator('.sieve-recording')).toHaveCount(8);
  state.data.recordings=all;
  await page.clock.fastForward(30001);
  await expect(page.getByRole('navigation',{name:'Recording pages'}).getByRole('status')).toHaveText('1–10 of 24 recordings');
});

const originalsTransfer = (overrides = {}) => ({
  available:true, state:'UPLOADED_FOR_CUSTOMER_QC', total_files:604, uploaded_files:604,
  total_bytes:25394461079, uploaded_bytes:25394461079,
  potential_unique_technical_hours:4.696644566, uploaded_hours:4.696644566,
  complete:true, external_transfer_completed:true, customer_accepted:false, human_review:'PENDING',
  updated_at:new Date().toISOString(), ...overrides,
});

test('verified original folders add hours with explicit split and pending customer QC', async ({page},info) => {
  const state=await setup(page);state.pipeline.supplement_delivery=originalsTransfer();
  state.pipeline.validation.state='PASS';
  await page.goto('/portal/ops?tab=sieve');
  const uploaded=metric(page,'Uploaded to Sieve');
  await expect(uploaded).toContainText('10.73 h');
  await page.screenshot({path:info.outputPath('supplement-delivered.png'),fullPage:true});
  await expect(uploaded).toContainText('6.03 h formatted + 4.70 h original folders for customer QC');
  await expect(uploaded).toContainText('not accepted hours');
  await expect(uploaded).toContainText('customer acceptance not recorded');
  await expect(metric(page,'Originals transfer')).toContainText('Sent for customer QC');
  await expect(metric(page,'Originals transfer')).toContainText('604 / 604 files');
  await expect(metric(page,'Originals transfer')).toContainText('Human review and acceptance pending');
  await expect(page.getByLabel('What happens next')).toContainText('Formatted batch only');
  await summary(page,'Processing details').click();
  await expect(page.getByRole('region',{name:'Originals customer transfer',exact:true})).toContainText('separate from the formatted batch');
  await expect(page.getByRole('region',{name:'Private extra footage',exact:true})).toContainText('Historical private staging snapshot');
  await expectNoHorizontalOverflow(page);
  expect(state.requests.every(r=>r.method==='GET')).toBe(true);
});

for(const transferState of ['PREPARING','UPLOADING','FAILED','INCONSISTENT']) {
  test(`${transferState} originals remain excluded from uploaded hours`, async ({page}) => {
    const state=await setup(page);
    state.pipeline.supplement_delivery=originalsTransfer({state:transferState,complete:false,external_transfer_completed:false,
      uploaded_hours:null,uploaded_files:100,uploaded_bytes:2e9});
    await page.goto('/portal/ops?tab=sieve');
    await expect(metric(page,'Uploaded to Sieve')).toContainText('6.03 h');
    await expect(metric(page,'Uploaded to Sieve')).not.toContainText('10.73');
    await expect(metric(page,'Originals transfer')).toContainText('100 / 604 files');
    await expect(metric(page,'Originals transfer')).toContainText('excluded from uploaded hours');
    await expect(metric(page,'Originals transfer').getByRole('progressbar')).toHaveAttribute('value','100');
    await expectNoHorizontalOverflow(page);
  });
}

test('contradictory completion and unavailable originals never inflate delivered hours', async ({page}) => {
  const state=await setup(page);state.pipeline.supplement_delivery=originalsTransfer({uploaded_files:603});
  await page.goto('/portal/ops?tab=sieve');
  await expect(metric(page,'Uploaded to Sieve')).toContainText('6.03 h');
  await expect(metric(page,'Uploaded to Sieve')).not.toContainText('10.73');
  state.pipeline.supplement_delivery={available:false};
  await page.getByRole('button',{name:'Refresh dashboard'}).click();
  await expect(metric(page,'Originals transfer')).toContainText('Transfer status unavailable');
  await expect(metric(page,'Originals transfer').getByRole('progressbar')).toHaveCount(0);
  await expect(metric(page,'Uploaded to Sieve')).toContainText('6.03 h');
});
