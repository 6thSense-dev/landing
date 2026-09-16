import { test, expect } from '@playwright/test';
import { expectNoHorizontalOverflow } from './helpers.js';

const group = (label, inherited = 3600) => ({ label, seconds: 3600, inherited_seconds: inherited, recordings: 1 });
async function setup(page) {
  const state = { expired: false, failing: false, requests: [], data: {
    automatic_sync: true, updated_at: new Date().toISOString(), sync: { completed_at: new Date().toISOString() }, bucket: '6thsense-sieve', prefix: 'inherited/v1/',
    totals: { clean_seconds: 7200, inherited_seconds: 3600, recordings: 2, inherited_recordings: 1, copied_bytes: 1e9, countries: 2, entities: 2, cameras: 2, status_counts: { inherited: 1, blocked: 1 } },
    breakdowns: { country: [group('Korea'), group('China',0)], entity: [group('한규태 / 한그라픽스'), group('Hejia',0)], activity: [group('Print Removal'), group('Unclassified',0)], clean_date: [{...group('2026-09-15'), seconds:7200, recordings:2}] },
    recordings: [
      { run_id:'korea', recording:'ego_20260901_120000_ABC123', country:'Korea', entity:{name:'한규태 / 한그라픽스'}, activity:'Print Removal', camera:'ABC123', format:'Split stereo', retained_seconds:3600, status:'inherited' },
      { run_id:'china', recording:'ego_20260825_073921_169252_s02', country:'China', entity:{name:'Hejia'}, activity:'Unclassified', camera:'169252', format:'Split stereo', retained_seconds:3600, status:'blocked', reason:'Clean artifact is missing' },
    ],
  }};
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    state.requests.push({ path, method:route.request().method() });
    if (path === '/api/auth/me') return route.fulfill({ json:{id:100,role:'ops',email:'ops@example.test'} });
    if (path === '/api/ops/sieve/availability') return route.fulfill({ json:{visible:!state.expired} });
    if (path === '/api/ops/sieve/state') return route.fulfill({ status:state.expired?410:state.failing?503:200, json:state.data });
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
  await page.getByLabel('Filter recordings by country',{exact:true}).selectOption('China');
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
