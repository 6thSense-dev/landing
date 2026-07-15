/**
 * Build-time SEO prerender.
 *
 * This site is a client-rendered SPA: the served HTML body is an empty
 * `<div id="root">`, so crawlers that don't execute JS (Bing, DuckDuckGo,
 * most social + AI bots, and Google's first indexing pass) see no content.
 *
 * This Vite plugin injects a semantic, crawlable summary of the homepage —
 * built from the SAME `homeNarrative.js` copy the UI renders, so it stays a
 * single source of truth — into the static HTML at build time. The block is
 * visually-hidden (see the inline style in index.html) and removed the instant
 * JS boots (see main.jsx), so JS users and screen readers never see duplicate
 * content. No headless browser / Chromium needed — works in the Alpine build.
 */
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import {
  heroCopy,
  tractionItems,
  platformStages,
  platformSummary,
  dataCatalogTiles,
  catalogSceneExamples,
  catalogMeta,
  credibilityPrinciples,
} from "../src/homeNarrative.js";
import { productPages } from "../src/seo/pages.js";

const ORIGIN = "https://6thsense.dev";

const esc = (s) =>
  String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

function buildSeoHtml() {
  const problem = tractionItems
    .map((i) => `<article><h3>${esc(i.title)}</h3><p>${esc(i.detail)}</p></article>`)
    .join("");
  const stages = platformStages
    .map((s) => `<li><strong>${esc(s.label)}</strong> — ${esc(s.caption)}</li>`)
    .join("");
  const catalog = dataCatalogTiles
    .map((t) => `<article><h3>${esc(t.title)}</h3><p>${esc(t.spec)}</p></article>`)
    .join("");
  const scenes = catalogSceneExamples.map((s) => `<li>${esc(s)}</li>`).join("");
  const principles = credibilityPrinciples
    .map((p) => `<article><h3>${esc(p.title)}</h3><p>${esc(p.body)}</p></article>`)
    .join("");

  return `<div id="seo-prerender" class="seo-prerender">
  <h1>6thSense — tactile capture hardware for dexterous robotics</h1>
  <p>${esc(heroCopy.deck)}</p>
  <p>${esc(heroCopy.tagline)}</p>
  <section><h2>Why tactile capture hardware</h2>${problem}</section>
  <section><h2>How the capture stack works</h2><p>${esc(platformSummary)}</p><ol>${stages}</ol></section>
  <section><h2>${esc(catalogMeta.title)}</h2>${catalog}</section>
  <section><h2>Representative task families</h2><ul>${scenes}</ul></section>
  <section><h2>How we earn trust</h2>${principles}</section>
</div>`;
}

/**
 * Crawlable content block for a secondary page (from src/seo/pages.js).
 * Same `#seo-prerender` id + class as the homepage block, so main.jsx strips it
 * on boot and the visually-hidden style applies.
 */
function buildPageSeoHtml(page) {
  const sections = page.sections
    .map((s) => {
      const body = s.body ? `<p>${esc(s.body)}</p>` : "";
      const items = s.items
        ? `<ul>${s.items.map((li) => `<li>${esc(li)}</li>`).join("")}</ul>`
        : "";
      return `<section><h2>${esc(s.h2)}</h2>${body}${items}</section>`;
    })
    .join("");
  const cards = page.cards
    ? `<section><h2>Explore the stack</h2>${page.cards
        .map(
          (c) =>
            `<article><h3><a href="${c.href}">${esc(c.title)}</a></h3><p>${esc(c.blurb)}</p></article>`
        )
        .join("")}</section>`
    : "";
  const related = page.related
    ? `<nav>${page.related
        .map((r) => `<a href="${r.href}">${esc(r.label)}</a>`)
        .join(" ")}</nav>`
    : "";

  return `<div id="seo-prerender" class="seo-prerender">
  <h1>${esc(page.h1)}</h1>
  <p>${esc(page.intro)}</p>
  ${sections}${cards}${related}
</div>`;
}

/** Swap a `content="..."` attribute on a tag matched by an attr=value pair. */
function setMetaContent(html, attr, value, target) {
  const re = new RegExp(
    `(<meta\\s+${attr}="${target}"\\s+content=")[^"]*(")`,
    "s"
  );
  return html.replace(re, (_m, a, b) => a + esc(value) + b);
}

/**
 * Derive a full static HTML document for a secondary route from the built
 * homepage `index.html` (which already carries the hashed asset tags), swapping
 * in route-specific title/description/canonical/OG/Twitter + crawlable block.
 */
function renderPageHtml(baseHtml, page) {
  const url = `${ORIGIN}${page.path}`;
  let html = baseHtml;
  html = html.replace(/<title>[\s\S]*?<\/title>/, `<title>${esc(page.title)}</title>`);
  html = setMetaContent(html, "name", page.description, "description");
  html = html.replace(
    /(<link\s+rel="canonical"\s+href=")[^"]*(")/,
    (_m, a, b) => a + url + b
  );
  html = setMetaContent(html, "property", url, "og:url");
  html = setMetaContent(html, "property", page.title, "og:title");
  html = setMetaContent(html, "property", page.description, "og:description");
  html = setMetaContent(html, "name", page.title, "twitter:title");
  html = setMetaContent(html, "name", page.description, "twitter:description");
  // Replace the homepage crawl block (no nested <div>, so the first </div> closes it).
  html = html.replace(
    /<div id="seo-prerender"[\s\S]*?<\/div>/,
    buildPageSeoHtml(page)
  );
  return html;
}

export function seoPrerenderPlugin() {
  return {
    name: "seo-prerender",
    transformIndexHtml(html) {
      const block = buildSeoHtml();
      // Inject as a sibling right after #root; main.jsx removes it on boot.
      return html.replace(
        '<div id="root"></div>',
        `<div id="root"></div>\n    ${block}`
      );
    },
    // After the bundle is written, emit dist/<path>/index.html for each secondary
    // page so JS-less crawlers get real, route-specific content. Caddy serves the
    // folder index for the pretty URL; the SPA fallback still hydrates client nav.
    writeBundle(options) {
      const outDir = options.dir || "dist";
      const baseHtml = readFileSync(join(outDir, "index.html"), "utf8");
      for (const page of productPages) {
        const rel = page.path.replace(/^\/+/, "");
        const dir = join(outDir, rel);
        mkdirSync(dir, { recursive: true });
        writeFileSync(join(dir, "index.html"), renderPageHtml(baseHtml, page), "utf8");
      }
    },
  };
}
