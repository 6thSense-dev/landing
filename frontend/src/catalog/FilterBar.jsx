/**
 * FilterBar — search, facet chips, active-filter summary, result count, sort.
 *
 * This component NEVER filters. It reads precomputed buckets out of `facets` and calls
 * `onChange` with the next value object; the page owns the filtering and the sort.
 *
 * Value object (exact shape, always emitted whole):
 *   { q, category[], subcategory[], country[], capture, modality[], rights[], hands, qa[], split[], sort }
 *
 *   capture and hands are SCALARS (null = no constraint); the rest of the facet keys are
 *   arrays. `subcategory` has no chip group of its own — the category chips are the primary
 *   grouping control — but it is passed through untouched so the page can drive it from a URL.
 *   The manifest facet is named `qa_grade`; the filter key is `qa`.
 *
 * Sort tokens: "recent" | "longest" | "title".
 *
 * ---------------------------------------------------------------------------------------
 * `totalClips` is the size of the whole corpus, and it is what lets a facet retire
 * itself: see dropUniversal(). Pass 0 (or omit it) and every published bucket is
 * rendered, which is the right default for a caller that does not know the total.
 *
 * The capture toggle is GONE (2026-08). Every clip in the corpus is egocentric stereo, so the
 * `Stereo | Mono` segmented control had one live option and could not narrow anything: a filter
 * that cannot filter is noise on a dense page. `capture` is still carried through the value
 * object untouched, still honoured by the page's matchesFilters, and still surfaced as a
 * removable pill in the active-filter row — so a capture constraint arriving from a URL is
 * visible and clearable even with no chip group to clear it from. CatalogPage should stop
 * relying on the control existing; see the note in the integrator report.
 *
 * Stickiness: the bar pins itself only from 60rem up. Below that the facet block is taller than
 * a third of a phone viewport, and pinning it would trade the grid — the thing the buyer came
 * for — for a control panel they use once. It scrolls away instead.
 * ---------------------------------------------------------------------------------------
 */
import React, { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Search, X } from "lucide-react";
import { formatCount, labelize } from "./format.js";

const TOP_N = 6;
const DEBOUNCE_MS = 200;

/**
 * A facet with more than this many visible buckets is laid out FULL WIDTH, next to
 * Category, instead of being packed into a quarter-width column with the short ones.
 *
 * Not a style preference — a measurement. The secondary block is a wrapping row of
 * roughly 15rem groups, and Rights' longest chip ("Redistribution: denied 24") is
 * wider than that on its own, so six of them stacked one per line while Country, QA
 * grade and Split took one line each: a 380px panel about 60% empty, directly above
 * the first card. See the note on .cat-fb__facets-rest in parts.grid.css.
 *
 * Four is where a group stops fitting one line of a narrow column. It is a threshold
 * on the DATA, not a hardcoded facet name, so the day Rights collapses to two buckets
 * it rejoins the short row on its own, and the day QA grade grows to eight it gets the
 * full width without anyone editing this file.
 */
const WIDE_AT = 4;

/* facet  = key in catalog.facets
   key    = key in the filter value object
   multi  = array-valued (OR within the facet) vs scalar (null = no constraint)
   tone   = visual rank. "primary" is the grid's own grouping and is the one chip row that
            gets weight; everything else, country included, is a qualifier and reads lighter. */
/* `duration` puts the bucket's DURATION on the chip beside its clip count.
   On Rights only, because rights are the one facet where the count is not the
   question: "Model training: granted 18" does not tell a buyer how much material
   they could actually put in a training run, and 18 clips of 30 is 11.5 of 19
   minutes, not 60% of the corpus. The figures are already in the manifest
   (`FacetBucket.hours`), and the split buckets have quoted them since v1. */
const CHIP_GROUPS = [
  { facet: "category", key: "category", label: "Category", multi: true, tone: "primary" },
  { facet: "country", key: "country", label: "Country", multi: true, tone: "plain" },
  { facet: "modality", key: "modality", label: "Modality", multi: true, tone: "plain" },
  { facet: "rights", key: "rights", label: "Rights", multi: true, tone: "plain", duration: true },
  { facet: "hands", key: "hands", label: "Hands", multi: false, tone: "plain" },
  { facet: "qa_grade", key: "qa", label: "QA grade", multi: true, tone: "plain" },
  { facet: "split", key: "split", label: "Split", multi: true, tone: "plain" },
];

/* Every constrainable key, in the order the active-filter row lists them. `subcategory` and
   `capture` have no chip group but can arrive from a URL, so they MUST be removable here or
   they become unclearable. */
const ACTIVE_KEYS = [
  { facet: "category", key: "category", label: "Category", multi: true },
  { facet: "subcategory", key: "subcategory", label: "Subcategory", multi: true },
  { facet: "country", key: "country", label: "Country", multi: true },
  { facet: "capture", key: "capture", label: "Capture", multi: false },
  { facet: "modality", key: "modality", label: "Modality", multi: true },
  { facet: "rights", key: "rights", label: "Rights", multi: true },
  { facet: "hands", key: "hands", label: "Hands", multi: false },
  { facet: "qa_grade", key: "qa", label: "QA grade", multi: true },
  { facet: "split", key: "split", label: "Split", multi: true },
];

const SORT_OPTIONS = [
  { value: "recent", label: "Most recent" },
  { value: "longest", label: "Longest" },
  { value: "title", label: "Title A–Z" },
];

const ARROW_KEYS = ["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"];
const EMPTY = [];
const EMPTY_EXPANDED = {};

/* Only used if the page mounts us before its filter state exists; emitting from it still
   produces the full, correctly-shaped value object. */
const EMPTY_VALUE = Object.freeze({
  q: "",
  category: EMPTY,
  subcategory: EMPTY,
  country: EMPTY,
  capture: null,
  modality: EMPTY,
  rights: EMPTY,
  hands: null,
  qa: EMPTY,
  split: EMPTY,
  sort: "recent",
});

function asArray(v) {
  return Array.isArray(v) ? v : EMPTY;
}

/**
 * Drop the buckets that cannot narrow anything.
 *
 * A chip whose count equals the whole corpus selects every card that is already on
 * screen: pressing it changes nothing, and a row of them ("Video 30 · Tactile 30 ·
 * IMU 30 · Segcap 30 · Calibration 30") reads as five broken controls. This is the
 * same rule that retired the `Stereo | Mono` toggle, generalised so it self-heals:
 * the day a clip ships without IMU, `imu` stops being universal and the Modality
 * group comes back on its own. Nothing is hardcoded to this corpus.
 *
 * It removes a CONTROL, never a FACT: that every clip carries video + tactile is
 * stated on the masthead and on every card, which is where a claim belongs. And a
 * selected value is always kept, universal or not, so a constraint arriving in a
 * URL stays visible and clearable.
 *
 * When every bucket in a facet is universal the group empties and is dropped by the
 * caller's `buckets.length > 0` filter.
 */
function dropUniversal(buckets, total, selected) {
  if (!(total > 0)) return buckets;
  return buckets.filter((b) => selected.has(b.value) || (b.clips || 0) < total);
}

/** Sort buckets by clip count, then append any selected value the manifest has no bucket for,
 *  so an active filter can never become invisible (and therefore unclearable). */
function buildBuckets(facetList, selected) {
  const src = Array.isArray(facetList) ? facetList.slice() : [];
  src.sort((a, b) => (b.clips || 0) - (a.clips || 0));
  if (!selected.size) return src;
  const known = new Set(src.map((b) => b.value));
  selected.forEach((v) => {
    if (!known.has(v)) src.push({ value: v, label: v, clips: 0, hours: 0 });
  });
  return src;
}

function normalizeCount(rc) {
  if (rc && typeof rc === "object") {
    return {
      clips: typeof rc.clips === "number" ? rc.clips : 0,
      hours: typeof rc.hours === "number" ? rc.hours : null,
    };
  }
  return { clips: typeof rc === "number" ? rc : 0, hours: null };
}

/* ------------------------------------------------------------------------ chip group */

/** A facet bucket's duration, in the unit the manifest says the collection reads in.
 *  `hours` is ALWAYS stored in hours (CONTRACT.md §3.1.1); only the rendering changes. */
function bucketDuration(hours, unit) {
  if (typeof hours !== "number" || !Number.isFinite(hours) || hours <= 0) return null;
  if (unit === "minutes") {
    const m = hours * 60;
    return `${m < 10 ? m.toFixed(1) : Math.round(m)} min`;
  }
  return `${hours < 10 ? hours.toFixed(1) : Math.round(hours)} h`;
}

function ChipGroup({
  groupId,
  label,
  tone,
  buckets,
  selected,
  multi,
  expanded,
  onExpand,
  onToggle,
  duration,
  durationUnit,
}) {
  const rowRef = useRef(null);
  const [rovIdx, setRovIdx] = useState(null);

  const visible = useMemo(() => {
    if (expanded || buckets.length <= TOP_N) return buckets;
    const head = buckets.slice(0, TOP_N);
    const tailSelected = buckets.slice(TOP_N).filter((b) => selected.has(b.value));
    return tailSelected.length ? head.concat(tailSelected) : head;
  }, [buckets, expanded, selected]);

  const hidden = buckets.length - visible.length;

  /* Roving tabindex: one tab stop per group, arrows move inside it. Default the stop to the
     first selected chip so tabbing in lands on something meaningful. */
  const firstSelected = visible.findIndex((b) => selected.has(b.value));
  const rov =
    rovIdx == null
      ? firstSelected >= 0
        ? firstSelected
        : 0
      : Math.min(rovIdx, Math.max(0, visible.length - 1));

  const onKeyDown = useCallback((e) => {
    const isArrow = ARROW_KEYS.indexOf(e.key) !== -1;
    if (!isArrow && e.key !== "Home" && e.key !== "End") return;
    const row = rowRef.current;
    if (!row) return;
    const nodes = Array.prototype.slice.call(row.querySelectorAll('button[data-chip="1"]'));
    if (!nodes.length) return;
    const cur = nodes.indexOf(document.activeElement);
    let next;
    if (e.key === "Home") next = 0;
    else if (e.key === "End") next = nodes.length - 1;
    else {
      const dir = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1;
      next = ((cur < 0 ? 0 : cur) + dir + nodes.length) % nodes.length;
    }
    e.preventDefault();
    nodes[next].focus();
    setRovIdx(next);
  }, []);

  if (!buckets.length) return null;

  return (
    <div
      className={`cat-fb__group cat-fb__group--${tone || "plain"}`}
      role="group"
      aria-labelledby={`${groupId}-lbl`}
    >
      <span className="cat-fb__glabel" id={`${groupId}-lbl`}>
        {label}
      </span>
      <div className="cat-fb__chiprow" id={`${groupId}-chips`} ref={rowRef} onKeyDown={onKeyDown}>
        {visible.map((b, i) => {
          const on = selected.has(b.value);
          const dur = duration ? bucketDuration(b.hours, durationUnit) : null;
          return (
            <button
              key={b.value}
              type="button"
              data-chip="1"
              className={`cat-fb__chip${on ? " is-on" : ""}`}
              aria-pressed={on}
              tabIndex={i === rov ? 0 : -1}
              onFocus={() => setRovIdx(i)}
              onClick={() => onToggle(b.value, multi)}
            >
              <span className="cat-fb__chip-t">{b.label}</span>
              <span className="cat-fb__chip-n">{b.clips}</span>
              {dur ? <span className="cat-fb__chip-h">{dur}</span> : null}
            </button>
          );
        })}
        {hidden > 0 || (expanded && buckets.length > TOP_N) ? (
          <button
            type="button"
            className="cat-fb__more"
            aria-expanded={Boolean(expanded)}
            aria-controls={`${groupId}-chips`}
            onClick={onExpand}
          >
            {expanded ? "Show less" : `${hidden} more`}
          </button>
        ) : null}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------------- filter bar */

export default function FilterBar({
  facets,
  value = EMPTY_VALUE,
  onChange,
  resultCount,
  totalClips = 0,
  durationUnit = "hours",
  geoDeclared = false,
}) {
  const uid = useId();
  const inputRef = useRef(null);
  const sentinelRef = useRef(null);
  const barRef = useRef(null);
  const [stuck, setStuck] = useState(false);
  const [expanded, setExpanded] = useState(EMPTY_EXPANDED);

  /* Always read the freshest value/onChange without making `emit` a new function each render;
     the debounce effect below depends on its identity. */
  const latest = useRef({ value, onChange });
  latest.current = { value, onChange };

  const emit = useCallback((patch) => {
    const { value: v, onChange: cb } = latest.current;
    if (cb) cb({ ...v, ...patch });
  }, []);

  /* ---------------------------------------------------------------- search (debounced) */

  const [qDraft, setQDraft] = useState(value.q || "");
  /* The last q this component is responsible for. Lets us tell our own echo apart from an
     external reset (Clear all, a URL change) without clobbering what the user is typing. */
  const qOwn = useRef(value.q || "");

  useEffect(() => {
    const incoming = value.q || "";
    if (incoming !== qOwn.current) {
      qOwn.current = incoming;
      setQDraft(incoming);
    }
  }, [value.q]);

  useEffect(() => {
    if (qDraft === qOwn.current) return undefined;
    const t = setTimeout(() => {
      qOwn.current = qDraft;
      emit({ q: qDraft });
    }, DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [qDraft, emit]);

  const clearQuery = useCallback(() => {
    qOwn.current = "";
    setQDraft("");
    emit({ q: "" });
    if (inputRef.current) inputRef.current.focus();
  }, [emit]);

  /* "/" focuses the search field, unless the user is already typing somewhere or a modal owns
     the screen — stealing focus out of a focus-trapped dialog would be a real bug. */
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "/" || e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target;
      if (t) {
        const tag = t.tagName;
        if (t.isContentEditable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
        if (typeof t.closest === "function" && t.closest('[aria-modal="true"]')) return;
      }
      if (!inputRef.current) return;
      e.preventDefault();
      inputRef.current.focus();
      inputRef.current.select();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  /* ------------------------------------------------------------------------ stickiness */

  useEffect(() => {
    const el = sentinelRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return undefined;

    /*
     * The sentinel crosses y=0, but the bar PINS at y = --cat-sticky-top (the fixed
     * top bar's height). With no rootMargin the elevation state switched one
     * topbar-height LATE, leaving a scroll window in which the bar was pinned with no
     * hairline and grid content bleeding under it.
     *
     * The offset is read off the bar's own used `top`, not off the custom property:
     * `--cat-sticky-top` resolves to `3.5rem`, and a rootMargin needs pixels. A
     * sticky element's computed `top` is already the used px value, and below the
     * 60rem breakpoint the bar is static and it reads `auto` -- which is exactly the
     * 0 we want there. Re-measured on resize because that breakpoint flips.
     */
    const stickyTop = () => {
      const bar = barRef.current;
      if (!bar) return 0;
      const px = parseFloat(getComputedStyle(bar).top);
      return Number.isFinite(px) ? Math.max(0, px) : 0;
    };

    let io = null;
    const connect = () => {
      if (io) io.disconnect();
      io = new IntersectionObserver(
        (entries) => {
          const e = entries[0];
          /* `!isIntersecting` alone is true both ABOVE and BELOW the root, so the
             bar wore its pinned elevation while it was still a screen and a half
             below the fold. Stuck means the sentinel is above the root's TOP EDGE
             — which after the rootMargin is the pin line, not y=0. Measured in
             Chromium, the exit entry reports boundingClientRect.top = 51 against
             rootBounds.top = 56, so comparing against 0 never fires at all. */
          const edge = e.rootBounds ? e.rootBounds.top : 0;
          setStuck(!e.isIntersecting && e.boundingClientRect.top < edge);
        },
        {
          threshold: 0,
          rootMargin: `-${stickyTop()}px 0px 0px 0px`,
        },
      );
      io.observe(el);
    };
    connect();

    let raf = 0;
    const onResize = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        connect();
      });
    };
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      if (raf) cancelAnimationFrame(raf);
      if (io) io.disconnect();
    };
  }, []);

  /* ---------------------------------------------------------------------------- toggles */

  const toggleChip = useCallback(
    (key, val, multi) => {
      const v = latest.current.value;
      if (multi) {
        const cur = asArray(v[key]);
        const next = cur.indexOf(val) !== -1 ? cur.filter((x) => x !== val) : cur.concat(val);
        emit({ [key]: next });
      } else {
        emit({ [key]: (v[key] == null ? null : v[key]) === val ? null : val });
      }
    },
    [emit]
  );

  const removeValue = useCallback(
    (key, val, multi) => {
      const v = latest.current.value;
      if (multi) emit({ [key]: asArray(v[key]).filter((x) => x !== val) });
      else emit({ [key]: null });
    },
    [emit]
  );

  /* ------------------------------------------------------------------------ chip groups */

  const groups = useMemo(
    () =>
      CHIP_GROUPS.map((g) => {
        const raw = value[g.key];
        const selected = g.multi
          ? new Set(asArray(raw))
          : new Set(raw == null ? EMPTY : [raw]);
        const buckets = dropUniversal(
          buildBuckets(facets && facets[g.facet], selected),
          totalClips,
          selected,
        );
        /* On a generated corpus a country is DECLARED by the take, not observed:
           the banner above the grid says these are not recordings, so labelling
           the control "Country" asserts something the media cannot support. The
           facet still filters — the field is real and it is what the takes say —
           it is just named for what it is. Reverts on its own when the corpus is
           recorded. */
        const label =
          geoDeclared && g.facet === "country" ? "Locale (declared)" : g.label;
        return { ...g, label, selected, buckets };
      }).filter((g) => g.buckets.length > 0),
    [facets, value, totalClips, geoDeclared]
  );

  /* --------------------------------------------------------- active filters (removable) */

  /** value -> label, per facet. The manifest ships the display label precisely so the UI
   *  carries no lookup table; labelize() is the floor for a value with no bucket. */
  const labelIndex = useMemo(() => {
    const idx = {};
    if (facets && typeof facets === "object") {
      for (const name of Object.keys(facets)) {
        const list = facets[name];
        if (!Array.isArray(list)) continue;
        const m = new Map();
        for (const b of list) if (b && b.value != null) m.set(b.value, b.label || labelize(b.value));
        idx[name] = m;
      }
    }
    return idx;
  }, [facets]);

  const activeItems = useMemo(() => {
    const out = [];
    if (value.q && value.q.trim() !== "") {
      out.push({ id: "q", group: "Search", label: `“${value.q.trim()}”`, key: "q" });
    }
    for (const spec of ACTIVE_KEYS) {
      const raw = value[spec.key];
      const vals = spec.multi ? asArray(raw) : raw == null ? EMPTY : [raw];
      for (const v of vals) {
        const m = labelIndex[spec.facet];
        out.push({
          id: `${spec.key}:${v}`,
          /* Same rename as the chip group: a removable pill reading
             "Country: China" would re-assert, in the one place a buyer's own
             choice is echoed back, the thing the group label just stopped
             claiming. */
          group:
            geoDeclared && spec.facet === "country" ? "Locale (declared)" : spec.label,
          label: (m && m.get(v)) || labelize(v),
          key: spec.key,
          value: v,
          multi: spec.multi,
        });
      }
    }
    return out;
  }, [value, labelIndex, geoDeclared]);

  const clearAll = useCallback(() => {
    qOwn.current = "";
    setQDraft("");
    emit({
      q: "",
      category: EMPTY,
      subcategory: EMPTY,
      country: EMPTY,
      capture: null,
      modality: EMPTY,
      rights: EMPTY,
      hands: null,
      qa: EMPTY,
      split: EMPTY,
    });
  }, [emit]);

  const { clips, hours } = normalizeCount(resultCount);

  /* Full width: the grid's primary grouping, plus anything too wide to sit in a
     quarter-width column (see WIDE_AT). Everything else packs into the short row. */
  const isWide = (g) => g.tone === "primary" || g.buckets.length > WIDE_AT;
  const primaryGroups = groups.filter(isWide);
  const secondaryGroups = groups.filter((g) => !isWide(g));

  const renderGroup = (g) => (
    <ChipGroup
      key={g.key}
      groupId={`${uid}-${g.key}`}
      label={g.label}
      tone={g.tone}
      buckets={g.buckets}
      selected={g.selected}
      multi={g.multi}
      expanded={Boolean(expanded[g.key])}
      onExpand={() => setExpanded((prev) => ({ ...prev, [g.key]: !prev[g.key] }))}
      onToggle={(val, multi) => toggleChip(g.key, val, multi)}
      duration={Boolean(g.duration)}
      durationUnit={durationUnit}
    />
  );

  return (
    <>
      <div ref={sentinelRef} className="cat-fb__sentinel" aria-hidden="true" />
      <div
        ref={barRef}
        className={`cat-fb${stuck ? " is-stuck" : ""}`}
        role="search"
        aria-label="Filter clips"
      >
        <div className="cat-fb__bar">
          <div className="cat-fb__search">
            <Search className="cat-fb__searchicon" size={15} strokeWidth={1.8} aria-hidden="true" />
            <input
              ref={inputRef}
              id={`${uid}-q`}
              className="cat-fb__input"
              type="search"
              value={qDraft}
              onChange={(e) => setQDraft(e.target.value)}
              placeholder="Search clips…"
              aria-label="Search clips"
              autoComplete="off"
              spellCheck="false"
            />
            {qDraft ? (
              <button type="button" className="cat-fb__clearq" onClick={clearQuery} aria-label="Clear search">
                <X size={13} strokeWidth={2.4} aria-hidden="true" />
              </button>
            ) : (
              <kbd className="cat-fb__kbd" aria-hidden="true">
                /
              </kbd>
            )}
          </div>

          <div className="cat-fb__sort">
            <label className="cat-fb__glabel" htmlFor={`${uid}-sort`}>
              Sort
            </label>
            <select
              id={`${uid}-sort`}
              className="cat-fb__select"
              value={value.sort || "recent"}
              onChange={(e) => emit({ sort: e.target.value })}
            >
              {SORT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>

          <p className="cat-fb__count" aria-live="polite">
            <span className="cat-fb__count-n">{formatCount(clips)}</span>
            <span className="cat-fb__count-u">{clips === 1 ? "clip" : "clips"}</span>
            {hours == null ? null : (
              <span className="cat-fb__count-h">
                {hours < 0.1 && hours > 0 ? hours.toFixed(2) : hours.toFixed(1)} h
              </span>
            )}
          </p>
        </div>

        {groups.length ? (
          <div className="cat-fb__facets">
            {primaryGroups.length ? (
              <div className="cat-fb__facets-lead">{primaryGroups.map(renderGroup)}</div>
            ) : null}
            {/* Only SHORT groups reach here — anything with more than WIDE_AT
                buckets was promoted into the full-width block above. They pack
                into a wrapping, top-aligned row: natural widths, no padded-out
                tracks, and no group inheriting a taller neighbour's height. */}
            {secondaryGroups.length ? (
              <div className="cat-fb__facets-rest">{secondaryGroups.map(renderGroup)}</div>
            ) : null}
          </div>
        ) : null}

        {activeItems.length ? (
          <div className="cat-fb__active">
            <span className="cat-fb__glabel cat-fb__glabel--active">Filtering</span>
            <ul className="cat-fb__pills">
              {activeItems.map((it) => (
                <li key={it.id}>
                  <button
                    type="button"
                    className="cat-fb__apill"
                    onClick={() =>
                      it.key === "q" ? clearQuery() : removeValue(it.key, it.value, it.multi)
                    }
                    aria-label={`Remove filter ${it.group}: ${it.label}`}
                  >
                    <span className="cat-fb__apill-g">{it.group}</span>
                    <span className="cat-fb__apill-t">{it.label}</span>
                    <X className="cat-fb__apill-x" size={12} strokeWidth={2.6} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
            <button type="button" className="cat-fb__clearall" onClick={clearAll}>
              {`Clear all (${activeItems.length})`}
            </button>
          </div>
        ) : null}
      </div>
    </>
  );
}
