/**
 * parts.jsx — the definition-list primitives every metadata-shaped tab uses.
 *
 * Extracted from MetadataTab when the Calibration & sync tab landed and needed
 * the same `Def` / `Block` pair. Two copies of a renderer whose whole job is to
 * apply ONE rendering rule consistently is how the rule stops being consistent,
 * and the rule here is the contract's R2:
 *
 *   `null` means the ingest could not determine the value. It is drawn as an
 *   em-dash. It is never drawn as 0, never as "No", never as an empty cell.
 *
 * An em-dash in a buyer-facing record reads as "no assessment was made", which
 * counsel treats as worse than a determined "No" — so it must never be produced
 * by accident, and a real 0 must never be turned into one.
 */

import { ArrowUpRight } from "lucide-react";

import { assetUrl } from "../useCatalog.js";
import { dash } from "../format.js";

/** `rolling_shutter` -> `Rolling shutter`. null/"" -> null (never "Null"). */
export function humanise(value) {
  if (value == null || value === "") return null;
  const s = String(value).replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** true -> Yes, false -> No, null/undefined -> em-dash (contract rule R2). */
export function yesNo(v) {
  if (v === true) return "Yes";
  if (v === false) return "No";
  return dash(null);
}

/**
 * A number to `digits` decimals, or null.
 *
 * Explicitly NOT `value || null`: 0 is a real measurement here (a zero clock
 * offset, a zero drift) and rendering it as an em-dash would turn a determined
 * answer into "we did not look".
 */
export function num(value, digits = 3, unit = "") {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const text = digits == null ? String(value) : value.toFixed(digits);
  return unit ? `${text} ${unit}` : text;
}

/** An asset reference to something fetchable, or null. Never throws. */
export function href(url) {
  if (!url) return null;
  if (/^https:\/\//.test(url)) return url;
  try {
    return assetUrl(url);
  } catch {
    return null;
  }
}

/** One label/value pair in a `cat-m-defs` grid. */
export function Def({ label, value, mono, title }) {
  /* yesNo()/dash() already resolve an unknown to an em-dash, so treat that
     string as empty too and the "unknown" styling stays consistent. */
  const empty = value == null || value === "" || value === "—";
  return (
    <div className="cat-m-def" title={title}>
      <dt className="cat-label">{label}</dt>
      <dd className={`${mono ? "cat-mono " : ""}${empty ? "cat-m-def--dash" : ""}`}>
        {empty ? dash(null) : value}
      </dd>
    </div>
  );
}

/**
 * A titled section with an optional right-aligned aside.
 *
 * The aside is NOT mono. It carries counts and dates ("12 files · 3.4 MB",
 * "reviewed 2026-01-02", "independent validation: passed") — measurements and
 * prose, not machine strings — so it is Pretendard with tabular figures, which
 * `.cat-m-aside` sets.
 */
export function Block({ title, aside, children }) {
  return (
    <section className="cat-m-block">
      <h4 className="cat-m-blocktitle">
        <span className="cat-label">{title}</span>
        {aside ? <span className="cat-m-aside">{aside}</span> : null}
      </h4>
      {children}
    </section>
  );
}

/** A document link, rendered only when the URL survived redaction. */
export function DocLink({ url, children }) {
  const target = href(url);
  if (!target) return null;
  return (
    <a className="cat-m-doclink" href={target} target="_blank" rel="noreferrer noopener">
      <span>{children}</span>
      <ArrowUpRight size={12} aria-hidden="true" />
    </a>
  );
}
