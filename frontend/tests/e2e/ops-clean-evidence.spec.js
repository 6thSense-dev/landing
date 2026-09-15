import { test, expect } from '@playwright/test';
const base = { run_id: 'fixture', device_id: 'ABC123', wearer_id: 1, retained_seconds: 3600, rejected_seconds: 60, source_seconds: 3660, recording_count: 1, rate_krw_hour: 100, estimated_krw: 100, paid: false, recordings: [], warnings: [], review_intervals: [] };
async function open(page, changes) {
 const requests = [];
 const clean = { runs: [{ ...base, ...changes }], cameras: [{ device_id:'ABC123', wearer_id:1 }], wearers:[{id:1,name:'Synthetic contributor',workplace:'Fixture lab',rate_krw_hour:200,is_active:true}] };
 await page.route('**/api/**', async route => {
  const req=route.request(), path=new URL(req.url()).pathname;
  requests.push({method:req.method(),path});
  const body=path==='/api/auth/me' ? {id:1,role:'admin',email:'fixture@example.test'} : path==='/api/ops/state' ? {episodes:[],wearers:[],tasks:[],totals:{},rate_krw:0,last_scan:''} : path==='/api/ops/clean/scan' ? {...clean, imported:0} : clean;
  await route.fulfill({json:body});
 });
 await page.goto('/portal/ops');
 await page.getByRole('button',{name:'Clean',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Clean footage & retained time'})).toBeVisible();
 await page.getByText('Batch details & source recordings (1)', {exact:true}).click();
 return requests;
}
for(const policy of [{ no_hands_threshold_seconds:17 },{mode:'manual',note:'<script>invalid()</script>'}]) {
 test(`actual policy ${JSON.stringify(policy)}`,async({page})=>{
  const requests=await open(page,{policy});
  const card=page.locator('.ops-clean-card');
  await card.getByText('Recorded QC policy',{exact:true}).click();
  await expect(card.locator('pre')).toHaveText(JSON.stringify(policy,null,2));
  await expect(card).not.toContainText('more than 30 seconds');
  await expect(card).toContainText('not verified task-usable time');
  await expect(card).toContainText('collector credit');
  await expect(card).toContainText('not transfer evidence');
  await expect(card).toContainText('₩100 / hour · run rate snapshot');
  await expect(card).toContainText('Current contributor details do not establish historical agreements.');
  await expect(card).toContainText('1h 00m 00s');
  await expect(card).toContainText('0h 01m 00s');
  await expect(card).not.toContainText('approved hour');
  expect(requests.every(r=>r.method==='GET')).toBe(true);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await page.getByRole('button',{name:'Refresh clean footage'}).click();
  await expect(page.getByRole('status')).toContainText('0 new clean collection(s) imported.');
  expect(requests.filter(r=>r.method!=='GET')).toEqual([{method:'POST',path:'/api/ops/clean/scan'}]);
  await expect(card).toContainText('₩100 / hour · run rate snapshot');
 });
}
for(const policy of [undefined,{}]) {
 test(`unknown policy ${JSON.stringify(policy)} and rate`,async({page})=>{
  const requests=await open(page,{policy,rate_krw_hour:null,estimated_krw:null,paid:true});
  const card=page.locator('.ops-clean-card');
  await card.getByText('Recorded QC policy',{exact:true}).click();
  await expect(card).toContainText('Policy unknown: this run did not provide a policy.');
  await expect(card).toContainText('QC estimate: Unknown');
  await expect(card).toContainText('Run rate snapshot missing');
  await expect(card).toContainText('flagged paid');
  await expect(card).not.toContainText('₩0');
  expect(requests.every(r=>r.method==='GET')).toBe(true);
 });
}
