/*
 * Catalog acceptance harness — the end-to-end proof that the four halves of this
 * feature (bundle, API, auth, UI) work TOGETHER against real bytes.
 *
 * Deliberately NOT in frontend/tests/e2e: every spec there runs offline against
 * `vite preview` with `page.route` mocks, and is expected to pass with no backend.
 * This one requires a live Postgres, a seeded guest, a running API pointed at a
 * real bundle, and a dev server. Putting it in `testDir` would make the default
 * `npx playwright test` fail for anyone without that stack up.
 *
 * Run it from docs/catalog/DEPLOY.md §7, or locally:
 *
 *   CATALOG_E2E_SITE=http://127.0.0.1:5199 \
 *   CATALOG_E2E_API=http://127.0.0.1:8099 \
 *   CATALOG_E2E_PW="$(pass catalog/guest)" \
 *   node scripts/catalog/e2e/catalog_e2e.cjs
 *
 * CATALOG_E2E_PW is required and has no default: the guest password is a live
 * shared credential and must not exist as a literal anywhere in this repo.
 *
 * Exit 0 = every assertion held. Screenshots land in docs/catalog/screenshots/.
 */
const path = require("path");
const fs = require("fs");

// playwright is a devDependency of frontend/, so resolve it from there rather
// than requiring this file to be run with that as the cwd.
const REPO = path.resolve(__dirname, "..", "..", "..");
const { chromium } = require(require.resolve("playwright", {
  paths: [path.join(REPO, "frontend", "node_modules"), REPO],
}));

const SITE = process.env.CATALOG_E2E_SITE || "http://127.0.0.1:5199";
const API  = process.env.CATALOG_E2E_API  || "http://127.0.0.1:8099";
const SHOTS = process.env.CATALOG_E2E_SHOTS || path.join(REPO, "docs", "catalog", "screenshots");
const GUEST_ID = process.env.CATALOG_E2E_ID || "guest";
// No default. A shared production credential must never be a literal in a
// public repo, and a fallback silently re-asserts a rotated value.
const GUEST_PW = process.env.CATALOG_E2E_PW;
if (!GUEST_PW) {
  console.error(
    "CATALOG_E2E_PW is not set. Export the guest password (password manager: " +
    "'catalog guest') before running this harness; there is deliberately no default."
  );
  process.exit(2);
}
fs.mkdirSync(SHOTS, { recursive: true });
const VIEWPORTS = [
  { name: "360",  width: 360,  height: 780 },
  { name: "768",  width: 768,  height: 1024 },
  { name: "1440", width: 1440, height: 900 },
];

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail === undefined ? "" : String(detail) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? "  :: " + detail : ""}`);
}

/*
 * Two classes of "error" are the design working, not a defect, and are counted
 * separately rather than ignored silently:
 *
 *  - 401 GET /api/auth/me before login. useSession probes for an existing cookie
 *    on mount; logged out, the honest answer is 401. Chrome logs every >=400 as a
 *    console error, so a clean app still prints two. Pre-existing on origin/main.
 *  - net::ERR_ABORTED on a media URL. Switching tabs unmounts <video>, which
 *    cancels its in-flight range request. Nothing failed; the fetch was withdrawn.
 */
function isSessionProbe(url, status) {
  return status === 401 && /\/api\/auth\/me$/.test(url);
}
/*
 * Screenshots are evidence, so they must show a settled frame. Waiting a fixed
 * number of ms does not guarantee one: in a cold context under load a capture
 * can land after layout but before the text of a just-scrolled element is
 * composited, which reads in the PNG as a button with no label. Wait for fonts,
 * for any scroll-into-view to finish, and for two clean animation frames.
 */
async function settle(page) {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((r) => setTimeout(r, 250));
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  });
}
async function shoot(page, path) {
  await settle(page);
  await page.screenshot({ path });
}

function attachWatchers(page, bag) {
  bag.expected = bag.expected || [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text().slice(0, 300);
    // Chrome's generic "Failed to load resource: ... 401" has no URL in the text;
    // it is paired with the response listener below, which does the real triage.
    if (/status of 401/.test(t)) bag.expected.push(t);
    else bag.console.push(t);
  });
  page.on("pageerror", (e) => bag.console.push("pageerror: " + String(e).slice(0, 300)));
  page.on("requestfailed", (r) => {
    const err = (r.failure() || {}).errorText || "";
    const line = `${r.method()} ${r.url().slice(0,160)} :: ${err}`;
    if (err === "net::ERR_ABORTED" && /\.(mp4|webm|jpg|png)(\?|$)/.test(r.url())) bag.expected.push(line);
    else bag.failed.push(line);
  });
  page.on("response", (r) => {
    if (r.status() < 400) return;
    const line = `${r.status()} ${r.request().method()} ${r.url().slice(0,160)}`;
    if (isSessionProbe(r.url(), r.status())) bag.expected.push(line);
    else bag.bad.push(line);
  });
}

async function login(page) {
  await page.addInitScript((api) => { window.__API__ = api; }, API);
  await page.goto(`${SITE}/login`, { waitUntil: "networkidle" });
  const id = page.locator('input[name="identifier"], input[name="email"], input[type="email"], input[type="text"]').first();
  await id.fill(GUEST_ID);
  await page.locator('input[type="password"]').first().fill(GUEST_PW);
  await Promise.all([
    page.waitForURL(/\/portal\//, { timeout: 30000 }),
    page.locator('button[type="submit"]').first().click(),
  ]);
}

(async () => {
  const browser = await chromium.launch();

  /* ---------- a/b/c/d at 1440 ---------- */
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const bag = { console: [], failed: [], bad: [] };
  attachWatchers(page, bag);

  await login(page);
  check("a. /login accepts the guest credential and lands on /portal/catalog",
        /\/portal\/catalog/.test(page.url()), page.url());

  await page.waitForSelector(".cat-card, [data-clip-id], article", { timeout: 30000 });
  await page.waitForLoadState("networkidle");

  const cardSel = await page.evaluate(() => {
    for (const s of [".cat-card", "[data-clip-id]", "article"]) {
      if (document.querySelectorAll(s).length >= 5) return s;
    }
    return null;
  });
  const nCards = cardSel ? await page.locator(cardSel).count() : 0;
  /* Against the manifest's OWN total, not a number typed here: a hardcoded 29 went
     stale the moment the fixture's cross-hand-rate bug was fixed and the take it had
     been quarantining came back. `> 0` keeps the tautology out -- an empty grid and
     an empty manifest must not agree their way to a pass. */
  const corpus = await page.evaluate(async (api) => {
    const m = await (await fetch(`${api}/api/catalog`, { credentials: "include" })).json();
    return { total: m.collection.totals.clips, listed: m.clips.length };
  }, API);
  check("b1. grid renders every clip the manifest declares",
        corpus.total > 0 && corpus.listed === corpus.total && nCards === corpus.total,
        `${nCards} cards vs totals.clips=${corpus.total} / clips[]=${corpus.listed}`);

  // Posters are loading="lazy", so only the above-the-fold ones exist until the
  // grid is scrolled. Walk the whole page, then assert on every <img> that was
  // actually requested.
  await page.evaluate(async () => {
    const step = Math.round(window.innerHeight * 0.8);
    for (let y = 0; y <= document.body.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 260));
    }
    window.scrollTo(0, 0);
    await new Promise((r) => setTimeout(r, 400));
  });
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => [...document.querySelectorAll("img")].every((i) => i.complete), null, { timeout: 30000 }).catch(() => {});

  // posters actually decoded
  const posters = await page.evaluate(() => {
    const out = { total: 0, loaded: 0, broken: [] };
    for (const img of document.querySelectorAll("img")) {
      out.total++;
      if (img.complete && img.naturalWidth > 0) out.loaded++;
      else out.broken.push(img.currentSrc || img.src || "(no src)");
    }
    return out;
  });
  check("b2. every poster <img> decoded (after scrolling the whole grid)",
        posters.total >= 29 && posters.broken.length === 0,
        `${posters.loaded}/${posters.total} loaded; broken=${JSON.stringify(posters.broken.slice(0,3))}`);
  check("b3. zero unexpected console errors on the grid", bag.console.length === 0,
        JSON.stringify(bag.console.slice(0, 4)) + `  [${bag.expected.length} expected: pre-login /api/auth/me 401]`);
  check("b4. zero failed requests on the grid",
        bag.failed.length === 0 && bag.bad.length === 0,
        `failed=${JSON.stringify(bag.failed.slice(0,3))} http4xx5xx=${JSON.stringify(bag.bad.slice(0,3))}`);

  // ---- unit rendering (the 60x bug) ----
  // The task section renders as BARS above ~2 clips per bar and as a COUNT TABLE
  // below it. Both must express minutes: in bar mode that is the rotated y-axis
  // caption, in table mode it is the value column. Either satisfies the rule; an
  // hours figure anywhere fails it.
  const unitText = await page.evaluate(() => {
    const t = document.body.innerText;
    const grab = (re) => { const m = t.match(re); return m ? m[0] : null; };
    const listVals = [...document.querySelectorAll(".cat-chart-table-num.is-strong")]
      .map((e) => e.textContent.trim());
    return {
      minutesTile: grab(/\d[\d.,]*\s*min\b/),
      hoursTile: grab(/\d[\d.,]*\s*h\b/),
      // The rotated y-axis caption is an <svg><text>; innerText does not see it.
      axis: [...document.querySelectorAll("svg text")].map((t) => t.textContent.trim())
              .filter((t) => /^(Minutes|Hours|Clips)$/.test(t)),
      chartTicks: [...document.querySelectorAll("svg text")].map((t) => t.textContent.trim())
              .filter((t) => /\d/.test(t)).slice(0, 4),
      listMode: listVals.length > 0,
      listVals: listVals.slice(0, 3),
      listInMinutes: listVals.length > 0 && listVals.every((v) => /\bmin\b/.test(v)),
      wrappedLabel: [...document.querySelectorAll(".cat-stat, [class*=stat]")]
              .some((e) => /Usable tactile/i.test(e.textContent || "")),
      // "By category | By task" is only rendered when the manifest publishes a
      // categories[] roll-up that is strictly coarser than tasks[].
      views: [...document.querySelectorAll(".cat-chart-seg [role=radio]")]
              .map((b) => b.textContent.trim()),
    };
  });
  check("b5. header + task section honour duration_unit=minutes (no 60x error)",
        !!unitText.minutesTile && !unitText.hoursTile &&
        (unitText.listMode ? unitText.listInMinutes : unitText.axis.includes("Minutes")),
        JSON.stringify(unitText));
  /* b5b was "the section is always a count list". It is now the real rule, which is
     STRICTER: the form follows the clips-per-bar of whichever roll-up is showing.
     `benchmark.categories[]` (10 bars x 3 clips) earns the bars and is the default;
     `benchmark.tasks[]` (25 bars x ~1 clip) does not and must fall back to the
     table. Both halves are asserted by driving the control, so a regression that
     drew 25 picket-fence bars would fail here exactly as it did before. */
  {
    const hasSeg = unitText.views.length === 2;
    const byTask = page.locator('.cat-chart-seg [role="radio"]', { hasText: /by task/i }).first();
    const readForm = () => page.evaluate(() => ({
      bars: document.querySelectorAll(".cat-chart-plotwrap svg rect, .cat-chart-plotwrap svg path").length,
      rows: document.querySelectorAll(".cat-chart-table tbody tr").length,
      axis: [...document.querySelectorAll("svg text")].map((t) => t.textContent.trim())
              .filter((t) => /^(Minutes|Hours|Clips)$/.test(t)).length,
    }));
    const asCategory = await readForm();
    let asTask = null;
    if (hasSeg) {
      await byTask.click();
      await page.waitForTimeout(900);
      asTask = await readForm();
      await page.locator('.cat-chart-seg [role="radio"]', { hasText: /by category/i }).first().click();
      await page.waitForTimeout(900);
    }
    check("b5b. each roll-up is drawn as what its clips-per-bar can support",
          hasSeg
            ? asCategory.bars > 0 && asCategory.axis > 0 && asCategory.rows === 0 &&
              asTask.rows > 0 && asTask.bars === 0
            : unitText.listMode && !unitText.axis.includes("Minutes"),
          JSON.stringify({ views: unitText.views, category: asCategory, task: asTask }));
  }

  // The stat row must sit on one baseline: a label that wraps to two lines drops
  // its value below every neighbour, which reads as a broken tile.
  const baseline = await page.evaluate(() => {
    const vals = [...document.querySelectorAll(".cat-stat")].map((s) => {
      const v = s.querySelector("b, strong, .cat-stat-value, :scope > *:last-child");
      return v ? { label: (s.querySelector("span,dt,.cat-stat-label") || {}).textContent, top: Math.round(v.getBoundingClientRect().top) } : null;
    }).filter(Boolean);
    const tops = [...new Set(vals.map((v) => v.top))];
    return { n: vals.length, tops, vals };
  });
  check("b6. stat-tile values share one baseline",
        baseline.n === 0 || baseline.tops.length === 1,
        JSON.stringify(baseline.tops) + " from " + baseline.n + " tiles");

  /* ---------- h. the presign clock comes from the response, not a build constant ---------- */
  const presign = await page.evaluate(async (api) => {
    const r = await fetch(`${api}/api/catalog`, { credentials: "include" });
    const m = await r.json();
    return { expires_at: m.expires_at ?? null, url_form: m.url_form ?? null };
  }, API);
  check("h1. the API declares a top-level expires_at (the field the UI reads)",
        typeof presign.expires_at === "string" && Number.isFinite(Date.parse(presign.expires_at)),
        JSON.stringify(presign));

  await shoot(page, `${SHOTS}/grid-1440.png`);

  /* ---------- c/d: modal ---------- */
  const bagM = { console: [], failed: [], bad: [] };
  attachWatchers(page, bagM);
  await page.locator(cardSel).first().click();
  const dialog = page.locator('[role="dialog"]').first();
  await dialog.waitFor({ state: "visible", timeout: 20000 });
  check("c1. clicking a card opens the detail modal", true, "role=dialog visible");

  const tabs = page.locator('[role="tab"]');
  const nTabs = await tabs.count();
  const tabNames = [];
  for (let i = 0; i < nTabs; i++) tabNames.push((await tabs.nth(i).innerText()).trim());
  check("c2. six tabs present", nTabs === 6, tabNames.join(" | "));
  check("c2b. the Calibration & sync tab exists (H3 + H7 are rendered, not only in the JSON)",
        tabNames.some((t) => /calib/i.test(t)), tabNames.join(" | "));

  const tabReport = [];
  for (let i = 0; i < nTabs; i++) {
    await tabs.nth(i).click();
    await page.waitForTimeout(1400);
    const panel = page.locator('[role="tabpanel"]').first();
    const txt = (await panel.innerText().catch(() => "")).trim();
    const html = await panel.innerHTML().catch(() => "");
    const media = await panel.evaluate((el) => ({
      imgs: el.querySelectorAll("img").length,
      okImgs: [...el.querySelectorAll("img")].filter((i) => i.complete && i.naturalWidth > 0).length,
      svg: el.querySelectorAll("svg").length,
      canvas: el.querySelectorAll("canvas").length,
      video: el.querySelectorAll("video").length,
      rows: el.querySelectorAll("tr, dt, li").length,
    })).catch(() => ({}));
    const empty = /couldn.t|unavailable|failed|error|not available/i.test(txt) && txt.length < 220;
    tabReport.push({ tab: tabNames[i], chars: txt.length, ...media, empty });
    check(`c3.${i + 1} tab "${tabNames[i]}" renders real content`,
          !empty && (txt.length > 60 || media.video > 0 || media.svg > 0 || media.canvas > 0 || media.okImgs > 0),
          JSON.stringify({ chars: txt.length, ...media }));
  }

  /* c3b. THE FOCUS TRAP HOLDS ON THE DEFAULT TAB.
   *
   * The tab strip uses a roving tabindex, so the five unselected tabs are
   * tabIndex=-1 buttons that still match `button:not([disabled])`. When the trap
   * took first/last off that unfiltered list, `last` was the Metadata button --
   * a node Tab can never reach -- so `active === last` never held and Tab walked
   * straight out of an aria-modal dialog into the grid behind it. It hit the
   * DEFAULT tab of every clip, because on Video the modal body is not rendered
   * and the tab strip IS the end of the DOM.
   *
   * Tabbed from the selected tab button, not from the top of the dialog, because
   * that is the exact position the bug fired from.
   */
  {
    const vIdx = tabNames.findIndex((t) => /video/i.test(t));
    await tabs.nth(vIdx >= 0 ? vIdx : 0).click();
    await page.waitForTimeout(600);
    await page.locator('[role="tab"][aria-selected="true"]').first().focus();
    const walk = [];
    for (let i = 0; i < 12; i++) {
      await page.keyboard.press("Tab");
      walk.push(await page.evaluate(() => {
        const a = document.activeElement;
        if (!a || a === document.body) return { out: true, what: "body" };
        return {
          out: !(a.closest && a.closest('[role="dialog"]')),
          what: (a.getAttribute("aria-label") || a.textContent || a.tagName).trim().slice(0, 22),
        };
      }));
    }
    const escaped = walk.filter((w) => w.out);
    check("c3b. Tab cannot leave the dialog from the default (Video) tab",
          escaped.length === 0,
          escaped.length ? `escaped to: ${JSON.stringify(escaped)}` :
            `12 stops, all inside: ${walk.map((w) => w.what).join(" > ").slice(0, 160)}`);
    // and backwards, from the first stop
    await page.keyboard.press("Shift+Tab");
    const back = await page.evaluate(() =>
      !!(document.activeElement && document.activeElement.closest &&
         document.activeElement.closest('[role="dialog"]')));
    check("c3c. Shift+Tab cannot leave the dialog either", back, String(back));
  }

  // d. the video really loads
  const videoTabIdx = tabNames.findIndex((t) => /video/i.test(t));
  await tabs.nth(videoTabIdx >= 0 ? videoTabIdx : 0).click();
  await page.waitForTimeout(500);
  const vid = page.locator("video").first();
  await vid.waitFor({ state: "attached", timeout: 15000 });
  const vstate = await vid.evaluate(async (v) => {
    v.muted = true;
    try { await v.play(); } catch (e) { /* autoplay may be blocked; readyState is the assertion */ }
    const t0 = Date.now();
    while (v.readyState < 2 && Date.now() - t0 < 25000) await new Promise((r) => setTimeout(r, 200));
    await new Promise((r) => setTimeout(r, 900));
    return { readyState: v.readyState, w: v.videoWidth, h: v.videoHeight, dur: v.duration,
             ct: v.currentTime, paused: v.paused, err: v.error ? v.error.code : null,
             src: (v.currentSrc || "").slice(0, 130) };
  });
  check("d. video element loads (readyState >= 2)", vstate.readyState >= 2, JSON.stringify(vstate));
  check("d2. video actually advances (it plays)", vstate.ct > 0 || vstate.readyState >= 3, JSON.stringify({ct: vstate.ct, rs: vstate.readyState}));

  check("c4. zero unexpected console errors across every tab", bagM.console.length === 0, JSON.stringify(bagM.console.slice(0, 4)));
  check("c5. zero unexpected failed requests across every tab",
        bagM.failed.length === 0 && bagM.bad.length === 0,
        `failed=${JSON.stringify(bagM.failed.slice(0,3))} http=${JSON.stringify(bagM.bad.slice(0,3))}` +
        `  [${bagM.expected.length} expected: <video> teardown aborts]`);

  fs.writeFileSync(path.join(SHOTS, "..", "e2e-tabreport.json"), JSON.stringify(tabReport, null, 1));

  /* ---------- hover contrast on every control ----------
   * A `:hover` rule that scores higher than the `.is-on` rule repaints the
   * SELECTED control's label in the same colour as the pill it sits on. The
   * pointer is always resting on the thing you just clicked, so the label of the
   * active tab disappears in normal use. Hover each control for real and compare
   * the painted foreground against the painted background.
   */
  async function hoverContrast(pg, scope) {
    const els = pg.locator(`${scope} button, ${scope} [role="tab"], ${scope} [role="radio"], ${scope} a`);
    const n = Math.min(await els.count(), 40);
    const bad = [];
    for (let i = 0; i < n; i++) {
      const el = els.nth(i);
      if (!(await el.isVisible().catch(() => false))) continue;
      await el.hover({ trial: false, timeout: 3000 }).catch(() => {});
      await pg.waitForTimeout(60);
      const r = await el.evaluate((e) => {
        const cs = getComputedStyle(e);
        const opaque = (x) => x && x !== "rgba(0, 0, 0, 0)" && x !== "transparent";
        let bg = cs.backgroundColor;
        for (let a = e; a && !opaque(bg); a = a.parentElement) bg = getComputedStyle(a).backgroundColor;
        const fg = cs.webkitTextFillColor && cs.webkitTextFillColor !== "rgb(0, 0, 0)" ? cs.webkitTextFillColor : cs.color;
        return { txt: (e.textContent || "").trim().slice(0, 24), fg, bg, same: fg === bg };
      }).catch(() => null);
      if (r && r.same && r.txt) bad.push(r);
    }
    return bad;
  }
  /* An SVG that is deliberately wider than its scroll container must not be
   * clamped by the zero-specificity media reset in catalog.css. When it is, the
   * strip silently stops scrolling AND -- because these SVGs carry a matching
   * viewBox -- the coordinate space is scaled down to fit, so the signal shrinks
   * into a corner of a plot whose axis still claims the full range.
   */
  const imuIdx = tabNames.findIndex((t) => /imu/i.test(t));
  if (imuIdx >= 0) { await tabs.nth(imuIdx).click(); await page.waitForTimeout(2500); }
  const clamped = await page.evaluate(() => {
    const out = [];
    for (const svg of document.querySelectorAll("svg[width]")) {
      // Icons declare a nominal width and are then sized by CSS on purpose; that
      // is not the failure this looks for. Only plot canvases matter here.
      if (/lucide|icon/i.test(svg.getAttribute("class") || "")) continue;
      const attr = Number(svg.getAttribute("width"));
      if (!Number.isFinite(attr) || attr <= 64) continue;
      const w = svg.getBoundingClientRect().width;
      if (w > 0 && attr - w > 1.5) {
        out.push({ cls: (svg.getAttribute("class") || "").slice(0, 40),
                   attrW: Math.round(attr), renderedW: Math.round(w),
                   maxWidth: getComputedStyle(svg).maxWidth });
      }
    }
    return out;
  });
  check("c7. no chart SVG is scaled away from its declared width",
        clamped.length === 0, JSON.stringify(clamped));

  const scrollers = await page.evaluate(() => {
    const out = [];
    for (const sel of [".cat-imu-scroll", ".cat-chart-plotwrap"]) {
      for (const el of document.querySelectorAll(sel)) {
        const kid = el.querySelector("svg[width]");
        if (!kid) continue;
        out.push({ sel, attrW: Math.round(Number(kid.getAttribute("width"))),
                   scrollW: el.scrollWidth, clientW: el.clientWidth,
                   scrolls: el.scrollWidth > el.clientWidth + 4 });
      }
    }
    return out;
  });
  check("c8. a strip wider than its viewport can actually be scrolled",
        scrollers.length > 0 && scrollers.every((s) => s.attrW <= s.clientW + 4 || s.scrolls),
        JSON.stringify(scrollers));

  if (videoTabIdx >= 0) { await tabs.nth(videoTabIdx).click(); await page.waitForTimeout(800); }

  const modalContrast = await hoverContrast(page, '[role="dialog"]');
  check("c6. no control's label matches its own background while hovered",
        modalContrast.length === 0, JSON.stringify(modalContrast.slice(0, 4)));

  /* ---------- c9. the calibration + sync values are actually on screen ---------- */
  const calIdx = tabNames.findIndex((t) => /calib/i.test(t));
  if (calIdx >= 0) {
    await tabs.nth(calIdx).click();
    await page.waitForTimeout(1200);
    const cal = await page.evaluate(() => {
      const t = document.querySelector('[role="dialog"]').innerText;
      return {
        model: /kannala|pinhole|radtan|equidistant|double sphere/i.test(t),
        intrinsics: /\bfx\b/i.test(t) && /\bcx\b/i.test(t),
        baseline: /baseline/i.test(t),
        readout: /readout/i.test(t),
        convention: /offset_ns\s*=|t_imu\s*=/i.test(t),
        streams: /tactile_left|tactile_right/i.test(t),
        noise: /noise density/i.test(t),
      };
    });
    check("c9. Calibration & sync renders the camera model, intrinsics, baseline and readout time",
          cal.model && cal.intrinsics && cal.baseline && cal.readout, JSON.stringify(cal));
    check("c10. it renders the per-stream sync table and the offset sign convention verbatim",
          cal.streams && cal.convention && cal.noise, JSON.stringify(cal));
  } else {
    check("c9. Calibration & sync renders the camera model, intrinsics, baseline and readout time",
          false, "no calibration tab found");
  }

  /* ---------- c11. the H4 check table and the documentation links ---------- */
  const metaIdx = tabNames.findIndex((t) => /metadata/i.test(t));
  if (metaIdx >= 0) {
    await tabs.nth(metaIdx).click();
    await page.waitForTimeout(1200);
    const meta = await page.evaluate(() => {
      const d = document.querySelector('[role="dialog"]');
      const t = d.innerText;
      const links = [...d.querySelectorAll("a[href]")].map((a) => a.textContent.trim());
      return {
        disposition: /accepted/i.test(t),
        checkIds: /sync_max_skew_ms/i.test(t),
        thresholds: /threshold/i.test(t),
        results: d.querySelectorAll(".cat-qa-result").length,
        datasheet: links.some((l) => /DATASHEET/i.test(l)),
        checksums: links.some((l) => /checksums/i.test(l)),
        redactionRecord: /redaction record/i.test(t),
      };
    });
    check("c11. Metadata renders the H4 check table (check_id, result, measured, threshold)",
          meta.checkIds && meta.thresholds && meta.results > 5 && meta.disposition,
          JSON.stringify(meta));
    check("c12. Metadata links the per-clip documentation a guest is allowed to read",
          meta.datasheet && meta.checksums, JSON.stringify(meta));
    check("c13. Metadata states the H6 redaction record's outcome AND its provenance",
          meta.redactionRecord, JSON.stringify(meta));
  }

  /* 12 of the 29 clips genuinely ship no redaction record, and the tab now says so
     in words rather than drawing an em-dash. Assert the FULL record on a clip that
     has one — the four fields (targets, reviewer, reviewed, items) the renderer
     used to throw away are the ones counsel asks for first. */
  const withRecord = await page.evaluate(async (api) => {
    const m = await (await fetch(`${api}/api/catalog`, { credentials: "include" })).json();
    for (const c of m.clips) {
      const doc = await (await fetch(c.detail, { credentials: "include" })).json();
      if (doc.privacy && doc.privacy.redaction) return doc.id;
    }
    return null;
  }, API);
  if (withRecord) {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    await page.goto(`${SITE}/portal/catalog?clip=${withRecord}#tab=metadata`, { waitUntil: "networkidle" });
    await page.locator('[role="dialog"]').first().waitFor({ state: "visible", timeout: 20000 });
    await page.waitForTimeout(1500);
    const rec = await page.evaluate(() => {
      const d = document.querySelector('[role="dialog"]');
      const t = d.innerText.toLowerCase();
      return {
        targets: /targets searched for/.test(t),
        chips: d.querySelectorAll(".cat-m-chips li").length,
        reviewer: /reviewer/.test(t),
        reviewed: /reviewed/.test(t),
        items: /items redacted/.test(t),
        policy: /policy version/.test(t),
      };
    });
    check("c14. the full H6 review record renders: targets, reviewer, reviewed, items, policy",
          rec.targets && rec.chips > 0 && rec.reviewer && rec.reviewed && rec.items && rec.policy,
          JSON.stringify(rec));
  } else {
    check("c14. the full H6 review record renders: targets, reviewer, reviewed, items, policy",
          false, "no clip in the bundle carries privacy.redaction");
  }

  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);

  /* ---------- g. the header tells the truth about sync, provenance and access ---------- */
  const header = await page.evaluate(async (api) => {
    const m = await (await fetch(`${api}/api/catalog`, { credentials: "include" })).json();
    const t = document.body.innerText;
    const cta = [...document.querySelectorAll("button, a")]
      .find((e) => /request full access/i.test(e.textContent || ""));
    const ctaHref = cta && cta.tagName === "A" ? cta.getAttribute("href") : null;
    return {
      totals: {
        max: m.collection.totals.sync_max_alignment_error_ms,
        over: m.collection.totals.sync_clips_over_one_frame,
        measured: m.collection.totals.sync_clips_measured,
      },
      provenance: m.collection.provenance_class,
      // The producer's own notice must survive verbatim for a preview account.
      notice: m.collection.notice,
      accessNotice: m.access ? m.access.notice : null,
      howToRequest: m.access ? m.access.how_to_request : null,
      // ...and be visible, not merely present in the JSON.
      noticeOnScreen: m.collection.notice ? t.includes(m.collection.notice.slice(0, 60)) : false,
      howOnScreen: m.access && m.access.how_to_request
        ? t.includes(m.access.how_to_request.slice(0, 40)) : false,
      syncTileOnScreen: /max sync error/i.test(t),
      syncValueOnScreen: /\d+\.\d+\s*ms/i.test(t),
      overFrameOnScreen: /over one frame/i.test(t),
      syntheticBanner: /synthetic/i.test(t),
      claimsOneFrame: /(within|to)\s+(about\s+)?(one|1)\s+(video\s+)?frame/i.test(t),
      cta: cta ? { tag: cta.tagName, href: ctaHref, disabled: !!cta.disabled } : null,
    };
  }, API);
  fs.writeFileSync(path.join(SHOTS, "..", "e2e-header.json"), JSON.stringify(header, null, 1));

  check("g1. the measured max sync error is a stat tile, with the count over one frame",
        header.syncTileOnScreen && header.syncValueOnScreen && header.overFrameOnScreen &&
        typeof header.totals.max === "number" && header.totals.measured > 0,
        JSON.stringify({ ...header.totals, tile: header.syncTileOnScreen }));
  check("g2. no copy on the page claims frame-level sync while clips exceed one frame",
        !(header.claimsOneFrame && header.totals.over > 0),
        `claim=${header.claimsOneFrame} over=${header.totals.over}/${header.totals.measured}`);
  check("g3. a synthetic corpus says so above the grid",
        header.provenance === "recorded" || header.syntheticBanner,
        `provenance_class=${header.provenance} banner=${header.syntheticBanner}`);
  check("g4. the producer's own collection notice survives redaction verbatim and is on screen",
        !!header.notice && header.noticeOnScreen && !!header.accessNotice,
        JSON.stringify({ notice: (header.notice || "").slice(0, 60), onScreen: header.noticeOnScreen,
                         access: (header.accessNotice || "").slice(0, 40) }));
  check("g5. the Request-full-access CTA has a real destination",
        !!header.cta && (header.cta.tag === "A" ? /^mailto:/.test(header.cta.href || "") : true),
        JSON.stringify(header.cta));
  check("g6. access.how_to_request is rendered, not just computed",
        !!header.howToRequest && header.howOnScreen,
        JSON.stringify({ copy: (header.howToRequest || "").slice(0, 50), onScreen: header.howOnScreen }));

  /* ---------- e. withheld assets ---------- */
  const clipId = await page.evaluate(() => {
    const el = document.querySelector("[data-clip-id]");
    return el ? el.getAttribute("data-clip-id") : null;
  });
  const withheld = await page.evaluate(async (api) => {
    const r = await fetch(`${api}/api/catalog`, { credentials: "include" });
    const m = await r.json();
    const first = m.clips[0].detail;
    const cr = await fetch(first, { credentials: "include" });
    const c = await cr.json();
    return {
      status: cr.status,
      id: c.id,
      tactile_left: c.media?.tactile?.left ?? "MISSING_KEY",
      tactile_right: c.media?.tactile?.right ?? "MISSING_KEY",
      archive: c.media?.archive ?? "MISSING_KEY",
      imu_csv: c.media?.imu?.csv ?? "MISSING_KEY",
      imu_f32: c.media?.imu?.f32 ?? "MISSING_KEY",
      segcap_json: c.media?.segcap?.json ?? "MISSING_KEY",
      frame_times: c.media?.video?.frame_times ?? "MISSING_KEY",
      video_sbs: c.media?.video?.stereo_sbs ?? "MISSING_KEY",
      pkg_urls: (c.package_contents || []).map((p) => p.url),
      redaction: c.privacy?.redaction ?? null,
      access: c.access,
      known_limitations: c.known_limitations,
    };
  }, API);
  fs.writeFileSync(path.join(SHOTS, "..", "e2e-withheld.json"), JSON.stringify(withheld, null, 1));
  const nulled = ["tactile_left","tactile_right","archive","imu_csv","imu_f32","segcap_json","frame_times"]
    .filter((k) => withheld[k] !== null && withheld[k] !== "MISSING_KEY");
  /* H6 is a RIGHTS artefact, not payload: a guest must be able to read what was
     searched for, under which policy, by whom and when. The record_url pointer is
     no longer withheld either — this bundle happens to carry no record file, so
     the URL assertion lives in backend/tests/test_catalog_api.py against a fixture
     that does; here we assert the review record itself survives redaction. */
  check("e0. the H6 redaction review record survives redaction for a guest",
        withheld.redaction === null || (withheld.redaction &&
          Array.isArray(withheld.redaction.targets) &&
          typeof withheld.redaction.reviewer === "string"),
        JSON.stringify(withheld.redaction));
  check("e1. every withheld asset is null in the guest's clip JSON",
        nulled.length === 0, nulled.length ? `still present: ${JSON.stringify(nulled.map(k=>[k,withheld[k]]))}` : "npz, archive, imu csv+f32, segcap, frame_times all null");
  check("e2. the encoded mp4 IS present (requirement #3)",
        typeof withheld.video_sbs === "string" && withheld.video_sbs.startsWith("http"),
        String(withheld.video_sbs).slice(0, 110));
  check("e3. package_contents carry no download URLs",
        withheld.pkg_urls.length > 0 && withheld.pkg_urls.every((u) => u === null),
        `${withheld.pkg_urls.length} entries, all null: ${withheld.pkg_urls.every((u)=>u===null)}`);

  /* e6. THE OPEN EVALUATION CLIP IS ACTUALLY VERIFIABLE.
   *
   * Withholding frame_times.csv, the tactile arrays and the geometry sidecar from
   * every clip made every figure on the page vendor-asserted, on a corpus the page
   * also says is synthetic -- a brochure. One clip, named by the manifest and
   * re-checked against its own rights, ships the four files that let a buyer
   * recompute the headline claim in their own loader. Everything else stays shut,
   * on that clip and on all the others (e1 above asserts the others).
   */
  const openEval = await page.evaluate(async (api) => {
    const m = await (await fetch(`${api}/api/catalog`, { credentials: "include" })).json();
    const sa = m.collection.sample_archive;
    if (!sa || !sa.clip_id) return { skipped: "no sample_archive in the manifest" };
    const c = await (await fetch(`${api}/api/catalog/clips/${sa.clip_id}`,
                                 { credentials: "include" })).json();
    const head = async (u) => {
      if (!u) return null;
      try { return (await fetch(u, { credentials: "include" })).status; } catch { return "neterr"; }
    };
    return {
      id: sa.clip_id,
      rights: c.rights,
      archiveUrl: !!sa.url,
      served: {
        frame_times: c.media?.video?.frame_times || null,
        tactile_left: c.media?.tactile?.left || null,
        tactile_layout: c.media?.tactile?.layout || null,
        archive: c.media?.archive?.url || null,
      },
      /* `??` collapses null and undefined, and null is exactly the state under
         test, so these carry the raw value: a withheld pointer is null, and a key
         the record never had is undefined. Both count as withheld; a STRING does
         not, and that is the only thing that must fail here. */
      stillWithheld: {
        tactile_right: c.media?.tactile?.right,
        imu_csv: c.media?.imu?.csv,
        imu_f32: c.media?.imu?.f32,
        segcap: c.media?.segcap?.json,
        calibration: c.media?.calibration?.raw,
        pkg: (c.package_contents || []).map((p) => p.url),
      },
      status: {
        frame_times: await head(c.media?.video?.frame_times),
        tactile_left: await head(c.media?.tactile?.left),
        archive: await head(c.media?.archive?.url),
      },
      notice: (c.known_limitations || [])[0] || "",
    };
  }, API);
  fs.writeFileSync(path.join(SHOTS, "..", "e2e-openclip.json"), JSON.stringify(openEval, null, 1));

  const oe = openEval;
  const granted = oe.rights && ["model_training", "commercial_use", "redistribution", "derived_model"]
    .every((k) => oe.rights[k] === "granted");
  check("e6. the open evaluation clip's rights are granted end to end",
        !!granted, JSON.stringify(oe.rights));
  check("e7. a guest can download the open clip's package, timestamps, one hand and its geometry",
        oe.archiveUrl && Object.values(oe.served).every(Boolean) &&
          Object.values(oe.status).every((s) => s === 200),
        JSON.stringify({ archiveUrl: oe.archiveUrl, status: oe.status }));
  const shutKeys = ["tactile_right", "imu_csv", "imu_f32", "segcap", "calibration"];
  const leaked = shutKeys.filter((k) => typeof oe.stillWithheld[k] === "string");
  check("e8. the open clip still withholds everything the exemption does not name",
        leaked.length === 0 &&
          oe.stillWithheld.pkg.length > 0 && oe.stillWithheld.pkg.every((u) => u === null),
        leaked.length
          ? `leaked: ${JSON.stringify(leaked)}`
          : `${shutKeys.join(", ")} all null; ${oe.stillWithheld.pkg.length} package URLs null`);
  check("e9. the open clip says so in its own record",
        /open evaluation clip/i.test(oe.notice), oe.notice.slice(0, 90));

  // direct fetch of a withheld byte path must not serve it
  const direct = await page.evaluate(async (api) => {
    const id = "ego-20251130-000121-16a260";
    const probes = [
      `${api}/api/catalog/local/media/${id}/tactile/left.npz`,
      `${api}/api/catalog/local/archives/${id}.tar.zst`,
      `${api}/api/catalog/local/media/${id}/imu/imu.csv`,
      `${api}/api/catalog/local/clips/${id}.json`,
      `${api}/api/catalog/local/../catalog.json`,
    ];
    const out = [];
    for (const u of probes) {
      try { const r = await fetch(u, { credentials: "include" }); out.push([u.replace(api, ""), r.status]); }
      catch (e) { out.push([u.replace(api, ""), "neterr"]); }
    }
    return out;
  }, API);
  fs.writeFileSync(path.join(SHOTS, "..", "e2e-direct.json"), JSON.stringify(direct, null, 1));
  check("e4. unsigned direct GETs of withheld bytes are refused",
        direct.every(([, s]) => s === 403 || s === 404), JSON.stringify(direct));

  /* The capability IS the signature. Strip it and the same URL must stop working —
   * in local mode that is the HMAC, in S3 mode the presigned query. This is the
   * production question ("can a guest who learns a key just fetch it?") and it is
   * asked identically of both drivers.
   */
  const unsigned = await page.evaluate(async () => {
    const r = await fetch("/__none__").catch(() => null); void r;
    const m = await (await fetch(`${window.__API__}/api/catalog`, { credentials: "include" })).json();
    const c = await (await fetch(m.clips[0].detail, { credentials: "include" })).json();
    const urls = [c.poster, c.media?.video?.stereo_sbs || c.media?.video?.mono].filter(Boolean);
    const out = [];
    for (const u of urls) {
      const bare = u.split("?")[0];
      const sr = await fetch(u, { credentials: "omit", method: "GET" }).then((x) => x.status).catch(() => "neterr");
      const br = await fetch(bare, { credentials: "omit", method: "GET" }).then((x) => x.status).catch(() => "neterr");
      out.push({ url: bare.slice(-52), signed: sr, unsigned: br });
    }
    return out;
  });
  check("e5. stripping the signature stops the bytes (both drivers)",
        unsigned.length > 0 && unsigned.every((u) => u.signed === 200 && [401, 403, 404].includes(u.unsigned)),
        JSON.stringify(unsigned));

  await page.locator(cardSel).first().click();
  await page.locator('[role="dialog"]').first().waitFor({ state: "visible", timeout: 20000 });
  await page.waitForTimeout(1000);
  await shoot(page, `${SHOTS}/modal-1440.png`);

  /* ---------- f. logout ---------- */
  const bagL = { console: [], failed: [], bad: [] };
  attachWatchers(page, bagL);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
  let loggedOut = false;
  const logout = page.locator('button:has-text("Log out"), button:has-text("Sign out"), a:has-text("Log out"), a:has-text("Sign out")').first();
  if (await logout.count()) {
    await logout.click();
    await page.waitForURL(/\/login/, { timeout: 20000 }).catch(() => {});
    loggedOut = true;
  } else {
    await page.evaluate((api) => fetch(`${api}/api/auth/logout`, { method: "POST", credentials: "include" }), API);
    loggedOut = true;
  }
  await page.goto(`${SITE}/portal/catalog`, { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  check("f. after logout /portal/catalog redirects to /login",
        /\/login/.test(page.url()), `${loggedOut ? "" : "(no logout control found) "}${page.url()}`);

  await ctx.close();

  /* ---------- h2. the refresh clock really follows the response ----------
   *
   * The UI half of h1, asserted by BEHAVIOUR rather than by reading a private
   * field: the manifest response is intercepted and its `expires_at` rewritten to
   * 95 seconds out. If the UI reads that field, staleAt lands ~20 s from now (the
   * refresh margin is 90 s, floored at a 20 s minimum) and a second GET
   * /api/catalog happens inside the window below. If it ignores `expires_at` and
   * falls back to the build-time VITE_CATALOG_PRESIGN_TTL (900 s), staleAt is 810 s
   * out and nothing refetches — which is exactly the silent config drift this
   * assertion exists to catch, and which no amount of server-side testing sees.
   */
  {
    const hctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const hpage = await hctx.newPage();
    let manifestHits = 0;
    let rewritten = 0;
    await hpage.route(`${API}/api/catalog`, async (route) => {
      manifestHits += 1;
      const res = await route.fetch();
      let body = await res.text();
      try {
        const doc = JSON.parse(body);
        doc.expires_at = new Date(Date.now() + 95_000).toISOString().replace(/\.\d+Z$/, "Z");
        body = JSON.stringify(doc);
        rewritten += 1;
      } catch {
        /* leave the body alone; the assertion below will fail loudly */
      }
      const headers = { ...res.headers() };
      delete headers["content-length"];
      await route.fulfill({ status: res.status(), headers, body });
    });
    await login(hpage);
    await hpage.waitForSelector(cardSel, { timeout: 30000 });
    await hpage.waitForLoadState("networkidle");
    const before = manifestHits;
    // 20 s to staleAt, plus slack for the fetch and the timer.
    await hpage.waitForTimeout(33_000);
    check("h2. the UI refetches on the SERVER's expires_at, not the build-time TTL",
          rewritten > 0 && manifestHits > before,
          `manifest GETs ${before} -> ${manifestHits} in 33 s after expires_at was ` +
          `rewritten to +95 s (rewritten ${rewritten}). With the 900 s build-time ` +
          `fallback the next refresh would be 810 s out and this count would not move.`);
    await hctx.close();
  }

  /* ---------- responsive screenshots ---------- */
  for (const vp of VIEWPORTS) {
    const c = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 1 });
    const p = await c.newPage();
    const b = { console: [], failed: [], bad: [] };
    attachWatchers(p, b);
    await login(p);
    await p.waitForSelector(cardSel, { timeout: 30000 });
    await p.waitForLoadState("networkidle");
    await p.waitForTimeout(1200);
    await shoot(p, `${SHOTS}/grid-${vp.name}.png`);
    // a second frame further down the page, where the cards actually are
    await p.evaluate(() => {
      const g = document.querySelector(".cat-grid, [class*=grid]");
      if (g) g.scrollIntoView({ block: "start" });
    });
    await p.waitForTimeout(1500);
    await shoot(p, `${SHOTS}/grid-${vp.name}-cards.png`);
    await p.evaluate(() => window.scrollTo(0, 0));
    await p.waitForTimeout(500);

    // overflow audit on the grid
    const grid = await p.evaluate(() => {
      const de = document.documentElement;
      const inScroller = (el) => {
        for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
          if (/auto|scroll/.test(getComputedStyle(a).overflowX)) return true;
        }
        return false;
      };
      const over = [];
      for (const el of document.querySelectorAll("body *")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        const cs = getComputedStyle(el);
        if (cs.position === "fixed") continue;
        if (inScroller(el)) continue;
        if (r.right > de.clientWidth + 1.5 || r.left < -1.5) {
          over.push({ tag: el.tagName.toLowerCase(), cls: (el.className || "").toString().slice(0, 60),
                      left: Math.round(r.left), right: Math.round(r.right) });
        }
      }
      return { hScroll: de.scrollWidth > de.clientWidth + 1, sw: de.scrollWidth, cw: de.clientWidth, over: over.slice(0, 8) };
    });
    check(`resp.grid.${vp.name} no horizontal overflow`, !grid.hScroll, JSON.stringify(grid));

    const gridContrast = await (async () => {
      const els = p.locator("main button, main [role=\"radio\"], main a, header button");
      const n = Math.min(await els.count(), 40);
      const bad = [];
      for (let i = 0; i < n; i++) {
        const el = els.nth(i);
        if (!(await el.isVisible().catch(() => false))) continue;
        await el.hover({ timeout: 3000 }).catch(() => {});
        await p.waitForTimeout(50);
        const r = await el.evaluate((e) => {
          const cs = getComputedStyle(e);
          const opaque = (x) => x && x !== "rgba(0, 0, 0, 0)" && x !== "transparent";
          let bg = cs.backgroundColor;
          for (let a = e; a && !opaque(bg); a = a.parentElement) bg = getComputedStyle(a).backgroundColor;
          return { txt: (e.textContent || "").trim().slice(0, 24), fg: cs.color, bg, same: cs.color === bg };
        }).catch(() => null);
        if (r && r.same && r.txt) bad.push(r);
      }
      return bad;
    })();
    check(`resp.grid.${vp.name} no control's label matches its background while hovered`,
          gridContrast.length === 0, JSON.stringify(gridContrast.slice(0, 4)));
    await p.evaluate(() => window.scrollTo(0, 0));
    await p.waitForTimeout(300);

    await p.locator(cardSel).first().click();
    await p.locator('[role="dialog"]').first().waitFor({ state: "visible", timeout: 20000 });
    await p.waitForTimeout(1600);
    await shoot(p, `${SHOTS}/modal-${vp.name}.png`);

    // Every tab, at every width — the Video tab alone hides the densest layouts.
    const mtabs = p.locator('[role="tab"]');
    const nmt = await mtabs.count();
    for (let i = 0; i < nmt; i++) {
      const nm = (await mtabs.nth(i).innerText()).trim().toLowerCase().replace(/[^a-z0-9]+/g, "");
      await mtabs.nth(i).click();   // leaves the pointer resting on the tab, like a real one
      await p.waitForTimeout(1500);
      await shoot(p, `${SHOTS}/modal-${vp.name}-${nm}.png`);
      const t = await p.evaluate(() => {
        const d = document.querySelector('[role="dialog"]');
        const de = document.documentElement;
        const dr = d.getBoundingClientRect();
        return { fitsX: dr.left >= -1 && dr.right <= de.clientWidth + 1,
                 fitsY: dr.top >= -1 && dr.bottom <= de.clientHeight + 1,
                 h: Math.round(dr.height), vh: de.clientHeight,
                 panelScrolls: [...d.querySelectorAll("*")].some((e) => e.scrollHeight > e.clientHeight + 4 && /auto|scroll/.test(getComputedStyle(e).overflowY)) };
      });
      check(`resp.modal.${vp.name}.${nm} stays inside the viewport`,
            t.fitsX && (t.fitsY || t.panelScrolls),
            JSON.stringify(t));
      // Guard the thing the screenshots are evidence of: every tab keeps a
      // painted, non-transparent label, including the just-scrolled active one.
      const labels = await p.evaluate(() => [...document.querySelectorAll('[role="tab"]')].map((t) => {
        const sp = t.querySelector("span") || t;
        const cs = getComputedStyle(sp);
        const r = sp.getBoundingClientRect();
        return { txt: sp.textContent.trim(), on: t.getAttribute("aria-selected") === "true",
                 op: cs.opacity, vis: cs.visibility, w: Math.round(r.width), h: Math.round(r.height) };
      }));
      const blank = labels.filter((l) => !l.txt || l.w < 8 || l.h < 8 || l.vis !== "visible" || Number(l.op) < 0.9);
      check(`resp.modal.${vp.name}.${nm} every tab label is painted`,
            blank.length === 0, JSON.stringify(blank.length ? blank : labels.map((l) => l.txt)));
    }
    await mtabs.nth(0).click();
    await p.waitForTimeout(900);

    const modal = await p.evaluate(() => {
      const de = document.documentElement;
      const d = document.querySelector('[role="dialog"]');
      const dr = d.getBoundingClientRect();
      // A child sticking out of an ancestor that scrolls horizontally on purpose
      // (the tab strip below 640px is one) is the scroller working, not a break.
      const inScroller = (el) => {
        for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
          if (/auto|scroll/.test(getComputedStyle(a).overflowX)) return true;
        }
        return false;
      };
      // Visually-hidden text (clip-path: inset(50%), 1px box) is 100% of the
      // "clipped text" a naive scrollWidth check finds. It is meant to be clipped.
      const srOnly = (el) => {
        const cs = getComputedStyle(el);
        return el.clientWidth <= 1 || el.clientHeight <= 1 ||
               cs.clipPath === "inset(50%)" || cs.clip === "rect(0px, 0px, 0px, 0px)";
      };
      const over = [];
      for (const el of d.querySelectorAll("*")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (srOnly(el) || inScroller(el)) continue;
        if (r.right > dr.right + 1.5 || r.left < dr.left - 1.5) {
          over.push({ tag: el.tagName.toLowerCase(), cls: (el.className || "").toString().slice(0, 50),
                      l: Math.round(r.left), r: Math.round(r.right) });
        }
      }
      // clipped text: element whose scrollWidth exceeds clientWidth with no ellipsis/scroll
      const clipped = [];
      for (const el of d.querySelectorAll("*")) {
        if (el.children.length) continue;
        if (srOnly(el) || inScroller(el)) continue;
        const cs = getComputedStyle(el);
        if (el.scrollWidth > el.clientWidth + 2 && cs.overflowX === "hidden" && cs.textOverflow !== "ellipsis") {
          clipped.push({ tag: el.tagName.toLowerCase(), cls: (el.className||"").toString().slice(0,50),
                         sw: el.scrollWidth, cw: el.clientWidth, txt: (el.textContent||"").trim().slice(0, 44) });
        }
      }
      return { dialog: { l: Math.round(dr.left), r: Math.round(dr.right), w: Math.round(dr.width),
                         t: Math.round(dr.top), b: Math.round(dr.bottom) },
               vw: de.clientWidth, vh: de.clientHeight,
               fitsX: dr.left >= -1 && dr.right <= de.clientWidth + 1,
               over: over.slice(0, 8), clipped: clipped.slice(0, 8) };
    });
    check(`resp.modal.${vp.name} fits the viewport horizontally`, modal.fitsX, JSON.stringify(modal.dialog) + " vw=" + modal.vw);
    check(`resp.modal.${vp.name} nothing overflows the dialog`, modal.over.length === 0, JSON.stringify(modal.over));
    check(`resp.modal.${vp.name} no clipped text`, modal.clipped.length === 0, JSON.stringify(modal.clipped));
    check(`resp.${vp.name} zero unexpected console errors`, b.console.length === 0,
          JSON.stringify(b.console.slice(0, 3)) + `  [${b.expected.length} expected]`);
    await c.close();
  }

  await browser.close();
  fs.writeFileSync(path.join(SHOTS, "..", "e2e-results.json"), JSON.stringify(results, null, 1));
  const failed = results.filter((r) => !r.ok);
  console.log(`\n==== ${results.length - failed.length}/${results.length} passed ====`);
  if (failed.length) { console.log("FAILURES:"); failed.forEach((f) => console.log("  - " + f.name + " :: " + f.detail)); }
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error("HARNESS ERROR", e); process.exit(2); });
