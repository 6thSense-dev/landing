/**
 * Builds the social link-preview (Open Graph / Twitter) card at 1200x630.
 *
 *   node scripts/build-og-image.mjs                 # all variants -> /tmp/og-out
 *   node scripts/build-og-image.mjs --variant=pair  # one variant
 *   node scripts/build-og-image.mjs --variant=pair --install
 *   node scripts/build-og-image.mjs --variant=pair --install=og-image-v4.png
 *
 * --install writes public/og-image-v3.png and does NOT overwrite an existing
 * file. That is deliberate. Facebook, LinkedIn, Slack and X all cache the
 * unfurl against the image URL, for weeks in some cases, so overwriting the
 * path in place ships a new card that almost nobody sees. Bumping the filename
 * (and the two <meta> tags in index.html) is the only reliable way to
 * invalidate them - which is what the "-v2" in the old name was already for.
 * Leave the superseded file on disk: links shared before the swap still point
 * at it.
 *
 * Why a generator and not a hand-made PNG: the card carries the positioning
 * line, the spec readout and the wordmark, all of which change. The previous
 * card was a static export whose wordmark collided with the product knockout
 * and whose red/green "molecule field" predates the palette in DESIGN.md; when
 * the copy moved on there was no way to regenerate it. This renders from the
 * same fonts, colors and product knockouts the site itself ships, so the card
 * can never drift from the design system without the source drifting too.
 *
 * Everything here follows DESIGN.md: dark ground #0e0d0a, one warm orange
 * accent, General Sans display / Geist Mono for the instrument readout, a
 * radial glow behind the rim-lit product, restrained grain. No other hues.
 *
 * The product knockouts are alpha-cropped IN THE PAGE (canvas) rather than at
 * fixed pixel offsets, so re-shooting a glove does not silently reframe the
 * card. See tightCrop().
 */

import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs/promises";
import { constants as fsc } from "node:fs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FRONTEND = path.resolve(HERE, "..");
const PUBLIC = path.join(FRONTEND, "public");

const W = 1200;
const H = 630;
/* Supersample, then let the browser box-filter back down to 1200x630. The
   product knockouts have long curved alpha edges that alias badly at 1x. */
const SS = 2;

/* ---------------------------------------------------------------- palette */
/* Straight out of DESIGN.md > Color. Do not add hues. */
const C = {
  ground: "#0e0d0a",
  ink: "#f4f1ea",
  muted: "#a49c86",
  accent: "#F0612A",
  hairline: "rgba(255,255,255,.12)",
};

/* ------------------------------------------------------------------- copy */
/* Mirrors index.html's og:title / og:description and the shipped stat set in
   pages/ProductsV2.jsx, so the card cannot contradict the page it unfurls. */
const COPY = {
  wordmark: "6THSENSE",
  headline: "The touch layer for dexterous robots",
  tagline: ["Robots have five senses.", "We are building the sixth."],
  sub: "Gloves that feel, and custom tactile skin molded to robot hands.",
  specs: ["440 channels", "0.01 N", "<1 ms", "200 Hz"],
};

/* --------------------------------------------------------------- variants */
/* `art` names the right-hand composition; `lede` picks which line leads. */
/* glowX = where the warm radial is centred, as a percentage of the card. It
   has to sit ON the product's optical centre: a glow parked beside the
   knockout reads as a stain on the background instead of as light coming off
   the thing. Single knockout sits further right than the pair's combined mass,
   so the two differ. */
const VARIANTS = {
  glove: { art: "glove", lede: "headline", glowX: "84%" },
  pair: { art: "pair", lede: "headline", glowX: "75%" },
  tagline: { art: "glove", lede: "tagline", glowX: "84%" },
};

const asset = (p) => "file://" + path.join(PUBLIC, p);

function html(variant) {
  const v = VARIANTS[variant];
  const font = (file) => "file://" + path.join(PUBLIC, "fonts", file);

  /* The brand mark, drawn rather than <img>'d. logos/Logo_Alpha.png is a
     1024x1024 raster with ~40% transparent padding and dark-brown dots that
     the site has to white-out with a filter (see .nav-logo in styles.css);
     at mark size on a card that round-trips through a feed's own rescaling,
     vector is simply cleaner. Geometry is copied from OpenerAnimation.css
     (.opener-dot--1..6): 18%-wide dots on a stair-step, 6th at top-right.
     Centers are left+9 / top+9; the viewBox is the content bbox, so the SVG
     has no dead padding and sits on the text baseline predictably.

     The sixth dot takes the accent. DESIGN.md lists dots as an accent surface,
     and the whole mark IS the "sixth sense" story - flattening it to one ink
     value (what the nav does, because an accent dot next to a nav label reads
     as a notification badge) throws that away at the one size where there is
     room for it. Flip it to C.ink here if you want the nav's treatment. */
  const mark = (px) => `
    <svg class="mark" width="${px}" height="${(px * 74) / 90}" viewBox="6 16 90 74"
         fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <circle cx="15" cy="81" r="9" fill="${C.ink}"/>
      <circle cx="39" cy="81" r="9" fill="${C.ink}"/>
      <circle cx="39" cy="53" r="9" fill="${C.ink}"/>
      <circle cx="63" cy="53" r="9" fill="${C.ink}"/>
      <circle cx="63" cy="25" r="9" fill="${C.ink}"/>
      <circle cx="87" cy="25" r="9" fill="${C.accent}"/>
    </svg>`;

  const lede =
    v.lede === "tagline"
      ? `<h1 class="lede lede--tagline">${COPY.tagline[0]}<br/>${COPY.tagline[1]}</h1>`
      : `<h1 class="lede">${COPY.headline}</h1>`;

  /* Separators are accent dots, not middots: at 13px a middot in Geist Mono is
     nearly invisible against --muted, and the dot echoes the mark. */
  const specs = COPY.specs
    .map((s) => `<span class="spec">${s}</span>`)
    .join(`<span class="spec-sep"></span>`);

  /* Sources are alpha-cropped in-page by cropImages() before the shot.

     The open-hand glove comes from the homepage scroll sequence (frame-005),
     NOT from hero/glove/pose-skin.webp. Same glove, same frame - but pose-skin
     was brightened for the /products layered composite (mean luma 166 vs 100),
     and at that exposure it blows out to near-white on the dark ground and
     stops reading as the matte charcoal fabric the thing actually is. */
  const art =
    v.art === "pair"
      ? `<div class="art art--pair">
           <figure class="fig fig--glove">
             <img data-src="${asset("hero/glove/frame-005.webp")}" alt=""/>
             <figcaption>Capture glove</figcaption>
           </figure>
           <figure class="fig fig--robo">
             <img data-src="${asset("hero/glove/robo.webp")}" alt=""/>
             <figcaption>Custom skin</figcaption>
           </figure>
         </div>`
      : `<div class="art art--glove">
           <img data-src="${asset("hero/glove/frame-005.webp")}" alt=""/>
         </div>`;

  return `<!doctype html>
<html><head><meta charset="utf-8"/>
<style>
  @font-face { font-family:'General Sans'; font-weight:500; font-style:normal;
    src:url('${font("generalsans-500-norm.woff2")}') format('woff2'); }
  @font-face { font-family:'General Sans'; font-weight:600; font-style:normal;
    src:url('${font("generalsans-600-norm.woff2")}') format('woff2'); }
  @font-face { font-family:'General Sans'; font-weight:700; font-style:normal;
    src:url('${font("generalsans-700-norm.woff2")}') format('woff2'); }
  @font-face { font-family:'Geist Mono'; font-weight:400; font-style:normal;
    src:url('${font("geistmono-400-norm-latin-b291d8.woff2")}') format('woff2'); }

  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:${W}px; height:${H}px; }
  body {
    background:${C.ground};
    font-family:'General Sans', sans-serif;
    -webkit-font-smoothing:antialiased;
    overflow:hidden;
  }

  .card { position:relative; width:${W}px; height:${H}px; overflow:hidden; }

  /* Warm radial behind the product - the "glow stage" the hero uses.
     Two rules keep it from going muddy. It is TIGHT (a wide, low-alpha orange
     over near-black integrates to brown sludge across the whole right half
     rather than to light), and it is composited with screen, so it can only
     ever add luminance - a normal-blended translucent orange darkens the warm
     grey it sits on, which is exactly the dirty-smear look. The falloff is
     done by 64%, well clear of the text column. */
  .glow {
    position:absolute; inset:0; mix-blend-mode:screen;
    background:
      radial-gradient(44% 60% at ${v.glowX} 46%, rgba(240,97,42,.24), rgba(240,97,42,.075) 40%, transparent 68%),
      radial-gradient(70% 90% at 6% 4%, rgba(255,255,255,.045), transparent 52%);
  }
  /* Grain. feTurbulence at a high baseFrequency is film grain, not texture;
     .04 is the point where it kills gradient banding in a feed's JPEG
     re-encode without ever being visible as noise. */
  .grain {
    position:absolute; inset:0; opacity:.04; mix-blend-mode:overlay;
    background-image:url("data:image/svg+xml;utf8,\
<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160'>\
<filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.9' numOctaves='3'/></filter>\
<rect width='160' height='160' filter='url(%23n)'/></svg>");
  }

  /* 72px gutters. A feed can crop 1200x630 to 2:1, taking 15px off the top and
     bottom, so nothing lives closer than ~64px to a horizontal edge. */
  .inner {
    position:relative; height:100%;
    padding:64px 72px;
    display:flex; flex-direction:column; justify-content:space-between;
    width:625px;
  }

  .lockup { display:flex; align-items:center; gap:11px; }
  .lockup .mark { display:block; }
  .lockup .word {
    font-size:15px; font-weight:600; letter-spacing:.2em; color:${C.ink};
  }

  .lede {
    font-size:62px; font-weight:700; line-height:1.04; letter-spacing:-.02em;
    color:${C.ink}; max-width:520px; text-wrap:balance;
  }
  .lede--tagline { font-size:56px; letter-spacing:-.018em; }
  .sub {
    margin-top:20px; max-width:440px;
    font-size:19px; font-weight:500; line-height:1.45; color:${C.muted};
  }

  .readout { display:flex; align-items:center; gap:14px; }
  .spec {
    font-family:'Geist Mono', monospace; font-size:13.5px; font-weight:400;
    letter-spacing:.055em; text-transform:uppercase; color:${C.muted};
    white-space:nowrap;
  }
  .spec-sep {
    width:4px; height:4px; border-radius:50%; background:${C.accent};
    flex-shrink:0;
  }

  /* ------------------------------------------------------------------ art */
  .art { position:absolute; pointer-events:none; }

  /* Single knockout: anchored to the right gutter and optically centred on the
     glow, not on the panel - the glove's wrist is visually heavier than its
     fingertips, so geometric centring reads as sitting too low. */
  .art--glove {
    right:60px; top:50%; transform:translateY(-50%);
    height:492px; display:flex; align-items:center;
  }
  .art--glove img {
    height:492px; width:auto; display:block;
    filter:drop-shadow(0 26px 46px rgba(0,0,0,.55));
  }

  /* Pair: the Glove -> Skin spine, in that reading order. Both hands are open
     palms so the silhouettes rhyme. The glove is the larger of the two and
     comes first because it is the product that ships today (DESIGN.md: "Lead
     with the real, buyable glove"); the robot hand is the destination, so it
     sits smaller and further back.

     The robot hand is shown bare - the skin is molded per hand and there is no
     honest stock render of it, and DESIGN.md forbids faking product shots. So
     the caption says what the product IS ("Custom skin") rather than claiming
     the render shows one fitted.

     Equal-height figures bottom-aligned, rather than each absolutely placed:
     that is what puts the two captions on ONE baseline. Placing them by hand
     drifts the moment either knockout's aspect changes. */
  .art--pair {
    right:68px; top:50%; transform:translateY(-50%);
    display:flex; align-items:flex-end; gap:30px;
  }
  .fig {
    margin:0; height:434px;
    display:flex; flex-direction:column; align-items:center; justify-content:flex-end;
  }
  .fig img { width:auto; display:block; }
  .fig figcaption {
    margin-top:20px;
    font-family:'Geist Mono', monospace; font-size:11.5px; letter-spacing:.14em;
    text-transform:uppercase; color:${C.muted}; white-space:nowrap;
  }
  /* The robot hand's render ends at the wrist while the glove runs on into a
     cuff, so bottom-aligning the two boxes leaves its palm sitting low against
     the glove's. Lift it to put the two palms on roughly one line. */
  .fig--robo img {
    height:258px; margin-bottom:44px;
    filter:drop-shadow(0 18px 34px rgba(0,0,0,.5));
  }
  .fig--glove img {
    height:376px; filter:drop-shadow(0 24px 42px rgba(0,0,0,.55));
  }

  /* Hairline along the bottom edge, warming toward the product end. Gives the
     card a floor so the knockout does not look like it is falling out.
     1px and never fully opaque: at 3px with a solid accent stop this stops
     being a hairline and reads as a progress bar. */
  .floor {
    position:absolute; left:0; right:0; bottom:0; height:1px;
    background:linear-gradient(90deg,
      rgba(255,255,255,.10) 0%, rgba(240,97,42,.28) 58%, rgba(240,97,42,.52) 100%);
  }
</style></head>
<body>
  <div class="card">
    <div class="glow"></div>
    ${art}
    <div class="grain"></div>
    <div class="inner">
      <div class="lockup">${mark(30)}<span class="word">${COPY.wordmark}</span></div>
      <div>
        ${lede}
        <p class="sub">${COPY.sub}</p>
      </div>
      <div class="readout">${specs}</div>
    </div>
    <div class="floor"></div>
  </div>
</body></html>`;
}

/**
 * Alpha-crops every [data-src] image to its visible bounds, in-page.
 *
 * The knockouts carry transparent padding that differs per asset (pose-skin is
 * ~55% empty on its left; frame-005 has a few stray 1px dust specks hard
 * against the right edge). Cropping by hand-measured pixel offsets means a
 * re-shot glove silently reframes the card, and a getBBox()-style scan is
 * defeated by the dust. So: threshold alpha, then keep only rows/columns
 * holding more than `MIN_RUN` of the opposite axis - dust drops out, the
 * product does not.
 */
async function cropImages(page) {
  await page.evaluate(async () => {
    const ALPHA = 128;
    const MIN_RUN = 0.004; /* fraction of the axis; 4 rows in a 1000px image */

    const load = (src) =>
      new Promise((res, rej) => {
        const i = new Image();
        i.onload = () => res(i);
        i.onerror = () => rej(new Error("load failed: " + src));
        i.src = src;
      });

    for (const el of document.querySelectorAll("img[data-src]")) {
      const img = await load(el.dataset.src);
      const c = document.createElement("canvas");
      c.width = img.naturalWidth;
      c.height = img.naturalHeight;
      const g = c.getContext("2d", { willReadFrequently: true });
      g.drawImage(img, 0, 0);
      const { data } = g.getImageData(0, 0, c.width, c.height);

      const cols = new Uint32Array(c.width);
      const rows = new Uint32Array(c.height);
      for (let y = 0; y < c.height; y++) {
        for (let x = 0; x < c.width; x++) {
          if (data[(y * c.width + x) * 4 + 3] > ALPHA) {
            cols[x]++;
            rows[y]++;
          }
        }
      }
      const span = (arr, other) => {
        const min = Math.max(1, Math.floor(other * MIN_RUN));
        let a = 0;
        let b = arr.length - 1;
        while (a < arr.length && arr[a] <= min) a++;
        while (b > a && arr[b] <= min) b--;
        return [a, b];
      };
      const [x0, x1] = span(cols, c.height);
      const [y0, y1] = span(rows, c.width);

      const out = document.createElement("canvas");
      out.width = x1 - x0 + 1;
      out.height = y1 - y0 + 1;
      out
        .getContext("2d")
        .drawImage(img, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
      el.src = out.toDataURL("image/png");
      el.removeAttribute("data-src");
    }
  });
}

async function render(browser, variant, outDir) {
  const page = await browser.newPage({
    viewport: { width: W, height: H },
    deviceScaleFactor: SS,
  });
  /* Must be a real file:// document, not setContent(): an about:blank page
     cannot fetch file:// subresources, so the fonts and knockouts silently
     never arrive. The scratch file lives inside public/ so every file:// URL
     in the markup shares its directory origin, which is also what makes the
     canvas readable in cropImages() (with --allow-file-access-from-files). */
  const scratch = path.join(PUBLIC, `.og-scratch-${variant}.html`);
  await fs.writeFile(scratch, html(variant));
  try {
    await page.goto("file://" + scratch, { waitUntil: "load" });
  } finally {
    await fs.rm(scratch, { force: true });
  }
  await page.evaluate(() => document.fonts.ready);
  await cropImages(page);
  await page.evaluate(
    () =>
      new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );

  const big = await page.screenshot({ type: "png" });
  await page.close();

  /* Box-filter ${SS}x -> 1x in a throwaway page. Chromium's high-quality
     canvas resample beats shipping the aliased 1x shot, and keeps the whole
     pipeline inside the browser (no Pillow / sharp / sips dependency). */
  const shrink = await browser.newPage({
    viewport: { width: W, height: H },
    deviceScaleFactor: 1,
  });
  const dataUrl = "data:image/png;base64," + big.toString("base64");
  const b64 = await shrink.evaluate(
    async ({ url, w, h }) => {
      const img = new Image();
      await new Promise((res, rej) => {
        img.onload = res;
        img.onerror = rej;
        img.src = url;
      });
      const c = document.createElement("canvas");
      c.width = w;
      c.height = h;
      const g = c.getContext("2d");
      g.imageSmoothingEnabled = true;
      g.imageSmoothingQuality = "high";
      g.drawImage(img, 0, 0, w, h);
      return c.toDataURL("image/png").split(",")[1];
    },
    { url: dataUrl, w: W, h: H },
  );
  await shrink.close();

  const buf = Buffer.from(b64, "base64");
  const file = path.join(outDir, `og-${variant}.png`);
  await fs.writeFile(file, buf);
  console.log(
    `  ${variant.padEnd(8)} -> ${file}  (${(buf.length / 1024).toFixed(0)} KB)`,
  );
  return file;
}

/* --------------------------------------------------------------------- go */
const argv = process.argv.slice(2);
const arg = (n) => argv.find((a) => a.startsWith(`--${n}=`))?.split("=")[1];
const wanted = arg("variant");
const installFlag = argv.find((a) => a === "--install" || a.startsWith("--install="));
const installName = arg("install") ?? "og-image-v3.png";
const outDir = arg("out") ?? "/tmp/og-out";

if (wanted && !VARIANTS[wanted]) {
  console.error(
    `unknown variant "${wanted}" - pick one of: ${Object.keys(VARIANTS).join(", ")}`,
  );
  process.exit(1);
}
if (installFlag && !wanted) {
  console.error("--install needs --variant=<name> so it is unambiguous");
  process.exit(1);
}

await fs.mkdir(outDir, { recursive: true });
/* Sweep scratch files a hard kill (Ctrl-C mid-render) left behind. They live in
   public/, so vite would otherwise copy one straight into dist/. */
for (const f of await fs.readdir(PUBLIC)) {
  if (f.startsWith(".og-scratch-")) await fs.rm(path.join(PUBLIC, f));
}
const browser = await chromium.launch({
  /* cropImages() reads pixels back out of a canvas the knockouts were drawn
     into; without this Chromium treats each file:// image as its own opaque
     origin and taints the canvas, so getImageData throws. */
  args: ["--allow-file-access-from-files"],
});
console.log(`rendering ${W}x${H} @${SS}x ->`);
const built = {};
for (const name of wanted ? [wanted] : Object.keys(VARIANTS)) {
  built[name] = await render(browser, name, outDir);
}
await browser.close();

if (installFlag) {
  const dest = path.join(PUBLIC, installName);
  /* COPYFILE_EXCL: refuse to clobber. If the destination already exists the
     card has shipped under that URL and the caches are warm, so the right move
     is a new filename, not a silent overwrite. */
  await fs.copyFile(built[wanted], dest, fsc.COPYFILE_EXCL).catch((e) => {
    if (e.code !== "EEXIST") throw e;
    console.error(
      `\n${installName} already exists. Social caches key on the URL, so ` +
        `overwriting it would not reach anyone who has already unfurled the ` +
        `link.\nPick a new name: --install=og-image-v4.png (and update the ` +
        `og:image / twitter:image tags in index.html).`,
    );
    process.exit(1);
  });
  console.log(`installed ${wanted} -> ${path.relative(FRONTEND, dest)}`);
  console.log("now point og:image + twitter:image in index.html at this file");
}
