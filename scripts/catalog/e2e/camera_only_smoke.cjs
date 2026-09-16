/** Synthetic component smoke test. No API, account, device, or external network.
 * Run: node scripts/catalog/e2e/camera_only_smoke.cjs
 * Optional: CATALOG_SMOKE_SHOTS=/private/output/dir to retain screenshots.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const repo = path.resolve(__dirname, '../../..');
const frontend = path.join(repo, 'frontend');
const resolve = name => require.resolve(name, { paths: [frontend] });
const { chromium } = require(resolve('playwright'));

(async () => {
  const { createServer } = await import(pathToFileURL(path.join(path.dirname(resolve('vite/package.json')), 'dist/node/index.js')));
  const tag = `.camera-smoke-${process.pid}`;
  const html = path.join(frontend, `${tag}.html`);
  const jsx = path.join(frontend, `${tag}.jsx`);
  const { default: react } = await import(pathToFileURL(resolve("@vitejs/plugin-react")));
  let server, browser;
  try {
    await fs.writeFile(html, `<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body><div id="root"></div><script type="module" src="/${tag}.jsx"></script></body></html>`);
    await fs.writeFile(jsx, `
      import React from 'react';
      import { createRoot } from 'react-dom/client';
      import ClipCard from './src/catalog/ClipCard.jsx';
      import QaBlock from './src/catalog/tabs/QaBlock.jsx';
      import './src/styles.css';
      import './src/catalog/catalog.css';
      const checks = ['tactile_crc_pass_rate', 'tactile_channel_coverage', 'tactile_census_reproducible'].map(check_id => ({check_id, category:'tactile', result:'not_applicable', measured:null, threshold:null}));
      const qa = {grade:'A', disposition:'accepted', checks_warn:0, checks_fail:0, checks, usable_channels:{}, tactile_coverage:null, sync_validated:true};
      const clip = {id:'synthetic-camera', name:'Synthetic camera-only clip', description:'Synthetic fixture only', capture:'stereo_egocentric', hands:[], modalities:['video','imu'], country:'CN', duration_s:10, resolution:[1920,600], poster:null, preview:null, qa};
      createRoot(document.getElementById('root')).render(<main className="cat-root cat-page" style={{padding:16}}><section className="cat-grid"><div id="camera"><ClipCard clip={clip} onOpen={()=>{}}/></div><div id="missing"><ClipCard clip={{...clip,id:'synthetic-missing',hands:['left']}} onOpen={()=>{}}/></div><div id="mono"><ClipCard clip={{...clip,id:'synthetic-mono',capture:'mono'}} onOpen={()=>{}}/></div></section><section id="quality" className="cat-d-overlay" style={{position:"relative",inset:"auto",display:"block",padding:0,background:"transparent"}}><div className="cat-d-panel" style={{maxHeight:"none",width:"100%"}}><div className="cat-d-body"><QaBlock qa={qa}/></div></div></section></main>);
    `);
    server = await createServer({ configFile: false, plugins: [react()], root: frontend, server: { host: '127.0.0.1', port: 0 } });
    await server.listen();
    const port = server.httpServer.address().port;
    const origin = `http://127.0.0.1:${port}`;
    browser = await chromium.launch({ headless: true });
    const page = await browser.newPage();
    const errors = [], forbidden = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => {
      const u = new URL(route.request().url());
      if (u.origin !== origin || u.pathname.startsWith('/api/')) {
        forbidden.push(u.origin + u.pathname);
        return route.abort();
      }
      return route.continue();
    });
    for (const width of [360, 1440]) {
      await page.setViewportSize({ width, height: 1100 });
      await page.goto(`${origin}/${tag}.html`);
      await page.locator('#camera .cat-card__mark').waitFor();
      assert.equal(await page.locator('#camera .cat-card__mark').textContent(), 'Stereo · Camera only');
      assert.equal(await page.locator('#camera .cat-card__mark--alert').count(), 0);
      assert.equal(await page.locator('#missing .cat-card__mark--alert').textContent(), 'Census missing');
      assert.equal(await page.locator('#mono .cat-card__mark--alert').textContent(), 'Not stereo');
      assert.match(await page.locator('#quality').innerText(), /3 n\/a/);
      assert.doesNotMatch(await page.locator('#quality').innerText(), /3 not run/);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false, `horizontal overflow at ${width}`);
      if (process.env.CATALOG_SMOKE_SHOTS) {
        await fs.mkdir(process.env.CATALOG_SMOKE_SHOTS, { recursive: true });
        await page.screenshot({ path: path.join(process.env.CATALOG_SMOKE_SHOTS, `camera-only-${width}.png`), fullPage: true });
      }
      console.log(`PASS ${width}px: equal product tone, real missing-census/mono alerts, separate n/a tally, no overflow`);
    }
    assert.deepEqual(errors, [], 'browser runtime errors');
    assert.deepEqual(forbidden, [], 'unexpected external/API request');
  } finally {
    if (browser) await browser.close();
    if (server) await server.close();
    await Promise.all([fs.rm(html, { force: true }), fs.rm(jsx, { force: true })]);
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
