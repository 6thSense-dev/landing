import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { formatHours, formatMinutes, dash } from "./format.js";
import "./parts.chart.css";

/*
 * Task distribution — hand-rolled stacked-bar chart.
 *
 * Renders `catalog.benchmark` (see catalog.schema.json#/$defs/Benchmark):
 *   { unit: "hours"|"minutes"|"clips",
 *     series:     [{ id, label, color }],      // stacking order, bottom-up == legend order
 *     tasks:      [{ label, short_label?, clips, values: { [seriesId]: number } }],
 *     categories: [{ value, label, short_label?, clips, values: { [seriesId]: number } }] }
 *
 * No charting library: everything below is inline SVG laid out in real pixels from a
 * ResizeObserver measurement, so text never scales oddly the way it does under a
 * stretched viewBox.
 *
 * IT DOES NOT ALWAYS DRAW BARS, AND IT DOES NOT ALWAYS DRAW ONE BAR PER TASK.
 *
 * A stacked bar chart is a claim that the stacks differ from each other in a way
 * worth looking at. On the delivered corpus -- 29 clips of 30-45 s across 24 task
 * labels -- that claim is false at task level: it is roughly one clip per bar, so
 * the chart is 24 near-identical slabs of half a minute each. A staff engineer
 * reads that as a chart built because catalogs have charts, and it primes them to
 * distrust the numbers that DO matter.
 *
 * Two mechanisms answer that, in order:
 *
 *   1. AGGREGATION. The default view rolls the bars up to their CATEGORY -- the
 *      same taxonomy bucket `facets.category` is built from -- which turns 24
 *      one-clip bars into ~10 bars of two to three clips each, with real
 *      differences in height. Per-task detail is one click away.
 *
 *   2. FORM. Whatever the grouping, `clips` per bar decides how it is drawn:
 *        >= LIST_MODE_CLIPS_PER_BAR  ->  the stacked bars.
 *        below it                    ->  a plain count table: label, clips, magnitude.
 *      So "By category" draws the chart and "By task" shows the ledger, because
 *      that is what each level of the data can honestly support.
 *
 * The Top-N toggle is likewise suppressed unless the tallest bar actually towers
 * over the median, and a single-series legend is a static swatch rather than a
 * button that can blank the whole chart.
 *
 * ── WHERE THE CATEGORY BARS COME FROM ──────────────────────────────────────
 * `benchmark.categories[]` is a SECOND ROLL-UP PUBLISHED BY THE INGEST -- the same
 * clips and the same measured seconds as `tasks[]`, folded on `ClipSummary.category`
 * instead of the subcategory. It is read here verbatim.
 *
 * This component MUST NOT aggregate `tasks[]` into categories itself. It holds no
 * clip-to-category map, so client-side rolling would mean bucketing by display
 * label, and a label parse that mis-buckets is invisible until a buyer counts the
 * bars. The schema says so outright (catalog.schema.json#/$defs/Benchmark).
 *
 * A comparison bar (a published third-party whole-corpus total) appears in BOTH
 * arrays with `clips: null`, keyed on its series id, and belongs to no bucket of
 * ours -- the producer keeps it standing alone rather than folding it in.
 *
 * A manifest with no `categories` (or one that collapses to fewer than two bars,
 * or to no fewer bars than `tasks`) sets `canGroup` false: the segmented control
 * is not rendered and this is exactly the task-level chart. Nothing breaks.
 */

/* ── constants ──────────────────────────────────────────────────────────── */

// Fallback ramp for series that ship `color: null`. The contract says the UI may
// assign a colour by index from its own ramp; these ARE the catalog's ramp tokens,
// referenced rather than copied so the chart cannot drift from catalog.css. The
// last two are the extension of the ramp past what the tokens define.
const RAMP = [
  "var(--cat-series-1, #14120c)",
  "var(--cat-series-2, #9a8fb0)",
  "var(--cat-series-3, #6b7a99)",
  "var(--cat-series-4, #a69a60)",
  "var(--cat-series-5, #592202)",
  "#8a8560",
  "#c2b8a3",
];

const TOP_N = 20;

/**
 * Below this many clips per bar the bars carry no information the labels do not,
 * and the honest rendering is a count table. Two is the threshold because at two
 * takes per bar the heights can at least differ by a factor the eye can read; at
 * one they are the durations of individual clips lined up in a row.
 */
const LIST_MODE_CLIPS_PER_BAR = 2;

/**
 * The Top-N toggle only earns its place when there is a head to separate from a
 * tail. If the tallest bar is under this multiple of the median, "Top 20" of 24
 * near-identical bars is a control that changes nothing and looks accidental.
 */
const TOP_N_SPREAD = 3;

const PAD_T = 18; // breathing room above the tallest bar
const PAD_T_VALUES = 30; // …and the extra the direct value labels need
const PAD_R = 14;
const AXIS_TITLE_W = 18; // the rotated "MINUTES" caption
const GUTTER = 10; // between tick labels and the plot
const AXIS_MIN_W = 46;

/* Pitch is the per-bar slot width. Few bars get a wide slot -- 10 category bars
   crammed to 44px in a 1100px card is the "empty plot" defect, just relocated. */
const WIDE_N = 12;
const PITCH_MAX_WIDE = 88;
const PITCH_MAX = 46;
const BAR_MAX_WIDE = 40;
const BAR_MAX = 13;
const BAR_MIN = 3;

const NARROW = 720; // below this the plot is shorter and we scroll sooner
const TICK_CH = 6.2; // px advance of a Pretendard tabular digit at 11px
const LABEL_CH = 5.8; // px advance of mixed-case Pretendard at 11px
const VALUE_CH = 6.2;
/* Truncation bounds for the rotated x labels. Parallel 45-degree labels never
   collide with each other, so the real limits are how deep the label band may
   get (LABEL_MAX_CH) and how far the leftmost label may run before it leaves
   the card (derived per layout, below). */
const LABEL_MAX_CH = 18;
const LABEL_MIN_CH = 8;
/* Leading inset for the bars in scroll mode. Without it a rotated label runs
   left of the first bar, out of the plot and under the pinned axis, where a
   scrolled strip leaves it stranded beside a bar that is no longer on screen. */
const SCROLL_INSET = 40;
const SIN45 = Math.SQRT1_2;
const VALUE_MIN_PITCH = 42; // below this slot width a direct value label collides
const TIP_MAX_W = 288; // keep in step with .cat-chart-tip max-width

/* ── pure helpers ───────────────────────────────────────────────────────── */

// `dash` may be exported as the em-dash string or as a null-formatting helper.
const EM_DASH = (() => {
  try {
    return typeof dash === "function" ? dash(null) : dash || "—";
  } catch {
    return "—";
  }
})();

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function truncate(s, n) {
  const t = String(s);
  return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t;
}

/** 1 / 2 / 5 x 10^n. `round` snaps to the nearest, otherwise rounds up. */
function niceNum(range, round) {
  const exp = Math.floor(Math.log10(range));
  const frac = range / 10 ** exp;
  let nf;
  if (round) nf = frac < 1.5 ? 1 : frac < 3 ? 2 : frac < 7 ? 5 : 10;
  else nf = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10;
  return nf * 10 ** exp;
}

/**
 * Axis ticks from the actual data max — never a hardcoded ladder.
 * Returns the tick values, the axis top, and the decimals the step needs.
 */
function niceTicks(max, target) {
  if (!(max > 0) || !Number.isFinite(max)) return { ticks: [0], top: 1, decimals: 0 };
  // Derive the step from the raw max, not from a pre-rounded range: rounding 225 up
  // to 500 first costs a whole gridline and 33% dead headroom instead of 11%.
  const step = niceNum(max / Math.max(1, target - 1), true);
  const count = Math.ceil(max / step);
  const ticks = [];
  // Multiply rather than accumulate: 0.1 + 0.1 + 0.1 is not 0.3.
  for (let i = 0; i <= count; i += 1) ticks.push(i * step);
  return {
    ticks,
    top: count * step,
    decimals: clamp(-Math.floor(Math.log10(step)), 0, 6),
  };
}

/** Rect with only the top two corners rounded — for the topmost visible segment. */
function topRoundedPath(x, y, w, h, radius) {
  const r = Math.min(radius, w / 2, h);
  if (r <= 0.5) return `M${x} ${y}h${w}v${h}h${-w}Z`;
  return (
    `M${x} ${y + h}` +
    `L${x} ${y + r}` +
    `Q${x} ${y} ${x + r} ${y}` +
    `L${x + w - r} ${y}` +
    `Q${x + w} ${y} ${x + w} ${y + r}` +
    `L${x + w} ${y + h}` +
    "Z"
  );
}

function isRenderable(b) {
  return !!(
    b &&
    typeof b === "object" &&
    Array.isArray(b.series) &&
    b.series.length > 0 &&
    Array.isArray(b.tasks) &&
    b.tasks.length > 0
  );
}

/**
 * Normalise one published bar -- a `tasks[]` or a `categories[]` entry -- into the
 * row shape the renderer works in. Both arrays carry the same fields; `categories`
 * adds the machine `value`, which is the join key back to `facets.category`.
 *
 * Nothing is summed here. Both roll-ups arrive pre-folded from the ingest over the
 * same clips in the same unit, so the only job is to reject malformed entries.
 */
function rowsFrom(list, prefix) {
  if (!Array.isArray(list)) return [];
  return list
    .filter((t) => t && typeof t.label === "string" && t.label.trim() !== "")
    .map((t, sourceIndex) => ({
      key: `${prefix}:${typeof t.value === "string" && t.value ? t.value : sourceIndex}`,
      value: typeof t.value === "string" && t.value ? t.value : null,
      label: t.label,
      short: typeof t.short_label === "string" && t.short_label.trim() ? t.short_label.trim() : null,
      clips: Number.isFinite(t.clips) ? t.clips : null,
      values: t.values && typeof t.values === "object" ? t.values : {},
      sourceIndex,
    }));
}

/* ── segmented control ──────────────────────────────────────────────────── */

/**
 * A radiogroup of `.cat-pill`s. The pill is a shared component owned by
 * catalog.css, so the chart's controls restyle with every other control on the
 * page instead of inventing a third button idiom.
 */
function Segmented({ label, options, value, onChange }) {
  const onKeyDown = (e) => {
    if (!["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const dir = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : -1;
    const values = options.map((o) => o[0]);
    const i = values.indexOf(value);
    onChange(values[(i + dir + values.length) % values.length]);
    const group = e.currentTarget;
    // follow focus to whichever pill just became checked
    window.requestAnimationFrame(() => group.querySelector('[aria-checked="true"]')?.focus());
  };
  return (
    <div className="cat-pillgroup cat-chart-seg" role="radiogroup" aria-label={label} onKeyDown={onKeyDown}>
      {options.map(([v, l]) => (
        <button
          key={v}
          type="button"
          role="radio"
          className={`cat-pill${value === v ? " is-active" : ""}`}
          aria-checked={value === v}
          tabIndex={value === v ? 0 : -1}
          onClick={() => onChange(v)}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

/* ── the component ──────────────────────────────────────────────────────── */

export default function TaskDistribution({ benchmark }) {
  const ok = isRenderable(benchmark);

  // Hooks must run unconditionally, so everything below tolerates the empty case
  // and the `null` return happens at the very end.
  // `tasks[].values` are already expressed in `benchmark.unit` (CONTRACT.md §3.1.1),
  // so this only chooses a formatter — never a conversion. An unknown unit falls back
  // to hours, which is what a pre-`minutes` bundle means.
  const unit =
    ok && (benchmark.unit === "clips" || benchmark.unit === "minutes")
      ? benchmark.unit
      : "hours";
  const series = useMemo(
    () => (ok ? benchmark.series.filter((s) => s && typeof s.id === "string") : []),
    [ok, benchmark],
  );
  const note = ok && typeof benchmark.note === "string" && benchmark.note.trim() ? benchmark.note.trim() : null;

  const headingId = useId();
  const [view, setView] = useState("category"); // "category" | "task"
  const [mode, setMode] = useState("overall"); // "overall" | "top"
  const [hidden, setHidden] = useState(() => new Set());
  const [tip, setTip] = useState(null); // { i, source: "hover"|"focus" }
  const [width, setWidth] = useState(0);

  const barRefs = useRef([]);
  const detachRef = useRef(null);

  /* Measure the scroll container in real pixels.
   *
   * A CALLBACK ref, not useLayoutEffect over a ref object: the plot unmounts
   * whenever the view switches to the count table, and an effect keyed on
   * mount alone would leave the ResizeObserver watching a detached node and
   * the remounted plot stuck on a stale width. The callback runs on every
   * attach and detach, which is exactly the lifecycle being tracked.
   * It fires during commit, so `width` is set before the first paint. */
  const wrapRef = useCallback((el) => {
    if (detachRef.current) {
      detachRef.current();
      detachRef.current = null;
    }
    if (!el) return;
    const read = () => setWidth(el.clientWidth || el.getBoundingClientRect().width || 0);
    read();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", read);
      detachRef.current = () => window.removeEventListener("resize", read);
      return;
    }
    const ro = new ResizeObserver((entries) => {
      const cr = entries[0]?.contentRect;
      setWidth(cr ? cr.width : el.clientWidth);
    });
    ro.observe(el);
    detachRef.current = () => ro.disconnect();
  }, []);

  useEffect(
    () => () => {
      if (detachRef.current) detachRef.current();
    },
    [],
  );

  /* ── source rows: the two published roll-ups, read as-is (never re-folded) ── */

  const taskRows = useMemo(() => (ok ? rowsFrom(benchmark.tasks, "t") : []), [ok, benchmark]);
  const categoryRows = useMemo(
    () => (ok ? rowsFrom(benchmark.categories, "c") : []),
    [ok, benchmark],
  );

  /* Offering "By category" is only honest when the published roll-up actually
     aggregates: two or more bars, and strictly fewer of them than the task view.
     A manifest with no `categories` array, or one that is a 1:1 restatement of
     `tasks`, fails that and the control does not appear at all. */
  const canGroup = categoryRows.length >= 2 && categoryRows.length < taskRows.length;

  const activeView = canGroup ? view : "task";
  const sourceRows = activeView === "category" ? categoryRows : taskRows;

  const setViewAndReset = useCallback((v) => {
    setView(v);
    setMode("overall");
    setTip(null);
  }, []);

  const visible = useMemo(() => series.filter((s) => !hidden.has(s.id)), [series, hidden]);

  /* totals over the *visible* series, so hiding one keeps the chart descending */
  const ordered = useMemo(() => {
    const rows = sourceRows.map((t) => {
      const parts = [];
      let total = 0;
      series.forEach((s, si) => {
        const raw = t.values[s.id];
        const v = typeof raw === "number" && Number.isFinite(raw) && raw > 0 ? raw : 0;
        const shown = v > 0 && !hidden.has(s.id);
        if (shown) total += v;
        // resolve the colour once here so the two render sites cannot disagree
        parts.push({ id: s.id, label: s.label, color: s.color || RAMP[si % RAMP.length], value: v, shown });
      });
      return { ...t, parts, total };
    });
    rows.sort((a, b) => b.total - a.total || a.sourceIndex - b.sourceIndex);
    return rows;
  }, [sourceRows, series, hidden]);

  /* Clips per bar, from the manifest. Comparison bars carry null and are excluded
     from both the count and the denominator: they are whole-corpus totals, not our
     takes, and folding them in would flatter the ratio. */
  const shape = useMemo(() => {
    const own = ordered.filter((t) => Number.isFinite(t.clips));
    if (own.length === 0) return { known: false, perBar: null, clips: 0, bars: 0 };
    const clips = own.reduce((sum, t) => sum + t.clips, 0);
    return { known: true, perBar: clips / own.length, clips, bars: own.length };
  }, [ordered]);

  const listMode = shape.known && shape.perBar < LIST_MODE_CLIPS_PER_BAR;

  const tasks = mode === "top" && !listMode ? ordered.slice(0, TOP_N) : ordered;
  barRefs.current.length = tasks.length;

  /* A toggle over 24 bars that are all within a small factor of each other is a
     control that appears to do nothing. Require a real head-and-tail first. */
  const spread = useMemo(() => {
    if (ordered.length === 0) return 0;
    const sorted = ordered.map((t) => t.total).sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)];
    return median > 0 ? sorted[sorted.length - 1] / median : 0;
  }, [ordered]);
  const showModeToggle = !listMode && ordered.length > TOP_N && spread >= TOP_N_SPREAD;

  const dataMax = tasks.length ? tasks[0].total : 0; // already sorted descending
  const axis = useMemo(() => niceTicks(dataMax, 6), [dataMax]);

  /* ── formatters ── */

  // `formatHours` is only correct for the hours unit; clips get a plain count.
  const fmt = (v) => {
    if (!Number.isFinite(v)) return EM_DASH;
    if (unit === "hours") return formatHours(v);
    if (unit === "minutes") return formatMinutes(v);
    const digits = Math.abs(v) < 10 && !Number.isInteger(v) ? 1 : 0;
    return `${v.toLocaleString(undefined, { maximumFractionDigits: digits })} clips`;
  };

  /* Printed magnitudes -- the label above a bar, the magnitude column of the
     table -- carry no unit: the axis title and the column header each say it
     once, and repeating " min" on 24 rows is ink without information.
     They also share ONE decimal count, chosen so the SMALLEST value in the set
     keeps three significant digits. A column formatted per-value ("1.41" beside
     "0.746") is ragged and defeats the tabular figures. */
  const valueDecimals = (() => {
    if (unit === "clips") return tasks.every((t) => Number.isInteger(t.total)) ? 0 : 1;
    const positive = tasks.map((t) => t.total).filter((v) => v > 0);
    if (positive.length === 0) return axis.decimals;
    return clamp(2 - Math.floor(Math.log10(Math.min(...positive))), 0, 4);
  })();
  const col = (v) =>
    Number.isFinite(v)
      ? v.toLocaleString("en-US", {
          minimumFractionDigits: valueDecimals,
          maximumFractionDigits: valueDecimals,
        })
      : EM_DASH;

  /* ── layout, in real pixels ── */
  const n = tasks.length;
  const narrow = width > 0 && width < NARROW;
  const plotH = narrow ? 176 : 244;

  const tickText = axis.ticks.map((v) => v.toFixed(axis.decimals));
  const tickW = clamp(Math.max(...tickText.map((t) => t.length)) * TICK_CH, 18, 64);
  const axisW = Math.max(AXIS_MIN_W, Math.ceil(AXIS_TITLE_W + tickW + GUTTER));

  // Below the min pitch we scroll rather than squeeze 24 bars into 360px.
  const minPitch = narrow ? 22 : 15;
  const availW = Math.max(0, width - axisW - PAD_R);
  const fitPitch = n > 0 ? availW / n : 0;
  const scroll = n > 0 && fitPitch < minPitch;
  const pitchCap = n <= WIDE_N ? PITCH_MAX_WIDE : PITCH_MAX;
  const pitch = scroll ? minPitch : Math.min(fitPitch, pitchCap);

  // The plot is sized to `n * pitch` and the frame is centred, never stretched
  // to the container: capping pitch while keeping the container width is what
  // left the bars in the left fifth of the card with a void to their right at
  // 768.
  const plotPadL = scroll ? SCROLL_INSET : 0;
  const plotW = pitch * n;
  const plotSvgW = Math.max(1, plotPadL + plotW + PAD_R);

  /* A -45 degree label runs up and to the LEFT of the bar it names, so the
     leftmost one is bounded by whatever room there is before the plot starts:
     the axis column when the plot is static, the scroll inset when it is not.
     Truncating to a fixed 14 characters instead either wasted a wide layout or
     pushed the first label off the card at 360. */
  const labelMaxCh = clamp(
    Math.floor(((scroll ? SCROLL_INSET : axisW - 6) + pitch / 2) / (LABEL_CH * SIN45)),
    LABEL_MIN_CH,
    LABEL_MAX_CH,
  );
  const axisLabels = tasks.map((t) => truncate(t.short || t.label, labelMaxCh));
  const longest = axisLabels.reduce((m, str) => Math.max(m, str.length), 0);
  const xBand = clamp(Math.ceil(longest * LABEL_CH * SIN45) + 16, 38, 92);

  const allHidden = visible.length === 0;
  const valueText = tasks.map((t) => col(t.total));
  const widestValue = valueText.reduce((m, s) => Math.max(m, s.length), 0) * VALUE_CH;
  /* Direct labels beat a tooltip whenever they fit — a reader should not have to
     hover to learn a number that had room to be printed. */
  const showValues = !allHidden && n > 0 && n <= 18 && pitch >= VALUE_MIN_PITCH && widestValue <= pitch - 8;

  const padT = showValues ? PAD_T_VALUES : PAD_T;
  const plotB = padT + plotH;
  const svgH = padT + plotH + xBand;
  const barW = clamp(pitch * (n <= WIDE_N ? 0.5 : 0.6), BAR_MIN, n <= WIDE_N ? BAR_MAX_WIDE : BAR_MAX);
  const yOf = (v) => plotB - (axis.top > 0 ? (v / axis.top) * plotH : 0);

  /* clear a stale tooltip when the bar it pointed at goes away */
  useEffect(() => {
    if (tip && tip.i >= tasks.length) setTip(null);
  }, [tip, tasks.length]);

  const toggleSeries = useCallback((id) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const onBarKeyDown = useCallback((e, i) => {
    if (e.key === "Escape") return setTip(null);
    const delta = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    const next = delta && barRefs.current[i + delta];
    if (!next || typeof next.focus !== "function") return undefined;
    e.preventDefault();
    return next.focus();
  }, []);

  if (!ok) return null;

  const active = tip ? tasks[tip.i] : null;
  /* With one visible series the breakdown row and the total row are the same
     number twice. Print it once. */
  const allTipRows = active ? active.parts.filter((p) => p.shown && p.value > 0) : [];
  const tipRows = allTipRows.length > 1 ? allTipRows : [];
  const unitTitle = unit === "clips" ? "Clips" : unit === "minutes" ? "Minutes" : "Hours";
  const barNoun = activeView === "category" ? "categories" : "tasks";
  const barNoun1 = activeView === "category" ? "category" : "task";

  /* Tooltip placement, in plot coordinates (it scrolls with the strip).
     Anchored three ways rather than clamped: a clamped centre walks the box
     over the y axis when the leftmost bar is probed, which hides the very
     scale the number is being read against. */
  let tipStyle = null;
  if (active) {
    const cx = plotPadL + tip.i * pitch + pitch / 2;
    const barTop = yOf(active.total);
    const estH = 46 + tipRows.length * 18 + (tipRows.length ? 10 : 0);
    const above = barTop - estH - 10 >= 0;
    const half = TIP_MAX_W / 2 + 8;
    let left = cx;
    let tx = "-50%";
    if (plotSvgW <= TIP_MAX_W + 16) {
      left = plotSvgW / 2; // narrower than the box: centre it on the plot
    } else if (cx < half) {
      left = 0;
      tx = "0";
    } else if (plotSvgW - cx < half) {
      left = plotSvgW;
      tx = "-100%";
    }
    tipStyle = {
      left: `${left}px`,
      top: `${above ? barTop - 10 : Math.min(barTop + 12, plotB - 8)}px`,
      transform: `translate(${tx}, ${above ? "-100%" : "0"})`,
    };
  }

  return (
    <section className="cat-chart" aria-labelledby={headingId}>
      <header className="cat-chart-head">
        <div className="cat-chart-heading">
          <p className="cat-label cat-chart-eyebrow">Coverage</p>
          <h2 className="cat-h2 cat-chart-title" id={headingId}>
            {listMode ? "What was captured" : "Distribution"}
          </h2>
        </div>
        <div className="cat-chart-controls">
          {canGroup && (
            <Segmented
              label="Group task distribution by"
              options={[
                ["category", "By category"],
                ["task", "By task"],
              ]}
              value={activeView}
              onChange={setViewAndReset}
            />
          )}
          {showModeToggle && (
            <Segmented
              label="Task distribution scope"
              options={[
                ["overall", "Overall"],
                ["top", `Top ${TOP_N}`],
              ]}
              value={mode}
              onChange={setMode}
            />
          )}
        </div>
      </header>

      <div className="cat-chart-card">
        <div className="cat-chart-toolbar">
          <ul className="cat-chart-legend">
            {series.map((s, i) => {
              const on = !hidden.has(s.id);
              const dot = (
                <span
                  className="cat-chart-dot"
                  style={{ background: s.color || RAMP[i % RAMP.length] }}
                  aria-hidden="true"
                />
              );
              /* One series has nothing to isolate FROM. Making it a toggle offers
                 exactly one action -- blank the chart -- so it is a swatch. */
              if (series.length < 2) {
                return (
                  <li key={s.id}>
                    <span className="cat-chart-legend-static">
                      {dot}
                      <span className="cat-chart-legend-label">{s.label}</span>
                    </span>
                  </li>
                );
              }
              return (
                <li key={s.id}>
                  <button
                    type="button"
                    className={`cat-chart-legend-btn${on ? "" : " is-off"}`}
                    aria-pressed={on}
                    onClick={() => toggleSeries(s.id)}
                  >
                    {dot}
                    <span className="cat-chart-legend-label">{s.label}</span>
                  </button>
                </li>
              );
            })}
          </ul>

          {shape.known && (
            <p className="cat-chart-count">
              <span className="cat-chart-count-n">{tasks.length}</span>
              <span className="cat-chart-count-w">{tasks.length === 1 ? barNoun1 : barNoun}</span>
              <span className="cat-chart-count-sep" aria-hidden="true" />
              <span className="cat-chart-count-n">{shape.clips}</span>
              <span className="cat-chart-count-w">{shape.clips === 1 ? "clip" : "clips"}</span>
            </p>
          )}
        </div>

        <p className="cat-chart-sr">
          {listMode
            ? `Clips and ${unitTitle.toLowerCase()} per ${barNoun1}, as a table. ${tasks.length} ` +
              `${tasks.length === 1 ? barNoun1 : barNoun} across ${shape.clips} clips.`
            : `Stacked bar chart, ${unitTitle.toLowerCase()} per ${barNoun1}. ${tasks.length} ` +
              `${tasks.length === 1 ? barNoun1 : barNoun}, ${visible.length} of ${series.length} series shown. ` +
              "Each bar is focusable and reports its own breakdown."}
        </p>

        {listMode ? (
          /* One to two takes per bar. A count table says the same thing the bars
             would have, without implying a distribution that is not there. */
          <div className="cat-chart-tablewrap">
            <table className="cat-chart-table">
              <thead>
                <tr>
                  <th className="cat-label" scope="col">
                    {barNoun1}
                  </th>
                  <th className="cat-label" scope="col">
                    Clips
                  </th>
                  <th className="cat-label" scope="col">
                    {unitTitle}
                  </th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((t) => (
                  <tr key={t.key}>
                    <th scope="row" className="cat-chart-table-label" title={t.label}>
                      {t.label}
                    </th>
                    <td className="cat-chart-table-num">
                      {t.clips == null ? EM_DASH : t.clips}
                    </td>
                    <td className="cat-chart-table-num is-strong">{col(t.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div
            className={`cat-chart-plotwrap${scroll ? " is-scroll" : ""}`}
            ref={wrapRef}
            style={{ minHeight: `${svgH}px` }}
          >
            {width === 0 ? (
              /* Exact final height, so the measured render does not shift it. */
              <div className="cat-skeleton cat-chart-skeleton" style={{ height: `${svgH}px` }} />
            ) : (
              <div className="cat-chart-frame">
                {/* The y axis is its own SVG so it can stay pinned while the bar
                    strip scrolls under it at 360px — an axis that scrolls out of
                    view takes the only key to the bar heights with it. */}
                <div className="cat-chart-axis" style={{ width: `${axisW}px`, height: `${svgH}px` }}>
                  <svg width={axisW} height={svgH} aria-hidden="true" focusable="false">
                    {scroll && <rect className="cat-chart-axisbg" x="0" y="0" width={axisW} height={svgH} />}
                    {axis.ticks.map((v, i) => (
                      <text key={v} className="cat-chart-tick" x={axisW - GUTTER} y={yOf(v)} dy="0.32em">
                        {tickText[i]}
                      </text>
                    ))}
                    <text
                      className="cat-label cat-chart-axistitle"
                      transform={`translate(${AXIS_TITLE_W / 2 + 1} ${padT + plotH / 2}) rotate(-90)`}
                    >
                      {unitTitle}
                    </text>
                  </svg>
                </div>

                <div className="cat-chart-canvas" style={{ width: `${plotSvgW}px`, height: `${svgH}px` }}>
                  <svg width={plotSvgW} height={svgH} className="cat-chart-svg">
                    {/* gridlines */}
                    <g aria-hidden="true">
                      {axis.ticks.map((v, i) => (
                        <line
                          key={v}
                          className={i === 0 ? "cat-chart-baseline" : "cat-chart-gridline"}
                          x1={0}
                          x2={plotSvgW}
                          y1={yOf(v)}
                          y2={yOf(v)}
                        />
                      ))}
                    </g>

                    {/* bars */}
                    {allHidden ? (
                      <text className="cat-chart-empty" x={plotSvgW / 2} y={padT + plotH / 2}>
                        {`No series shown ${EM_DASH} re-enable one above`}
                      </text>
                    ) : (
                      <g
                        role="list"
                        aria-label={`${barNoun1 === "category" ? "Categories" : "Tasks"} by ${unitTitle.toLowerCase()}`}
                        className={`cat-chart-bars${tip ? " is-probing" : ""}`}
                      >
                        {tasks.map((t, i) => {
                          const x = plotPadL + i * pitch + (pitch - barW) / 2;
                          const cx = plotPadL + i * pitch + pitch / 2;
                          const shown = t.parts.filter((p) => p.shown && p.value > 0);
                          const topIdx = shown.length - 1;
                          let cum = 0;
                          const isOn = tip && tip.i === i;
                          const breakdown = shown.map((p) => `${p.label} ${fmt(p.value)}`).join(", ");
                          const clipNote = Number.isFinite(t.clips)
                            ? `. ${t.clips} ${t.clips === 1 ? "clip" : "clips"}`
                            : "";
                          return (
                            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
                            <g
                              key={t.key}
                              role="listitem"
                              tabIndex={0}
                              ref={(el) => {
                                barRefs.current[i] = el;
                              }}
                              className={`cat-chart-bar${isOn ? " is-active" : ""}`}
                              style={{ "--cat-bar-i": String(Math.min(i, 11)) }}
                              aria-label={`${t.label}. Total ${fmt(t.total)}${clipNote}${breakdown ? `. ${breakdown}` : ""}`}
                              onMouseEnter={() => setTip({ i, source: "hover" })}
                              onMouseLeave={() => setTip((p) => (p && p.i === i && p.source === "hover" ? null : p))}
                              onFocus={() => setTip({ i, source: "focus" })}
                              onBlur={() => setTip((p) => (p && p.i === i && p.source === "focus" ? null : p))}
                              onKeyDown={(e) => onBarKeyDown(e, i)}
                            >
                              {/* full-height hit target: hovering a 10px bar is otherwise fiddly */}
                              <rect
                                className="cat-chart-hit"
                                x={plotPadL + i * pitch}
                                y={padT}
                                width={pitch}
                                height={plotH}
                              />
                              <g className="cat-chart-stack">
                                {shown.map((p, k) => {
                                  const y1 = yOf(cum + p.value);
                                  const y0 = yOf(cum);
                                  cum += p.value;
                                  const h = y0 - y1;
                                  if (!(h > 0)) return null;
                                  // 0.4px of overlap downward kills the antialiased seam
                                  const hh = k === 0 ? h : h + 0.4;
                                  return k === topIdx ? (
                                    <path key={p.id} d={topRoundedPath(x, y1, barW, hh, 3)} fill={p.color} />
                                  ) : (
                                    <rect key={p.id} x={x} y={y1} width={barW} height={hh} fill={p.color} />
                                  );
                                })}
                                {showValues && t.total > 0 && (
                                  <text className="cat-chart-value" x={cx} y={yOf(t.total) - 9}>
                                    {valueText[i]}
                                  </text>
                                )}
                              </g>
                            </g>
                          );
                        })}
                      </g>
                    )}

                    {/* x labels, rotated out of the plot */}
                    <g aria-hidden="true">
                      {tasks.map((t, i) => (
                        <text
                          key={`${t.key}-lbl`}
                          className={`cat-chart-xlabel${tip && tip.i === i ? " is-active" : ""}`}
                          transform={`translate(${plotPadL + i * pitch + pitch / 2} ${plotB + 13}) rotate(-45)`}
                        >
                          <title>{t.label}</title>
                          {axisLabels[i]}
                        </text>
                      ))}
                    </g>
                  </svg>

                  {active && (
                    <div className="cat-chart-tip" style={tipStyle} role="presentation">
                      <p className="cat-chart-tip-title">{active.label}</p>
                      {tipRows.length > 0 && (
                        <dl className="cat-chart-tip-rows">
                          {tipRows.map((p) => (
                            <div key={p.id}>
                              <dt>
                                <span className="cat-chart-dot" style={{ background: p.color }} aria-hidden="true" />
                                <span className="cat-chart-tip-name">{p.label}</span>
                              </dt>
                              <dd>{fmt(p.value)}</dd>
                            </div>
                          ))}
                        </dl>
                      )}
                      <p className={`cat-chart-tip-total${tipRows.length ? "" : " is-only"}`}>
                        <span>{Number.isFinite(active.clips) ? `${active.clips} ${active.clips === 1 ? "clip" : "clips"}` : "Total"}</span>
                        <span>{fmt(active.total)}</span>
                      </p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {note && <p className="cat-chart-note">{note}</p>}
      </div>
    </section>
  );
}
