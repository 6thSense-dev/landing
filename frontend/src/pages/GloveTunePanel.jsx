import { useEffect, useMemo, useState } from "react";
import { GLOVE_ALIGN, GLOVE_CYCLE_MS, GLOVE_FRAME_IDS, liveTune } from "../lib/gloveAlign.js";

/**
 * In-page tuning overlay for the /products Skin flip-book. Reached with `?tune`.
 *
 * This exists alongside /glove-tune deliberately. /glove-tune is the precision
 * tool: it onion-skins all six frames over each other on a bare stage. This panel
 * is the opposite trade — you tune against the REAL scene, at the real box size,
 * over the real aurora, while the crossfade actually runs. That is the only place
 * you can judge whether the pulse is gone in context.
 *
 * It writes into `liveTune` (module-level, mutable) rather than React state that
 * the animation depends on, because the flip-book runs in a requestAnimationFrame
 * loop inside ProductsV2's own effect. Pushing slider values through React state
 * the effect depends on would restart the animation on every drag tick.
 *
 * Nothing here ships to a normal visitor: without `?tune` the component is never
 * mounted and `liveTune.active` stays false, so the loop reads the constants.
 */
export default function GloveTunePanel() {
  const [cycleMs, setCycleMs] = useState(liveTune.cycleMs);
  const [align, setAlign] = useState(() =>
    Object.fromEntries(GLOVE_FRAME_IDS.map((id) => [id, { ...liveTune.align[id] }])));
  const [hold, setHold] = useState(liveTune.hold);
  const [compare, setCompare] = useState(liveTune.compare);
  const [alpha, setAlpha] = useState(liveTune.compareAlpha);
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(true);

  // Hand control back on unmount so a client-side route change can't leave the
  // page frozen in a tuning state.
  useEffect(() => {
    liveTune.active = true;
    return () => {
      liveTune.active = false;
      liveTune.hold = null;
      liveTune.compare = false;
    };
  }, []);

  useEffect(() => { liveTune.cycleMs = cycleMs; }, [cycleMs]);
  useEffect(() => { liveTune.hold = hold; }, [hold]);
  useEffect(() => { liveTune.compare = compare; }, [compare]);
  useEffect(() => { liveTune.compareAlpha = alpha; }, [alpha]);
  useEffect(() => {
    for (const id of GLOVE_FRAME_IDS) Object.assign(liveTune.align[id], align[id]);
  }, [align]);

  const setField = (id, key) => (v) =>
    setAlign((a) => ({ ...a, [id]: { ...a[id], [key]: v } }));

  const block = useMemo(() => {
    const rows = GLOVE_FRAME_IDS.map((id) => {
      const a = align[id];
      return `  "${id}": { scale: ${(+a.scale).toFixed(3)}, x: ${(+a.x).toFixed(2)}, y: ${(+a.y).toFixed(2)} },`;
    }).join("\n");
    return `export const GLOVE_ALIGN = {\n${rows}\n};\n\nexport const GLOVE_CYCLE_MS = ${Math.round(cycleMs)};`;
  }, [align, cycleMs]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(block);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch { setCopied(false); }
  };

  const reset = () => {
    setHold(null); setCompare(false); setCycleMs(GLOVE_CYCLE_MS);
    setAlign(Object.fromEntries(GLOVE_FRAME_IDS.map((id) =>
      [id, { ...(GLOVE_ALIGN[id] || { scale: 1, x: 0, y: 0 }) }])));
  };

  const wrap = {
    position: "fixed", top: 14, right: 14, zIndex: 9999, width: open ? 336 : "auto",
    maxHeight: "calc(100vh - 28px)", overflowY: "auto",
    background: "rgba(10,10,13,.94)", border: "1px solid rgba(240,97,42,.5)",
    borderRadius: 10, padding: open ? "14px 16px" : "8px 12px", color: "#f4f1ea",
    font: "13px/1.45 -apple-system,BlinkMacSystemFont,'SF Pro Text',sans-serif",
    backdropFilter: "blur(8px)", boxShadow: "0 18px 50px rgba(0,0,0,.6)",
  };

  if (!open) {
    return <div style={wrap}><button onClick={() => setOpen(true)} style={btn}>tune ▸</button></div>;
  }

  return (
    <div style={wrap}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <b style={{ color: "#F0612A", letterSpacing: ".08em", fontSize: 11 }}>GLOVE TUNER</b>
        <button onClick={() => setOpen(false)} style={btn}>hide</button>
      </div>

      {/* ---- the one-frame workflow, first because it's the normal case ---- */}
      <div style={{
        border: `1px solid ${compare ? "#F0612A" : "rgba(244,241,234,.2)"}`,
        borderRadius: 7, padding: "9px 11px", marginBottom: 12,
        background: compare ? "rgba(240,97,42,.08)" : "transparent",
      }}>
        <label style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12.5 }}>
          <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} />
          <b>compare 000 vs 001</b>
        </label>
        <div style={hint}>
          Freezes the fist (000) solid with 001 ghosted on top, so 000 is the only
          frame you have to touch. Animation and <i>hold</i> are ignored while this is on.
        </div>
        {compare && (
          <Row label={`001 ghost opacity — ${alpha.toFixed(2)}`}>
            <input type="range" min={0.1} max={0.9} step={0.01} value={alpha}
              onChange={(e) => setAlpha(+e.target.value)} style={range} />
          </Row>
        )}
      </div>

      <Row label={`speed — ${(cycleMs / 1000).toFixed(1)}s per closed→open→closed`}>
        <input type="range" min={2000} max={20000} step={100} value={cycleMs}
          onChange={(e) => setCycleMs(+e.target.value)} style={range} />
      </Row>
      <div style={hint}>Lower = faster. Wall-clock, so identical on 60Hz and 120Hz.</div>

      <div style={{ height: 1, background: "rgba(244,241,234,.14)", margin: "12px 0 10px" }} />

      {GLOVE_FRAME_IDS.map((id, i) => {
        const a = align[id];
        const dimmed = compare && i > 1;
        return (
          <div key={id} style={{ marginBottom: 12, opacity: dimmed ? 0.35 : 1 }}>
            <div style={{ fontSize: 12, color: "#ded7c9", marginBottom: 3 }}>
              {!compare && (
                <button onClick={() => setHold(hold === i ? null : i)}
                  title={hold === i ? "resume cycling" : "freeze on this frame"}
                  style={{ ...btn, padding: "1px 6px", fontSize: 11, marginRight: 6,
                    borderColor: hold === i ? "#F0612A" : "rgba(244,241,234,.28)",
                    color: hold === i ? "#F0612A" : "#f4f1ea" }}>
                  {hold === i ? "held" : "hold"}
                </button>
              )}
              <b>frame {id}</b>
              {i === 0 && <span style={{ color: "#F0612A" }}> · the fist</span>}
              {i === 1 && compare && <span style={{ color: "#9a9384" }}> · ghost reference</span>}
              {i === GLOVE_FRAME_IDS.length - 1 && <span style={{ color: "#9a9384" }}> · open</span>}
            </div>
            <Mini label="size" value={a.scale} min={0.5} max={1.6} step={0.005}
              fmt={(v) => `${(+v).toFixed(3)}×`} onChange={setField(id, "scale")} />
            <Mini label="up / down" value={a.y} min={-30} max={30} step={0.25}
              fmt={(v) => `${(+v) > 0 ? "+" : ""}${(+v).toFixed(2)}%`} onChange={setField(id, "y")} />
            <Mini label="left / right" value={a.x} min={-30} max={30} step={0.25}
              fmt={(v) => `${(+v) > 0 ? "+" : ""}${(+v).toFixed(2)}%`} onChange={setField(id, "x")} />
          </div>
        );
      })}

      <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
        <button onClick={copy} style={{ ...btn, flex: 1, borderColor: "rgba(240,97,42,.6)" }}>
          {copied ? "copied ✓" : "copy for gloveAlign.js"}
        </button>
        <button onClick={reset} style={btn}>reset</button>
      </div>

      <pre style={{
        margin: "10px 0 0", padding: "8px 10px", background: "rgba(0,0,0,.5)",
        borderRadius: 6, fontSize: 10.5, lineHeight: 1.4, maxHeight: 130,
        overflow: "auto", color: "#bdb6a8", whiteSpace: "pre",
      }}>{block}</pre>
    </div>
  );
}

const btn = {
  appearance: "none", cursor: "pointer", background: "rgba(244,241,234,.08)",
  color: "#f4f1ea", border: "1px solid rgba(244,241,234,.28)", borderRadius: 6,
  padding: "6px 10px", font: "inherit", fontSize: 12,
};
const range = { width: "100%", accentColor: "#F0612A", margin: "3px 0 0" };
const hint = { fontSize: 11.5, color: "#8d8578", lineHeight: 1.4, marginTop: 6 };

function Row({ label, children }) {
  return (
    <label style={{ display: "block", marginBottom: 8 }}>
      <span style={{ fontSize: 12, color: "#ded7c9" }}>{label}</span>
      {children}
    </label>
  );
}

/** Compact labelled slider with a live tabular readout on the right. */
function Mini({ label, value, min, max, step, fmt, onChange }) {
  return (
    <label style={{ display: "block", marginBottom: 2 }}>
      <span style={{ fontSize: 11, color: "#9a9384", display: "flex", justifyContent: "space-between" }}>
        <span>{label}</span>
        <span style={{ fontVariantNumeric: "tabular-nums", color: "#c9c2b4" }}>{fmt(value)}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(+e.target.value)} style={range} />
    </label>
  );
}
