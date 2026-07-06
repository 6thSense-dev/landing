import { useState, Suspense, lazy } from "react";
import { SKIN_ALIGN } from "../lib/skinAlign.js";

// TEMPORARY alignment tool for the Skin composite (robotic hand + glove photo).
// Route: /skin-tune. Drag the sliders until the two halves line up, then read
// the values off the panel and hand them back (or paste into the CSS/props).
// Delete this file + its route when the alignment is locked in.

const HandTurntable = lazy(() => import("../lib/HandTurntable.jsx"));

const STAGE_W = 640;
const STAGE_H = 560;

function Slider({ label, value, min, max, step, onChange }) {
  return (
    <label style={{ display: "grid", gridTemplateColumns: "132px 1fr 64px", gap: 10, alignItems: "center", fontSize: 13 }}>
      <span style={{ color: "#cfcfcf" }}>{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: "100%" }}
      />
      <input
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: 60, background: "#111", color: "#fff", border: "1px solid #333", borderRadius: 4, padding: "3px 5px", fontSize: 12 }}
      />
    </label>
  );
}

// Start the tuner from the exact values the live page is using.
const DEFAULTS = { ...SKIN_ALIGN };

export default function SkinTune() {
  const [s, setS] = useState(DEFAULTS);
  const set = (k) => (v) => setS((p) => ({ ...p, [k]: v }));
  const reset = () => setS(DEFAULTS);

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0b", color: "#eee", fontFamily: "ui-monospace, Menlo, monospace", padding: 24, display: "flex", gap: 28, flexWrap: "wrap" }}>
      {/* ---- stage ---- */}
      <div>
        <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 8 }}>
          /skin-tune — robotic (left) + glove (right). Drag to align, then copy the values below.
        </div>
        <div
          style={{
            position: "relative",
            width: STAGE_W,
            height: STAGE_H,
            background: "#0a0a0b",
            border: "1px solid #222",
            overflow: "hidden",
          }}
        >
          {/* composite: all three layers scale together by `size` (matches the
              production .ev-skin-composite so this is WYSIWYG). */}
          <div style={{ position: "absolute", inset: 0, transform: `scale(${s.size})`, transformOrigin: "center" }}>
            {/* bottom: robotic hand (still) */}
            <div style={{ position: "absolute", inset: 0, zIndex: 1 }}>
              <Suspense fallback={<div style={{ padding: 20, opacity: 0.5 }}>loading model…</div>}>
                <HandTurntable still scale={s.robScale} posX={s.robX} posY={s.robY} rotY={s.robRotY} />
              </Suspense>
            </div>
            {/* middle: black mask over the right, starting at robCrop */}
            <div
              style={{
                position: "absolute",
                top: 0,
                bottom: 0,
                right: 0,
                left: `${s.robCrop}%`,
                zIndex: 2,
                background: "#050505",
                WebkitMaskImage: "linear-gradient(to right, transparent 0, #000 7%)",
                maskImage: "linear-gradient(to right, transparent 0, #000 7%)",
              }}
            />
            {/* top: glove photo, clipped to the right of gloCrop */}
            <img
              src="/hero/glove/pose-skin.webp"
              alt="glove"
              style={{
                position: "absolute",
                inset: 0,
                zIndex: 3,
                width: "100%",
                height: "100%",
                objectFit: "contain",
                objectPosition: "center",
                clipPath: `inset(0 0 0 ${s.gloCrop}%)`,
                transform: `translate(${s.gloX}%, ${s.gloY}%) scale(${s.gloScale}) scaleX(${s.flip ? -1 : 1})`,
              }}
            />
          </div>
          {/* seam guide (fixed at stage centre, not scaled) */}
          <div style={{ position: "absolute", top: 0, bottom: 0, left: "50%", width: 1, background: "rgba(240,97,42,0.4)", zIndex: 4, pointerEvents: "none" }} />
        </div>
      </div>

      {/* ---- controls ---- */}
      <div style={{ minWidth: 380, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div style={{ color: "#f0612a", fontWeight: 700, marginBottom: 8 }}>OVERALL</div>
          <Slider label="size (both)" value={s.size} min={0.2} max={1.2} step={0.02} onChange={set("size")} />
        </div>
        <div>
          <div style={{ color: "#f0612a", fontWeight: 700, marginBottom: 8 }}>ROBOTIC HAND</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Slider label="crop (mask %)" value={s.robCrop} min={0} max={100} step={1} onChange={set("robCrop")} />
            <Slider label="size (scale)" value={s.robScale} min={0.4} max={3} step={0.02} onChange={set("robScale")} />
            <Slider label="pos X" value={s.robX} min={-1.2} max={1.2} step={0.01} onChange={set("robX")} />
            <Slider label="pos Y" value={s.robY} min={-1.2} max={1.2} step={0.01} onChange={set("robY")} />
            <Slider label="rotate Y (rad)" value={s.robRotY} min={-3.14} max={3.14} step={0.02} onChange={set("robRotY")} />
          </div>
        </div>

        <div>
          <div style={{ color: "#f0612a", fontWeight: 700, marginBottom: 8 }}>GLOVE PHOTO</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Slider label="crop (clip %)" value={s.gloCrop} min={0} max={100} step={1} onChange={set("gloCrop")} />
            <Slider label="size (scale)" value={s.gloScale} min={0.3} max={2} step={0.01} onChange={set("gloScale")} />
            <Slider label="pos X (%)" value={s.gloX} min={-60} max={60} step={1} onChange={set("gloX")} />
            <Slider label="pos Y (%)" value={s.gloY} min={-60} max={60} step={1} onChange={set("gloY")} />
            <label style={{ fontSize: 13, display: "flex", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={s.flip} onChange={(e) => set("flip")(e.target.checked)} />
              flip glove horizontally
            </label>
          </div>
        </div>

        <button onClick={reset} style={{ alignSelf: "start", background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 6, padding: "6px 12px", cursor: "pointer" }}>
          reset
        </button>

        {/* live values readout */}
        <pre style={{ background: "#111", border: "1px solid #333", borderRadius: 6, padding: 12, fontSize: 12, whiteSpace: "pre-wrap" }}>
{`SIZE     ${s.size}
ROBOTIC  scale=${s.robScale}  posX=${s.robX}  posY=${s.robY}  rotY=${s.robRotY}  crop=${s.robCrop}%
GLOVE    scale=${s.gloScale}  x=${s.gloX}%  y=${s.gloY}%  crop=${s.gloCrop}%  flip=${s.flip}`}
        </pre>
        <div style={{ fontSize: 12, opacity: 0.6 }}>
          When it looks right, paste this block back to me and I'll bake it into the Skin section.
        </div>
      </div>
    </div>
  );
}
