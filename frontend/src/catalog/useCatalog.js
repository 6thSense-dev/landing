/**
 * useCatalog.js — the catalog's only data layer.
 *
 * Two documents exist: the collection manifest and one detail record per clip.
 * Both come from the portal API, which is the ONLY thing that knows where the
 * bytes really live:
 *
 *   GET /api/catalog             -> the whole manifest
 *   GET /api/catalog/clips/{id}  -> one full clip record
 *
 * The API resolves the caller's role, drops everything that role may not see,
 * and rewrites every surviving asset URL to an **absolute, short-lived
 * presigned S3 URL**. Bytes go S3 -> browser directly; they never pass through
 * the API. Two consequences run through this whole file:
 *
 *  1. `assetUrl()` no longer prefixes anything. It is a passthrough — but it
 *     stays the single choke point, because "where does a URL come from" is
 *     exactly the kind of thing that grows a second implementation in a corner
 *     of a tab component if you let it.
 *
 *  2. **URLs expire** (CATALOG_PRESIGN_TTL, 900 s by default). A buyer who
 *     leaves the tab open through a meeting must not come back to a dead
 *     video. So every document carries a `staleAt`, the hooks silently refetch
 *     before that moment, and any asset that fails with an S3 expiry status
 *     (or an <img>/<video> that errors) triggers one refetch-and-retry.
 *
 * Session, CSRF and error shape all come from the portal's own `portalFetch`,
 * so the catalog behaves like every other authenticated page on the site.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { portalFetch } from "../portal/portalFetch.js";

/* ------------------------------------------------------------------ */
/* Contract with the API                                               */
/* ------------------------------------------------------------------ */

/** Manifest endpoint. Mirrors the router prefix in app/api/routes/catalog.py. */
export const CATALOG_PATH = "/api/catalog";

/** One clip record. `id` is [a-z0-9-] per the schema; encoded anyway. */
export function clipPath(id) {
  return `${CATALOG_PATH}/clips/${encodeURIComponent(id)}`;
}

/** Schema families this UI understands, and the single major version of each. */
const CATALOG_FAMILY = "6s-catalog";
const CLIP_FAMILY = "6s-clip";
const SUPPORTED_MAJOR = "1";

/**
 * Fallback presign lifetime, in seconds, used only when a document does not
 * declare its own. Mirrors CATALOG_PRESIGN_TTL on the API; set
 * VITE_CATALOG_PRESIGN_TTL at build time if the server default ever moves.
 */
const DEFAULT_PRESIGN_TTL_S = Number(import.meta.env.VITE_CATALOG_PRESIGN_TTL) || 900;

/**
 * Refresh this long before the URLs actually die. Big enough to cover a slow
 * refetch plus a video element re-opening its connection; small enough that a
 * 900 s TTL still yields one refresh per view, not a poll.
 */
const REFRESH_MARGIN_MS = 90_000;

/** Never arm a refresh timer tighter than this, whatever the TTL claims. */
const MIN_REFRESH_INTERVAL_MS = 20_000;

/** Backoff after a silent refresh fails. The stale document stays on screen. */
const REFRESH_RETRY_MS = 30_000;

/** Hard floor between two asset-failure-triggered refreshes. */
const EXPIRY_RETRY_COOLDOWN_MS = 10_000;

/** How many clip records to keep. ~30 clips ship, so this holds the corpus. */
const CLIP_CACHE_MAX = 40;

/** S3 answers an expired or malformed signature with one of these. */
const EXPIRED_STATUSES = new Set([400, 401, 403]);

/* ------------------------------------------------------------------ */
/* URL resolution                                                      */
/* ------------------------------------------------------------------ */

/**
 * Base for the defensive case below. `portalFetch` prepends the same value to
 * its paths, so a relative asset resolves to the same origin the JSON came
 * from.
 */
const API_BASE = import.meta.env.VITE_API_URL ?? "";

/**
 * Resolve an asset reference to something fetchable.
 *
 * - `null` / non-string / empty -> `null`. A null asset means "this does not
 *   exist", and it must stay null so callers draw a placeholder instead of
 *   requesting a directory and rendering a broken image.
 * - An absolute URL — which, post-rewrite, is every real asset — passes
 *   through **untouched**. Presigned S3 URLs carry their credentials in the
 *   query string; prefixing one destroys the signature.
 * - Anything still relative is a bug on the API side (it should have been
 *   rewritten). Rather than let the browser resolve it against
 *   `/portal/catalog` and quietly fetch the SPA's index.html, we resolve it
 *   against the API's catalog root, which is the only base it could ever have
 *   meant. Wrong-but-loud beats wrong-but-silent.
 *
 * @param {string|null|undefined} url
 * @returns {string|null}
 */
export function assetUrl(url) {
  if (typeof url !== "string") return null;
  const s = url.trim();
  if (s === "") return null;
  // Scheme-qualified (https:, data:, blob:) or protocol-relative: already absolute.
  if (/^[a-z][a-z0-9+.-]*:/i.test(s) || s.startsWith("//")) return s;
  const base = `${API_BASE}${CATALOG_PATH}`.replace(/\/+$/, "");
  return `${base}/${s.replace(/^\/+/, "")}`;
}

/**
 * Expand a `collection.paths` template by verbatim substitution.
 *
 * Legacy path. The API materialises `poster` and `preview` on every clip
 * summary because a presigned URL cannot be produced by string substitution —
 * but the templates are still honoured if a manifest carries them, and the
 * result goes through assetUrl() like anything else.
 */
export function expandTemplate(template, clip) {
  if (typeof template !== "string" || template === "" || !clip) return null;
  let missing = false;
  const out = template.replace(/\{(id|slug)\}/g, (_, key) => {
    const value = clip[key];
    if (typeof value !== "string" || value === "") {
      missing = true;
      return "";
    }
    return value;
  });
  return missing ? null : out;
}

/**
 * Resolve one of a clip's three templated assets to its raw manifest value.
 *
 * The presence rule from the contract, implemented literally:
 *   key ABSENT            -> expand collection.paths[kind]
 *   key present and null  -> the asset does not exist; return null
 *   key present, a string -> use it
 *
 * @param {object} clip        a ClipSummary or a full clip record
 * @param {"poster"|"preview"|"detail"} kind
 * @param {object} [collection] catalog.collection, for the templates
 * @returns {string|null}
 */
export function clipAssetPath(clip, kind, collection) {
  if (!clip) return null;
  if (Object.prototype.hasOwnProperty.call(clip, kind)) {
    const own = clip[kind];
    return typeof own === "string" && own.trim() !== "" ? own : null;
  }
  const template = collection && collection.paths ? collection.paths[kind] : null;
  return expandTemplate(template, clip);
}

/** The same three assets, resolved to a fetchable URL. */
export function clipAssetUrl(clip, kind, collection) {
  return assetUrl(clipAssetPath(clip, kind, collection));
}

/** Find a clip summary in the manifest by id. Returns null when absent. */
export function findClip(catalog, id) {
  if (!catalog || !Array.isArray(catalog.clips) || !id) return null;
  return catalog.clips.find((c) => c && c.id === id) || null;
}

/* ------------------------------------------------------------------ */
/* Summary -> record projection                                        */
/* ------------------------------------------------------------------ */

/**
 * Project a ClipSummary into the shape of a full clip record.
 *
 * Used for a clip whose `detail` is explicitly null: there is no record to
 * fetch, but the modal still has to render something, and the summary is real
 * data we already hold. Every detail-only field is set to its honest "nothing
 * here" value — which is what makes the tabs disable themselves, because
 * `imu_preview: null`, `tactile_preview: null` and `segments: []` are exactly
 * the signals the UI already reads.
 *
 * The alternative — returning a bare null clip — pushes a three-way state
 * (loading / absent / loaded) onto every consumer, and the first one to read it
 * as two-way renders a spinner that never stops.
 */
const PROJECTIONS = new WeakSet();

/**
 * True when `clip` came from summaryAsClip rather than from a fetched detail
 * record. Tracked in a WeakSet rather than as a property so the object stays
 * exactly the shape the clip schema describes.
 */
export function isSummaryProjection(clip) {
  return clip != null && PROJECTIONS.has(clip);
}

export function summaryAsClip(summary, collection) {
  if (!summary) return null;
  const projected = {
    schema: "6s-clip/1.0",
    id: summary.id,
    slug: summary.slug,
    split: summary.split ?? null,
    title: summary.title,
    description_short: summary.description_short ?? null,
    description: null,
    category: summary.category,
    subcategory: summary.subcategory ?? null,
    country: summary.country ?? null,
    recorded_month: summary.recorded_month ?? null,
    capture: summary.capture,
    duration_s: summary.duration_s,
    resolution: summary.resolution ?? null,
    fps: summary.fps ?? null,
    modalities: Array.isArray(summary.modalities) ? summary.modalities : [],
    hands: Array.isArray(summary.hands) ? summary.hands : [],
    subjects: summary.subjects ?? null,
    bytes: summary.bytes ?? null,
    // Already-resolved URLs, exactly as a real record would carry them.
    poster: clipAssetPath(summary, "poster", collection),
    preview: clipAssetPath(summary, "preview", collection),
    detail: null,

    // The summary's rights and privacy are byte-identical subsets of the
    // record's. The keys only the record carries are unknown, not false.
    rights: {
      ...(summary.rights || {}),
      license_id: null,
      license_name: null,
      license_url: null,
      restrictions: [],
      attribution_required: null,
      holder: null,
      determined_utc: null,
    },
    privacy: {
      ...(summary.privacy || {}),
      notice_given: null,
      identifiable_persons: null,
      identifiable_premises: null,
      redaction: null,
      retention: null,
      consent: null,
      // Not asserted: we will not claim a legal position we cannot evidence.
      reidentification_prohibited: null,
    },
    qa: {
      ...(summary.qa || {}),
      // The one detail-only QA field that IS derivable: a clip only reaches
      // the catalog if it was accepted.
      disposition: "accepted",
      video_frames_delivered: null,
      video_timestamps: null,
      frame_count_matches_timestamps: null,
      checksums_verified: null,
      checks: [],
    },

    // Detail-only payloads. Null/empty here is what disables the tabs.
    media: {
      video: null,
      imu: null,
      tactile: null,
      segcap: null,
      calibration: null,
      docs: null,
      archive: null,
    },
    imu_preview: null,
    tactile_preview: null,
    segments: [],
    package_contents: [],
    sync: null,
    calibration: null,
    provenance: {
      take_id: null,
      device_id: null,
      firmware: null,
      operator: null,
      recorded_local: null,
      packaged_utc: null,
      pipeline_version: null,
    },
    metadata: null,
    known_limitations: [
      "This clip ships no detail record. What is shown is the catalog summary only: " +
        "media locations, IMU and tactile previews, segments, synchronisation, calibration " +
        "and the package file list are all unavailable for it.",
    ],
  };
  PROJECTIONS.add(projected);
  return projected;
}

/* ------------------------------------------------------------------ */
/* Fetching                                                            */
/* ------------------------------------------------------------------ */

/** An API failure carrying the HTTP status, so callers can branch on 401/403. */
export class CatalogError extends Error {
  constructor(message, status) {
    super(message);
    this.name = "CatalogError";
    this.status = status;
  }
}

function abortError() {
  const err = new Error("aborted");
  err.name = "AbortError";
  return err;
}

/** Pull a human-readable reason out of whatever error shape the API returned. */
function detailOf(data) {
  if (!data || typeof data !== "object") return "";
  for (const key of ["error", "message", "detail"]) {
    const v = data[key];
    if (typeof v === "string" && v.trim() !== "") return ` — ${v.trim()}`;
  }
  return "";
}

/**
 * GET a catalog document through the portal's fetch wrapper.
 *
 * portalFetch swallows network errors into `{ok:false, status:0}` and never
 * throws, including on abort — so the abort has to be re-detected here, or an
 * aborted request would surface as "could not reach the API".
 */
async function apiGet(path, signal) {
  const { ok, status, data } = await portalFetch(path, signal ? { signal } : {});
  if (signal && signal.aborted) throw abortError();
  if (ok) return data;
  if (status === 0) {
    throw new CatalogError("Couldn't reach the server. Check your connection and try again.", 0);
  }
  if (status === 401) {
    throw new CatalogError("Your session has expired. Sign in again to view the catalog.", 401);
  }
  if (status === 403) {
    throw new CatalogError("This account is not permitted to view the catalog.", 403);
  }
  if (status === 404) {
    throw new CatalogError(`Not found: ${path}${detailOf(data)}`, 404);
  }
  throw new CatalogError(`HTTP ${status} fetching ${path}${detailOf(data)}`, status);
}

/**
 * Fetch a presigned S3 asset.
 *
 * `credentials: "omit"` is not incidental: the URL is already authenticated by
 * its signature, and sending the sid cookie cross-origin to S3 would turn a
 * simple CORS GET into a credentialed one that the bucket policy rejects.
 *
 * An expired signature comes back as 400/401/403; that schedules exactly one
 * refetch of the owning document, after which the component re-renders with a
 * fresh URL and its effect re-runs. The retry is therefore the ordinary render
 * path, not a second code path that could drift from it.
 */
export async function fetchAsset(url, init = {}) {
  const res = await fetch(url, { credentials: "omit", ...init });
  if (!res.ok && EXPIRED_STATUSES.has(res.status)) notifyAssetExpired(url);
  return res;
}

/**
 * Refuse an unknown major version before anything tries to render it.
 * A minor bump is additive and safe; a major bump removes or retypes a field.
 */
function assertSchema(doc, family, what) {
  const tag = doc && typeof doc.schema === "string" ? doc.schema : null;
  if (!tag) {
    throw new CatalogError(
      `${what} has no \`schema\` field; refusing to render an unidentified document.`,
      200,
    );
  }
  const slash = tag.indexOf("/");
  const gotFamily = slash === -1 ? tag : tag.slice(0, slash);
  const gotMajor = slash === -1 ? "" : tag.slice(slash + 1).split(".")[0];
  if (gotFamily !== family || gotMajor !== SUPPORTED_MAJOR) {
    throw new CatalogError(
      `${what} is \`${tag}\`; this catalog UI understands ${family}/${SUPPORTED_MAJOR}.x only.`,
      200,
    );
  }
}

/* ------------------------------------------------------------------ */
/* Presign expiry                                                      */
/* ------------------------------------------------------------------ */

function positiveNumber(v) {
  const n = typeof v === "string" ? Number(v) : v;
  return typeof n === "number" && Number.isFinite(n) && n > 0 ? n : null;
}

/**
 * When do this document's presigned URLs stop working?
 *
 * **The API declares it as a top-level `expires_at`** (an ISO-8601 string), set
 * from CATALOG_PRESIGN_TTL by catalog_redact.present_manifest/present_clip. That
 * field is read FIRST and is the answer in production.
 *
 * The `presign.*` and `media_expires_at` forms below are tolerated shapes, not
 * the contract — they cost nothing and mean a server that moves the field does
 * not silently fall back. The build-time constant is the last resort only: it is
 * a guess that is right exactly as long as two independently-set values agree,
 * and the whole point of the server declaring an expiry is not having to rely on
 * that. `presignExpiry.source` on the returned entry records which one answered,
 * so a drift is observable instead of invisible.
 */
function presignExpiry(doc, receivedAt) {
  const p = (doc && typeof doc.presign === "object" && doc.presign) || {};
  // The field the API actually sends, first.
  const at = doc?.expires_at ?? p.expires_at ?? p.expiresAt ?? doc?.media_expires_at;
  if (typeof at === "string") {
    const ms = Date.parse(at);
    if (Number.isFinite(ms)) return { at: ms, source: "server" };
  }
  const ttl =
    positiveNumber(p.expires_in) ??
    positiveNumber(p.ttl_s) ??
    positiveNumber(p.ttl_seconds);
  if (ttl != null) return { at: receivedAt + ttl * 1000, source: "server" };
  return { at: receivedAt + DEFAULT_PRESIGN_TTL_S * 1000, source: "default" };
}

/** Wrap a freshly fetched document with the two timestamps the hooks need. */
function entryFor(doc) {
  const receivedAt = Date.now();
  const { at: expiresAt, source: expirySource } = presignExpiry(doc, receivedAt);
  const staleAt = Math.max(receivedAt + MIN_REFRESH_INTERVAL_MS, expiresAt - REFRESH_MARGIN_MS);
  return { doc, receivedAt, expiresAt, staleAt, expirySource };
}

/* ------------------------------------------------------------------ */
/* Module-level cache                                                  */
/* ------------------------------------------------------------------ */

/**
 * Whose documents are in the cache below.
 *
 * Redaction is applied SERVER-SIDE, per request, from the caller's role — so a
 * cached response is a document for one identity and no other. The cache is
 * module-level and outlives a React tree, which means log out as `founder` and
 * back in as `guest` in the same tab and the guest would otherwise be handed the
 * founder's manifest, presigned `sample_archive.url` and all, for the rest of the
 * TTL. That is the redaction boundary being crossed by client state.
 *
 * So the cache is KEYED on identity: `bindCatalogIdentity()` is called with the
 * current session's `id:role` on every render of the page that owns the data, and
 * a mismatch empties the cache synchronously, before any hook reads it. Not just
 * cleared on logout — a login can switch identity without a logout, and a cleared
 * cache reloads while a wrongly-keyed one does not announce itself at all.
 *
 * `null` means "nothing cached yet".
 */
let cacheIdentity = null;

/** The manifest, once it has arrived. Replaced only on a successful refetch. */
let manifestEntry = null;
/** The in-flight manifest fetch, so N consumers share one request. */
let manifestPromise = null;

/**
 * id -> entry. A Map is insertion-ordered, so re-inserting on read turns it
 * into an LRU and the oldest key is always `keys().next()`. Bounded because a
 * long browsing session must not accumulate every record plus its URLs.
 */
const clipCache = new Map();

function cacheRead(id) {
  if (!clipCache.has(id)) return null;
  const entry = clipCache.get(id);
  clipCache.delete(id);
  clipCache.set(id, entry);
  return entry;
}

function cacheWrite(id, entry) {
  if (clipCache.has(id)) clipCache.delete(id);
  clipCache.set(id, entry);
  while (clipCache.size > CLIP_CACHE_MAX) {
    const oldest = clipCache.keys().next();
    if (oldest.done) break;
    clipCache.delete(oldest.value);
  }
}

/* ---- change notification -------------------------------------------- */

const listeners = new Set();

function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  for (const fn of Array.from(listeners)) {
    try {
      fn();
    } catch {
      /* one bad subscriber must not stop the rest */
    }
  }
}

/* ---- manifest ------------------------------------------------------- */

/** The in-flight background refresh, so N stale consumers share one request. */
let refreshPromise = null;

/**
 * URLs already retried once after an asset error. Declared here rather than next
 * to notifyAssetExpired() because clearCatalogCache() empties it: a URL that is
 * being discarded along with its document must be retryable again if it comes
 * back with a fresh signature.
 */
const retriedUrls = new Set();

/**
 * Fetch (or reuse) the manifest. Shared across every hook instance.
 *
 * Deliberately not abortable: the promise is shared, so one unmounting consumer
 * must not cancel the fetch the rest of the page is waiting on.
 */
export function ensureCatalog() {
  if (manifestEntry) return Promise.resolve(manifestEntry.doc);
  if (!manifestPromise) {
    // Whose request this is. If the identity changes while it is in flight the
    // response is one role's redaction of the document and must not be written
    // into a cache that now belongs to another; the identity switch already
    // cleared `manifestPromise`, so a fresh fetch is on its way.
    const owner = cacheIdentity;
    manifestPromise = apiGet(CATALOG_PATH)
      .then((doc) => {
        assertSchema(doc, CATALOG_FAMILY, "the catalog manifest");
        if (owner !== cacheIdentity) return doc;
        manifestEntry = entryFor(doc);
        return doc;
      })
      .catch((err) => {
        // Drop the rejected promise so a retry re-fetches instead of
        // re-serving the failure forever.
        manifestPromise = null;
        throw err;
      });
  }
  return manifestPromise;
}

/**
 * Refetch the manifest in the background, keeping the current one on screen
 * until the new one lands. Every clip record's URLs were minted in the same
 * window, so they are marked stale at the same time — each open record then
 * refreshes itself through its own hook rather than being dropped, which is
 * what keeps the modal from flashing back to a spinner.
 */
export function refreshCatalog() {
  if (refreshPromise) return refreshPromise;
  const owner = cacheIdentity;
  refreshPromise = apiGet(CATALOG_PATH)
    .then((doc) => {
      assertSchema(doc, CATALOG_FAMILY, "the catalog manifest");
      if (owner !== cacheIdentity) return doc;  // see ensureCatalog()
      manifestEntry = entryFor(doc);
      manifestPromise = Promise.resolve(doc);
      notify();
      return doc;
    })
    .finally(() => {
      refreshPromise = null;
    });
  return refreshPromise;
}

/**
 * Display label for one facet value, from the manifest's own `facets`.
 *
 * Synchronous and cache-only: it answers from the manifest already in memory
 * and never fetches. Anything that can render a facet value has, by definition,
 * already got the manifest -- the grid could not have drawn the card, and the
 * modal could not have found the clip, without it.
 *
 * WHY THIS EXISTS. `facets[].label` is required by catalog.schema.json and the
 * ingest now refuses to build a bundle whose country has no display name, all so
 * the UI carries no code table of its own that could drift out of step with the
 * filter bar. The clip DETAIL record carries only `country: "CN"`, so without
 * this the modal was the one surface in the product printing an alpha-2 code at a
 * buyer while the card two clicks away said "China".
 *
 * Returns the raw value when the manifest has no bucket for it -- an unmapped
 * code renders as itself, which makes a corpus that has drifted outside its
 * declared scope VISIBLE rather than quietly plausible.
 */
export function facetLabel(facet, value) {
  if (typeof value !== "string" || value === "") return value;
  const doc = manifestEntry ? manifestEntry.doc : null;
  const list = doc && doc.facets ? doc.facets[facet] : null;
  if (!Array.isArray(list)) return value;
  for (const b of list) {
    if (b && b.value === value && typeof b.label === "string" && b.label !== "") return b.label;
  }
  return value;
}

/** Drop every cache. Used by the error state's retry button. */
export function clearCatalogCache() {
  manifestEntry = null;
  manifestPromise = null;
  refreshPromise = null;
  clipCache.clear();
  retriedUrls.clear();
  notify();
}

/**
 * Bind the module cache to one identity, dropping it if the identity changed.
 *
 * NOT a hook, despite being called from a render body: it holds no React state
 * and is safe to call from anywhere, including the module-scope listener below.
 * It runs during render precisely because it must land before any hook reads the
 * cache — an effect would fire after this component had already rendered the
 * previous role's document once, which is exactly one render too late.
 *
 * @param {string|null} identity  `${user.id}:${user.role}`, or null when signed out.
 * @returns {boolean} true when a cache belonging to someone else was dropped.
 */
export function bindCatalogIdentity(identity) {
  const next = identity == null ? null : String(identity);
  if (next === cacheIdentity) return false;
  const hadOther = cacheIdentity !== null && (manifestEntry !== null || clipCache.size > 0);
  cacheIdentity = next;
  if (hadOther || manifestEntry !== null || clipCache.size > 0) {
    manifestEntry = null;
    manifestPromise = null;
    refreshPromise = null;
    clipCache.clear();
    retriedUrls.clear();
  }
  return hadOther;
}

/** The identity the cache currently belongs to. Exported for tests and the e2e. */
export function catalogCacheIdentity() {
  return cacheIdentity;
}

/*
 * Defence in depth for the identity keying above. `useSession` fires this on
 * every login and logout; this module only exists in the page's memory once the
 * lazy catalog chunk has loaded, which is exactly when there is a cache to drop.
 * Registered at module scope so it is live from the first import, not from the
 * first render.
 */
if (typeof window !== "undefined") {
  window.addEventListener("6s-portal:session-changed", (event) => {
    bindCatalogIdentity(event && "detail" in event ? event.detail : null);
  });
}

/* ---- expiry recovery ------------------------------------------------ */

let lastExpiryRefreshAt = 0;

/**
 * Report that an asset would not load, most likely because its presigned URL
 * expired.
 *
 * <img> and <video> report `error` with no status, so this cannot distinguish
 * an expired signature from a genuinely missing object. It does not need to:
 * the response is bounded to one refetch per URL and one refetch per cooldown
 * window overall, so a permanently broken file costs a single extra request
 * and then nothing. Marking the documents stale (rather than dropping them)
 * means the page keeps rendering while the fresh URLs are on their way.
 */
export function notifyAssetExpired(url) {
  if (typeof url === "string" && url !== "") {
    if (retriedUrls.has(url)) return;
    // Bound the set: it only exists to stop a loop, not to be a history.
    if (retriedUrls.size > 128) retriedUrls.clear();
    retriedUrls.add(url);
  }
  const now = Date.now();
  if (now - lastExpiryRefreshAt < EXPIRY_RETRY_COOLDOWN_MS) return;
  lastExpiryRefreshAt = now;

  // Mark everything spent without dropping it, so the page keeps rendering
  // while the replacements are in flight...
  if (manifestEntry) manifestEntry = { ...manifestEntry, staleAt: 0, expiresAt: 0 };
  for (const [id, entry] of clipCache) {
    clipCache.set(id, { ...entry, staleAt: 0, expiresAt: 0 });
  }
  // ...then wake every consumer. Each open clip record notices its own entry is
  // stale and refetches itself; the manifest is refetched here, directly rather
  // than by waiting on a timer, because "now" is the whole point.
  notify();
  refreshCatalog().catch(() => {
    /* Already visible as a broken asset; a second error surface adds nothing. */
  });
}

/* ------------------------------------------------------------------ */
/* Hooks                                                               */
/* ------------------------------------------------------------------ */

/**
 * Arm a timer that fires at `staleAt` and refreshes silently, backing off and
 * retrying if the refresh itself fails. Returns nothing; the caller re-renders
 * because `refresh` calls notify().
 */
function useSilentRefresh(active, staleAt, refresh) {
  useEffect(() => {
    // `staleAt == null`, not `!staleAt`: an expired document is marked with
    // staleAt 0, which is falsy, and treating that as "nothing to schedule" is
    // exactly backwards — it is the one case that must refresh immediately.
    if (!active || staleAt == null) return undefined;
    let cancelled = false;
    let timer = null;
    const arm = (delay) => {
      timer = setTimeout(() => {
        if (cancelled) return;
        Promise.resolve()
          .then(refresh)
          .catch(() => {
            // Keep the stale document on screen and try again shortly. If the
            // user touches a dead asset first, notifyAssetExpired() gets there
            // sooner.
            if (!cancelled) arm(REFRESH_RETRY_MS);
          });
      }, delay);
    };
    arm(Math.max(0, staleAt - Date.now()));
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [active, staleAt, refresh]);
}

/**
 * The collection manifest.
 *
 * `staleAt` is the epoch-ms moment at which the presigned URLs in this document
 * should be considered spent. The hook already refreshes itself then; it is
 * exposed so a host page can show or act on it. `expirySource` says where that
 * moment came from — `"server"` when the response declared `expires_at`,
 * `"default"` when it did not and the build-time constant had to answer.
 *
 * `identity` is the current session's `${id}:${role}`, or null when signed out.
 * The module cache is keyed on it (see bindCatalogIdentity): pass it and a role
 * change can never be served from another role's cached, already-redacted
 * document.
 *
 * @param {string|null} [identity]
 * @returns {{status:"loading"|"ready"|"error", catalog:object|null,
 *            error:Error|null, staleAt:number|null, expiresAt:number|null,
 *            expirySource:"server"|"default"|null, retry:()=>void}}
 */
export function useCatalog(identity = null) {
  // Synchronous, in the render body, BEFORE the first read below: an effect
  // would run after this component had already rendered the previous role's
  // document once.
  bindCatalogIdentity(identity);

  const read = () =>
    manifestEntry
      ? {
          status: "ready",
          catalog: manifestEntry.doc,
          error: null,
          staleAt: manifestEntry.staleAt,
          expiresAt: manifestEntry.expiresAt,
          expirySource: manifestEntry.expirySource,
        }
      : {
          status: "loading", catalog: null, error: null,
          staleAt: null, expiresAt: null, expirySource: null,
        };

  const [state, setState] = useState(read);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    const sync = () => {
      if (alive && manifestEntry) setState(read);
    };
    const unsubscribe = subscribe(sync);
    ensureCatalog().then(sync, (err) => {
      if (alive) {
        setState({
          status: "error", catalog: null, error: err,
          staleAt: null, expiresAt: null, expirySource: null,
        });
      }
    });
    return () => {
      alive = false;
      unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attempt]);

  useSilentRefresh(state.status === "ready", state.staleAt, refreshCatalog);

  const retry = useCallback(() => {
    clearCatalogCache();
    setState({
      status: "loading", catalog: null, error: null,
      staleAt: null, expiresAt: null, expirySource: null,
    });
    setAttempt((n) => n + 1);
  }, []);

  return { ...state, retry };
}

/**
 * One clip's full detail record, fetched on demand and cached by id.
 *
 * Pass `null` when no clip is open; the hook then reports "idle" and fetches
 * nothing. Changing the id aborts any in-flight request for the previous one,
 * so arrowing quickly through clips cannot land an older response on top of a
 * newer one.
 *
 * `clip` is non-null whenever `status` is "ready", always. A clip whose
 * `detail` is explicitly null has no record to fetch, and the hook then hands
 * back the summary projected into record shape (see summaryAsClip) rather than
 * a bare null — so a caller never has to distinguish "loading" from "loaded but
 * empty", and a modal can never hang on a spinner that will not resolve.
 *
 * A record whose presigned URLs are about to expire is refetched in place: the
 * previous record stays mounted, and `clip` is simply replaced when the new one
 * arrives. Nothing flashes.
 *
 * @param {string|null} id
 * @returns {{status:"idle"|"loading"|"ready"|"error", clip:object|null,
 *            error:Error|null, staleAt:number|null, hasDetailRecord:boolean}}
 */
export function useClip(id) {
  const fresh = (entry) => entry != null && Date.now() < entry.staleAt;

  const [state, setState] = useState(() => {
    if (id == null) return { status: "idle", clip: null, error: null, staleAt: null };
    const entry = cacheRead(id);
    return fresh(entry)
      ? { status: "ready", clip: entry.doc, error: null, staleAt: entry.staleAt }
      : { status: "loading", clip: null, error: null, staleAt: null };
  });

  /** Bumped by the subscription when a cached record goes stale. */
  const [round, setRound] = useState(0);

  /* Keep the last good record on screen across a silent refetch. */
  const shownRef = useRef(state.clip);
  shownRef.current = state.status === "ready" ? state.clip : shownRef.current;

  useEffect(() => {
    if (id == null) {
      shownRef.current = null;
      setState({ status: "idle", clip: null, error: null, staleAt: null });
      return undefined;
    }

    const cached = cacheRead(id);
    if (fresh(cached)) {
      setState({ status: "ready", clip: cached.doc, error: null, staleAt: cached.staleAt });
      return undefined;
    }

    let alive = true;
    const owner = catalogCacheIdentity();
    const controller = new AbortController();
    // A stale-but-present record keeps rendering while the refetch is in
    // flight; only a cold open shows the spinner.
    const carry = cached ? cached.doc : shownRef.current && shownRef.current.id === id ? shownRef.current : null;
    setState(
      carry
        ? { status: "ready", clip: carry, error: null, staleAt: null }
        : { status: "loading", clip: null, error: null, staleAt: null },
    );

    (async () => {
      const catalog = await ensureCatalog();
      const summary = findClip(catalog, id);
      if (!summary) {
        throw new CatalogError(`No clip \`${id}\` in this collection.`, 404);
      }
      // `detail` present-and-null means "this clip ships no record". The
      // manifest is authoritative about that, so we do not ask the API.
      const hasDetail =
        !Object.prototype.hasOwnProperty.call(summary, "detail") ||
        (typeof summary.detail === "string" && summary.detail.trim() !== "");
      if (!hasDetail) {
        const projected = summaryAsClip(summary, catalog.collection);
        // Pinned to the manifest's own lifetime: its URLs came from there.
        cacheWrite(id, {
          doc: projected,
          receivedAt: Date.now(),
          expiresAt: manifestEntry ? manifestEntry.expiresAt : 0,
          staleAt: manifestEntry ? manifestEntry.staleAt : 0,
        });
        return cacheRead(id);
      }
      const doc = await apiGet(clipPath(id), controller.signal);
      assertSchema(doc, CLIP_FAMILY, `the clip record for \`${id}\``);
      // The session changed under this request: this record is another role's
      // redaction of the clip and is discarded rather than cached. See
      // bindCatalogIdentity().
      if (owner !== catalogCacheIdentity()) return null;
      if (doc.id !== id) {
        // Not fatal — we render what we asked for — but it means the manifest
        // and the record disagree, which is a stale-bundle symptom.
        console.warn(`[catalog] record fetched as \`${id}\` declares id \`${doc.id}\`.`);
      }
      const entry = entryFor(doc);
      cacheWrite(id, entry);
      return entry;
    })().then(
      (entry) => {
        // `entry === null` means the session changed under the request; the
        // document was discarded and there is nothing to render from it.
        if (alive && entry) {
          setState({ status: "ready", clip: entry.doc, error: null, staleAt: entry.staleAt });
        }
      },
      (err) => {
        if (!alive || (err && err.name === "AbortError")) return;
        setState({ status: "error", clip: null, error: err, staleAt: null });
      },
    );

    return () => {
      alive = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, round]);

  /* Refetch when something else invalidates the cache (an expired asset, or a
     manifest refresh that reset every record's clock). */
  useEffect(() => {
    if (id == null) return undefined;
    return subscribe(() => {
      const entry = clipCache.get(id);
      if (!entry || !fresh(entry)) setRound((n) => n + 1);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const refreshThis = useCallback(() => {
    setRound((n) => n + 1);
    return Promise.resolve();
  }, []);

  useSilentRefresh(state.status === "ready", state.staleAt, refreshThis);

  return useMemo(
    () => ({
      ...state,
      hasDetailRecord:
        state.status === "ready" && state.clip != null && !isSummaryProjection(state.clip),
    }),
    [state],
  );
}
