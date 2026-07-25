import { useEffect, useMemo, useRef, useState } from "react";
import { GLOVE_ALIGN, GLOVE_FRAME_IDS, gloveFrameSrc } from "../lib/gloveAlign.js";

// TEMPORARY alignment tool for the glove flip-book on /products.
// Route: /glove-tune.
//
// The 6 glove photos aren't framed identically (the closed-fist frame reads
// bigger than the open ones), so the crossfade pulses. Here you pick the odd
// frame out, see the other five ONION-SKINNED underneath it, then drag/resize
// until its hand matches theirs. Copy the printed block into lib/gloveAlign.js
// and the live page picks it up.
//
// Delete this file + its route once the frames are locked in.

const STAGE_W = 640;
const STAGE_H = 560;
const IDENTITY = { scale: 1, x: 0, y: 0 };

function Slider({ label, value, min, max, step, onChange }) {
  return (
    <label style={{ display: "grid", gridTemplateColumns: "108px 1fr 70px", gap: 10, alignItems: "center", fontSize: 13 }}>
      <span style={{ color: "#cfcfcf" }}>{label}</span>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))} style={{ width: "100%" }} />
      <input type="number" value={value} step={step}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: 66, background: "#111", color: "#fff", border: "1px solid #333", borderRadius: 4, padding: "3px 5px", fontSize: 12 }} />
    </label>
  );
}

const round = (n, p = 3) => parseFloat(n.toFixed(p));

export default function GloveTune() {
  // Start from whatever the live page is currently shipping.
  const [align, setAlign] = useState(() => {
    const seed = {};
    GLOVE_FRAME_IDS.forEach((id) => { seed[id] = { ...IDENTITY, ...(GLOVE_ALIGN[id] || {}) }; });
    return seed;
  });
  // Which frame you're correcting. 000 is the closed fist in the current set,
  // but any frame can be the odd one out, so this is free-choice.
  const [sel, setSel] = useState(GLOVE_FRAME_IDS[0]);
  const [onion, setOnion] = useState(0.28);
  const [showOthers, setShowOthers] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [copied, setCopied] = useState(false);

  const stageRef = useRef(null);
  const dragRef = useRef(null);
  // Live crossfade preview (mirrors the products-page sine flip-book).
  const [playPos, setPlayPos] = useState(0);

  const cur = align[sel];
  const setCur = (patch) => setAlign((p) => ({ ...p, [sel]: { ...p[sel], ...patch } }));
  const set = (k) => (v) => setCur({ [k]: round(v) });

  // ---- drag to move the selected frame ----
  useEffect(() => {
    const onMove = (e) => {
      const d = dragRef.current;
      if (!d) return;
      // translate % is relative to the element box, and the element fills the
      // stage — so pixels map to percent by the stage's own size. Same box model
      // as production, which is what makes this WYSIWYG.
      const dxPct = ((e.clientX - d.startX) / STAGE_W) * 100;
      const dyPct = ((e.clientY - d.startY) / STAGE_H) * 100;
      setCur({ x: round(d.baseX + dxPct, 2), y: round(d.baseY + dyPct, 2) });
    };
    const onUp = () => { dragRef.current = null; };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [sel]);

  const onStageDown = (e) => {
    if (playing) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, baseX: cur.x, baseY: cur.y };
    e.preventDefault();
  };

  // ---- wheel to resize, arrows to nudge ----
  const onWheel = (e) => {
    if (playing) return;
    setCur({ scale: round(Math.min(2, Math.max(0.3, cur.scale - e.deltaY * 0.0012))) });
  };

  useEffect(() => {
    const onKey = (e) => {
      if (playing) return;
      const step = e.shiftKey ? 1 : 0.2;
      if (e.key === "ArrowLeft") { setCur({ x: round(cur.x - step, 2) }); e.preventDefault(); }
      if (e.key === "ArrowRight") { setCur({ x: round(cur.x + step, 2) }); e.preventDefault(); }
      if (e.key === "ArrowUp") { setCur({ y: round(cur.y - step, 2) }); e.preventDefault(); }
      if (e.key === "ArrowDown") { setCur({ y: round(cur.y + step, 2) }); e.preventDefault(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cur, sel, playing]);

  // ---- crossfade preview: same sin() pacing as ProductsV2 ----
  useEffect(() => {
    if (!playing) return;
    let raf, t0 = performance.now();
    const tick = (now) => {
      const t = now - t0;
      const last = GLOVE_FRAME_IDS.length - 1;
      setPlayPos((Math.sin(t * 0.012 * 0.06) * 0.5 + 0.5) * last);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const tf = (a) => `translate(${a.x}%, ${a.y}%) scale(${a.scale})`;

  const block = useMemo(() => {
    const rows = GLOVE_FRAME_IDS.map((id) => {
      const a = align[id];
      return `  "${id}": { scale: ${a.scale}, x: ${a.x}, y: ${a.y} },`;
    }).join("\n");
    return `export const GLOVE_ALIGN = {\n${rows}\n};`;
  }, [align]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(block);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  const resetFrame = () => setAlign((p) => ({ ...p, [sel]: { ...IDENTITY } }));
  const resetAll = () => {
    const seed = {};
    GLOVE_FRAME_IDS.forEach((id) => { seed[id] = { ...IDENTITY }; });
    setAlign(seed);
  };

  // Preview blend state (only used while playing).
  const pBase = Math.floor(playPos);
  const pNext = Math.min(pBase + 1, GLOVE_FRAME_IDS.length - 1);
  const pBlend = playPos - pBase;

  return (
    <div style={{ minHeight: "100vh", background: "#0a0a0b", color: "#eee", fontFamily: "ui-monospace, Menlo, monospace", padding: 24, display: "flex", gap: 28, flexWrap: "wrap" }}>
      {/* ---- stage ---- */}
      <div>
        <div style={{ fontSize: 12, opacity: 0.6, marginBottom: 8, maxWidth: STAGE_W }}>
          /glove-tune — drag the bright frame to move · scroll to resize · arrows nudge (shift = coarse).
          The dim frames are the other five, for size-matching.
        </div>
        <div
          ref={stageRef}
          data-stage="glove-tune"
          onMouseDown={onStageDown}
          onWheel={onWheel}
          style={{
            position: "relative", width: STAGE_W, height: STAGE_H,
            background: "#0a0a0b", border: "1px solid #222", overflow: "hidden",
            cursor: playing ? "default" : (dragRef.current ? "grabbing" : "grab"),
            userSelect: "none",
          }}
        >
          {playing ? (
            <>
              {/* live crossfade with corrections applied — verifies the pulse is gone */}
              <img src={gloveFrameSrc(GLOVE_FRAME_IDS[pBase])} alt=""
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", transform: tf(align[GLOVE_FRAME_IDS[pBase]]) }} />
              <img src={gloveFrameSrc(GLOVE_FRAME_IDS[pNext])} alt=""
                style={{ position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain", opacity: pBlend, transform: tf(align[GLOVE_FRAME_IDS[pNext]]) }} />
            </>
          ) : (
            <>
              {/* onion skin: every non-selected frame, dimmed */}
              {showOthers && GLOVE_FRAME_IDS.filter((id) => id !== sel).map((id) => (
                <img key={id} src={gloveFrameSrc(id)} alt=""
                  style={{
                    position: "absolute", inset: 0, width: "100%", height: "100%",
                    objectFit: "contain", opacity: onion, transform: tf(align[id]),
                    pointerEvents: "none",
                  }} />
              ))}
              {/* the frame you're correcting, full strength on top */}
              <img src={gloveFrameSrc(sel)} alt=""
                style={{
                  position: "absolute", inset: 0, width: "100%", height: "100%",
                  objectFit: "contain", transform: tf(cur), pointerEvents: "none",
                }} />
            </>
          )}
          {/* centre crosshair, so you can judge drift against a fixed reference */}
          <div style={{ position: "absolute", top: 0, bottom: 0, left: "50%", width: 1, background: "rgba(240,97,42,0.35)", pointerEvents: "none" }} />
          <div style={{ position: "absolute", left: 0, right: 0, top: "50%", height: 1, background: "rgba(240,97,42,0.35)", pointerEvents: "none" }} />
        </div>
      </div>

      {/* ---- controls ---- */}
      <div style={{ minWidth: 400, display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div style={{ color: "#f0612a", fontWeight: 700, marginBottom: 8 }}>FRAME</div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {GLOVE_FRAME_IDS.map((id) => {
              const touched = align[id].scale !== 1 || align[id].x !== 0 || align[id].y !== 0;
              return (
                <button key={id} onClick={() => setSel(id)}
                  style={{
                    background: id === sel ? "#f0612a" : "#1a1a1c",
                    color: id === sel ? "#0a0a0b" : "#ddd",
                    border: `1px solid ${touched ? "#f0612a" : "#333"}`,
                    borderRadius: 6, padding: "6px 10px", cursor: "pointer",
                    fontFamily: "inherit", fontSize: 12, fontWeight: id === sel ? 700 : 400,
                  }}>
                  {id}{touched ? " •" : ""}
                </button>
              );
            })}
          </div>
          <div style={{ fontSize: 11, opacity: 0.5, marginTop: 6 }}>
            • = frame has a correction. Pick the fist frame, then match it to the dim ones.
          </div>
        </div>

        <div>
          <div style={{ color: "#f0612a", fontWeight: 700, marginBottom: 8 }}>ADJUST · frame {sel}</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Slider label="size (scale)" value={cur.scale} min={0.3} max={2} step={0.005} onChange={set("scale")} />
            <Slider label="pos X (%)" value={cur.x} min={-40} max={40} step={0.2} onChange={set("x")} />
            <Slider label="pos Y (%)" value={cur.y} min={-40} max={40} step={0.2} onChange={set("y")} />
          </div>
        </div>

        <div>
          <div style={{ color: "#f0612a", fontWeight: 700, marginBottom: 8 }}>VIEW</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <Slider label="onion opacity" value={onion} min={0} max={1} step={0.02} onChange={setOnion} />
            <label style={{ fontSize: 13, display: "flex", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={showOthers} onChange={(e) => setShowOthers(e.target.checked)} />
              show the other 5 frames
            </label>
            <label style={{ fontSize: 13, display: "flex", gap: 8, alignItems: "center" }}>
              <input type="checkbox" checked={playing} onChange={(e) => setPlaying(e.target.checked)} />
              play the crossfade (check the pulse is gone)
            </label>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <button onClick={resetFrame} style={{ background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontFamily: "inherit" }}>
            reset frame {sel}
          </button>
          <button onClick={resetAll} style={{ background: "#222", color: "#fff", border: "1px solid #444", borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontFamily: "inherit" }}>
            reset all
          </button>
          <button onClick={copy} style={{ background: "#f0612a", color: "#0a0a0b", border: "none", borderRadius: 6, padding: "6px 12px", cursor: "pointer", fontFamily: "inherit", fontWeight: 700 }}>
            {copied ? "copied ✓" : "copy block"}
          </button>
        </div>

        <pre style={{ background: "#111", border: "1px solid #333", borderRadius: 6, padding: 12, fontSize: 12, whiteSpace: "pre-wrap", margin: 0 }}>
{block}
        </pre>
        <div style={{ fontSize: 12, opacity: 0.6 }}>
          Paste this over <code>GLOVE_ALIGN</code> in <code>src/lib/gloveAlign.js</code> — or send it
          to me and I'll bake it in. The live /products page reads the same object.
        </div>
      </div>
    </div>
  );
}
