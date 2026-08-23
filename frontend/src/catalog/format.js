/**
 * format.js — every string the catalog shows a buyer is produced here.
 *
 * One rule governs this file: `null` means "the ingest could not determine
 * this". It never means zero, never means false, and it is ALWAYS rendered as
 * an em-dash. `dash()` is the only sanctioned way to render an unknown, and
 * every formatter below routes through the same convention so a null can never
 * silently become "0", "0:00" or "".
 *
 * No dependencies. Pure functions. Safe to copy into the real site as-is.
 */

/** The one character an unknown is allowed to render as. */
export const EM_DASH = "—";

/**
 * The ONLY way unknowns are rendered.
 *
 * Deliberately `== null` (loose): it catches both null and undefined, and
 * nothing else. `0`, `false` and `""` are real, determined values and pass
 * straight through.
 */
export function dash(v) {
  return v == null ? EM_DASH : v;
}

/** True for a finite number. Guards every numeric formatter below. */
function isNum(n) {
  return typeof n === "number" && Number.isFinite(n);
}

/**
 * Seconds -> "M:SS". null/undefined/non-finite/negative -> em-dash.
 *
 * Durations over an hour keep counting minutes ("61:40") rather than growing an
 * hours field, because the card's mono duration column is sized for M:SS and
 * clips are minutes long. Seconds are rounded, not truncated: 84.6 s is 1:25.
 */
export function formatDuration(seconds) {
  if (!isNum(seconds) || seconds < 0) return EM_DASH;
  const total = Math.round(seconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m + ":" + String(s).padStart(2, "0");
}

const BYTE_UNITS = ["B", "kB", "MB", "GB", "TB", "PB"];

/**
 * Byte count -> "1.4 GB". null/undefined/non-finite/negative -> em-dash.
 *
 * Decimal SI (1000), matching the unit labels used: kB/MB/GB mean 10^3/10^6/10^9.
 * Mixing 1024 with an SI label is precisely the factor-of-1024 error the
 * contract warns about, so the base and the label agree here by construction.
 * Bytes render whole; every other unit gets at most one decimal, with a
 * trailing ".0" trimmed (2 GB, not 2.0 GB).
 */
export function formatBytes(n) {
  if (!isNum(n) || n < 0) return EM_DASH;
  if (n < 1000) return Math.round(n) + " B";
  let value = n;
  let unit = 0;
  while (value >= 1000 && unit < BYTE_UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return trimZeros(value.toFixed(1)) + " " + BYTE_UNITS[unit];
}

/**
 * Hours -> "84.6 h". null/undefined/non-finite/negative -> em-dash.
 *
 * Precision scales with magnitude so a small honest total survives. 0.0235 h is
 * the true figure for a single 84.6 s sample; rounding it to "0 h" hides the
 * entire collection, which is the specific failure the contract calls out.
 */
export function formatHours(h) {
  if (!isNum(h) || h < 0) return EM_DASH;
  if (h === 0) return "0 h";
  let decimals;
  if (h >= 10) decimals = 1;
  else if (h >= 1) decimals = 2;
  // Below 1 h, keep three significant digits rather than a fixed decimal count.
  else decimals = Math.min(6, 2 - Math.floor(Math.log10(h)));
  return trimZeros(h.toFixed(decimals)) + " h";
}

/**
 * Minutes -> "18.3 min". null/undefined/non-finite/negative -> em-dash.
 *
 * Same precision ladder as `formatHours`, one decade down: a ~20 minute corpus is
 * exactly the case `duration_unit: "minutes"` exists for, and the individual task
 * bars in it run to fractions of a minute.
 */
export function formatMinutes(m) {
  if (!isNum(m) || m < 0) return EM_DASH;
  if (m === 0) return "0 min";
  let decimals;
  if (m >= 10) decimals = 1;
  else if (m >= 1) decimals = 2;
  else decimals = Math.min(6, 2 - Math.floor(Math.log10(m)));
  return trimZeros(m.toFixed(decimals)) + " min";
}

const COUNT_FMT = new Intl.NumberFormat("en-US");

/** Integer -> "29,507". null/undefined/non-finite -> em-dash. */
export function formatCount(n) {
  if (!isNum(n)) return EM_DASH;
  return COUNT_FMT.format(n);
}

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/**
 * "2026-08" -> "Aug 2026". Anything that is not a valid YYYY-MM -> em-dash.
 *
 * Parsed by hand rather than through Date: `new Date("2026-08")` is UTC
 * midnight, which in any negative-offset timezone renders as July.
 */
export function formatMonth(ym) {
  if (typeof ym !== "string") return EM_DASH;
  const m = /^(\d{4})-(0[1-9]|1[0-2])$/.exec(ym);
  if (!m) return EM_DASH;
  return MONTHS[Number(m[2]) - 1] + " " + m[1];
}

/* ------------------------------------------------------------------ */
/* Extras. Not part of the agreed interface, but used across the app   */
/* so the same value never gets formatted two different ways.          */
/* ------------------------------------------------------------------ */

/**
 * lower_snake_case -> "Bin picking".
 *
 * Facet buckets ship a `label` and the UI MUST prefer it — that is why labels
 * are in the data. This is the fallback for the places a raw enum value is all
 * we have (a clip's own `category`/`subcategory`, which carry no label).
 */
export function labelize(value) {
  if (typeof value !== "string" || value === "") return EM_DASH;
  const words = value.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/**
 * [1920, 600] -> "1920 x 600". Anything else -> em-dash.
 * Uses a real multiplication sign, not the letter x.
 */
export function formatResolution(res) {
  if (!Array.isArray(res) || res.length < 2) return EM_DASH;
  const [w, h] = res;
  if (!isNum(w) || !isNum(h)) return EM_DASH;
  return w + "×" + h;
}

/**
 * 30.06 -> "30.06 fps". Never rounds to an integer: rounding is how a 2 ms/s
 * drift becomes invisible, which the contract names explicitly.
 */
export function formatFps(fps) {
  if (!isNum(fps) || fps <= 0) return EM_DASH;
  return trimZeros(fps.toFixed(2)) + " fps";
}

/**
 * Fraction in [0,1] -> "99.99%". Kept at enough precision to distinguish a CRC
 * pass rate of 0.9999 (grade A) from 0.999 (grade B), which one decimal cannot.
 */
export function formatPercent(fraction, decimals = 2) {
  if (!isNum(fraction)) return EM_DASH;
  return trimZeros((fraction * 100).toFixed(decimals)) + "%";
}

/** "12.30" -> "12.3", "2.0" -> "2". Never touches a string without a dot. */
function trimZeros(s) {
  return s.indexOf(".") === -1 ? s : s.replace(/\.?0+$/, "");
}
