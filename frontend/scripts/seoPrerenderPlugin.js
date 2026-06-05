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
  <h1>6thSense — tactile egocentric datasets for dexterous robotics</h1>
  <p>${esc(heroCopy.deck)}</p>
  <p>${esc(heroCopy.tagline)}</p>
  <section><h2>Why touch-aware demonstration data</h2>${problem}</section>
  <section><h2>How we build datasets</h2><p>${esc(platformSummary)}</p><ol>${stages}</ol></section>
  <section><h2>${esc(catalogMeta.title)}</h2>${catalog}</section>
  <section><h2>Representative task families</h2><ul>${scenes}</ul></section>
  <section><h2>How we earn trust</h2>${principles}</section>
</div>`;
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
  };
}
