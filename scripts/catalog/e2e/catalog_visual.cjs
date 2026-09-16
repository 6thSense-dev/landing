/*
 * Catalog VISUAL audit — the measurement half of the 2026-08 design pass.
 *
 * catalog_e2e.cjs proves the stack works. This proves the page LOOKS right, and
 * it does it by measuring rather than by eyeballing a PNG:
 *
 *   - Pretendard is actually the painted face, at 200/400/600/800, in the catalog
 *     and NOT on the marketing site (a leaked @font-face would show up there).
 *   - Nothing on the page is wider than the page, at 360 / 768 / 1440.
 *   - Every .cat-figure is a single line (a wrapped stat figure is the defect the
 *     eight-tile row had).
 *   - The corpus is CN + HK only, and every clip is stereo egocentric + tactile.
 *   - The logo mark and a working sign-out are on screen in the top bar.
 *   - Zero console errors.
 *
 * It also writes the framed screenshots the design review reads: the top bar +
 * masthead, the filter bar + first grid row, and the task chart, per width.
 *
 *   CATALOG_E2E_SITE=http://127.0.0.1:5199 \
 *   CATALOG_E2E_API=http://127.0.0.1:8099 \
 *   CATALOG_E2E_PW="$(pass catalog/guest)" \
 *   node scripts/catalog/e2e/catalog_visual.cjs
 *
 * Exit 0 = every assertion held.
 */
const path = require("path");
const fs = require("fs");

const REPO = path.resolve(__dirname, "..", "..", "..");
const { chromium } = require(require.resolve("playwright", {
  paths: [path.join(REPO, "frontend", "node_modules"), REPO],
}));

const SITE = process.env.CATALOG_E2E_SITE || "http://127.0.0.1:5199";
const API = process.env.CATALOG_E2E_API || "http://127.0.0.1:8099";
const SHOTS = process.env.CATALOG_E2E_SHOTS || path.join(REPO, "docs", "catalog", "screenshots");
const GUEST_ID = process.env.CATALOG_E2E_ID || "guest";
const GUEST_PW = process.env.CATALOG_E2E_PW;
if (!GUEST_PW) {
  console.error("CATALOG_E2E_PW is not set; there is deliberately no default.");
  process.exit(2);
}
fs.mkdirSync(SHOTS, { recursive: true });

const VIEWPORTS = [
  { name: "360", width: 360, height: 900 },
  { name: "768", width: 768, height: 1100 },
  { name: "1440", width: 1440, height: 950 },
];

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok: !!ok, detail: detail === undefined ? "" : String(detail) });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail !== undefined ? "  :: " + detail : ""}`);
}

async function settle(page) {
  /* Park the pointer off every control first. Playwright leaves the mouse where
     the last click put it, so scrolling a section into view under that resting
     position opens its hover state -- the first chart capture came out with a
     tooltip pinned open and nine bars dimmed, which is not what the page does. */
  await page.mouse.move(0, 0);
  await page.evaluate(() => { if (document.activeElement) document.activeElement.blur(); });
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((r) => setTimeout(r, 250));
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  });
}

/**
 * Screenshot a region defined by one or more selectors, with a little air.
 *
 * DOCUMENT coordinates against a fullPage capture, not viewport coordinates: a
 * region taller than the window (the masthead at 360, the chart at 1440) has a
 * viewport clip that runs off the bottom of the image, and Playwright rejects it.
 */
async function shootRegion(page, file, selectors, pad = 8) {
  await settle(page);
  /* BRING THE REGION ON SCREEN FIRST.
   *
   * The posters are `loading="lazy"` and their cards carry `content-visibility:
   * auto`, so an element the viewport has never reached has simply not fetched
   * its image. `filters-1440.png` was captured with the page scrolled to the top
   * and the first card 200px below the fold, and came out with a grey box where
   * the thumbnail is — a screenshot standing as evidence for a defect the running
   * page does not have. Centre the region, let it load, THEN capture; the clip is
   * in document coordinates -- EXCEPT that `.cat-topbar` is `position: fixed`, so
   * its document rect follows the scroll. Restore the original scroll position
   * before measuring and capturing: an image that has loaded stays loaded, so the
   * frame is the one the harness always took and the thumbnails are painted. */
  const scrollBack = await page.evaluate(() => window.scrollY);
  await page.evaluate((sels) => {
    let t = Infinity, b = -Infinity;
    for (const s of sels) {
      for (const el of document.querySelectorAll(s)) {
        const q = el.getBoundingClientRect();
        if (q.width === 0 || q.height === 0) continue;
        t = Math.min(t, q.top + window.scrollY);
        b = Math.max(b, q.bottom + window.scrollY);
      }
    }
    if (t === Infinity) return;
    window.scrollTo(0, Math.max(0, (t + b) / 2 - window.innerHeight / 2));
  }, selectors);
  await page.waitForTimeout(400);
  /* Then wait for the images INSIDE the region to decode, with a ceiling so a
     genuinely broken asset still produces a picture of the breakage, not a hang. */
  await page
    .waitForFunction(
      (sels) => {
        const imgs = [];
        for (const s of sels) {
          for (const el of document.querySelectorAll(s)) {
            imgs.push(...el.querySelectorAll("img"));
            if (el.tagName === "IMG") imgs.push(el);
          }
        }
        return imgs.every((i) => i.complete);
      },
      selectors,
      { timeout: 8000 },
    )
    .catch(() => {});
  await page.evaluate((y) => window.scrollTo(0, y), scrollBack);
  await page.waitForTimeout(250);
  await settle(page);
  const box = await page.evaluate((sels) => {
    let l = Infinity, t = Infinity, r = -Infinity, b = -Infinity, n = 0;
    const ox = window.scrollX, oy = window.scrollY;
    for (const s of sels) {
      for (const el of document.querySelectorAll(s)) {
        const q = el.getBoundingClientRect();
        if (q.width === 0 || q.height === 0) continue;
        l = Math.min(l, q.left + ox); t = Math.min(t, q.top + oy);
        r = Math.max(r, q.right + ox); b = Math.max(b, q.bottom + oy); n++;
      }
    }
    const de = document.documentElement;
    return n ? { x: l, y: t, w: r - l, h: b - t,
                 dw: Math.max(de.scrollWidth, de.clientWidth),
                 dh: Math.max(de.scrollHeight, de.clientHeight) } : null;
  }, selectors);
  if (!box) return false;
  const x = Math.max(0, Math.round(box.x - pad));
  const y = Math.max(0, Math.round(box.y - pad));
  const clip = {
    x, y,
    width: Math.min(box.dw - x, Math.round(box.w + pad * 2)),
    height: Math.min(box.dh - y, Math.round(box.h + pad * 2)),
  };
  if (clip.width <= 0 || clip.height <= 0) return false;
  /* `.cat-card` carries `content-visibility: auto`, which is what keeps a
     thousand-card grid cheap — and which renders a card BLANK when it is
     outside the rendered viewport. A fullPage capture stitches beyond the
     viewport, so the first card came out as a grey box in filters-1440.png:
     a screenshot showing a defect the running page does not have. Suspend the
     optimisation for the duration of the capture and restore it, so the
     evidence is a picture of what a scrolled user sees. */
  await shootFullPage(page, file, clip);
  return true;
}

/**
 * A fullPage capture with `content-visibility` suspended for the duration.
 *
 * `.cat-card` carries `content-visibility: auto`, which is what keeps a
 * thousand-card grid cheap — and which renders a card BLANK when it is outside
 * the rendered viewport. A fullPage capture stitches well beyond the viewport,
 * so `page-*.png` came out as a masthead followed by forty empty rectangles: a
 * design-review artefact showing none of the design. Suspending the
 * optimisation for the capture (and restoring it after) makes the picture the
 * one a scrolling reader sees, which is the only thing these files are for.
 */
async function shootFullPage(page, file, clip) {
  const relaxed = await page.addStyleTag({
    content:
      ".cat-card { content-visibility: visible !important; }" +
      /* Un-skipping a cell also STARTS its reveal animation, and the first row's
         is `animation: cat-cell-in ... both` with a per-cell delay — so
         `fill-mode: both` holds those cells at the `from` keyframe (opacity 0)
         for their delay, and Chromium's capture-beyond-viewport pass restarts
         them at the instant of capture. Two of the three first-row cards came
         out fully transparent in page-1440.png. Land every animation on its end
         state for the duration of the shot; the motion is asserted elsewhere and
         a still frame of it is not what these files are for. */
      "*, *::before, *::after { animation-delay: 0s !important;" +
      " animation-duration: 0.001s !important; transition-duration: 0.001s !important; }",
  });
  /* Un-skipping a card starts its lazy poster fetching for the first time, so
     waiting a fixed beat captures whichever ones happened to win the race. Wait
     for the images themselves, with a ceiling so a genuinely broken asset still
     produces a picture of the breakage rather than a hang. */
  await page
    .waitForFunction(
      () => [...document.querySelectorAll(".cat-card img")].every((i) => i.complete),
      undefined,
      { timeout: 15000 },
    )
    .catch(() => {});
  await page.waitForTimeout(400);
  try {
    await page.screenshot(clip ? { path: file, clip, fullPage: true }
                                : { path: file, fullPage: true });
  } finally {
    await relaxed.evaluate((el) => el.remove()).catch(() => {});
  }
}

/**
 * Injected into every page: the height of the thing a user actually aims at.
 *
 *  - a bare <input> is 22px inside a 44px pill; the SHELL is the target, so a
 *    form control is measured at its nearest bordered ancestor;
 *  - an absolutely-positioned ::before/::after that hangs outside the box is a
 *    deliberate hit-area expander (the modal's 38px video controls use one) and
 *    counts toward the height;
 *  - a link inside a sentence is exempt, per WCAG 2.5.8's own inline exception:
 *    forcing 44px on `data@6thsense.dev` mid-paragraph fixes nothing and blows
 *    the leading apart.
 */
const MEASURE_CONTROLS = () => {
  window.measureControls = (min) => {
    const inProse = (el) => {
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        if (/^(P|LI|DD|DT|SMALL|FIGCAPTION|BLOCKQUOTE|SUMMARY)$/.test(a.tagName)) return true;
      }
      return false;
    };
    const shell = (el) => {
      if (!/^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) return el;
      for (let a = el.parentElement, n = 0; a && n < 3; a = a.parentElement, n++) {
        const cs = getComputedStyle(a);
        if (parseFloat(cs.borderTopWidth) > 0 || cs.backgroundColor !== "rgba(0, 0, 0, 0)") return a;
      }
      return el;
    };
    const hit = (el) => {
      let h = el.getBoundingClientRect().height;
      for (const p of ["::before", "::after"]) {
        const cs = getComputedStyle(el, p);
        if (!cs || cs.content === "none" || cs.position !== "absolute") continue;
        const t = parseFloat(cs.top) || 0, b = parseFloat(cs.bottom) || 0;
        if (t < 0 || b < 0) h += Math.abs(Math.min(t, 0)) + Math.abs(Math.min(b, 0));
      }
      return h;
    };
    const bad = [];
    for (const el of document.querySelectorAll(
      ".cat-root button, .cat-root a[href], .cat-root select, .cat-root input, " +
      ".cat-root [role=radio], .cat-root [role=tab]"
    )) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (el.tagName === "A" && inProse(el)) continue;
      const box = shell(el);
      const h = hit(box);
      const w = box.getBoundingClientRect().width;
      if (h < min || w < min) {
        bad.push({ cls: (el.className || "").toString().slice(0, 40), tag: el.tagName.toLowerCase(),
                   txt: (el.textContent || "").trim().slice(0, 22),
                   h: Math.round(h), w: Math.round(w) });
      }
    }
    return bad;
  };
};

async function login(page) {
  await page.addInitScript(MEASURE_CONTROLS);
  await page.addInitScript((api) => { window.__API__ = api; }, API);
  await page.goto(`${SITE}/login`, { waitUntil: "networkidle" });
  await page.locator('input[name="identifier"], input[type="text"], input[type="email"]').first().fill(GUEST_ID);
  await page.locator('input[type="password"]').first().fill(GUEST_PW);
  await Promise.all([
    page.waitForURL(/\/portal\//, { timeout: 30000 }),
    page.locator('button[type="submit"]').first().click(),
  ]);
}

(async () => {
  const browser = await chromium.launch();

  /* ---------- 1. the manifest's own scope ---------- */
  {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 950 } });
    const page = await ctx.newPage();
    await login(page);
    await page.waitForSelector(".cat-card", { timeout: 30000 });
    const scope = await page.evaluate(async (api) => {
      const m = await (await fetch(`${api}/api/catalog`, { credentials: "include" })).json();
      const countries = [...new Set(m.clips.map((c) => c.country))].sort();
      const captures = [...new Set(m.clips.map((c) => c.capture))].sort();
      const noTactile = m.clips.filter((c) => !(c.modalities || []).includes("tactile")).map((c) => c.id);
      const noVideo = m.clips.filter((c) => !(c.modalities || []).includes("video")).map((c) => c.id);
      return {
        countries,
        facetCountries: (m.facets.country || []).map((b) => `${b.value}=${b.label}`),
        totalsCountries: m.collection.totals.countries,
        captures,
        noTactile,
        noVideo,
        clips: m.clips.length,
      };
    }, API);
    check("v1. every clip is in China or Hong Kong, and nothing else is",
          JSON.stringify(scope.countries) === '["CN","HK"]' &&
          JSON.stringify(scope.totalsCountries) === '["CN","HK"]' &&
          scope.facetCountries.join(",") === "CN=China,HK=Hong Kong",
          JSON.stringify(scope));
    check("v2. every clip is stereo egocentric video + tactile",
          JSON.stringify(scope.captures) === '["stereo_egocentric"]' &&
          scope.noTactile.length === 0 && scope.noVideo.length === 0,
          JSON.stringify({ captures: scope.captures, noTactile: scope.noTactile, noVideo: scope.noVideo }));

    /* the UI must not print a raw alpha-2 anywhere a human reads */
    const rawCodes = await page.evaluate(() => {
      const bad = [];
      for (const el of document.querySelectorAll(".cat-card__meta *, .cat-substat, .cat-fb__chip")) {
        if (el.children.length) continue;
        const t = (el.textContent || "").trim();
        if (/^(CN|HK)$/.test(t)) bad.push({ cls: (el.className || "").toString().slice(0, 40), t });
      }
      return bad;
    });
    check("v3. the UI shows country NAMES, never the bare alpha-2 code",
          rawCodes.length === 0, JSON.stringify(rawCodes.slice(0, 5)));

    /* the filter bar must not offer a chip that selects the whole corpus */
    const deadChips = await page.evaluate(() => {
      const total = document.querySelectorAll(".cat-card").length;
      const out = [];
      for (const c of document.querySelectorAll(".cat-fb__chip")) {
        const n = Number((c.querySelector(".cat-fb__chipn") || {}).textContent || NaN);
        if (Number.isFinite(n) && n >= total) out.push({ t: c.textContent.trim().slice(0, 30), n, total });
      }
      return out;
    });
    check("v4. no filter chip selects the entire corpus (a control that cannot narrow)",
          deadChips.length === 0, JSON.stringify(deadChips.slice(0, 6)));

    /* v4b. The grid must STATE the product, not only flag its absence.
       The card used to badge only a mono clip, so a buyer scanning thirty
       thumbnails was never told anywhere in the grid that all of them are
       stereo + tactile — and a record with a missing `capture` silently stamped
       "Mono" on a card.

       THERE ARE TWO PRODUCT MARKS, and both are correct: "STEREO · TACTILE" and
       "STEREO · CAMERA ONLY". This used to demand the first on every card, which
       is a fact about THIS drop (v2 asserts it properly, off the manifest) and
       not a fact about the grid. Asserted here instead: every card carries a
       mark, every mark names one of the two products, and no card wears the
       alert tone — camera-only is a product and must never be rendered as a
       defect. */
    const PRODUCT_MARKS = ["STEREO · TACTILE", "STEREO · CAMERA ONLY"];
    const marks = await page.evaluate((ok) => {
      const cards = [...document.querySelectorAll(".cat-card")];
      const texts = cards.map((c) => {
        const m = c.querySelector(".cat-card__mark");
        return m ? m.textContent.trim().toUpperCase() : null;
      });
      return {
        cards: cards.length,
        marked: texts.filter((t) => ok.includes(t)).length,
        others: [...new Set(texts.filter((t) => !ok.includes(t)))],
        alerted: document.querySelectorAll(".cat-card__mark--alert").length,
        saysMono: /\bmono\b/i.test(document.querySelector(".cat-grid").textContent || ""),
      };
    }, PRODUCT_MARKS);
    check("v4b. every card names one of the two products, none is alert-toned, none says Mono",
          marks.cards > 0 && marks.marked === marks.cards && marks.alerted === 0 &&
          !marks.saysMono,
          JSON.stringify(marks));

    /* v4c. One baseline per grid row. The card title reserves two lines and the
       channel census always takes its own, so a short title or a narrow QA cell
       cannot move a card's signal strip relative to its neighbours'. */
    const rhythm = await page.evaluate(() => {
      const cards = [...document.querySelectorAll(".cat-card")];
      const rows = new Map();
      for (const c of cards) {
        const r = c.getBoundingClientRect();
        const key = Math.round(r.top / 4);
        const strip = c.querySelector(".cat-card__specs");
        if (!strip) continue;
        const off = Math.round(strip.getBoundingClientRect().top - r.top);
        if (!rows.has(key)) rows.set(key, []);
        rows.get(key).push(off);
      }
      const bad = [];
      for (const [k, offs] of rows) {
        const spread = Math.max(...offs) - Math.min(...offs);
        if (offs.length > 1 && spread > 1) bad.push({ row: k, offs, spread });
      }
      return { rows: rows.size, bad };
    });
    check("v4c. every card in a grid row puts its signal strip on one baseline",
          rhythm.bad.length === 0, JSON.stringify(rhythm).slice(0, 220));

    /* v4d. The sticky filter bar actually sticks. Its containing block used to be
       a section exactly as tall as the bar, so the travel available to it was
       zero: computed `position: sticky, top: 56px` and a viewport top of -1322 at
       scrollY 2500. Everything built around it was dead code. */
    {
      /* This block runs in the 1440-wide context above, which is where the bar
         is sticky at all (it pins from 60rem up; below that the facet panel is
         over a third of a phone viewport and pinning it would trade the grid for
         a control panel used once). */
      const travel = [];
      for (const y of [0, 1400, 2600]) {
        /* eslint-disable no-await-in-loop */
        await page.evaluate((yy) => window.scrollTo(0, yy), y);
        await page.waitForTimeout(400);
        travel.push(await page.evaluate(() => {
          const fb = document.querySelector(".cat-fb");
          const cs = getComputedStyle(fb);
          return {
            y: Math.round(window.scrollY),
            top: Math.round(fb.getBoundingClientRect().top),
            pin: cs.position === "sticky" ? Math.round(parseFloat(cs.top) || 0) : null,
            stuck: fb.classList.contains("is-stuck"),
          };
        }));
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.waitForTimeout(300);
      const pinned = travel.filter((t) => t.y > 0);
      check("v4d. the filter bar pins under the top bar instead of scrolling away",
            pinned.length > 0 && pinned.every((t) => t.pin != null && Math.abs(t.top - t.pin) <= 1),
            JSON.stringify(travel));
      check("v4e. the pinned elevation state tracks the pin line, not y=0",
            travel[0] && travel[0].stuck === false && pinned.every((t) => t.stuck === true),
            JSON.stringify(travel.map((t) => [t.y, t.stuck])));
    }

    /* v4f. Text a buyer READS clears 7:1 on paper. The grid held itself to that
       with --cat-ink-2 while the modal and the header used --muted (6.25:1) for
       the same rank of copy, so the two surfaces did not look like one system. */
    const contrast = await page.evaluate(() => {
      const lin = (c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
      const lum = ([r, g, b]) => 0.2126 * lin(r / 255) + 0.7152 * lin(g / 255) + 0.0722 * lin(b / 255);
      const parse = (s) => (s.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
      const bgOf = (el) => {
        let n = el;
        while (n && n !== document.documentElement) {
          const b = getComputedStyle(n).backgroundColor;
          const p = parse(b);
          if (p.length === 3 && !/rgba\(.*,\s*0\)/.test(b)) return p;
          n = n.parentElement;
        }
        return [255, 255, 255];
      };
      const bad = [];
      const READ = ".cat-lead, .cat-stat-sub, .cat-masthead__line, .cat-access__how, " +
                   ".cat-card__sub, .cat-card__dur, .cat-card__census, .cat-card__country";
      for (const el of document.querySelectorAll(READ)) {
        const t = (el.textContent || "").trim();
        if (!t) continue;
        const cs = getComputedStyle(el);
        const fg = parse(cs.color);
        const bg = bgOf(el);
        if (fg.length !== 3) continue;
        const a = lum(fg) + 0.05;
        const b = lum(bg) + 0.05;
        const ratio = Math.round(((a > b ? a / b : b / a)) * 100) / 100;
        if (ratio < 7) bad.push({ cls: (el.className || "").toString().split(" ")[0], ratio, color: cs.color });
      }
      return bad;
    });
    check("v4f. every read-text rule on paper clears 7:1",
          contrast.length === 0, JSON.stringify(contrast.slice(0, 5)));

    /* logo + sign-out */
    const chrome = await page.evaluate(() => {
      const mark = document.querySelector(".cat-wordmark__mark, .cat-topbar img");
      const out = document.querySelector('button:has(> svg), button');
      const logout = [...document.querySelectorAll("button, a")]
        .find((e) => /log ?out|sign ?out/i.test(e.textContent || ""));
      const r = logout ? logout.getBoundingClientRect() : null;
      return {
        mark: mark ? { src: mark.currentSrc || mark.src, w: Math.round(mark.getBoundingClientRect().width),
                       h: Math.round(mark.getBoundingClientRect().height),
                       decoded: mark.complete && mark.naturalWidth > 0 } : null,
        logout: r ? { w: Math.round(r.width), h: Math.round(r.height), txt: logout.textContent.trim() } : null,
        _o: !!out,
      };
    });
    check("v5. the logo mark is in the top bar and decoded",
          !!chrome.mark && chrome.mark.decoded && chrome.mark.w > 12, JSON.stringify(chrome.mark));
    check("v6. a guest can sign out, and the target is >= 44px tall",
          !!chrome.logout && chrome.logout.h >= 44, JSON.stringify(chrome.logout));

    /* Pretendard must NOT have leaked onto the marketing site */
    await page.goto(`${SITE}/`, { waitUntil: "networkidle" });
    await settle(page);
    const leak = await page.evaluate(() => {
      const faces = [];
      for (const f of document.fonts) faces.push(f.family);
      const body = getComputedStyle(document.body).fontFamily;
      return { pretendardFaces: faces.filter((f) => /pretendard/i.test(f)).length, body };
    });
    check("v7. Pretendard does not leak onto the marketing site",
          leak.pretendardFaces === 0 && !/pretendard/i.test(leak.body), JSON.stringify(leak));
    await ctx.close();
  }

  /* ---------- 2. per-viewport typography, layout and framing ---------- */
  for (const vp of VIEWPORTS) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height }, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    const errs = [];
    page.on("console", (m) => { if (m.type() === "error" && !/status of 401/.test(m.text())) errs.push(m.text().slice(0, 200)); });
    page.on("pageerror", (e) => errs.push("pageerror: " + String(e).slice(0, 200)));
    await login(page);
    await page.waitForSelector(".cat-card", { timeout: 30000 });
    await page.waitForLoadState("networkidle");
    await settle(page);

    /* --- fonts, measured, not eyeballed --- */
    const fonts = await page.evaluate(async () => {
      await document.fonts.ready;
      const P = '"Pretendard Variable"';
      const weights = [200, 300, 400, 500, 600, 700, 800];
      const loaded = {};
      for (const w of weights) loaded[w] = document.fonts.check(`${w} 16px ${P}`);
      const sample = (sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const cs = getComputedStyle(el);
        return { ff: cs.fontFamily.split(",")[0].replace(/["']/g, ""), fw: cs.fontWeight,
                 fs: cs.fontSize, ls: cs.letterSpacing };
      };
      const usedWeights = new Set();
      for (const el of document.querySelectorAll(".cat-root *")) {
        const cs = getComputedStyle(el);
        if (/pretendard/i.test(cs.fontFamily) && (el.textContent || "").trim()) usedWeights.add(cs.fontWeight);
      }
      return {
        loaded,
        body: sample(".cat-root"),
        figure: sample(".cat-figure"),
        label: sample(".cat-label"),
        cardTitle: sample(".cat-card__title"),
        mono: sample(".cat-mono"),
        usedWeights: [...usedWeights].sort((a, b) => a - b),
      };
    });
    check(`t.${vp.name} Pretendard is loaded at 200/400/600/800`,
          fonts.loaded[200] && fonts.loaded[400] && fonts.loaded[600] && fonts.loaded[800],
          JSON.stringify(fonts.loaded));
    check(`t.${vp.name} body copy computes to Pretendard, not a fallback sans`,
          !!fonts.body && /pretendard/i.test(fonts.body.ff), JSON.stringify(fonts.body));
    check(`t.${vp.name} the weight axis is used expressively (>= 5 distinct weights)`,
          fonts.usedWeights.length >= 5, JSON.stringify(fonts.usedWeights));
    check(`t.${vp.name} the stat figure is set in a light weight at a display size`,
          !!fonts.figure && Number(fonts.figure.fw) <= 300 && parseFloat(fonts.figure.fs) >= 26,
          JSON.stringify(fonts.figure));
    check(`t.${vp.name} .cat-label is semibold and tracked out`,
          !!fonts.label && Number(fonts.label.fw) >= 600 && parseFloat(fonts.label.ls) > 0,
          JSON.stringify(fonts.label));
    check(`t.${vp.name} mono is reserved for machine strings (Geist Mono, not Pretendard)`,
          !fonts.mono || /geist|mono/i.test(fonts.mono.ff), JSON.stringify(fonts.mono));

    /* --- one line per figure --- */
    const figures = await page.evaluate(() => {
      const out = [];
      for (const el of document.querySelectorAll(".cat-figure, .cat-stat-value, .cat-substat-value")) {
        const cs = getComputedStyle(el);
        const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
        const h = el.getBoundingClientRect().height;
        const lines = Math.round(h / lh);
        if (lines > 1) out.push({ cls: (el.className || "").toString().slice(0, 40),
                                  txt: (el.textContent || "").trim().slice(0, 30),
                                  h: Math.round(h), lh: Math.round(lh), lines });
      }
      return out;
    });
    check(`l.${vp.name} every stat figure occupies exactly one line`,
          figures.length === 0, JSON.stringify(figures.slice(0, 6)));

    /* --- nothing wider than the page --- */
    const over = await page.evaluate(() => {
      const de = document.documentElement;
      const inScroller = (el) => {
        for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
          if (/auto|scroll/.test(getComputedStyle(a).overflowX)) return true;
        }
        return false;
      };
      const bad = [];
      for (const el of document.querySelectorAll("body *")) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.height === 0) continue;
        if (getComputedStyle(el).position === "fixed" || inScroller(el)) continue;
        if (r.right > de.clientWidth + 1.5 || r.left < -1.5) {
          bad.push({ tag: el.tagName.toLowerCase(), cls: (el.className || "").toString().slice(0, 46),
                     l: Math.round(r.left), r: Math.round(r.right) });
        }
      }
      return { sw: de.scrollWidth, cw: de.clientWidth, bad: bad.slice(0, 8) };
    });
    check(`l.${vp.name} page scrollWidth <= clientWidth`, over.sw <= over.cw + 1,
          `${over.sw} <= ${over.cw}  ${JSON.stringify(over.bad)}`);

    /* --- control sizing on a MOUSE ---
     * 44px is a finger measurement and parts.grid.css applies it under
     * `@media (pointer: coarse)`, which is right: forcing every facet chip to
     * 44px on a desktop would treble the height of the filter bar to solve a
     * problem a mouse does not have. The floor asserted here is the one that DOES
     * apply to a mouse: WCAG 2.5.8 Target Size (Minimum), 24x24 CSS px, level AA.
     * The 44px AAA figure is asserted for real in the touch pass below. */
    const small = await page.evaluate(() => measureControls(24));
    check(`l.${vp.name} every mouse control clears WCAG 2.5.8 AA (24px)`, small.length === 0,
          `${small.length} under 24: ` + JSON.stringify(small.slice(0, 8)));

    /* --- framed screenshots --- */
    await page.evaluate(() => window.scrollTo(0, 0));
    await shootRegion(page, `${SHOTS}/header-${vp.name}.png`, [".cat-topbar", ".cat-masthead"]);
    const fbOk = await shootRegion(page, `${SHOTS}/filters-${vp.name}.png`,
                                   [".cat-fb", ".cat-grid__cell:nth-child(-n+3)"]);
    check(`s.${vp.name} filter bar + first grid row captured`, fbOk, `${SHOTS}/filters-${vp.name}.png`);
    await page.evaluate(() => {
      const c = document.querySelector(".cat-chart, .cat-chart-card, [aria-label='Task coverage']");
      if (c) c.scrollIntoView({ block: "center" });
    });
    await page.waitForTimeout(900);
    const chOk = await shootRegion(page, `${SHOTS}/chart-${vp.name}.png`,
                                   [".cat-chart-card", ".cat-chart", "[aria-label='Task coverage']"]);
    check(`s.${vp.name} task chart captured`, chOk, `${SHOTS}/chart-${vp.name}.png`);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(400);
    await settle(page);
    await shootFullPage(page, `${SHOTS}/page-${vp.name}.png`, null);

    check(`e.${vp.name} zero console errors`, errs.length === 0, JSON.stringify(errs.slice(0, 4)));
    await ctx.close();
  }

  /* ---------- 3. the same page on a finger ----------
   * `pointer: coarse` is the media query the 44px rules are gated on, so it has
   * to be emulated to be tested. A desktop Chrome at 360px wide reports a FINE
   * pointer and silently skips every one of them. */
  for (const vp of [VIEWPORTS[0], VIEWPORTS[1]]) {
    const ctx = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      hasTouch: true, isMobile: true, deviceScaleFactor: 2,
    });
    const page = await ctx.newPage();
    await login(page);
    await page.waitForSelector(".cat-card", { timeout: 30000 });
    await page.waitForLoadState("networkidle");
    await settle(page);
    const coarse = await page.evaluate(() => window.matchMedia("(pointer: coarse)").matches);
    const small = await page.evaluate(() => measureControls(44));
    check(`touch.${vp.name} the coarse-pointer rules are actually in effect`, coarse, String(coarse));
    check(`touch.${vp.name} every control has a 44px hit area`, small.length === 0,
          `${small.length} under 44: ` + JSON.stringify(small.slice(0, 10)));
    const ov = await page.evaluate(() => {
      const de = document.documentElement;
      return { sw: de.scrollWidth, cw: de.clientWidth };
    });
    check(`touch.${vp.name} no horizontal overflow at 44px targets`, ov.sw <= ov.cw + 1,
          `${ov.sw} <= ${ov.cw}`);
    await ctx.close();
  }

  await browser.close();
  fs.writeFileSync(path.join(SHOTS, "..", "e2e-visual.json"), JSON.stringify(results, null, 1));
  const failed = results.filter((r) => !r.ok);
  console.log(`\n==== ${results.length - failed.length}/${results.length} passed ====`);
  if (failed.length) { console.log("FAILURES:"); failed.forEach((f) => console.log("  - " + f.name + " :: " + f.detail)); }
  process.exit(failed.length ? 1 : 0);
})().catch((e) => { console.error("HARNESS ERROR", e); process.exit(2); });
