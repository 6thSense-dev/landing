import { useEffect, useRef, useState, Suspense, lazy } from "react";
import { Link } from "react-router-dom";
import { useReducedMotion } from "framer-motion";
import SiteNav from "../SiteNav.jsx";
import AuroraGL from "./AuroraGL.jsx";
import AuroraBg from "../lib/AuroraBg.jsx";
import { useRevealNav } from "../useRevealNav.js";
import "./products-v2.css";

// Hand3D pulls in three's STLLoader, the big skin-dissolve shaders, and (at
// runtime) the ~4MB STL model + a second WebGL context. Load it as a separate
// chunk via React.lazy so the Skin/Eye2 scenes and the aurora paint immediately;
// we also defer MOUNTING it until the Hand scene is near the viewport (see the
// IntersectionObserver below), so that heavy work never competes with first paint.
const Hand3D = lazy(() => import("./Hand3D.jsx"));

// Small shared WebGL-availability probe (cheap, synchronous). Used to pick the GL
// aurora vs the Canvas2D fallback, and to gate the 3D hand.
const hasWebGL = () => {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
};

// GLSL aurora is now the DEFAULT (Ronak-approved: colorful + smooth). It runs the
// blob rasterization on the GPU. Graceful fallback: if WebGL is unavailable we
// fall back to the Canvas2D AuroraBg, and `?v2&nogl` is an escape hatch that
// forces Canvas2D explicitly. (The preserveDrawingBuffer:true fix lives in
// AuroraGL and is untouched.)
const USE_GL_AURORA = (() => {
  if (typeof window === "undefined") return false;
  const q = new URLSearchParams(window.location.search);
  if (q.has("nogl")) return false; // escape hatch -> Canvas2D
  return hasWebGL();               // otherwise GL by default, Canvas2D if no WebGL
})();

// The animated 3D Aero-hand is the DEFAULT on the Hand scene (fingers-up,
// palm-to-viewer, framed as the hero, with the async tactile-skin dissolve).
// Graceful fallback: if WebGL is unavailable we keep the robo.webp image, and
// `?v2&nohand3d` forces the image explicitly. (`?hand3d` still works as a no-op
// opt-in for back-compat.)
const USE_HAND3D = (() => {
  if (typeof window === "undefined") return false;
  const q = new URLSearchParams(window.location.search);
  if (q.has("nohand3d")) return false;
  return hasWebGL();
})();

/**
 * /products v2 — Apple-style scroll page (design locked with Ronak in the prototype).
 *
 * Aurora background (Canvas2D, random-palette wispy patches, mouse-push, per-scene
 * subtle tone lift) + three product scenes that scale/stagger in as they center,
 * a soft TOC side-nav, and a flip-book gesture on the Skin glove.
 *
 * This is Phase 1 of the port: Canvas2D aurora (verifiable, matches the approved
 * look). Phase 2 swaps the aurora to a three.js GLSL shader for perf; Phase 3 adds
 * the live 3D Aero-hand + skin-warp on the Hand scene.
 */

const STAGES = [
  {
    idx: "01 · Skin", title: "Skin",
    line: "A data glove that feels. Every touch, recorded as force.",
    img: "/hero/glove/frame-001.webp", glove: true, cta: "Talk to us",
    // Verified against the 6thSense-authored glove spec sheet (gbrain:
    // drive/ronak/02-product/01-glove/2026-07-06-spec-6thSense-tactile-glove-spec-sheet):
    // 440 channels (20×22 grid), 16-bit (~0.01 N), <1 ms response, ~200 Hz.
    stats: [["440", "tactile channels"], ["0.01N", "resolution"], ["<1ms", "response"], ["200Hz", "sustained"]],
  },
  {
    idx: "02 · Eye2", title: "Eye2",
    line: "The egocentric camera that sees what the hand feels. First-person video, synced to touch.",
    img: "/eye2-dark.png", cta: "Request a demo",
    // Verified against the 6thSense-authored Eye2 spec sheet (gbrain:
    // drive/ronak/02-product/02-camera/eye2/2026-07-15-spec-eye2-camera-wireless;
    // cross-checked with the Kosha stereo-camera sales agreement).
    // Eye2 is the WIRELESS variant: 4000×1200 global-shutter stereo @30fps, H.264
    // via onboard encoder, WiFi streaming, onboard compute (no Jetson) + microSD,
    // 6-axis IMU. NOTE: 60fps / USB 3.0 / TDK-ICM42688P IMU is the WIRED Eye1 — do
    // NOT use those here (gbrain: .../eye1/2026-07-04-spec-eye1-camera-spec-sheet-wired).
    stats: [["4000×1200", "stereo capture"], ["30fps", "global shutter"], ["Wireless", "WiFi streaming"], ["Onboard", "compute + microSD"]],
  },
  {
    idx: "03 · Hand", title: "Hand",
    line: "Custom tactile skin, molded 1:1 to a dexterous hand, a gripper, any surface you build.",
    img: "/hero/glove/robo.webp", cta: "Build with us",
    // NOTE: the previous "162 sensing points" / "200k impacts at 3MPa" came from a
    // SUPPLIER datasheet (JQ Industries / 矩侨), NOT a 6thSense product — removed.
    // We ALSO removed the provisional "16-bit / <1ms / ~200Hz" numbers: those were
    // DERIVED from the glove spec on the premise that the robot skin is the same
    // sensing family molded per surface, but there is NO owned 6thSense ROBOT-SKIN
    // spec sheet to verify them against — so we do not show unverified hard specs
    // on the live customer page. Reverted to the OLD page's non-numeric copy
    // (1:1 molded fit / Any surface / Per-task touch layout) until a real
    // robot-skin spec doc exists; then re-add verified numbers here.
    stats: [["1:1", "molded fit"], ["Any", "surface"], ["Per-task", "touch layout"]],
  },
];

const GLOVE_FRAMES = ["000", "001", "002", "003", "004", "005"].map((n) => `/hero/glove/frame-${n}.webp`);

export default function ProductsV2() {
  const rootRef = useRef(null);
  // Two stacked glove frame layers (bottom = current frame, top = next frame) that
  // crossfade for a smooth fingers-opening loop instead of a hard flip-book swap.
  const gloveARef = useRef(null);
  const gloveBRef = useRef(null);
  const handSecRef = useRef(null);
  // Eye2 finish toggle: false => /eye2-dark.png (black+orange, default), true => /eye2-hero.png (white).
  const [eye2Light, setEye2Light] = useState(false);
  // hand3dNear: the Hand scene has scrolled near the viewport -> OK to mount the
  // heavy 3D component. hand3dReady: the model finished loading + first render ->
  // remove the robo.webp placeholder. Two stages so first paint stays cheap and
  // the user never sees an empty gap while the STL loads.
  const [hand3dNear, setHand3dNear] = useState(false);
  const [hand3dReady, setHand3dReady] = useState(false);
  // Eye2 scene "tone lift" (0..1) shared with the aurora each frame; the aurora
  // brightens its base as the Eye2 scene centers. Kept identical to the original.
  const lightRef = useRef(0);
  // reuse the site's real flagship navbar (keep the main site chrome; replace only the products content)
  const reduceMotion = useReducedMotion();
  const { className: navClassName } = useRevealNav({ reduceMotion: !!reduceMotion });

  // Defer mounting the 3D hand until the Hand scene is near the viewport, so the
  // ~4MB STL fetch + second WebGL init don't jank first paint or fight the aurora.
  useEffect(() => {
    if (!USE_HAND3D) return;
    const el = handSecRef.current;
    if (!el) return;
    if (!("IntersectionObserver" in window)) { setHand3dNear(true); return; }
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { setHand3dNear(true); io.disconnect(); }
    }, { rootMargin: "300px 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    // The aurora background (Canvas2D or GL) now lives in its own component; this
    // effect owns only the scene-reveal, sidenav, glove flip-book, and the Eye2
    // "tone lift" it feeds the Canvas2D aurora via lightRef.

    let H = window.innerHeight;

    const sceneEls = [...root.querySelectorAll(".scene")].map((el) => ({ el, txt: [...el.querySelectorAll(".idx,h1,.oneliner,.stats,.cta,.eye2-toggle")], img: el.querySelector(".pimg"), top: 0, h: 0 }));
    const measure = () => { for (const s of sceneEls) { s.top = s.el.offsetTop; s.h = s.el.offsetHeight; } };
    measure();
    const navEls = [...root.querySelectorAll(".sidenav a")];
    const onNav = (e) => { e.preventDefault(); const i = +e.currentTarget.dataset.i; sceneEls[i]?.el.scrollIntoView({ behavior: "smooth", block: "center" }); };
    navEls.forEach((a) => a.addEventListener("click", onNav));

    // preload glove frames
    GLOVE_FRAMES.forEach((src) => { const im = new Image(); im.src = src; });

    let scrollY = window.scrollY, t = 0, curActive = -1, gBase = -1, gNext = -1, raf = 0;
    const onScroll = () => { scrollY = window.scrollY; };
    const onResize = () => { H = window.innerHeight; measure(); };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);

    const frame = () => {
      t += 1;
      const c1 = sceneEls[1] ? (sceneEls[1].top + sceneEls[1].h / 2 - scrollY) : 9e9;
      // Feed the Canvas2D aurora the Eye2 tone lift (no-op when the GL aurora is active).
      lightRef.current = Math.max(0, Math.min(1, 1 - Math.abs(c1 - H / 2) / (H * .62)));

      const vc = H / 2; let best = 0, bestT = -1;
      sceneEls.forEach((s, idx) => {
        const c = s.top + s.h / 2 - scrollY;
        const dist = Math.abs(c - vc);
        // PLATEAU: full/crisp while within ~10% of center, only fades near transitions
        const tt = Math.max(0, Math.min(1, 1 - (dist - H * 0.10) / (H * 0.55)));
        const dir = c > vc ? 1 : -1;
        if (tt > bestT) { bestT = tt; best = idx; }
        if (s.img) {
          s.img.style.transform = `translateY(${((1 - tt) * dir * -26).toFixed(1)}px) scale(${(0.9 + 0.1 * tt).toFixed(3)})`;
          s.img.style.opacity = (0.25 + 0.75 * tt).toFixed(3);
        }
        s.txt.forEach((e, j) => {
          const et = Math.max(0, Math.min(1, tt * 1.5 - j * 0.10));
          e.style.opacity = (0.05 + 0.95 * et).toFixed(3);
          e.style.transform = `translateY(${((1 - et) * 22).toFixed(1)}px)`;
        });
      });
      if (best !== curActive) { curActive = best; navEls.forEach((a, i) => a.classList.toggle("on", i === best)); }
      // NOTE: no full light-mode text flip — the Eye2 scene is only a SUBTLE bg tone lift,
      // so copy must stay light (dark text on the still-dark bg was invisible). isLight unused.

      // Smooth glove crossfade: keep the SAME pace/gesture (sin drives a continuous
      // position across the frames), then blend between the two nearest frames.
      // Bottom layer holds the current frame at full opacity; the top layer fades
      // the next frame in (opacity = fractional part), so it's a buttery dissolve.
      if (gloveARef.current && gloveBRef.current) {
        const last = GLOVE_FRAMES.length - 1;
        const fpos = (Math.sin(t * 0.012) * .5 + .5) * last; // continuous 0..last
        const base = Math.floor(fpos);
        const next = Math.min(base + 1, last);
        const blend = fpos - base;
        if (base !== gBase) { gBase = base; gloveARef.current.src = GLOVE_FRAMES[base]; }
        if (next !== gNext) { gNext = next; gloveBRef.current.src = GLOVE_FRAMES[next]; }
        gloveBRef.current.style.opacity = blend.toFixed(3);
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
      navEls.forEach((a) => a.removeEventListener("click", onNav));
    };
  }, []);

  return (
    <div className="pv2" ref={rootRef}>
      {USE_GL_AURORA
        ? <AuroraGL />
        : <AuroraBg lightRef={lightRef} />}
      {/* the site's real flagship navbar (same as the rest of 6thsense.dev) */}
      <SiteNav className={navClassName} />
      <nav className="sidenav" aria-label="Products">
        {STAGES.map((s, i) => (
          <a key={s.title} data-i={i} href={`#${s.title.toLowerCase()}`}><i />{s.title}</a>
        ))}
      </nav>

      <div className="page">
        {STAGES.map((s, i) => (
          <section className="scene" id={s.title.toLowerCase()} key={s.title}
            ref={s.title === "Hand" ? handSecRef : undefined}>
            <div className="copy">
              <div className="idx">{s.idx}</div>
              <h1>{s.title}</h1>
              <p className="oneliner">{s.line}</p>
              <div className="stats">
                {s.stats.map(([n, l]) => (
                  <div className="stat" key={l}><b>{n}</b><span>{l}</span></div>
                ))}
              </div>
              <a className="cta" href="/#contact">{s.cta}</a>
            </div>
            {USE_HAND3D && s.title === "Hand"
              ? <div className="pimg hand3d">
                  {/* robo.webp stays on top until the 3D model has loaded + rendered */}
                  {!hand3dReady && (
                    <img className="hand3d-placeholder" src={s.img}
                      alt={`6thSense ${s.title}`} draggable="false"
                      loading="lazy" decoding="async" />
                  )}
                  {hand3dNear && (
                    <Suspense fallback={null}>
                      <Hand3D onReady={() => setHand3dReady(true)} />
                    </Suspense>
                  )}
                </div>
              : s.glove
              ? <div className="pimg glove-stack">
                  {/* bottom = current frame (opaque); top = next frame crossfading in */}
                  <img className="glove-layer" ref={gloveARef} src={GLOVE_FRAMES[0]}
                    alt={`6thSense ${s.title}`} draggable="false" loading="eager" decoding="async" />
                  <img className="glove-layer" ref={gloveBRef} src={GLOVE_FRAMES[1]}
                    alt="" aria-hidden="true" draggable="false" loading="eager"
                    decoding="async" style={{ opacity: 0 }} />
                </div>
              : s.title === "Eye2"
              ? <div className="pimg eye2-cell">
                  <img className={`eye2-img${eye2Light ? " light" : ""}`}
                    src={eye2Light ? "/eye2-hero.png" : "/eye2-dark.png"}
                    alt={`6thSense ${s.title}`} draggable="false"
                    loading="lazy" decoding="async" />
                  {/* finish preview (NOT a catalog/buy selector): the swatches
                      are the actual finish colors so they read as "the camera in
                      black / white". Default black — it looks best on-page; white
                      is what we ship. */}
                  <div className="eye2-finish" role="group" aria-label="Eye2 finish preview">
                    <span className="eye2-finish-label">Finish</span>
                    <button type="button" className={`sw sw-dark ${!eye2Light ? "on" : ""}`}
                      aria-pressed={!eye2Light} aria-label="Black finish" title="Black"
                      onClick={() => setEye2Light(false)} />
                    <button type="button" className={`sw sw-light ${eye2Light ? "on" : ""}`}
                      aria-pressed={eye2Light} aria-label="White finish" title="White"
                      onClick={() => setEye2Light(true)} />
                  </div>
                </div>
              : <img className="pimg"
                  src={s.img}
                  alt={`6thSense ${s.title}`} draggable="false"
                  loading={i === 0 ? "eager" : "lazy"} decoding="async" />}
          </section>
        ))}

        {/* Footer restored from the old /products page: required legal links. */}
        <footer className="pv2-footer">
          <span>6thSense · tactile hardware for dexterous robotics</span>
          <span className="pv2-footer-legal">
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
          </span>
          <Link className="pv2-footer-home" to="/">Skin · Hand · Eye2</Link>
        </footer>
      </div>

      <div className="hint"><span className="hint-scroll">scroll ↓</span><span className="hint-mouse"> &nbsp;·&nbsp; move your mouse through the aurora</span></div>
    </div>
  );
}
