import { useEffect, useMemo, useState } from "react";
import { GLOVE_ALIGN, GLOVE_CYCLE_MS, GLOVE_FRAME_IDS, liveTune } from "../lib/gloveAlign.js";

/**
 * In-page tuning overlay for the /products Skin flip-book. Reached with `?tune`.
 *
 * This exists alongside /glove-tune deliberately. /glove-tune is the precision
 * tool: it onion-skins the frames over each other so you can size-match by eye.
 * This panel is the opposite trade — you tune against the REAL scene, at the real
 * box size, over the real aurora, while the crossfade actually runs. That is the
 * only place you can judge whether the pulse is gone in context.
 *
 * It writes into `liveTune` (module-level, mutable) rather than React state that
 * the animation depends on, because the flip-book runs in a requestAnimationFrame
 * loop inside ProductsV2's own effect. Pushing slider values through React would
 * re-run that effect and restart the animation on every drag tick.
 *
 * Nothing here ships to a normal visitor: without `?tune` the component is never
 * mounted and `liveTune.active` stays false, so the loop reads the constants.
 */
export default function GloveTunePanel() {
  const [cycleMs, setCycleMs] = useState(liveTune.cycleMs);
  const [scale, setScale] = useState(() => ({ ...liveTune.scale }));
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(true);
  const [hold, setHold] = useState(liveTune.hold);

  // Mark tuning live for as long as the panel is mounted, and hand back control
  // on unmount so a client-side route change cannot leave the page in tune mode.
  useEffect(() => {
    liveTune.active = true;
    return () => { liveTune.active = false; liveTune.hold = null; };
  }, []);

  useEffect(() => { liveTune.cycleMs = cycleMs; }, [cycleMs]);
  useEffect(() => { Object.assign(liveTune.scale, scale); }, [scale]);
  useEffect(() => { liveTune.hold = hold; }, [hold]);

  const block = useMemo(() => {
    const rows = GLOVE_FRAME_IDS.map((id) => {
      const a = GLOVE_ALIGN[id] || { x: 0, y: 0 };
      return `  "${id}": { scale: ${Number(scale[id]).toFixed(3)}, x: ${a.x}, y: ${a.y} },`;
    }).join("\n");
    return `export const GLOVE_ALIGN = {\n${rows}\n};\n\nexport const GLOVE_CYCLE_MS = ${Math.round(cycleMs)};`;
  }, [scale, cycleMs]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(block);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  };

  const reset = () => {
    setHold(null);
    setCycleMs(GLOVE_CYCLE_MS);
    setScale(Object.fromEntries(GLOVE_FRAME_IDS.map((id) => [id, GLOVE_ALIGN[id]?.scale ?? 1])));
  };

  const wrap = {
    position: "fixed", top: 14, right: 14, zIndex: 9999, width: open ? 320 : "auto",
    background: "rgba(10,10,13,.93)", border: "1px solid rgba(240,97,42,.5)",
    borderRadius: 10, padding: open ? "14px 16px" : "8px 12px", color: "#f4f1ea",
    font: "13px/1.45 -apple-system,BlinkMacSystemFont,'SF Pro Text',sans-serif",
    backdropFilter: "blur(8px)", boxShadow: "0 18px 50px rgba(0,0,0,.6)",
  };

  if (!open) {
    return (
      <div style={wrap}>
        <button onClick={() => setOpen(true)} style={btn}>tune ▸</button>
      </div>
    );
  }

  return (
    <div style={wrap}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
        <b style={{ color: "#F0612A", letterSpacing: ".08em", fontSize: 11 }}>GLOVE TUNER</b>
        <button onClick={() => setOpen(false)} style={btn}>hide</button>
      </div>

      <Row label={`speed — ${(cycleMs / 1000).toFixed(1)}s per closed→open→closed`}>
        <input type="range" min={2000} max={20000} step={100} value={cycleMs}
          onChange={(e) => setCycleMs(+e.target.value)} style={range} />
      </Row>
      <div style={hint}>Lower = faster. Wall-clock, so it looks the same on 60Hz and 120Hz.</div>

      <div style={{ height: 1, background: "rgba(244,241,234,.14)", margin: "12px 0 10px" }} />
      <div style={{ fontSize: 11, letterSpacing: ".08em", color: "#F0612A", marginBottom: 8 }}>
        SIZE PER FRAME
      </div>

      {GLOVE_FRAME_IDS.map((id, i) => (
        <Row key={id} label={
          <span>
            <button
              onClick={() => setHold(hold === i ? null : i)}
              title={hold === i ? "resume cycling" : "freeze on this frame while you size it"}
              style={{
                ...btn, padding: "1px 6px", fontSize: 11, marginRight: 6,
                borderColor: hold === i ? "#F0612A" : "rgba(244,241,234,.28)",
                color: hold === i ? "#F0612A" : "#f4f1ea",
              }}>
              {hold === i ? "held" : "hold"}
            </button>
            frame {id}
            {i === 0 && <span style={{ color: "#9a9384" }}> (fist)</span>}
            {i === GLOVE_FRAME_IDS.length - 1 && <span style={{ color: "#9a9384" }}> (open)</span>}
            <span style={{ float: "right", fontVariantNumeric: "tabular-nums", color: "#c9c2b4" }}>
              {Number(scale[id]).toFixed(3)}×
            </span>
          </span>
        }>
          <input type="range" min={0.5} max={1.6} step={0.005} value={scale[id]}
            onChange={(e) => setScale((s) => ({ ...s, [id]: +e.target.value }))} style={range} />
        </Row>
      ))}

      <div style={hint}>
        Hit <b>hold</b> to freeze the scene on a frame, then drag its slider — otherwise the
        crossfade is only showing two frames at a time and sizing the others looks like
        nothing is happening. The fist is the one that reads oversized and makes it pulse,
        so pull <b>000</b> down until the jump goes away, then release and watch it run.
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
        <button onClick={copy} style={{ ...btn, flex: 1, borderColor: "rgba(240,97,42,.6)" }}>
          {copied ? "copied ✓" : "copy for gloveAlign.js"}
        </button>
        <button onClick={reset} style={btn}>reset</button>
      </div>

      <pre style={{
        margin: "10px 0 0", padding: "8px 10px", background: "rgba(0,0,0,.5)",
        borderRadius: 6, fontSize: 10.5, lineHeight: 1.4, maxHeight: 128,
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
