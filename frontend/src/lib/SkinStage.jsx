import { useState } from "react";
import { SKIN_ALIGN } from "./skinAlign.js";

// The Skin composite: ONE hand, left half = robotic dexterous-hand image, right
// half = tactile-skin glove photo. Both are flat 2D images in a fixed 640×560
// box, so the page and the aligner are pixel-identical at any screen size.
//
// Add ?align to the /products URL to get an on-page control panel — drag until
// it lines up, then paste the values block into src/lib/skinAlign.js.

// The crop lives on a NON-rotated wrapper (screen space) so the seam stays a
// vertical line no matter how the hand inside is rotated. The rotate/scale/move
// go on the <img> inside the wrapper.
const fillImg = {
  position: "absolute",
  inset: 0,
  width: "100%",
  height: "100%",
  objectFit: "contain",
  objectPosition: "center",
};
const wrap = (clipPath, zIndex) => ({ position: "absolute", inset: 0, zIndex, clipPath });

const roboClip = (c) => `inset(0 ${100 - c.robCrop}% ${c.robBottom}% 0)`;
const roboImg = (c) => ({
  ...fillImg,
  transform: `translate(${c.robX}%, ${c.robY}%) scale(${c.robScale}) rotate(${c.robRot}deg)`,
});
const gloClip = (c) => `inset(0 0 ${c.gloBottom}% ${c.gloCrop}%)`;
const gloImg = (c) => ({
  ...fillImg,
  transform: `translate(${c.gloX}%, ${c.gloY}%) rotate(${c.gloRot}deg) scale(${c.gloScale}) scaleX(${c.flip ? -1 : 1})`,
});

function Composite({ c }) {
  return (
    <div className="ev-skin-composite">
      <div style={wrap(roboClip(c), 1)}>
        <img className="ev-skin-robo" src="/hero/glove/robo.webp" alt="" aria-hidden="true" style={roboImg(c)} />
      </div>
      <div style={wrap(gloClip(c), 3)}>
        <img
          className="ev-skin-glove"
          src="/hero/glove/pose-skin.webp"
          alt="6thSense tactile skin — glove over a dexterous hand"
          style={gloImg(c)}
        />
      </div>
    </div>
  );
}

function Row({ label, k, v, min, max, step, set }) {
  return (
    <label style={{ display: "grid", gridTemplateColumns: "110px 1fr 52px", gap: 8, alignItems: "center", fontSize: 12 }}>
      <span>{label}</span>
      <input type="range" min={min} max={max} step={step} value={v} onChange={(e) => set(k, parseFloat(e.target.value))} />
      <input type="number" value={v} step={step} onChange={(e) => set(k, parseFloat(e.target.value))}
        style={{ width: 48, background: "#111", color: "#fff", border: "1px solid #333", borderRadius: 4, fontSize: 11 }} />
    </label>
  );
}

function Panel({ c, set }) {
  return (
    <div style={{ position: "fixed", top: 12, right: 12, zIndex: 9999, width: 340, background: "rgba(10,10,12,0.96)",
      border: "1px solid #333", borderRadius: 8, padding: 14, color: "#eee", fontFamily: "ui-monospace, Menlo, monospace",
      display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ color: "#f0612a", fontWeight: 700 }}>SKIN ALIGN (on-page)</div>
      <Row label="overall size" k="size" v={c.size} min={0.2} max={1.2} step={0.02} set={set} />
      <div style={{ color: "#f0612a", marginTop: 4 }}>robotic</div>
      <Row label="scale" k="robScale" v={c.robScale} min={0.3} max={2.5} step={0.02} set={set} />
      <Row label="pos X %" k="robX" v={c.robX} min={-60} max={60} step={1} set={set} />
      <Row label="pos Y %" k="robY" v={c.robY} min={-60} max={60} step={1} set={set} />
      <Row label="rotate °" k="robRot" v={c.robRot} min={-45} max={45} step={1} set={set} />
      <Row label="crop (seam) %" k="robCrop" v={c.robCrop} min={0} max={100} step={1} set={set} />
      <Row label="crop bottom %" k="robBottom" v={c.robBottom} min={0} max={80} step={1} set={set} />
      <div style={{ color: "#f0612a", marginTop: 4 }}>glove</div>
      <Row label="scale" k="gloScale" v={c.gloScale} min={0.3} max={2} step={0.02} set={set} />
      <Row label="pos X %" k="gloX" v={c.gloX} min={-60} max={60} step={1} set={set} />
      <Row label="pos Y %" k="gloY" v={c.gloY} min={-60} max={60} step={1} set={set} />
      <Row label="rotate °" k="gloRot" v={c.gloRot} min={-45} max={45} step={1} set={set} />
      <Row label="crop (clip) %" k="gloCrop" v={c.gloCrop} min={0} max={100} step={1} set={set} />
      <Row label="crop bottom %" k="gloBottom" v={c.gloBottom} min={0} max={80} step={1} set={set} />
      <label style={{ fontSize: 12, display: "flex", gap: 8 }}>
        <input type="checkbox" checked={c.flip} onChange={(e) => set("flip", e.target.checked)} /> flip glove
      </label>
      <pre style={{ background: "#000", border: "1px solid #333", borderRadius: 6, padding: 8, fontSize: 10.5, whiteSpace: "pre-wrap", margin: "6px 0 0" }}>
{`size:${c.size}, robScale:${c.robScale}, robX:${c.robX}, robY:${c.robY},
robRot:${c.robRot}, robCrop:${c.robCrop}, robBottom:${c.robBottom},
gloScale:${c.gloScale}, gloX:${c.gloX}, gloY:${c.gloY}, gloRot:${c.gloRot},
gloCrop:${c.gloCrop}, gloBottom:${c.gloBottom}, flip:${c.flip}`}
      </pre>
      <div style={{ fontSize: 11, opacity: 0.6 }}>Paste this into src/lib/skinAlign.js</div>
    </div>
  );
}

export default function SkinStage() {
  const [c, setC] = useState(SKIN_ALIGN);
  const set = (k, v) => setC((p) => ({ ...p, [k]: v }));
  const aligning =
    typeof window !== "undefined" && new URLSearchParams(window.location.search).has("align");
  return (
    <div className="ev-pstage ev-pstage--3d ev-skin-layered" style={{ "--skin-size": c.size }}>
      <span className="ev-badge ev-soon">In development</span>
      <Composite c={c} />
      <span className="ev-pstage-cap">robotic hand · tactile skin</span>
      {aligning && <Panel c={c} set={set} />}
    </div>
  );
}
