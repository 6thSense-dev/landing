/**
 * SegcapTab — segment captions.
 * ---------------------------------------------------------------------------
 * Props: { clip }
 *
 * A proportional ribbon of clip.segments over the clip's duration, plus one row
 * per segment: index, mono t0–t1, duration, label, verb, object chips,
 * description, and the annotation source (buyers price human annotation and
 * model output very differently, so the two are never conflated).
 *
 * Clicking a row jumps to that moment in the Video tab. The tabs only receive
 * `{ clip }`, so the request travels as a window event rather than a prop:
 *
 *   window.__6sCatalogSeek = { clipId, t_s, at }          <- mailbox
 *   window.dispatchEvent(new CustomEvent("6s-catalog:seek", { detail }))
 *
 * ClipDetail hears the event and switches to the Video tab; VideoTab hears it
 * and seeks, or -- if it was not mounted when the event fired -- drains the
 * mailbox on mount. Both are documented in ClipDetail.jsx.
 */

import { useMemo, useState } from "react";
import { Play } from "lucide-react";

import { formatDuration } from "../format.js";

const SEEK_EVENT = "6s-catalog:seek";
const SEEK_MAILBOX = "__6sCatalogSeek";

/** Ask the Video tab to move the playhead to `t_s`. */
export function requestSeek(clipId, t_s) {
  if (typeof window === "undefined") return;
  const detail = { clipId, t_s, at: Date.now() };
  window[SEEK_MAILBOX] = detail;
  window.dispatchEvent(new CustomEvent(SEEK_EVENT, { detail }));
}

export default function SegcapTab({ clip }) {
  const segments = useMemo(
    () => (Array.isArray(clip?.segments) ? clip.segments : []),
    [clip]
  );
  const [active, setActive] = useState(null);

  const total = useMemo(() => {
    const fromClip = Number(clip?.duration_s);
    if (Number.isFinite(fromClip) && fromClip > 0) return fromClip;
    return segments.reduce((m, s) => Math.max(m, Number(s.t1_s) || 0), 0);
  }, [clip, segments]);

  if (segments.length === 0) {
    const stated = (clip?.known_limitations || []).find((l) =>
      /annotat|segment|caption|label/i.test(l)
    );
    return (
      <div className="cat-empty">
        <p className="cat-empty__head">This clip is not annotated</p>
        <p className="cat-empty__body">
          <code>segments</code> is an empty array, which is a determined answer and not a missing
          field: nobody has labelled this take.
          {stated ? (
            <>
              {" "}
              The record says so in its own words: <em>{stated}</em>
            </>
          ) : null}
        </p>
      </div>
    );
  }

  const counted = segments.length;
  const covered = segments.reduce(
    (sum, s) => sum + Math.max(0, (Number(s.t1_s) || 0) - (Number(s.t0_s) || 0)),
    0
  );
  const sources = Array.from(new Set(segments.map((s) => s.source || "unstated")));

  return (
    <section className="cat-sc">
      <header className="cat-sc-head">
        <div>
          <h3 className="cat-sc-title">Segment captions</h3>
          <p className="cat-sc-sub">
            {counted} segment{counted === 1 ? "" : "s"} covering {formatDuration(covered)} of{" "}
            {formatDuration(total)}
            {total > 0 ? ` (${Math.round((covered / total) * 100)}%)` : ""} · source{" "}
            {sources.join(", ")}
          </p>
        </div>
      </header>

      <div className="cat-sc-ribbon" role="group" aria-label="Segment timeline">
        {segments.map((s, i) => {
          const t0 = Math.max(0, Number(s.t0_s) || 0);
          const t1 = Math.max(t0, Number(s.t1_s) || t0);
          const left = total > 0 ? (t0 / total) * 100 : 0;
          const width = total > 0 ? Math.max(0.6, ((t1 - t0) / total) * 100) : 0;
          const on = active === i;
          return (
            <button
              key={`${s.index ?? i}-${t0}`}
              type="button"
              className={`cat-sc-band${on ? " is-on" : ""}`}
              style={{ left: `${left}%`, width: `${width}%` }}
              onPointerEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onPointerLeave={() => setActive(null)}
              onBlur={() => setActive(null)}
              onClick={() => requestSeek(clip.id, t0)}
              aria-label={`Play segment ${(s.index ?? i) + 1}, ${s.label}, from ${formatDuration(
                t0
              )} to ${formatDuration(t1)}`}
            />
          );
        })}
      </div>
      <div className="cat-sc-scale" aria-hidden="true">
        <span className="cat-num">0:00</span>
        <span className="cat-num">{formatDuration(total)}</span>
      </div>

      <ol className="cat-sc-list">
        {segments.map((s, i) => {
          const t0 = Number(s.t0_s) || 0;
          const t1 = Number(s.t1_s) || t0;
          const on = active === i;
          return (
            <li key={`${s.index ?? i}-row-${t0}`}>
              <button
                type="button"
                className={`cat-sc-row${on ? " is-on" : ""}`}
                onPointerEnter={() => setActive(i)}
                onFocus={() => setActive(i)}
                onPointerLeave={() => setActive(null)}
                onBlur={() => setActive(null)}
                onClick={() => requestSeek(clip.id, t0)}
                aria-label={`Play ${s.label} at ${formatDuration(t0)} in the video tab`}
              >
                <span className="cat-sc-idx cat-num">
                  {String((s.index ?? i) + 1).padStart(2, "0")}
                </span>
                <span className="cat-sc-time cat-num">
                  {formatDuration(t0)}–{formatDuration(t1)}
                  <em>{(t1 - t0).toFixed(1)}s</em>
                </span>
                <span className="cat-sc-body">
                  <span className="cat-sc-label">
                    {s.label}
                    {s.verb ? <span className="cat-chip cat-chip--verb">{s.verb}</span> : null}
                    {s.source ? <span className="cat-chip">{s.source}</span> : null}
                    {typeof s.confidence === "number" ? (
                      <span className="cat-chip">{(s.confidence * 100).toFixed(0)}%</span>
                    ) : null}
                  </span>
                  {Array.isArray(s.objects) && s.objects.length ? (
                    <span className="cat-sc-objs">
                      {s.objects.map((o) => (
                        <span key={o} className="cat-chip cat-chip--obj">
                          {o}
                        </span>
                      ))}
                    </span>
                  ) : null}
                  {s.description ? <span className="cat-sc-desc">{s.description}</span> : null}
                </span>
                <span className="cat-sc-go" aria-hidden="true">
                  <Play size={13} />
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
