import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertTriangle, RotateCw, SearchX } from "lucide-react";

import CatalogTopBar from "./CatalogTopBar.jsx";
import CollectionHeader from "./CollectionHeader.jsx";
import TaskDistribution from "./TaskDistribution.jsx";
import FilterBar from "./FilterBar.jsx";
import CatalogGrid from "./CatalogGrid.jsx";
import ClipDetail from "./ClipDetail.jsx";
import { useCatalog } from "./useCatalog.js";
import { useSession } from "../portal/useSession.jsx";
import { formatCount } from "./format.js";
import "./catalog.css";
// AFTER catalog.css, deliberately: the chrome and masthead rules override a few
// of the shell's shared classes (.cat-stats, .cat-stat, .cat-page) and a
// specificity tie has to fall to this file. Its token and utility defaults are
// all :where()-wrapped, so they still lose to anything catalog.css authors.
import "./parts.header.css";

/**
 * CatalogPage — the buyer-facing catalog.
 *
 * This component owns ALL filter state and does ALL filtering and sorting, so
 * every child is dumb: the grid renders the clips it is handed, the filter bar
 * renders the facets it is handed and reports changes. One place decides what
 * is visible, which is what keeps "the count in the filter bar" and "the cards
 * on screen" from ever disagreeing.
 *
 * The open clip lives in the URL (`?clip=<id>`), not in state, so a buyer can
 * send a colleague a link to one clip.
 */

/** The filter value object, in full. Empty array / null means "no constraint". */
export const EMPTY_FILTERS = Object.freeze({
  q: "",
  category: [],
  subcategory: [],
  country: [],
  /* The `Stereo | Mono` control is gone from FilterBar -- every clip in the corpus
     is egocentric stereo, so it had one live option and could not narrow anything.
     The KEY stays here, and in matchesFilters and hasConstraints below, on purpose:
     a `capture` constraint can still arrive in a shared URL, and FilterBar renders
     it as a removable pill. Delete these three and such a link would silently
     filter a grid with no visible, clearable reason for the missing cards. */
  capture: null,
  modality: [],
  rights: [],
  hands: null,
  qa: [],
  split: [],
  sort: "recent",
});

/* ------------------------------------------------------------------ */
/* Filtering                                                           */
/* ------------------------------------------------------------------ */

// Longest suffix first so `commercial_use_on_request` is not mis-split.
const PERMISSION_SUFFIXES = ["_on_request", "_granted", "_denied"];

/**
 * Split a rights facet bucket value into the permission it constrains and the
 * value it requires: "model_training_granted" -> {model_training, granted}.
 * Returns null for anything that is not shaped that way.
 */
export function parseRightsBucket(bucket) {
  if (typeof bucket !== "string") return null;
  for (const suffix of PERMISSION_SUFFIXES) {
    if (bucket.endsWith(suffix) && bucket.length > suffix.length) {
      return { permission: bucket.slice(0, -suffix.length), value: suffix.slice(1) };
    }
  }
  return null;
}

/** Multi-select facets are OR within a facet, AND across facets. */
function orWithin(selected, test) {
  return selected.length === 0 || selected.some(test);
}

/** Everything `q` searches, lowercased once per clip per query. */
function haystack(clip) {
  return [clip.title, clip.description_short, clip.category, clip.country]
    .filter((s) => typeof s === "string" && s !== "")
    .join(" ")
    .toLowerCase();
}

export function matchesFilters(clip, f) {
  if (!clip) return false;

  const q = f.q.trim().toLowerCase();
  if (q !== "" && !haystack(clip).includes(q)) return false;

  if (!orWithin(f.category, (v) => v === clip.category)) return false;
  // A clip with a null subcategory is excluded when a subcategory filter is
  // active — null is not bucketed under a placeholder.
  if (!orWithin(f.subcategory, (v) => v === clip.subcategory)) return false;
  if (!orWithin(f.country, (v) => v === clip.country)) return false;

  if (f.capture != null && clip.capture !== f.capture) return false;

  const modalities = Array.isArray(clip.modalities) ? clip.modalities : [];
  if (!orWithin(f.modality, (v) => modalities.includes(v))) return false;

  const rights = clip.rights || {};
  if (
    !orWithin(f.rights, (bucket) => {
      const parsed = parseRightsBucket(bucket);
      return parsed != null && rights[parsed.permission] === parsed.value;
    })
  ) {
    return false;
  }

  /* `hands` is never null and [] is a determined answer, so there are FOUR selectable
     states, not three: left, right, both, and none. `none` is the camera-only product —
     one of the two this rig ships — and before it existed that clip matched no bucket in
     `facets.hands` at all, so a buyer who wanted exactly that product had no way to ask
     for it and no count to price it from. */
  const hands = Array.isArray(clip.hands) ? clip.hands : [];
  if (f.hands != null) {
    if (f.hands === "both" ? hands.length < 2
      : f.hands === "none" ? hands.length > 0
        : !hands.includes(f.hands)) return false;
  }

  const grade = clip.qa ? clip.qa.grade : null;
  if (!orWithin(f.qa, (v) => v === grade)) return false;

  // A clip with no split assignment drops out of every split filter rather than
  // being bucketed under a placeholder — the same rule as a null subcategory.
  if (!orWithin(f.split, (v) => v === clip.split)) return false;

  return true;
}

/**
 * Sort a filtered list. Always stable: ties keep the manifest's own order,
 * which is the order the producer intended the grid to show by default.
 */
export function sortClips(clips, sort) {
  const decorated = clips.map((clip, i) => ({ clip, i }));
  const byIndex = (a, b) => a.i - b.i;

  if (sort === "longest") {
    decorated.sort((a, b) => {
      const d = (b.clip.duration_s || 0) - (a.clip.duration_s || 0);
      return d !== 0 ? d : byIndex(a, b);
    });
  } else if (sort === "title") {
    decorated.sort((a, b) => {
      const d = String(a.clip.title || "").localeCompare(String(b.clip.title || ""), "en", {
        sensitivity: "base",
      });
      return d !== 0 ? d : byIndex(a, b);
    });
  } else {
    // "recent": newest recording month first. A clip with no known month sorts
    // last rather than pretending to be old.
    decorated.sort((a, b) => {
      const am = a.clip.recorded_month;
      const bm = b.clip.recorded_month;
      if (am == null && bm == null) return byIndex(a, b);
      if (am == null) return 1;
      if (bm == null) return -1;
      if (am === bm) return byIndex(a, b);
      return am < bm ? 1 : -1;
    });
  }
  return decorated.map((d) => d.clip);
}

/** True when anything other than the sort is constraining the list. */
function hasConstraints(f) {
  return (
    f.q.trim() !== "" ||
    f.capture != null ||
    f.hands != null ||
    f.category.length > 0 ||
    f.subcategory.length > 0 ||
    f.country.length > 0 ||
    f.modality.length > 0 ||
    f.rights.length > 0 ||
    f.qa.length > 0 ||
    f.split.length > 0
  );
}

/* ------------------------------------------------------------------ */
/* Page                                                                */
/* ------------------------------------------------------------------ */

export default function CatalogPage({ onRequestAccess }) {
  /* The catalog's module cache holds SERVER-REDACTED documents and live
     presigned URLs, and it outlives this component. Keying it on the signed-in
     identity is what stops a guest, logged in after a founder in the same tab,
     being handed the founder's manifest from memory. */
  const { user } = useSession();
  const identity = user ? `${user.id}:${user.role}` : null;
  const { status, catalog, error, retry } = useCatalog(identity);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [searchParams, setSearchParams] = useSearchParams();

  const openId = searchParams.get("clip");

  const clips = catalog && Array.isArray(catalog.clips) ? catalog.clips : null;

  const visible = useMemo(() => {
    if (!clips) return [];
    return sortClips(
      clips.filter((c) => matchesFilters(c, filters)),
      filters.sort,
    );
  }, [clips, filters]);

  /**
   * Distinct modalities across the collection. Not carried in `totals`, and
   * derived from clips[] rather than from the facet because clips[] is the
   * authority when the two disagree.
   */
  const modalityCount = useMemo(() => {
    if (!clips) return null;
    const seen = new Set();
    for (const c of clips) {
      for (const m of Array.isArray(c.modalities) ? c.modalities : []) seen.add(m);
    }
    return seen.size;
  }, [clips]);

  /**
   * The three header figures a buyer negotiates on that `totals` does not carry.
   *
   * Folded over clips[], for the same reason modalityCount is: clips[] is the
   * authority when it and totals disagree, and every field involved is already
   * in the summary, so this costs one pass over thirty objects and no fetch.
   *
   *   training  clips whose rights.model_training reads `granted`, and their
   *             duration. The headline "30 clips / 19 min" overstated what a lab
   *             could actually put in a training run by 2.4x, and the only way to
   *             find the real figure was to click a rights facet and read a chip
   *             count -- which reports clips, never minutes.
   *   cleared   the subset of those also granted for commercial use, with consent
   *             on file and a passed PII review: the clips with no open question
   *             left before a training run. Twelve of thirty, 7.8 minutes.
   *   census    the MEDIAN live-and-stable channel count on the worst hand, and
   *             the readout-site denominator, so the yield tile can state the
   *             census the clip records insist on quoting instead of the
   *             484-site grid size they forbid quoting.
   */
  const derived = useMemo(() => {
    if (!clips || clips.length === 0) return null;
    const minutes = (list) => list.reduce((n, c) => n + (Number(c.duration_s) || 0), 0) / 60;

    const training = clips.filter(
      (c) => c.rights && c.rights.model_training === "granted",
    );
    const cleared = training.filter(
      (c) =>
        c.rights.commercial_use === "granted" &&
        c.privacy &&
        c.privacy.consent_on_file === true &&
        c.privacy.pii_review === "passed",
    );

    /* The worst hand per clip, then the median over clips. Median, not mean: the
       distribution has a long bad tail (169 channels at the low end against 380 at
       the high) and a mean would quietly flatter it. `readout_sites` is not in the
       summary, so the denominator is re-derived from the one identity that IS:
       tactile_coverage = min(usable_channels) / readout_sites. */
    const worst = [];
    const sites = [];
    for (const c of clips) {
      const uc = c.qa && c.qa.usable_channels;
      if (!uc) continue;
      const hands = [uc.left, uc.right].filter((n) => typeof n === "number");
      if (!hands.length) continue;
      const low = Math.min(...hands);
      worst.push(low);
      const cov = c.qa.tactile_coverage;
      if (typeof cov === "number" && cov > 0) sites.push(Math.round(low / cov));
    }
    let census = null;
    if (worst.length && sites.length) {
      const sorted = worst.slice().sort((a, b) => a - b);
      const mid = sorted.length >> 1;
      const median =
        sorted.length % 2 ? sorted[mid] : Math.round((sorted[mid - 1] + sorted[mid]) / 2);
      /* One grid size, or none. A corpus with two different readout-site counts has
         no single denominator to quote, and inventing one is the defect this figure
         exists to remove. */
      const unique = Array.from(new Set(sites));
      if (unique.length === 1) census = { median, sites: unique[0] };
    }

    return {
      training: { clips: training.length, minutes: minutes(training) },
      cleared: { clips: cleared.length, minutes: minutes(cleared) },
      census,
    };
  }, [clips]);

  /**
   * value -> label for the country facet, e.g. { CN: "China", HK: "Hong Kong" }.
   *
   * The labels SHIP IN THE MANIFEST (facets.country[].label, required by
   * catalog.schema.json and enforced by the ingest, which now refuses to build a
   * bundle whose country has no display name). Reading them here rather than
   * carrying an ISO table in the UI is what stops the card and the filter bar
   * disagreeing about what a code is called. Memoised because ClipCard's memo
   * comparator checks this object by identity.
   */
  const countryLabels = useMemo(() => {
    const buckets = catalog && catalog.facets ? catalog.facets.country : null;
    if (!Array.isArray(buckets)) return null;
    const out = {};
    for (const b of buckets) {
      if (b && typeof b.value === "string" && typeof b.label === "string") out[b.value] = b.label;
    }
    return Object.keys(out).length ? out : null;
  }, [catalog]);

  /* ---- the open clip lives in the URL ---- */

  // The element that opened the modal, so focus can go back where it came from.
  const triggerRef = useRef(null);
  const wasOpen = useRef(openId);

  const setClipParam = useCallback(
    (id, { replace }) => {
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id == null) next.delete("clip");
          else next.set("clip", id);
          return next;
        },
        { replace },
      );
    },
    [setSearchParams],
  );

  const handleOpen = useCallback(
    (id) => {
      triggerRef.current = typeof document !== "undefined" ? document.activeElement : null;
      setClipParam(id, { replace: false });
    },
    [setClipParam],
  );

  const handleClose = useCallback(() => setClipParam(null, { replace: false }), [setClipParam]);

  /**
   * Step through the visible list. Accepts +1/-1 or "next"/"prev" so it does
   * not matter which the modal sends. Clamped, not wrapped: arrowing past the
   * last clip should stop, not silently loop back to the first.
   *
   * Arrow steps replace rather than push, so a buyer who arrows through twenty
   * clips does not have to press Back twenty times.
   */
  const handleNavigate = useCallback(
    (dir) => {
      if (!openId || visible.length === 0) return;
      const step = dir === "prev" || dir === "previous" || (typeof dir === "number" && dir < 0) ? -1 : 1;
      const at = visible.findIndex((c) => c.id === openId);
      if (at === -1) return;
      const to = at + step;
      if (to < 0 || to >= visible.length) return;
      setClipParam(visible[to].id, { replace: true });
    },
    [openId, visible, setClipParam],
  );

  // Return focus to the card that opened the modal.
  useEffect(() => {
    if (wasOpen.current && !openId) {
      const el = triggerRef.current;
      if (el && el.isConnected && typeof el.focus === "function") el.focus();
      triggerRef.current = null;
    }
    wasOpen.current = openId;
  }, [openId]);

  // Lock background scroll while the modal is open. Class-based and
  // self-cleaning, so it cannot fight the modal's own lock or strand an
  // inline style. The gutter compensation stops the page shifting sideways
  // when the scrollbar disappears.
  useEffect(() => {
    if (!openId || typeof document === "undefined") return undefined;
    const root = document.documentElement;
    const gutter = window.innerWidth - root.clientWidth;
    if (gutter > 0) root.style.setProperty("--cat-scrollbar-w", gutter + "px");
    root.classList.add("cat-scroll-locked");
    return () => {
      root.classList.remove("cat-scroll-locked");
      root.style.removeProperty("--cat-scrollbar-w");
    };
  }, [openId]);

  const clearFilters = useCallback(() => {
    setFilters((f) => ({ ...EMPTY_FILTERS, sort: f.sort }));
  }, []);

  /* ---- states ---- */

  /* The chrome is mounted in every state, including loading and error. It owns
     the only sign-out in the product, so it cannot be behind a successful
     manifest fetch — and rendering it identically in all three states means the
     page never reflows around it once the data lands. */
  if (status === "loading") {
    return (
      <div className="cat-root cat-root--chromed">
        <CatalogTopBar pending />
        <main className="cat-page cat-page--catalog" aria-busy="true">
          <p className="cat-sr-only" role="status">
            Loading the catalog.
          </p>
          <LoadingSkeleton />
        </main>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="cat-root cat-root--chromed">
        <CatalogTopBar />
        <main className="cat-page cat-page--catalog">
          <div className="cat-state cat-state--error" role="alert">
            <AlertTriangle size={26} aria-hidden="true" />
            <h2 className="cat-state-title">The catalog could not be loaded</h2>
            <p className="cat-state-body">{error ? error.message : "Unknown error."}</p>
            <button type="button" className="cat-btn cat-btn--primary" onClick={retry}>
              <RotateCw size={16} aria-hidden="true" />
              Try again
            </button>
          </div>
        </main>
      </div>
    );
  }

  const collection = catalog.collection || {};
  const constrained = hasConstraints(filters);

  return (
    <div className="cat-root cat-root--chromed">
      <CatalogTopBar
        collectionName={collection.name || null}
        collectionVersion={collection.version || null}
      />
      <main className="cat-page cat-page--catalog">
        <CollectionHeader
          collection={collection}
          totals={collection.totals}
          access={catalog.access}
          modalityCount={modalityCount}
          countryLabels={countryLabels}
          derived={derived}
          onRequestAccess={onRequestAccess}
        />

        {/*
          * ONE section for the filter bar AND the grid, deliberately.
          *
          * The bar is `position: sticky` from 60rem up. A sticky box cannot leave its
          * containing block, and it used to have a `<section className="cat-section">`
          * of its own whose only children were the sentinel and the bar — a containing
          * block exactly as tall as the box, so the travel available to it was zero and
          * it scrolled away like static content. Measured in Chromium at 1440x900:
          * computed `position: sticky`, `top: 56px`, and a viewport top of 165 / -335 /
          * -1322 at scrollY 900 / 1400 / 2500. Everything built around it —
          * --cat-sticky-top, the z-index:20 layering, the whole .cat-fb.is-stuck
          * elevation state — was dead code.
          *
          * Sharing the grid's section gives it the grid's height to travel over, which
          * is the only thing it ever needed. It is also why the "Filters" region label
          * is gone: FilterBar already exposes its own `role="search"` landmark, and two
          * nested regions for one control panel is noise in a screen reader's rotor.
          */}
        <section className="cat-section cat-section--browse" aria-label="Clips">
          <FilterBar
            facets={catalog.facets || {}}
            value={filters}
            onChange={setFilters}
            resultCount={visible.length}
            totalClips={clips ? clips.length : 0}
            durationUnit={(collection.totals || {}).duration_unit}
            geoDeclared={
              collection.provenance_class === "synthetic" ||
              collection.provenance_class === "mixed"
            }
          />

          {visible.length > 0 ? (
            <>
              {/* Announce the result count without stealing focus. */}
              <p className="cat-sr-only" role="status">
                {formatCount(visible.length)} clip{visible.length === 1 ? "" : "s"} shown.
              </p>
              <CatalogGrid
                clips={visible}
                onOpen={handleOpen}
                collection={collection}
                countryLabels={countryLabels}
              />
            </>
          ) : constrained ? (
            <div className="cat-state" role="status">
              <SearchX size={26} aria-hidden="true" />
              <h2 className="cat-state-title">No clips match</h2>
              <p className="cat-state-body">
                Nothing in this collection satisfies every filter at once.
              </p>
              <button type="button" className="cat-btn cat-btn--primary" onClick={clearFilters}>
                Clear filters
              </button>
            </div>
          ) : (
            <div className="cat-state" role="status">
              <h2 className="cat-state-title">No clips published yet</h2>
              <p className="cat-state-body">
                This collection is live but currently holds no accepted clips.
              </p>
            </div>
          )}
        </section>

        {/* Below the grid, not above it. On the delivered corpus this is one to
            two clips per task, so it is a coverage list rather than a
            distribution — useful, but not the first thing a buyer should meet.
            The clips are. A null benchmark hides the section entirely; there is
            never an empty axis. */}
        {catalog.benchmark ? (
          <section className="cat-section" aria-label="Task coverage">
            <TaskDistribution benchmark={catalog.benchmark} />
          </section>
        ) : null}
      </main>

      <ClipDetail clipId={openId} onClose={handleClose} onNavigate={handleNavigate} />
    </div>
  );
}

/**
 * Masthead + card placeholders at the EXACT geometry of the real thing, so the
 * page does not shift when the manifest lands (CLS 0). Skeletons, not a
 * spinner: a spinner says "wait", a skeleton says what is coming.
 *
 * Every box below is sized from the same clamp() the real element uses — see
 * the .cat-skel-* rules in parts.header.css — rather than from a rounded
 * guess, which is what made the old one jump a full line height.
 */
function LoadingSkeleton() {
  return (
    <div aria-hidden="true">
      <div className="cat-masthead">
        <div className="cat-masthead__grid">
          <div className="cat-masthead__lede">
            <div className="cat-skeleton cat-skel-title" />
            <div className="cat-skeleton cat-skel-standfirst" />
          </div>
          <div className="cat-skeleton cat-skel-access" />
        </div>
        <dl className="cat-stats">
          {[0, 1, 2, 3].map((i) => (
            <div className="cat-stat" key={i}>
              <dt>
                <div className="cat-skeleton cat-skeleton--label" style={{ width: "5.5rem" }} />
              </dt>
              <dd>
                <div className="cat-skeleton cat-skeleton--figure" style={{ width: "4.5rem" }} />
              </dd>
            </div>
          ))}
        </dl>
      </div>
      <div className="cat-section cat-section--grid">
        <div className="cat-grid">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div className="cat-card-skeleton" key={i}>
              <div className="cat-skeleton cat-skeleton--thumb" />
              <div className="cat-skeleton" style={{ width: "70%", height: "1rem" }} />
              <div className="cat-skeleton" style={{ width: "45%", height: "0.8rem" }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
