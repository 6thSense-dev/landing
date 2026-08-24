/**
 * TactileTab — the 22x22 gloves, told honestly.
 * ---------------------------------------------------------------------------
 * Props: { clip }
 *
 * What is real here, and where it comes from:
 *
 *   grid geometry      tactile_preview.grid / readout_sites
 *   channel census     tactile_preview.census.{left,right}   (counts)
 *   per-taxel status   clip.metadata.quality.channels.<hand>.{silent_idx,
 *                      rejected_idx, intermittent_idx}       (indices)
 *                      -- `metadata` is the contract's verbatim passthrough of
 *                      the capture pipeline's own document, so this is a
 *                      best-effort read: if the shape is not there we fall back
 *                      to the census counts alone and say so, rather than
 *                      guessing which taxels are dead.
 *   taxel -> (row,col) media.tactile.layout sidecar, hands.<h>.taxels[] giving
 *                      {i,row,col,region}. Without it we assume the plain
 *                      row-major rule and label the grid as unverified, because
 *                      an undocumented per-hand permutation is the single most
 *                      reliable way to render a glove mirrored.
 *   force over time    tactile_preview.peak_series  (peak over taxels; this is
 *                      an ENVELOPE, not a sensor -- the argmax channel moves)
 *   force imagery      tactile_preview.frames[]     (pre-rendered stills at
 *                      named percentiles, not a highlight reel)
 *
 * A dead channel is NEVER drawn as 0. Zero means "this working sensor felt
 * nothing"; a dead channel means "there is no sensor here", and the two are
 * drawn as different things (hatched grey, legend entry "no channel").
 *
 * Per-taxel force *frames* are not part of 6s-clip/1.0, so the grid renders
 * channel health and the rendered stills carry the force field. When a record
 * does ship a per-taxel frame source the grid colours from it -- see
 * `taxelValues` below, which is the single place that has to change.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Hand as HandIcon } from "lucide-react";

import { assetUrl, fetchAsset, notifyAssetExpired } from "../useCatalog.js";
import { formatCount, formatDuration, dash } from "../format.js";
import { PillGroup } from "./ImuTab.jsx";

const SEEK_EVENT = "6s-catalog:seek";
const SEEK_MAILBOX = "__6sCatalogSeek";

/* Perceptually ordered warm ramp: paper-deep -> accent. */
const RAMP = ["#ddd8cb", "#cfc4a2", "#bfa877", "#a67c3c", "#8a4a15", "#592202"];

function hex2rgb(h) {
  const v = parseInt(h.slice(1), 16);
  return [(v >> 16) & 255, (v >> 8) & 255, v & 255];
}

function rampColor(u) {
  const x = Math.min(1, Math.max(0, u)) * (RAMP.length - 1);
  const i = Math.floor(x);
  if (i >= RAMP.length - 1) return RAMP[RAMP.length - 1];
  const f = x - i;
  const a = hex2rgb(RAMP[i]);
  const b = hex2rgb(RAMP[i + 1]);
  const c = a.map((v, k) => Math.round(v + (b[k] - v) * f));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

/* ------------------------------------------------------------------ */
/* Peak series (same two-encoding rule as the IMU payload)             */
/* ------------------------------------------------------------------ */

function inlinePeak(ps) {
  const left = Array.isArray(ps.left) ? ps.left : null;
  const right = Array.isArray(ps.right) ? ps.right : null;
  const n = ps.n_readings ?? Math.max(left?.length || 0, right?.length || 0);
  return { n, left, right, get: (hand, i) => (hand === "left" ? left?.[i] : right?.[i]) };
}

function sidecarPeak(ps, buffer) {
  const sc = ps.sidecar;
  const order = Array.isArray(sc.order) ? sc.order : ["left"];
  const k = order.length;
  const stride = sc.stride_bytes || 4 * k;
  const floats = new Float32Array(buffer, 0, Math.floor(buffer.byteLength / 4));
  const n = Math.min(sc.n_readings ?? ps.n_readings ?? 0, Math.floor(buffer.byteLength / stride));
  const col = { left: order.indexOf("left"), right: order.indexOf("right") };
  return {
    n,
    left: col.left >= 0 ? true : null,
    right: col.right >= 0 ? true : null,
    get: (hand, i) => (col[hand] < 0 ? undefined : floats[i * k + col[hand]]),
  };
}

/* ------------------------------------------------------------------ */

export default function TactileTab({ clip }) {
  const tp = clip?.tactile_preview ?? null;
  const hands = useMemo(() => {
    const list = Array.isArray(clip?.hands) ? clip.hands : [];
    return list.length ? list : ["left", "right"].filter((h) => tp?.census?.[h]);
  }, [clip, tp]);

  const [rows, cols] = Array.isArray(tp?.grid) && tp.grid.length === 2 ? tp.grid : [22, 22];
  const fullScale = tp?.display_full_scale_counts ?? 300;

  const [layout, setLayout] = useState(null);
  const [layoutState, setLayoutState] = useState("idle");
  const [peak, setPeak] = useState(null);
  const [peakState, setPeakState] = useState("idle");
  const [playT, setPlayT] = useState(0);
  const [hoverCell, setHoverCell] = useState(null);
  const [stillHand, setStillHand] = useState("both");
  const scrubRef = useRef(null);

  /* ---------------- per-taxel geometry sidecar ---------------- */
  useEffect(() => {
    const rel = clip?.media?.tactile?.layout;
    if (!rel) {
      setLayout(null);
      setLayoutState("absent");
      return undefined;
    }
    let cancelled = false;
    setLayoutState("loading");
    let url = null;
    try {
      url = assetUrl(rel);
    } catch {
      url = null;
    }
    if (!url) {
      setLayoutState("absent");
      return undefined;
    }
    fetchAsset(url)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((json) => {
        if (cancelled) return;
        setLayout(json);
        setLayoutState("ready");
      })
      .catch(() => {
        if (!cancelled) setLayoutState("absent");
      });
    return () => {
      cancelled = true;
    };
  }, [clip]);

  /* ---------------- peak series ---------------- */
  useEffect(() => {
    const ps = tp?.peak_series;
    if (!ps) {
      setPeak(null);
      setPeakState("absent");
      return undefined;
    }
    let cancelled = false;
    if (ps.encoding === "sidecar_f32le" && ps.sidecar?.url) {
      setPeakState("loading");
      let url = null;
      try {
        url = assetUrl(ps.sidecar.url);
      } catch {
        url = null;
      }
      if (!url) {
        setPeakState("absent");
        return undefined;
      }
      fetchAsset(url)
        .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(String(r.status)))))
        .then((buf) => {
          if (cancelled) return;
          setPeak(sidecarPeak(ps, buf));
          setPeakState("ready");
        })
        .catch(() => {
          if (!cancelled) setPeakState("error");
        });
      return () => {
        cancelled = true;
      };
    }
    setPeak(inlinePeak(ps));
    setPeakState("ready");
    return () => {
      cancelled = true;
    };
  }, [tp]);

  /* ---------------- per-taxel status masks ---------------- */
  const masks = useMemo(() => buildMasks(clip, hands), [clip, hands]);

  /* ---------------- index -> (row,col) per hand ---------------- */
  const placement = useMemo(
    () => buildPlacement(layout, hands, rows, cols),
    [layout, hands, rows, cols]
  );

  /**
   * Per-taxel force values at the playhead, keyed by hand -> Float array of
   * length rows*cols, or null when the record ships no per-taxel frame source.
   * 6s-clip/1.0 has no such field, so this is null today and the grid renders
   * channel health instead of pretending to a force field it does not have.
   */
  const taxelValues = useMemo(() => null, []);

  /* ---------------- playhead <-> peak series ---------------- */
  const ps = tp?.peak_series ?? null;
  const peakRate = ps?.rate_hz ?? null;
  const peakT0 = ps?.t0_s ?? 0;
  const peakN = peak?.n ?? 0;
  const peakDuration =
    peakRate && peakN ? (peakN - 1) / peakRate : clip?.duration_s || 0;

  const peakMax = useMemo(() => {
    if (!peak || !peakN) return null;
    let m = 0;
    const stride = Math.max(1, Math.floor(peakN / 8000));
    for (const h of hands) {
      for (let i = 0; i < peakN; i += stride) {
        const v = peak.get(h, i);
        if (Number.isFinite(v) && v > m) m = v;
      }
    }
    return m || null;
  }, [peak, peakN, hands]);

  const nearestStill = useMemo(() => {
    const frames = Array.isArray(tp?.frames) ? tp.frames : [];
    if (!frames.length) return null;
    const pool =
      stillHand === "both" ? frames : frames.filter((f) => f.hand === stillHand || f.hand === "both");
    const list = pool.length ? pool : frames;
    let best = list[0];
    let bestD = Infinity;
    for (const f of list) {
      const d = Math.abs((f.t_s ?? 0) - playT);
      if (d < bestD) {
        bestD = d;
        best = f;
      }
    }
    return best;
  }, [tp, playT, stillHand]);

  /* ---------------- empty ---------------- */
  if (!tp) {
    return (
      <div className="cat-empty">
        <p className="cat-empty__head">No tactile data in this clip</p>
        <p className="cat-empty__body">
          <code>tactile_preview</code> is null and <code>hands</code> is{" "}
          <code>{JSON.stringify(clip?.hands ?? [])}</code>, so no glove was worn. Every clip in
          this catalog is egocentric stereo video <em>and</em> tactile, so this is a packaging
          fault to report rather than a shape the product ships — and it is still not the same
          as a glove that recorded nothing.
        </p>
      </div>
    );
  }

  const crcByHand = clip?.qa?.tactile_crc_pass_rate_by_hand ?? null;

  return (
    <section className="cat-t">
      <header className="cat-t-head">
        <div>
          <h3 className="cat-t-title">
            <HandIcon size={16} aria-hidden="true" />
            Tactile channel map
          </h3>
          <p className="cat-t-sub">
            {formatCount(tp.readout_sites ?? rows * cols)} readout sites per hand ·{" "}
            {hands.map((h) => `${h} ${dash(tp.usable_channels?.[h])}`).join(" · ")} live-and-stable
          </p>
        </div>
        {Array.isArray(tp.frames) && tp.frames.length ? (
          <PillGroup
            label="Rendered still hand"
            value={stillHand}
            onChange={setStillHand}
            options={[
              { value: "both", label: "Both" },
              { value: "left", label: "Left" },
              { value: "right", label: "Right" },
            ]}
          />
        ) : null}
      </header>

      {/* --------------- H9 units caveat, visible, not a tooltip --------------- */}
      <p className={`cat-note${tp.units === "raw_adc_counts" ? " cat-note--warn" : ""}`}>
        {tp.units === "raw_adc_counts" ? (
          <>
            Values are <strong>raw ADC counts — NOT calibrated to force units</strong>.
            {tp.adc_bits ? ` ${tp.adc_bits}-bit converter.` : ""}
            {tp.pedestal_counts != null
              ? ` Unloaded pedestal ${tp.pedestal_counts} counts — subtract it before anything means force.`
              : " The unloaded pedestal was not measured."}
            {tp.ceiling_counts != null
              ? ` A real press tops out at ${tp.ceiling_counts} counts; anything above that is a channel fault, not a load.`
              : ""}
            {tp.display_full_scale_counts != null
              ? ` Heatmaps are scaled 0–${tp.display_full_scale_counts}, deliberately below the ceiling so a typical contact is visible.`
              : ""}
          </>
        ) : (
          <>Values are calibrated to {tp.units}.</>
        )}
      </p>

      {/* --------------- the grids --------------- */}
      <div className="cat-t-grids">
        {hands.map((hand) => (
          <TaxelGrid
            key={hand}
            hand={hand}
            rows={rows}
            cols={cols}
            mask={masks[hand]}
            place={placement[hand]}
            values={taxelValues?.[hand] ?? null}
            fullScale={fullScale}
            census={tp.census?.[hand] ?? null}
            onHover={setHoverCell}
          />
        ))}
        {hands.length === 0 ? (
          <p className="cat-note">No hand was instrumented on this take.</p>
        ) : null}
      </div>

      <div className="cat-t-legendrow">
        <Legend fullScale={fullScale} units={tp.units} />
        <p className="cat-t-hover" aria-live="polite">
          {hoverCell
            ? `${hoverCell.hand} · row ${hoverCell.row}, col ${hoverCell.col} · index ${hoverCell.i}${
                hoverCell.region ? ` · ${hoverCell.region}` : ""
              } · ${hoverCell.status.replace("_", " ")}`
            : "Hover a cell for its index, region and channel status."}
        </p>
      </div>

      {masks.source === "none" ? (
        <p className="cat-note cat-note--warn">
          Per-taxel status indices are not in this record, so the map shows the readout lattice
          only. The census counts below are the authoritative figures.
        </p>
      ) : null}
      {layoutState === "absent" ? (
        <p className="cat-note cat-note--warn">
          No per-taxel geometry sidecar (<code>media.tactile.layout</code>), so the grid assumes the
          plain row-major rule
          {tp.index_rule ? ` rather than the record's stated "${tp.index_rule}"` : ""}. An
          undocumented per-hand permutation renders a glove mirrored, so treat the spatial
          arrangement as unverified.
        </p>
      ) : null}

      {/* --------------- peak trace + playhead --------------- */}
      <PeakStrip
        ps={ps}
        peak={peak}
        peakState={peakState}
        peakN={peakN}
        peakRate={peakRate}
        peakT0={peakT0}
        duration={peakDuration}
        hands={hands}
        value={playT}
        onChange={setPlayT}
        scrubRef={scrubRef}
        clipId={clip.id}
        fullScale={ps?.full_scale ?? tp.ceiling_counts ?? null}
        units={tp.units}
      />

      {/* --------------- rendered stills --------------- */}
      {Array.isArray(tp.frames) && tp.frames.length ? (
        <div className="cat-t-stills">
          <div className="cat-t-stills__main">
            {nearestStill ? (
              <figure>
                <img
                  src={safeAsset(nearestStill.png)}
                  onError={() => notifyAssetExpired(safeAsset(nearestStill.png))}
                  alt={`Rendered tactile heatmap, ${nearestStill.hand} hand, at ${formatDuration(
                    nearestStill.t_s
                  )}`}
                />
                <figcaption>
                  <span className="cat-num">{formatDuration(nearestStill.t_s)}</span>
                  {nearestStill.label ? <span className="cat-chip">{nearestStill.label}</span> : null}
                  <span>
                    {nearestStill.hand} · peak {dash(nearestStill.peak_counts)}{" "}
                    {tp.units === "raw_adc_counts" ? "counts" : tp.units}
                  </span>
                </figcaption>
              </figure>
            ) : null}
          </div>
          <ul className="cat-t-stills__reel">
            {tp.frames.map((f, i) => (
              <li key={`${f.png}-${i}`}>
                <button
                  type="button"
                  className={`cat-t-thumb${f === nearestStill ? " is-on" : ""}`}
                  onClick={() => setPlayT(f.t_s ?? 0)}
                  aria-label={`Show the ${f.label || "rendered"} frame at ${formatDuration(f.t_s)}, peak ${dash(
                    f.peak_counts
                  )}`}
                >
                  <img
                    src={safeAsset(f.png)}
                    onError={() => notifyAssetExpired(safeAsset(f.png))}
                    alt=""
                    aria-hidden="true"
                  />
                  <span className="cat-num">{f.label || formatDuration(f.t_s)}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="cat-note">
            Stills are sampled across the force distribution (p50 … max), not at the peak. A preview
            made only of maxima is a highlight reel.
          </p>
        </div>
      ) : null}

      {/* --------------- stats --------------- */}
      <div className="cat-t-stats">
        <Stat
          label="Sample rate"
          value={peakRate ? `${peakRate.toFixed(1)} Hz` : dash(null)}
          note={peakRate ? "peak trace" : "not stated in the record"}
        />
        <Stat label="Readout sites" value={formatCount(tp.readout_sites ?? rows * cols)} note="per hand" />
        <Stat
          label="Peak observed"
          value={peakMax != null ? formatCount(Math.round(peakMax)) : dash(null)}
          note={tp.units === "raw_adc_counts" ? "counts, over the whole take" : String(tp.units)}
        />
        <Stat
          label="Physical ceiling"
          value={tp.ceiling_counts != null ? formatCount(tp.ceiling_counts) : dash(null)}
          note="above this is a channel fault"
        />
        {hands.map((hand) => {
          const c = tp.census?.[hand];
          return (
            <Stat
              key={hand}
              label={`${hand} hand`}
              value={`${dash(c?.stable)} stable`}
              note={`${dash(c?.live)} live · ${dash(c?.silent)} silent · ${dash(
                c?.over_ceiling
              )} over ceiling · ${dash(c?.intermittent)} intermittent`}
            />
          );
        })}
        {hands.map((hand) => (
          <Stat
            key={`crc-${hand}`}
            label={`${hand} CRC pass`}
            value={
              crcByHand?.[hand] != null
                ? `${(crcByHand[hand] * 100).toFixed(3)}%`
                : clip?.qa?.tactile_crc_pass_rate != null
                  ? `${(clip.qa.tactile_crc_pass_rate * 100).toFixed(3)}%`
                  : dash(null)
            }
            note={crcByHand?.[hand] != null ? "this hand" : "worst hand"}
          />
        ))}
      </div>

      {hands.map((hand) => {
        const note = tp.census?.[hand]?.damage_note;
        return note ? (
          <p key={`dmg-${hand}`} className="cat-note">
            <strong className="cat-t-dmg">{hand.toUpperCase()}</strong> {note}
          </p>
        ) : null;
      })}

      {tp.note ? <p className="cat-note">{tp.note}</p> : null}
      {tp.derive_delta ? (
        <p className="cat-note">
          Derive a baseline-subtracted delta with:{" "}
          <code className="cat-code">{tp.derive_delta}</code>
        </p>
      ) : null}
      {ps ? (
        <p className="cat-note cat-note--warn">
          The peak trace is an <strong>envelope, not a sensor</strong>: the argmax taxel can change
          between adjacent samples, so a rise in this line may be two different taxels and must
          never be quoted as a rise time.
        </p>
      ) : null}
    </section>
  );
}

/* ------------------------------------------------------------------ */

function safeAsset(rel) {
  if (!rel) return undefined;
  try {
    return assetUrl(rel);
  } catch {
    return undefined;
  }
}

/**
 * Per-taxel status, read best-effort from the verbatim source metadata.
 * Returns { left: Uint8Array|null, right: ..., source: 'metadata'|'none' }
 * where 0 = ok, 1 = intermittent, 2 = over ceiling, 3 = silent.
 */
function buildMasks(clip, hands) {
  const channels = clip?.metadata?.quality?.channels;
  const out = { source: "none" };
  if (!channels || typeof channels !== "object") {
    for (const h of hands) out[h] = null;
    return out;
  }
  let any = false;
  for (const h of hands) {
    const c = channels[h];
    const sites = c?.readout_sites ?? clip?.tactile_preview?.readout_sites ?? 484;
    if (!c) {
      out[h] = null;
      continue;
    }
    const mask = new Uint8Array(sites);
    const put = (list, code) => {
      if (!Array.isArray(list)) return;
      any = true;
      for (const i of list) if (i >= 0 && i < sites) mask[i] = code;
    };
    put(c.intermittent_idx, 1);
    put(c.rejected_idx ?? c.over_ceiling_idx, 2);
    put(c.silent_idx, 3);
    out[h] = mask;
  }
  out.source = any ? "metadata" : "none";
  return out;
}

/**
 * index -> {row, col, region} per hand, from the geometry sidecar when it is
 * there, otherwise the plain row-major fallback.
 */
function buildPlacement(layout, hands, rows, cols) {
  const out = {};
  for (const hand of hands) {
    const taxels = layout?.hands?.[hand]?.taxels;
    if (Array.isArray(taxels) && taxels.length) {
      const map = new Array(rows * cols).fill(null);
      for (const t of taxels) {
        if (typeof t?.i !== "number") continue;
        map[t.i] = { row: t.row, col: t.col, region: t.region ?? null };
      }
      out[hand] = { map, verified: true };
    } else {
      const map = new Array(rows * cols);
      for (let i = 0; i < rows * cols; i += 1) {
        map[i] = { row: Math.floor(i / cols), col: i % cols, region: null };
      }
      out[hand] = { map, verified: false };
    }
  }
  return out;
}

const STATUS_NAME = ["ok", "intermittent", "over_ceiling", "silent"];

function TaxelGrid({ hand, rows, cols, mask, place, values, fullScale, census, onHover }) {
  const cell = 13;
  const gap = 1.4;
  const w = cols * (cell + gap) + gap;
  const h = rows * (cell + gap) + gap;
  const pid = `cat-t-hatch-${hand}`;
  const pidBad = `cat-t-hatchbad-${hand}`;

  const cells = [];
  const total = rows * cols;
  for (let i = 0; i < total; i += 1) {
    const p = place?.map?.[i];
    if (!p) continue;
    const status = mask ? STATUS_NAME[mask[i]] || "ok" : "unknown";
    const x = gap + p.col * (cell + gap);
    const y = gap + p.row * (cell + gap);
    let fill;
    if (status === "silent") fill = `url(#${pid})`;
    else if (status === "over_ceiling") fill = `url(#${pidBad})`;
    else if (values) fill = rampColor((values[i] ?? 0) / (fullScale || 1));
    else fill = RAMP[0];
    cells.push({ i, x, y, fill, status, row: p.row, col: p.col, region: p.region });
  }

  const summary = census
    ? `${hand} hand, ${rows} by ${cols} readout grid: ${census.stable ?? "unknown"} live-and-stable channels, ${
        census.silent ?? "unknown"
      } silent, ${census.over_ceiling ?? "unknown"} over ceiling, ${
        census.intermittent ?? "unknown"
      } intermittent.`
    : `${hand} hand, ${rows} by ${cols} readout grid.`;

  return (
    <figure className="cat-t-grid">
      <figcaption className="cat-t-grid__cap">
        <span>{hand.toUpperCase()}</span>
        {census ? (
          <span className="cat-t-grid__count">
            {dash(census.stable)} / {dash(census.readout_sites ?? rows * cols)} usable
          </span>
        ) : null}
      </figcaption>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="cat-t-grid__svg"
        role="img"
        aria-label={summary}
        onPointerLeave={() => onHover(null)}
      >
        <defs>
          <pattern id={pid} width="4" height="4" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
            <rect width="4" height="4" fill="#e2ded2" />
            <line x1="0" y1="0" x2="0" y2="4" stroke="#a7a08a" strokeWidth="1.4" />
          </pattern>
          <pattern id={pidBad} width="4" height="4" patternTransform="rotate(-45)" patternUnits="userSpaceOnUse">
            <rect width="4" height="4" fill="#e6dcd4" />
            <line x1="0" y1="0" x2="0" y2="4" stroke="#a35a3a" strokeWidth="1.4" />
          </pattern>
        </defs>
        {cells.map((c) => (
          <rect
            key={c.i}
            x={c.x}
            y={c.y}
            width={cell}
            height={cell}
            rx={2}
            fill={c.fill}
            className={`cat-t-cell cat-t-cell--${c.status}`}
            onPointerEnter={() =>
              onHover({ hand, i: c.i, row: c.row, col: c.col, region: c.region, status: c.status })
            }
          >
            <title>{`${hand} · i=${c.i} · row ${c.row}, col ${c.col}${
              c.region ? ` · ${c.region}` : ""
            } · ${c.status.replace("_", " ")}`}</title>
          </rect>
        ))}
      </svg>
    </figure>
  );
}

function Legend({ fullScale, units }) {
  const stops = [0, 0.25, 0.5, 0.75, 1];
  return (
    <div className="cat-t-legend">
      <span className="cat-t-legend__lab">0</span>
      <span className="cat-t-legend__ramp" aria-hidden="true">
        {stops.map((s) => (
          <i key={s} style={{ background: rampColor(s) }} />
        ))}
      </span>
      <span className="cat-t-legend__lab">
        {fullScale} {units === "raw_adc_counts" ? "counts" : units}
      </span>
      <span className="cat-t-legend__sep" aria-hidden="true" />
      <span className="cat-t-legend__key">
        <i className="cat-t-swatch cat-t-swatch--silent" aria-hidden="true" />
        no channel
      </span>
      <span className="cat-t-legend__key">
        <i className="cat-t-swatch cat-t-swatch--bad" aria-hidden="true" />
        over ceiling
      </span>
      <span className="cat-t-legend__key">
        <i className="cat-t-swatch cat-t-swatch--int" aria-hidden="true" />
        intermittent
      </span>
    </div>
  );
}

function PeakStrip({
  ps,
  peak,
  peakState,
  peakN,
  peakRate,
  peakT0,
  duration,
  hands,
  value,
  onChange,
  scrubRef,
  clipId,
  fullScale,
  units,
}) {
  const W = 1000;
  const H = 96;

  const paths = useMemo(() => {
    if (!peak || !peakN || !peakRate) return [];
    const scale = fullScale || 1;
    return hands.map((hand, k) => {
      const d = [];
      const columns = Math.min(W, peakN);
      const spp = peakN / columns;
      for (let x = 0; x < columns; x += 1) {
        const a = Math.floor(x * spp);
        const b = Math.min(peakN - 1, Math.floor((x + 1) * spp) - 1);
        let mx = -Infinity;
        for (let i = a; i <= b; i += 1) {
          const v = peak.get(hand, i);
          if (Number.isFinite(v) && v > mx) mx = v;
        }
        if (!Number.isFinite(mx)) continue;
        const px = (x / (columns - 1 || 1)) * W;
        const py = H - Math.min(1, Math.max(0, mx / scale)) * H;
        d.push(`${d.length === 0 ? "M" : "L"}${px.toFixed(1)} ${py.toFixed(1)}`);
      }
      return { hand, d: d.join(""), color: k === 0 ? "#262312" : "#8a4a15" };
    });
  }, [peak, peakN, peakRate, hands, fullScale]);

  if (!ps) {
    return (
      <div className="cat-t-peak cat-t-peak--empty">
        <p className="cat-note">
          No peak-force trace was computed for this clip (<code>tactile_preview.peak_series</code> is
          null), so there is nothing to scrub. The rendered stills below are still real frames at
          real timestamps.
        </p>
      </div>
    );
  }

  const idx = peakRate && peakN ? Math.min(peakN - 1, Math.max(0, Math.round((value - peakT0) * peakRate))) : 0;
  const playX = duration > 0 ? (value / duration) * W : 0;

  return (
    <div className="cat-t-peak">
      <div className="cat-t-peak__head">
        <h4>Peak force over time</h4>
        <span className="cat-num">
          {formatDuration(value)} / {formatDuration(duration)} ·{" "}
          {hands
            .map((h) => {
              const v = peak?.get(h, idx);
              return `${h} ${Number.isFinite(v) ? Math.round(v) : "—"}`;
            })
            .join("  ")}{" "}
          {units === "raw_adc_counts" ? "counts" : units}
        </span>
      </div>

      <div className="cat-t-peak__plot">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true" focusable="false">
          <line x1={0} x2={W} y1={H / 2} y2={H / 2} className="cat-imu-grid" />
          {peakState === "ready"
            ? paths.map((p) => (
                <path
                  key={p.hand}
                  d={p.d}
                  fill="none"
                  stroke={p.color}
                  strokeWidth={1}
                  vectorEffect="non-scaling-stroke"
                />
              ))
            : null}
          <line x1={playX} x2={playX} y1={0} y2={H} className="cat-t-playhead" />
        </svg>
        <input
          ref={scrubRef}
          className="cat-t-scrub"
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={Math.min(value, duration || 0)}
          aria-label="Tactile playhead"
          aria-valuetext={`${formatDuration(value)} of ${formatDuration(duration)}`}
          onChange={(e) => onChange(Number(e.target.value))}
        />
      </div>

      <div className="cat-t-peak__foot">
        <ul className="cat-imu-legend">
          {hands.map((h, k) => (
            <li key={h}>
              <span
                className="cat-imu-dot"
                style={{ background: k === 0 ? "#262312" : "#8a4a15" }}
                aria-hidden="true"
              />
              {h}
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="cat-btn"
          onClick={() => {
            const detail = { clipId, t_s: value, at: Date.now() };
            if (typeof window !== "undefined") {
              window[SEEK_MAILBOX] = detail;
              window.dispatchEvent(new CustomEvent(SEEK_EVENT, { detail }));
            }
          }}
        >
          Show this moment in the video
        </button>
      </div>
      {peakState === "loading" ? <p className="cat-note">Reading the peak sidecar…</p> : null}
      {peakState === "error" ? (
        <p className="cat-note cat-note--warn">The peak sidecar could not be fetched.</p>
      ) : null}
    </div>
  );
}

function Stat({ label, value, note }) {
  return (
    <div className="cat-t-stat">
      <span className="cat-label">{label}</span>
      <strong>{value}</strong>
      {note ? <span className="cat-t-stat__note">{note}</span> : null}
    </div>
  );
}
