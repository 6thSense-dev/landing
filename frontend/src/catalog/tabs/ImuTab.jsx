/**
 * ImuTab — every inertial reading, drawn.
 * ---------------------------------------------------------------------------
 * Props: { clip }
 *
 * This tab is not a summary and not a decimation. The strip is a horizontally
 * scrollable canvas at a fixed px-per-second zoom, so its full width is the
 * whole take. Only the visible window (plus a margin) is turned into an SVG
 * path on any given frame; inside that window, when there are more samples than
 * pixel columns, each column is reduced to a min/max pair, so a one-sample
 * spike is still a full-height tick rather than something a decimator dropped.
 *
 * Data source, per 6s-clip/1.0 section 5.1. The client dispatches on
 * `imu_preview.encoding` and never sniffs:
 *
 *   sidecar_f32le -> fetch imu_preview.sidecar.url as an ArrayBuffer, view it
 *                    as Float32Array; sample i, channel c is at float index
 *                    i * order.length + c. This is the full stream.
 *   inline_f32    -> imu_preview.channels.{accel,gyro}.{x,y,z}
 *
 * If a sidecar is declared but cannot be fetched we fall back to the inline
 * channels *and say so in the subline*. A buyer must never be shown a partial
 * stream that is labelled "full".
 */

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowUpRight, ZoomIn, ZoomOut } from "lucide-react";

import { assetUrl, fetchAsset } from "../useCatalog.js";
import { formatCount, formatDuration } from "../format.js";

const AXIS_COLORS = { x: "#262312", y: "#5f8f8a", z: "#c8a85a" };
const ZOOMS = [15, 30, 60, 120, 240, 480, 960, 1920, 3840];
const DEFAULT_ZOOM_INDEX = 3;
const PLOT_H = 300;
const AXIS_H = 26;
const OVERDRAW_PX = 500;
/* An SVG wider than this gets flaky in browsers; it also means the take is
   longer than any sane zoom, so we clamp rather than let the DOM decide. */
const MAX_STRIP_PX = 240000;

const GROUPS = [
  { id: "accel", label: "Accelerometer", channels: ["ax", "ay", "az"], noun: "Accelerometer motion" },
  { id: "gyro", label: "Gyroscope", channels: ["gx", "gy", "gz"], noun: "Gyroscope motion" },
];

/* ------------------------------------------------------------------ */
/* Series loading                                                      */
/* ------------------------------------------------------------------ */

function makeSidecarSeries(preview, buffer) {
  const sc = preview.sidecar;
  const order = Array.isArray(sc.order) ? sc.order : [];
  const k = order.length || 1;
  const stride = sc.stride_bytes || 4 * k;
  const floats = new Float32Array(buffer, 0, Math.floor(buffer.byteLength / 4));
  const capacity = Math.floor(buffer.byteLength / stride);
  const declared = sc.n_readings ?? preview.n_readings ?? capacity;
  const n = Math.min(declared, capacity);
  const idx = {};
  for (const ch of ["t", "ax", "ay", "az", "gx", "gy", "gz"]) idx[ch] = order.indexOf(ch);

  const dt = preview.dt_s;
  const t0 = preview.t0_s ?? 0;
  const tCol = idx.t;

  return {
    source: "sidecar",
    n,
    truncated: n < declared,
    at(i, ch) {
      const c = idx[ch];
      return c < 0 ? NaN : floats[i * k + c];
    },
    tAt(i) {
      if (dt != null) return t0 + i * dt;
      return tCol >= 0 ? floats[i * k + tCol] : t0 + i;
    },
    dt: dt ?? null,
    t0,
    has: {
      accel: idx.ax >= 0 && idx.ay >= 0 && idx.az >= 0,
      gyro: idx.gx >= 0 && idx.gy >= 0 && idx.gz >= 0,
    },
  };
}

function makeInlineSeries(preview) {
  const ch = preview.channels;
  if (!ch) return null;
  const a = ch.accel || null;
  const g = ch.gyro || null;
  const tArr = ch.t || null;
  const lengths = [a?.x?.length, g?.x?.length].filter((v) => typeof v === "number");
  if (lengths.length === 0) return null;
  const n = Math.min(...lengths);
  const dt = preview.dt_s;
  const t0 = preview.t0_s ?? 0;

  const map = {
    ax: a?.x,
    ay: a?.y,
    az: a?.z,
    gx: g?.x,
    gy: g?.y,
    gz: g?.z,
  };

  return {
    source: "inline",
    n,
    truncated: n < (preview.n_readings ?? n),
    at(i, key) {
      const arr = map[key];
      return arr ? arr[i] : NaN;
    },
    tAt(i) {
      if (dt != null) return t0 + i * dt;
      return tArr ? tArr[i] : t0 + i;
    },
    dt: dt ?? null,
    t0,
    has: { accel: Boolean(a?.x), gyro: Boolean(g?.x) },
  };
}

/* ------------------------------------------------------------------ */
/* Axis helpers                                                        */
/* ------------------------------------------------------------------ */

function niceTicks(lo, hi, target) {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-6; v += step) {
    out.push(Number(v.toFixed(10)));
  }
  return out;
}

function tickLabel(v) {
  const a = Math.abs(v);
  if (a === 0) return "0";
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  if (a >= 1) return v.toFixed(2);
  return v.toFixed(3);
}

/**
 * M:SS ticks, but with decimals once the step drops below a second -- at
 * 3840 px/s the ticks are 50 ms apart and a whole-second label would print
 * "0:00" five times in a row.
 */
function formatTick(seconds, step) {
  const m = Math.floor(seconds / 60);
  const rem = seconds - m * 60;
  if (step >= 1) return `${m}:${String(Math.round(rem)).padStart(2, "0")}`;
  const decimals = step >= 0.1 ? 1 : 2;
  const txt = rem.toFixed(decimals);
  return `${m}:${rem < 10 ? "0" : ""}${txt}`;
}

function timeStep(pxPerSec) {
  const candidates = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600];
  for (const c of candidates) if (c * pxPerSec >= 90) return c;
  return candidates[candidates.length - 1];
}

/* ------------------------------------------------------------------ */

export default function ImuTab({ clip }) {
  const preview = clip?.imu_preview ?? null;

  const [group, setGroup] = useState("accel");
  const [zoomIndex, setZoomIndex] = useState(DEFAULT_ZOOM_INDEX);
  const [series, setSeries] = useState(null);
  const [status, setStatus] = useState(preview ? "loading" : "empty");
  const [notice, setNotice] = useState(null);
  const [scroll, setScroll] = useState(0);
  const [viewW, setViewW] = useState(900);
  const [hover, setHover] = useState(null);

  const scrollRef = useRef(null);
  const rafRef = useRef(0);

  /* ---------------- load ---------------- */
  useEffect(() => {
    if (!preview) {
      setSeries(null);
      setStatus("empty");
      return undefined;
    }
    let cancelled = false;
    setStatus("loading");
    setNotice(null);

    const inline = () => {
      const s = makeInlineSeries(preview);
      if (cancelled) return;
      if (s) {
        setSeries(s);
        setStatus("ready");
      } else {
        setSeries(null);
        setStatus("error");
      }
    };

    if (preview.encoding === "sidecar_f32le" && preview.sidecar?.url) {
      const sc = preview.sidecar;
      let url = null;
      try {
        url = assetUrl(sc.url);
      } catch {
        url = null;
      }
      if (!url) {
        setNotice("The IMU sidecar URL could not be resolved.");
        inline();
        return () => {
          cancelled = true;
        };
      }
      fetchAsset(url)
        .then((res) => {
          if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
          return res.arrayBuffer();
        })
        .then((buf) => {
          if (cancelled) return;
          const stride = sc.stride_bytes || 4 * (sc.order?.length || 6);
          const expected = (sc.n_readings ?? 0) * stride;
          const s = makeSidecarSeries(preview, buf);
          if (expected && buf.byteLength !== expected) {
            setNotice(
              `Sidecar is ${formatCount(buf.byteLength)} B; the record declares ${formatCount(
                expected
              )} B. Showing the ${formatCount(s.n)} complete records it contains.`
            );
          }
          setSeries(s);
          setStatus("ready");
        })
        .catch((err) => {
          if (cancelled) return;
          setNotice(
            `The full-rate sidecar could not be fetched (${err.message}). Falling back to the inline preview.`
          );
          inline();
        });
      return () => {
        cancelled = true;
      };
    }

    inline();
    return () => {
      cancelled = true;
    };
  }, [preview]);

  /* ---------------- viewport tracking ---------------- */
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;
    /* Keep the last non-zero width. A zero measurement means the panel is
       display:none or not laid out yet, and adopting it would collapse the
       visible-range readout to "1-1" and stop any path from being built. */
    const measure = () => {
      const w = el.clientWidth;
      if (w > 0) setViewW(w);
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [status]);

  const onScroll = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      const el = scrollRef.current;
      if (el) setScroll(el.scrollLeft);
    });
  }, []);

  useEffect(() => () => cancelAnimationFrame(rafRef.current), []);

  /* ---------------- geometry ---------------- */
  const activeGroup = GROUPS.find((g) => g.id === group) || GROUPS[0];
  const n = series?.n ?? 0;
  const dtDeclared = series?.dt ?? preview?.dt_s ?? (preview?.rate_hz ? 1 / preview.rate_hz : null);
  /* A non-uniform series carries per-sample times instead of dt_s. The strip is
     laid out on the mean spacing so the x axis stays linear and scrollable; the
     hover readout still reports each sample's true time from the `t` channel. */
  const dt =
    dtDeclared ??
    (series && n > 1
      ? Math.max(1e-9, (series.tAt(n - 1) - series.tAt(0)) / (n - 1))
      : null);
  const durationS = series && dt ? Math.max(0, (n - 1) * dt) : clip?.duration_s || 0;

  const maxZoom = durationS > 0 ? MAX_STRIP_PX / durationS : Infinity;
  const pxPerSec = Math.min(ZOOMS[zoomIndex], Math.max(ZOOMS[0], maxZoom));
  const pxPerSample = dt ? dt * pxPerSec : 1;
  const stripW = Math.max(viewW, durationS * pxPerSec);

  const range = useMemo(() => {
    const declared = preview?.range?.[group];
    if (declared && Number.isFinite(declared.min) && Number.isFinite(declared.max)) {
      return { lo: declared.min, hi: declared.max };
    }
    if (!series || n === 0) return { lo: -1, hi: 1 };
    let lo = Infinity;
    let hi = -Infinity;
    const stride = Math.max(1, Math.floor(n / 4000));
    for (const ch of activeGroup.channels) {
      for (let i = 0; i < n; i += stride) {
        const v = series.at(i, ch);
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) return { lo: -1, hi: 1 };
    return { lo, hi };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preview, group, series, n, activeGroup.channels.join(",")]);

  const { lo, hi } = useMemo(() => {
    let a = range.lo;
    let b = range.hi;
    if (a === b) {
      a -= 1;
      b += 1;
    }
    const pad = (b - a) * 0.08;
    return { lo: a - pad, hi: b + pad };
  }, [range]);

  const yFor = useCallback(
    (v) => {
      if (!Number.isFinite(v)) return PLOT_H / 2;
      const p = (v - lo) / (hi - lo);
      return PLOT_H - Math.min(1, Math.max(0, p)) * PLOT_H;
    },
    [lo, hi]
  );

  /* visible sample window */
  const i0 = n === 0 ? 0 : clampInt(Math.floor((scroll - OVERDRAW_PX) / pxPerSample), 0, n - 1);
  const i1 = n === 0 ? 0 : clampInt(Math.ceil((scroll + viewW + OVERDRAW_PX) / pxPerSample), 0, n - 1);
  const vis0 = n === 0 ? 0 : clampInt(Math.floor(scroll / pxPerSample), 0, n - 1);
  const vis1 = n === 0 ? 0 : clampInt(Math.ceil((scroll + viewW) / pxPerSample), 0, n - 1);

  const paths = useMemo(() => {
    if (!series || n === 0) return [];
    return activeGroup.channels.map((ch, k) => ({
      ch,
      axis: ["x", "y", "z"][k],
      d: buildPath(series, ch, i0, i1, pxPerSample, yFor, n),
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, n, group, i0, i1, pxPerSample, yFor]);

  const yTicks = useMemo(() => niceTicks(lo, hi, 5), [lo, hi]);
  const tStep = timeStep(pxPerSec);
  const tTicks = useMemo(() => {
    const out = [];
    if (!(durationS > 0)) return out;
    const from = Math.max(0, Math.floor((scroll - OVERDRAW_PX) / pxPerSec / tStep) * tStep);
    const to = Math.min(durationS, (scroll + viewW + OVERDRAW_PX) / pxPerSec);
    for (let s = from; s <= to + 1e-9; s += tStep) out.push(Number(s.toFixed(6)));
    return out;
  }, [durationS, scroll, viewW, pxPerSec, tStep]);

  /* ---------------- hover ---------------- */
  const onPointerMove = useCallback(
    (event) => {
      const el = scrollRef.current;
      if (!el || !series || n === 0) return;
      const rect = el.getBoundingClientRect();
      const x = event.clientX - rect.left + el.scrollLeft;
      const i = clampInt(Math.round(x / pxPerSample), 0, n - 1);
      setHover({ i, x: i * pxPerSample });
    },
    [series, n, pxPerSample]
  );

  const zoomBy = useCallback(
    (delta) => {
      const el = scrollRef.current;
      const centreTime = el ? (el.scrollLeft + el.clientWidth / 2) / pxPerSec : 0;
      const next = clampInt(zoomIndex + delta, 0, ZOOMS.length - 1);
      setZoomIndex(next);
      requestAnimationFrame(() => {
        const node = scrollRef.current;
        if (!node) return;
        const nextPx = Math.min(ZOOMS[next], Math.max(ZOOMS[0], maxZoom));
        node.scrollLeft = Math.max(0, centreTime * nextPx - node.clientWidth / 2);
      });
    },
    [zoomIndex, pxPerSec, maxZoom]
  );

  /* ---------------- honest subline ---------------- */
  const nDeclared = preview?.n_readings ?? n;
  /* "Full" means we hold every reading the record declares, whichever encoding
     carried it -- an inline_f32 payload is complete by contract. It is only a
     "preview" when we actually have fewer, which happens when a declared
     sidecar could not be fetched and we fell back to the inline channels. */
  const isFull = series ? n >= nDeclared : false;
  const subline = !series
    ? "—"
    : isFull
      ? `${formatCount(n)} readings · full stream`
      : `preview · ${formatCount(n)} of ${formatCount(nDeclared)} readings`;

  const units = group === "accel" ? preview?.units?.accel : preview?.units?.gyro;
  const rawHref = useMemo(() => {
    const rel = clip?.media?.imu?.csv || clip?.media?.imu?.f32 || preview?.sidecar?.url || null;
    if (!rel) return null;
    try {
      return assetUrl(rel);
    } catch {
      return null;
    }
  }, [clip, preview]);

  /* ---------------- render ---------------- */

  if (!preview) {
    return (
      <div className="cat-empty">
        <p className="cat-empty__head">No inertial data in this clip</p>
        <p className="cat-empty__body">
          <code>imu_preview</code> is null, so there is nothing to plot. Where a rig carries an IMU
          that is present but not producing data, the record says so in{" "}
          <code>calibration.imu.status</code> rather than shipping an empty axis
          {clip?.calibration?.imu?.status ? (
            <>
              {" "}— this one reads <strong>{clip.calibration.imu.status}</strong>
              {clip.calibration.imu.model ? ` (${clip.calibration.imu.model})` : ""}
            </>
          ) : null}
          .
        </p>
      </div>
    );
  }

  const groupAvailable = series ? series.has[group] : true;

  /*
   * Is this stream on the collection's published timeline at all?
   *
   * Read off the clip's own sync record: a stream row with no offset and no
   * alignment error is delivered but not placed on the reference clock. For the
   * IMU in this corpus that is every clip, and it is the single most consequential
   * fact about the tab — an inertial stream with no time relation to video cannot
   * do VIO, which is what an IMU is FOR in an egocentric dataset, and cannot be
   * fused with tactile. It used to be legible only as four em-dashes in a table on
   * a different tab.
   */
  const imuSync = useMemo(() => {
    const rows = Array.isArray(clip?.sync?.streams) ? clip.sync.streams : [];
    return rows.find((r) => r && r.stream_id === "imu") || null;
  }, [clip]);
  const notAligned =
    imuSync != null &&
    imuSync.offset_ns == null &&
    imuSync.maximum_alignment_error_ms == null;
  const camImuOffset = clip?.calibration?.cam_imu?.time_offset_s;

  return (
    <section className="cat-imu">
      {notAligned ? (
        <p className="cat-note cat-note--warn" role="note">
          <AlertTriangle size={14} aria-hidden="true" />
          <span>
            <b>This stream is not time-aligned.</b> It is delivered, but it is not placed
            on the clock the video and the gloves share
            {imuSync.clock_id ? ` — it carries ${imuSync.clock_id}` : ""}. No measured
            offset and no alignment error exist for it, so it cannot be fused with the
            other streams as shipped
            {typeof camImuOffset === "number"
              ? `. The only published relation to the cameras is the camera-IMU
                 calibration constant (${camImuOffset} s), which is a rig property and
                 not a per-take measurement`
              : ""}
            .
          </span>
        </p>
      ) : null}

      <header className="cat-imu-head">
        <div>
          <h3 className="cat-imu-title">
            {activeGroup.noun}
            {rawHref ? (
              <a
                className="cat-d-titlelink"
                href={rawHref}
                target="_blank"
                rel="noreferrer noopener"
                aria-label="Open the raw IMU stream in a new tab"
              >
                <ArrowUpRight size={14} aria-hidden="true" />
              </a>
            ) : null}
          </h3>
          <p className="cat-imu-sub">
            {subline}
            {units ? <span className="cat-imu-units"> · {units}</span> : null}
          </p>
          <ul className="cat-imu-legend" aria-label="Axis colours">
            {["x", "y", "z"].map((axis) => (
              <li key={axis}>
                <span
                  className="cat-imu-dot"
                  style={{ background: AXIS_COLORS[axis] }}
                  aria-hidden="true"
                />
                {axis.toUpperCase()}
              </li>
            ))}
          </ul>
        </div>

        <div className="cat-imu-tools">
          <p className="cat-imu-visible" aria-live="polite">
            Visible {formatCount(vis0 + 1)}–{formatCount(vis1 + 1)}
            <span className="cat-imu-hint"> · Scroll horizontally for every reading</span>
          </p>
          <div className="cat-imu-toolrow">
            <PillGroup
              label="Inertial channel group"
              value={group}
              onChange={setGroup}
              options={GROUPS.map((g) => ({
                value: g.id,
                label: g.label,
                disabled: series ? !series.has[g.id] : false,
              }))}
            />
            <div className="cat-imu-zoom" role="group" aria-label="Time zoom">
              <button
                type="button"
                className="cat-iconbtn"
                onClick={() => zoomBy(-1)}
                disabled={zoomIndex === 0}
                aria-label="Zoom out"
              >
                <ZoomOut size={14} aria-hidden="true" />
              </button>
              <span className="cat-imu-zoomval" aria-hidden="true">
                {Math.round(pxPerSec)} px/s
              </span>
              <button
                type="button"
                className="cat-iconbtn"
                onClick={() => zoomBy(1)}
                disabled={zoomIndex === ZOOMS.length - 1 || pxPerSec >= maxZoom}
                aria-label="Zoom in"
              >
                <ZoomIn size={14} aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>
      </header>

      {notice ? (
        <p className="cat-note cat-note--warn" role="status">
          {notice}
        </p>
      ) : null}

      <div className="cat-imu-chart">
        <svg
          className="cat-imu-gutter"
          width={54}
          height={PLOT_H + AXIS_H}
          viewBox={`0 0 54 ${PLOT_H + AXIS_H}`}
          aria-hidden="true"
          focusable="false"
        >
          {yTicks.map((v) => (
            <text key={v} x={48} y={yFor(v) + 4} textAnchor="end" className="cat-imu-ylab">
              {tickLabel(v)}
            </text>
          ))}
        </svg>

        <div
          className="cat-imu-scroll"
          ref={scrollRef}
          onScroll={onScroll}
          onPointerMove={onPointerMove}
          onPointerLeave={() => setHover(null)}
          tabIndex={0}
          data-arrowkeys="own"
          role="img"
          aria-label={`${activeGroup.noun}: ${subline}. Three axis traces, ${
            units || "unitless"
          }, over ${formatDuration(durationS)}.`}
        >
          <svg
            className="cat-imu-svg"
            width={stripW}
            height={PLOT_H + AXIS_H}
            viewBox={`0 0 ${stripW} ${PLOT_H + AXIS_H}`}
            preserveAspectRatio="none"
            focusable="false"
          >
            {yTicks.map((v) => (
              <line
                key={`g${v}`}
                x1={0}
                x2={stripW}
                y1={yFor(v)}
                y2={yFor(v)}
                className="cat-imu-grid"
              />
            ))}

            {tTicks.map((s) => (
              <g key={`t${s}`}>
                <line
                  x1={s * pxPerSec}
                  x2={s * pxPerSec}
                  y1={0}
                  y2={PLOT_H}
                  className="cat-imu-vgrid"
                />
                <text x={s * pxPerSec + 4} y={PLOT_H + 17} className="cat-imu-xlab">
                  {formatTick(s, tStep)}
                </text>
              </g>
            ))}

            {status === "ready" && groupAvailable
              ? paths.map((p) => (
                  <path
                    key={p.ch}
                    d={p.d}
                    fill="none"
                    stroke={AXIS_COLORS[p.axis]}
                    strokeWidth={1}
                    strokeLinejoin="round"
                    vectorEffect="non-scaling-stroke"
                  />
                ))
              : null}

            {hover && status === "ready" ? (
              <line
                x1={hover.x}
                x2={hover.x}
                y1={0}
                y2={PLOT_H}
                className="cat-imu-cross"
              />
            ) : null}
            {hover && status === "ready" && groupAvailable
              ? activeGroup.channels.map((ch, k) => {
                  const v = series.at(hover.i, ch);
                  if (!Number.isFinite(v)) return null;
                  return (
                    <circle
                      key={ch}
                      cx={hover.x}
                      cy={yFor(v)}
                      r={2.5}
                      fill={AXIS_COLORS[["x", "y", "z"][k]]}
                    />
                  );
                })
              : null}
          </svg>
        </div>

        {status === "loading" ? (
          <div className="cat-imu-overlay" role="status">
            <span className="cat-d-shimmer" aria-hidden="true" />
            <span>Reading the full-rate stream…</span>
          </div>
        ) : null}

        {status === "error" ? (
          <div className="cat-imu-overlay" role="alert">
            <span>No readable inertial payload in this record.</span>
          </div>
        ) : null}

        {!groupAvailable && status === "ready" ? (
          <div className="cat-imu-overlay" role="status">
            <span>No {activeGroup.label.toLowerCase()} channels in this stream.</span>
          </div>
        ) : null}

        {hover && series && status === "ready" ? (
          <div className="cat-imu-readout" aria-hidden="true">
            <span className="cat-imu-readout__t">
              t {series.tAt(hover.i).toFixed(4)} s · #{formatCount(hover.i + 1)}
            </span>
            {activeGroup.channels.map((ch, k) => {
              const v = series.at(hover.i, ch);
              return (
                <span key={ch} className="cat-imu-readout__v">
                  <i style={{ background: AXIS_COLORS[["x", "y", "z"][k]] }} />
                  {["X", "Y", "Z"][k]} {Number.isFinite(v) ? v.toFixed(4) : "—"}
                </span>
              );
            })}
          </div>
        ) : null}
      </div>

      <p className="cat-note">
        {pxPerSample < 1
          ? `More readings than pixels at this zoom: each column is drawn as the min/max of the ${Math.max(
              1,
              Math.round(1 / pxPerSample)
            )} readings inside it, so nothing is dropped. Zoom in for one point per reading.`
          : "One point per reading at this zoom."}
        {preview?.note ? ` ${preview.note}` : ""}
        {preview?.frame ? ` Axes are in the ${preview.frame} frame.` : ""}
      </p>
    </section>
  );
}

/* ------------------------------------------------------------------ */

function buildPath(series, ch, i0, i1, pxPerSample, yFor, n) {
  const out = [];
  if (pxPerSample >= 1) {
    for (let i = i0; i <= i1; i += 1) {
      const v = series.at(i, ch);
      if (!Number.isFinite(v)) continue;
      out.push(`${out.length === 0 ? "M" : "L"}${(i * pxPerSample).toFixed(2)} ${yFor(v).toFixed(2)}`);
    }
    return out.join("");
  }

  const samplesPerPx = 1 / pxPerSample;
  const xStart = Math.floor(i0 * pxPerSample);
  const xEnd = Math.ceil(i1 * pxPerSample);
  for (let x = xStart; x <= xEnd; x += 1) {
    const a = Math.max(0, Math.floor(x * samplesPerPx));
    const b = Math.min(n - 1, Math.floor((x + 1) * samplesPerPx) - 1);
    if (b < a) continue;
    let mn = Infinity;
    let mx = -Infinity;
    for (let i = a; i <= b; i += 1) {
      const v = series.at(i, ch);
      if (v < mn) mn = v;
      if (v > mx) mx = v;
    }
    if (!Number.isFinite(mn) || !Number.isFinite(mx)) continue;
    out.push(`${out.length === 0 ? "M" : "L"}${x} ${yFor(mn).toFixed(2)}`);
    out.push(`L${x} ${yFor(mx).toFixed(2)}`);
  }
  return out.join("");
}

function clampInt(v, min, max) {
  if (!Number.isFinite(v)) return min;
  return Math.min(max, Math.max(min, Math.trunc(v)));
}

/**
 * Segmented pill toggle. Implemented as a radiogroup rather than a tablist so
 * it does not collide with the modal's real tablist; `data-arrowkeys="own"`
 * tells ClipDetail to leave Left/Right alone while focus is inside.
 */
export function PillGroup({ label, value, onChange, options }) {
  const refs = useRef([]);
  const live = options.filter((o) => !o.disabled);

  const move = (dir) => {
    if (live.length === 0) return;
    const at = live.findIndex((o) => o.value === value);
    const next = live[(at + dir + live.length) % live.length];
    onChange(next.value);
    requestAnimationFrame(() => {
      const index = options.findIndex((o) => o.value === next.value);
      refs.current[index]?.focus();
    });
  };

  return (
    <div className="cat-pillgroup" role="radiogroup" aria-label={label} data-arrowkeys="own">
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            aria-disabled={o.disabled || undefined}
            tabIndex={on ? 0 : -1}
            ref={(el) => {
              refs.current[i] = el;
            }}
            className={`cat-pill${on ? " is-on" : ""}${o.disabled ? " is-off" : ""}`}
            onClick={() => !o.disabled && onChange(o.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                e.preventDefault();
                move(1);
              } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                e.preventDefault();
                move(-1);
              }
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
