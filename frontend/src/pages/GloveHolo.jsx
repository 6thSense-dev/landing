import { Suspense, lazy, useState } from "react";

/**
 * TEMPORARY look-test at /glove-holo for the new Tripo-generated glove mesh
 * (public/models/glove-holo/glove-holo.fbx).
 *
 * The question this page answers: can this replace the current Skin visual?
 * "Compare" puts it next to what ships today — the /products Skin scene runs a
 * flip-book of /hero/glove/frame-00N.webp — so the swap can be judged, not
 * imagined. Nothing on a shipped page imports this; delete the file and its
 * route in main.jsx once the call is made.
 */

const HoloGlove = lazy(() => import("../lib/HoloGlove.jsx"));

const LOOKS = [
  ["holo", "Holographic"],
  ["textured", "Original texture"],
  ["solid", "Matte 6thSense"],
];
const HUES = [
  ["orange", "Orange #F0612A"],
  ["cyan", "Cyan"],
  ["white", "White"],
];

const ORANGE = "#f0612a";

// Yaw presets for the two faces that carry a product feature. Measured off the
// render, not guessed — the mesh's front is not the back of the hand.
const VIEWS = [
  ["4.71", "Back · AprilTag"],
  ["1.57", "Palm · grip pad"],
];
// Only light a preset up when the yaw is actually on it — otherwise the default
// front-on view falsely reads as "Palm" just by being the closer of the two.
const nearestView = (y) =>
  VIEWS.find(([v]) => Math.abs(parseFloat(v) - y) < 0.25)?.[0] ?? "";

function Slider({ label, value, min, max, step, onChange }) {
  return (
    <label style={{ display: "grid", gridTemplateColumns: "104px 1fr 50px", gap: 10, alignItems: "center", fontSize: 12.5 }}>
      <span style={{ color: "#cfcfcf" }}>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))} style={{ width: "100%" }} />
      <span style={{ color: "#8a8a8a", fontSize: 11.5, textAlign: "right" }}>{value}</span>
    </label>
  );
}

function Seg({ options, value, onChange }) {
  return (
    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
      {options.map(([v, label]) => (
        <button key={v} onClick={() => onChange(v)}
          style={{
            background: value === v ? ORANGE : "#18181b",
            color: value === v ? "#0a0a0b" : "#ddd",
            border: `1px solid ${value === v ? ORANGE : "#333"}`,
            borderRadius: 6, padding: "5px 11px", fontSize: 12,
            fontFamily: "inherit", fontWeight: value === v ? 700 : 400, cursor: "pointer",
          }}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Check({ label, checked, onChange }) {
  return (
    <label style={{ fontSize: 12.5, display: "flex", gap: 8, alignItems: "center", cursor: "pointer" }}>
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

// Every control is also a query param (?look=textured&spin=0&rotY=1.57&…) so a
// specific view can be linked, and so the screenshot script can drive the page
// without synthesising slider drags.
const Q = typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
const qStr = (k, d) => Q.get(k) ?? d;
const qNum = (k, d) => (Q.has(k) && !Number.isNaN(parseFloat(Q.get(k))) ? parseFloat(Q.get(k)) : d);
const qBool = (k, d) => (Q.has(k) ? !["0", "false", "no"].includes(Q.get(k)) : d);

export default function GloveHolo() {
  const [look, setLook] = useState(() => qStr("look", "holo"));
  const [hue, setHue] = useState(() => qStr("hue", "white"));
  const [wire, setWire] = useState(() => qBool("wire", true));
  const [spin, setSpin] = useState(() => qBool("spin", true));
  const [ring, setRing] = useState(() => qBool("ring", true));
  const [intensity, setIntensity] = useState(() => qNum("intensity", 1));
  const [scan, setScan] = useState(() => qNum("scan", 1));
  const [glitch, setGlitch] = useState(() => qNum("glitch", 0.6));
  const [rotX, setRotX] = useState(() => qNum("rotX", 0));
  // Opens on the back of the wrist so the AprilTag is the first thing you see;
  // the turntable carries on from there.
  const [rotY, setRotY] = useState(() => qNum("rotY", 4.71));
  // -0.45 rad of roll: the mesh is authored leaning right, so this is what
  // stands the forearm vertical and the fingers up.
  const [rotZ, setRotZ] = useState(() => qNum("rotZ", -0.45));
  // 0 = mesh as delivered (forearm included). ~0.3 cuts it at the wrist,
  // which is what the current Skin visual shows.
  const [trim, setTrim] = useState(() => qNum("trim", 0));
  // Grip pad + AprilTag overlay strength. 0 = mesh exactly as delivered.
  const [marks, setMarks] = useState(() => qNum("marks", 1));
  // Synthesised grips down the fingers, and their lattice density.
  const [gripExtend, setGripExtend] = useState(() => qNum("gripExtend", 1));
  const [gripScale, setGripScale] = useState(() => qNum("gripScale", 68));
  // Inward shrink, as a fraction of model height. Slims the bulky fingers.
  const [slim, setSlim] = useState(() => qNum("slim", 0.5));
  // Lengthen the fingers — the mesh reads short and stubby.
  const [stretch, setStretch] = useState(() => qNum("stretch", 0.5));
  const [compare, setCompare] = useState(() => qBool("compare", true));
  const [info, setInfo] = useState(null);
  const [err, setErr] = useState(null);

  const stage = {
    position: "relative", width: "100%", aspectRatio: "8 / 7",
    background: "radial-gradient(60% 60% at 50% 45%, rgba(240,97,42,0.10), rgba(10,10,11,0) 70%), #0a0a0b",
    border: "1px solid #222", borderRadius: 14, overflow: "hidden",
  };

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0b", color: "#eee", fontFamily: "ui-monospace, Menlo, monospace", padding: 22 }}>
      <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 14 }}>
        /glove-holo — new Tripo glove mesh, holographic look-test. Drag the model to spin, drag vertically to tilt.
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0,1fr) 360px", gap: 24, alignItems: "start" }}>
        {/* ---- stages ---- */}
        <div style={{ display: "grid", gridTemplateColumns: compare ? "1fr 1fr" : "1fr", gap: 18 }}>
          <div>
            <div style={{ fontSize: 11.5, color: ORANGE, marginBottom: 6, letterSpacing: 0.4 }}>NEW — glove-holo.fbx</div>
            <div style={stage} data-stage="new">
              {err ? (
                <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", padding: 24, textAlign: "center", fontSize: 12.5, color: "#d9534f" }}>
                  Could not render: {String(err)}
                  <br />
                  <span style={{ color: "#888" }}>(needs a real WebGL browser — headless has none)</span>
                </div>
              ) : (
                <Suspense fallback={<div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", fontSize: 12, opacity: 0.5 }}>loading mesh…</div>}>
                  <HoloGlove
                    look={look} hue={hue} wire={wire} spin={spin} ring={ring}
                    intensity={intensity} scan={scan} glitch={glitch}
                    rotX={rotX} rotY={rotY} rotZ={rotZ} trim={trim} marks={marks}
                    gripExtend={gripExtend} gripScale={gripScale} slim={slim} stretch={stretch}
                    onReady={setInfo} onError={(e) => setErr(e?.message || e)}
                  />
                </Suspense>
              )}
            </div>
          </div>

          {compare && (
            <div>
              <div style={{ fontSize: 11.5, color: "#8a8a8a", marginBottom: 6, letterSpacing: 0.4 }}>
                CURRENT — /products Skin scene
              </div>
              <div style={stage} data-stage="current">
                {/* The shipped Skin visual is this webp flip-book (see ProductsV2
                    STAGES[0].img); frame-001 is the pose the scene rests on. */}
                <img src="/hero/glove/frame-001.webp" alt="Current Skin glove render"
                  style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain" }} />
              </div>
            </div>
          )}
        </div>

        {/* ---- controls ---- */}
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div>
            <div style={{ color: ORANGE, fontWeight: 700, marginBottom: 8, fontSize: 12.5 }}>LOOK</div>
            <Seg options={LOOKS} value={look} onChange={setLook} />
          </div>

          <div>
            <div style={{ color: ORANGE, fontWeight: 700, marginBottom: 8, fontSize: 12.5 }}>HOLO TINT</div>
            <Seg options={HUES} value={hue} onChange={setHue} />
            <div style={{ fontSize: 11, opacity: 0.55, marginTop: 6, lineHeight: 1.5 }}>
              DESIGN.md: “restrained — black + white + one warm orange… warm, not sci-fi cyan.”
              Cyan/white are here for comparison only.
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            <div style={{ color: ORANGE, fontWeight: 700, fontSize: 12.5 }}>HOLO PARAMS</div>
            <Slider label="intensity" value={intensity} min={0.2} max={2.5} step={0.05} onChange={setIntensity} />
            <Slider label="scanlines" value={scan} min={0} max={1} step={0.05} onChange={setScan} />
            <Slider label="glitch" value={glitch} min={0} max={2} step={0.05} onChange={setGlitch} />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            <div style={{ color: ORANGE, fontWeight: 700, fontSize: 12.5 }}>PRODUCT MARKS</div>
            <Slider label="strength" value={marks} min={0} max={1.6} step={0.05} onChange={setMarks} />
            <Slider label="onto fingers" value={gripExtend} min={0} max={1} step={0.05} onChange={setGripExtend} />
            <Slider label="grip density" value={gripScale} min={12} max={110} step={1} onChange={setGripScale} />
            <Slider label="slim fingers" value={slim} min={0} max={1} step={0.05} onChange={setSlim} />
            <Slider label="longer fingers" value={stretch} min={0} max={1} step={0.05} onChange={setStretch} />
            <div style={{ fontSize: 11, opacity: 0.55, lineHeight: 1.5 }}>
              Anti-slip grip pad + AprilTag, composited from glove-marks.png so they
              survive the holo and matte looks. The tag is a real, detector-verified
              tag36h11 replacing the blobby glyph Tripo baked in. Tripo only painted
              grips on the palm, so “onto fingers” synthesises the rest as a
              triradiate lattice projected along the palm normal. 0 / 0 = as delivered.
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            <div style={{ color: ORANGE, fontWeight: 700, fontSize: 12.5 }}>POSE</div>
            <Seg options={VIEWS} value={nearestView(rotY)} onChange={(v) => { setRotY(parseFloat(v)); setSpin(false); }} />
            <Slider label="pitch X" value={rotX} min={-1.6} max={1.6} step={0.02} onChange={setRotX} />
            <Slider label="yaw Y" value={rotY} min={-3.14} max={3.14} step={0.02} onChange={setRotY} />
            <Slider label="roll Z" value={rotZ} min={-3.14} max={3.14} step={0.02} onChange={setRotZ} />
            <Slider label="trim forearm" value={trim} min={0} max={0.6} step={0.01} onChange={setTrim} />
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ color: ORANGE, fontWeight: 700, fontSize: 12.5 }}>TOGGLES</div>
            <Check label="auto-spin (turntable)" checked={spin} onChange={setSpin} />
            <Check label="wireframe overlay" checked={wire} onChange={setWire} />
            <Check label="turntable ring" checked={ring} onChange={setRing} />
            <Check label="compare with current Skin visual" checked={compare} onChange={setCompare} />
          </div>

          <pre style={{ background: "#111", border: "1px solid #333", borderRadius: 6, padding: 11, fontSize: 11, whiteSpace: "pre-wrap", lineHeight: 1.6, margin: 0 }}>
{`source   public/models/glove-holo/glove-holo.fbx
weight   1.5MB fbx + 3.7MB 4096² basecolor
mesh     ${info ? `${info.verts.toLocaleString()} verts / ${Math.round(info.tris).toLocaleString()} tris` : "…"}
bbox     ${info ? info.size.join(" × ") : "…"}
weld     ${info?.weld ?? "…"}
look     ${look} / ${hue}${wire ? " + wire" : ""}
palm     ${info?.palm ? info.palm.join(", ") : "…"}
axis     ${info?.axis ? info.axis.join(", ") : "…"}
pose     rotX=${rotX} rotY=${rotY} rotZ=${rotZ} trim=${trim}
shape    slim=${slim} stretch=${stretch}`}
          </pre>

          <div style={{ fontSize: 11, opacity: 0.55, lineHeight: 1.6 }}>
            Ship-blockers if we adopt this: convert FBX → GLB (Draco/meshopt) and
            downscale the texture — the raw pair is 5.2MB and pulls FBXLoader into
            the bundle. Also note DESIGN.md’s hardware-honesty rule: this mesh is
            AI-generated (Creator: Tripo), so it can’t stand in as a product shot
            without a call on that.
          </div>
        </div>
      </div>
    </div>
  );
}
