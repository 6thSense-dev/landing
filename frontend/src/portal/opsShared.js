/* Shared helpers for the ops area. Split out when the board grew tabs, so the
   Operations and Users screens format numbers and derive regions identically —
   two copies of regionOf() drifting apart would silently split one venue's
   episodes across two region filters. */

export const fmt = (n) => (n ?? 0).toLocaleString();
export const gb = (b) => `${((b ?? 0) / 1e9).toFixed(1)} GB`;
// "3.6 GB" instead of "3642 MB": four digits and a unit is the widest thing in
// the Min column, and nothing on this board is decided on the last 100 MB.
export const sizeChip = (mb) => (mb >= 1000 ? `${(mb / 1000).toFixed(1)} GB` : `${Math.round(mb)} MB`);

// Session names are S3 prefixes, so they are dated and they fork: one shoot in
// Korea is spread across `2026-09-03_korea-datafarm`, `…-mp4-only` and
// `2026-09-05_korea-6thsense`, and the operator asking "how is Korea doing" has
// to know all three. That is a question about a PLACE and the date in the prefix
// is about a delivery batch, so the region is DERIVED and nothing is renamed.
// Ported from region_of() in the laptop tool; keep the two in step.
export const REGION_WORDS = [
  ["korea", "Korea"], ["china", "China"], ["flowtest", "Flowtest"], ["trial", "Trial"],
];

export function regionOf(session) {
  let name = String(session ?? "");
  const cut = name.indexOf("_");
  // Strip a leading ISO date, but only if that is really what it is — a session
  // that simply has no date must keep its whole name rather than lose its first
  // word to the split.
  if (cut === 10 && /^\d{4}-\d{2}-\d{2}$/.test(name.slice(0, 10))) {
    name = name.slice(11);
  }
  const low = name.toLowerCase();
  for (const [needle, label] of REGION_WORDS) {
    if (low.includes(needle)) return label;
  }
  return name || "(unfiled)";
}

export const dayOf = (e) => (e.started_at || "").slice(0, 10);

// How long after a take was RECORDED its last byte landed. Bucketed rather than
// printed raw because the decision it feeds is coarse, and because uploads run
// as a nightly 02:00 batch: a ~20 hour lag is the NORMAL case and must not read
// as a problem. null means we do not know, never that it was fast.
export function uploadLagHours(startedAt, durationS, uploadedAt) {
  if (!startedAt || !uploadedAt) return null;
  const t0 = Date.parse(startedAt), t1 = Date.parse(uploadedAt);
  if (Number.isNaN(t0) || Number.isNaN(t1)) return null;
  return (t1 - (t0 + (durationS || 0) * 1000)) / 3.6e6;
}
