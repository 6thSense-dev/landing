import { useEffect, useRef, useState, Suspense, lazy } from "react";
import { Link } from "react-router-dom";
import { useReducedMotion } from "framer-motion";
import SiteNav from "../SiteNav.jsx";
import AuroraBg from "../lib/AuroraBg.jsx";
import { useRevealNav } from "../useRevealNav.js";
import { GLOVE_ALIGN, GLOVE_CYCLE_MS, GLOVE_FRAME_IDS, gloveFrameSrc, gloveFrameTransform, liveTune } from "../lib/gloveAlign.js";
import "./products-v2.css";

// Hand3D pulls in three's STLLoader, the big skin-dissolve shaders, and (at
// runtime) the ~4MB STL model + a second WebGL context. Load it as a separate
// chunk via React.lazy so the Skin/Eye2 scenes and the aurora paint immediately;
// we also defer MOUNTING it until the Hand scene is near the viewport (see the
// IntersectionObserver below), so that heavy work never competes with first paint.
const Hand3D = lazy(() => import("./Hand3D.jsx"));

// AuroraGL is lazy for the same reason, and it matters more than it looks: it was
// a STATIC import, so `three` shipped to every /products visitor whether or not
// the GL aurora ever rendered. Gating only the render would have saved 0 bytes --
// measured 138.5KB of three.module on a 390px production build with the 3D hand
// already gated off. Lazy is what actually makes the D5 gate below pay.
const AuroraGL = lazy(() => import("./AuroraGL.jsx"));

// PREVIEW ONLY (/products?hologlove): puts all three scenes into the same
// holographic-white language — the Skin glove replaces its webp flip-book, the
// Eye2 render becomes the real enclosure CAD (public/eye2.glb, built by
// scripts/build-eye2-cad.py), and the dexterous hand drops its dark PBR body
// for the same hologram. One shader behind all three: lib/holoMaterial.js.
// Query-gated, so the shipped page is untouched.
const HoloGlove = lazy(() => import("../lib/HoloGlove.jsx"));
const HoloTurntable = lazy(() => import("../lib/HoloTurntable.jsx"));

// `?tune` overlay: sliders for cycle speed and per-frame size, over the REAL scene.
// Lazy + query-gated so a normal visitor never downloads or mounts it.
const GloveTunePanel = lazy(() => import("./GloveTunePanel.jsx"));
const TUNING = typeof window !== "undefined" &&
  new URLSearchParams(window.location.search).has("tune");

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
// D5 (2026-07-27): phones get the Canvas2D aurora. Phones have WebGL, so the old
// probe said yes and pulled 138.5KB of `three` onto every mobile /products view
// for a background -- plus the battery cost of a GPU loop on a scrolling page.
// The Canvas2D fallback already existed and already looked right. 880px matches
// the breakpoint products-v2.css already treats as "mobile layout", so the two
// cannot disagree about what a phone is.
// Desktop is unchanged: still GL by default, as approved.
// Escape hatches both ways: `?nogl` forces Canvas2D anywhere, `?gl` forces GL on
// a phone so this is checkable on a real device without a rebuild.
const IS_PHONE = typeof window !== "undefined" &&
  window.matchMedia && window.matchMedia("(max-width: 880px)").matches;

const USE_GL_AURORA = (() => {
  if (typeof window === "undefined") return false;
  const q = new URLSearchParams(window.location.search);
  if (q.has("nogl")) return false; // escape hatch -> Canvas2D
  if (q.has("gl")) return hasWebGL(); // escape hatch -> force GL even on a phone
  if (IS_PHONE) return false;      // D5: no GL aurora on phones
  return hasWebGL();               // otherwise GL by default, Canvas2D if no WebGL
})();

// The animated 3D Aero-hand is the DEFAULT on the Hand scene (fingers-up,
// palm-to-viewer, framed as the hero, with the async tactile-skin dissolve).
// Graceful fallback: if WebGL is unavailable we keep the robo.webp image, and
// `?v2&nohand3d` forces the image explicitly. (`?hand3d` still works as a no-op
// opt-in for back-compat.)
// Phones take the image path too: the 3D hand costs ~3MB of STL mesh (base_link
// alone is 1.3MB) for a decorative render, which is most of the page weight on a
// phone. Same graceful fallback, just triggered by viewport as well as by WebGL.
const HAND3D_MIN_W = 720;
const USE_HAND3D = (() => {
  if (typeof window === "undefined") return false;
  const q = new URLSearchParams(window.location.search);
  if (q.has("nohand3d")) return false;
  if (window.innerWidth < HAND3D_MIN_W) return false;
  return hasWebGL();
})();

// Eye2 framing is query-tunable during the preview (?e2fill=, ?e2yaw=, ?e2tilt=)
// so the enclosure can be posed without a rebuild. Preview-only, like the gate.
const Q = typeof window === "undefined" ? new URLSearchParams() : new URLSearchParams(window.location.search);
const qnum = (k, d) => (Q.has(k) && !Number.isNaN(parseFloat(Q.get(k))) ? parseFloat(Q.get(k)) : d);

// Needs WebGL and a desktop layout. The threshold is 880, NOT HAND3D_MIN_W's
// 720: 880 is where products-v2.css switches to the single-column mobile
// layout, and gating at 720 would put four WebGL contexts inside a 46vh-tall
// stacked cell. Using the layout's own breakpoint also keeps the page either
// all-holographic or not at all, never a mix of hologram and flat render.
const HOLO_MIN_W = 880;
const USE_HOLOGLOVE = (() => {
  if (typeof window === "undefined") return false;
  const q = new URLSearchParams(window.location.search);
  if (!q.has("hologlove")) return false;
  if (window.innerWidth < HOLO_MIN_W) return false;
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

// Frame ids, URLs and per-frame corrective transforms all come from
// lib/gloveAlign.js, so the live page and /glove-tune can never drift apart.
// Fallback src for browsers without srcSet, and the identity of the frame the
// crossfade is currently on. The ladder below is what actually gets fetched.
const GLOVE_FRAMES = GLOVE_FRAME_IDS.map(gloveFrameSrc);
const GLOVE_TRANSFORMS = GLOVE_FRAME_IDS.map(gloveFrameTransform);

// Responsive ladder for the crossfade frames. Unlike the homepage, /products
// paints the glove CONTAINED in a small box, so the 2752px source is heavily
// oversupplied. Measured painted widths (object-fit: contain, always
// width-limited here because the box is never wider than 1.79:1):
//
//     390x844  dpr3 -> 342 CSS -> 1026 device px
//     360x740  dpr3 -> 312 CSS ->  936
//     430x932  dpr3 -> 382 CSS -> 1146
//    1440x900  dpr2 -> 625 CSS -> 1250
//   1920x1080  dpr1 -> 866 CSS ->  866
//
// The homepage's existing w1100 tier was tried here first and REJECTED on
// measurement: a source only ~1.07x the painted size still has to be resampled
// to land on it, and that second resample costs real detail. Edge energy
// retained at the 1026px phone size, vs the lossless master through the same
// browser downscale:
//
//     full 2752   100.0%      <- what ships today
//     w1100         77.4%     <- shipped homepage file (also a sub-q92 encode)
//     1100 fresh    80.4% Lanczos / 88.0% area-average
//     1400        101.2% Lanczos / 105.4% area-average
//     1600        114.7% / 120.4%   <- overshoots, aliasing
//
// 1100 loses 12-23% of edge detail depending on resampler; the sign and the
// ordering hold either way. That is the same "softens the fabric weave" failure
// the earlier GLOVE_FRAMES tier decision rejected, so w1100 is not usable here.
// 1400 is detail-neutral and still 60% lighter, so /products gets its own tier.
// Encoded q92 from the LOSSLESS masters (git a53cd6a) — never re-encoded from
// the shipped lossy files, so this is one generation of loss, same as full.
//
// Rungs are deliberately 1400 and 2752 with NO 1100 in between: adding a 1100
// rung would pull the main 390px phone case (1026 needed) back onto the blurry
// tier. 1400 covers every phone (936-1176) and 1440-class desktop (1250);
// dpr2 tablets at 768 (1440) and 2560 dpr2 (2458) correctly stay on full.
//
// Selection is left to srcSet/sizes rather than a width breakpoint because the
// requirement is painted px = box x dpr, so a width-only rule mis-serves a dpr2
// tablet just under the breakpoint and needlessly denies the small tier to a
// dpr1 desktop (which lands on 1400 correctly this way).
const GLOVE_SRCSET = GLOVE_FRAME_IDS.map(
  (n) => `/hero/glove/w1400/frame-${n}.webp 1400w, /hero/glove/frame-${n}.webp 2752w`
);
// Box width, slightly over-declared so rounding always errs toward the LARGER
// rung. Mobile (<=880px) is single-column with 24px side padding — exact.
// Desktop is the 58% grid track; 48vw measured within 1% at 2560 and over-
// declares at 1440/1920, which is the safe direction.
const TAU = Math.PI * 2;

// Transform for a frame using the LIVE tuner scale, keeping whatever x/y offset
// is already committed in GLOVE_ALIGN (the panel only drives size).
function liveTransform(id) {
  const a = liveTune.align[id] || GLOVE_ALIGN[id] || { scale: 1, x: 0, y: 0 };
  return `translate(${a.x}%, ${a.y}%) scale(${a.scale})`;
}
const GLOVE_SIZES = "(max-width: 880px) calc(100vw - 48px), 48vw";

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
  // Same two-stage mount for the preview glove. The Skin scene is first on the
  // page, so "near" is true almost immediately — the stage still matters,
  // because it keeps the FBX fetch off the critical path for first paint.
  const skinSecRef = useRef(null);
  const [glove3dNear, setGlove3dNear] = useState(false);
  const [glove3dReady, setGlove3dReady] = useState(false);
  const eye2SecRef = useRef(null);
  const [eye2HoloNear, setEye2HoloNear] = useState(false);
  const [eye2HoloReady, setEye2HoloReady] = useState(false);
  // Eye2 scene "tone lift" (0..1) shared with the aurora each frame; the aurora
  // brightens its base as the Eye2 scene centers. Kept identical to the original.
  const lightRef = useRef(0);
  // reuse the site's real flagship navbar (keep the main site chrome; replace only the products content)
  const reduceMotion = useReducedMotion();
  const { className: navClassName } = useRevealNav({ reduceMotion: !!reduceMotion });

  // Defer mounting the 3D hand until the Hand scene is near the viewport, so the
  // ~4MB STL fetch + second WebGL init don't jank first paint or fight the aurora.
  // One observer per holographic scene: four WebGL contexts on this page
  // (aurora + glove + Eye2 + hand) is a lot, so none of them are created until
  // their scene is close to the viewport.
  useEffect(() => {
    if (!USE_HOLOGLOVE) return;
    const watch = (el, set) => {
      if (!el) return null;
      if (!("IntersectionObserver" in window)) { set(true); return null; }
      const io = new IntersectionObserver((entries) => {
        if (entries.some((e) => e.isIntersecting)) { set(true); io.disconnect(); }
      }, { rootMargin: "300px 0px" });
      io.observe(el);
      return io;
    };
    const ios = [watch(skinSecRef.current, setGlove3dNear), watch(eye2SecRef.current, setEye2HoloNear)];
    return () => ios.forEach((io) => io?.disconnect());
  }, []);

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

    // Preload glove frames so the crossfade never waits on a fetch.
    //
    // This MUST go through srcset/sizes rather than assigning .src, or it
    // defeats the whole ladder: a bare `im.src = <full-res URL>` fetches the
    // 2752px file unconditionally, AND warms the cache with it, after which the
    // browser prefers that already-available larger candidate for the visible
    // layers too. The page then pays for both tiers and gets heavier, not
    // lighter. Setting srcset (with no src) starts the fetch for whichever
    // candidate the layers themselves will select.
    // Skipped in the ?hologlove preview: the flip-book is not on screen there,
    // so warming its ~2.1MB of frames would make the preview's page weight look
    // worse than the swap actually is.
    if (!USE_HOLOGLOVE) {
      GLOVE_SRCSET.forEach((set) => {
        const im = new Image();
        im.sizes = GLOVE_SIZES;
        im.srcset = set;
      });
    }

    let scrollY = window.scrollY, t = 0, curActive = -1, gBase = -1, gNext = -1, raf = 0;
    // t is elapsed MILLISECONDS since the loop started, not a frame counter, so the
    // flip-book runs at the same speed on 60Hz and 120Hz. t0 is set on first tick
    // rather than here so a slow first paint doesn't jump the animation forward.
    let t0 = 0;
    const onScroll = () => { scrollY = window.scrollY; };
    const onResize = () => { H = window.innerHeight; measure(); };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize);

    const frame = (now) => {
      if (!t0) t0 = now;
      t = now - t0;
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
        // Wall-clock driven, NOT rAF-tick driven: see GLOVE_CYCLE_MS. A tick count
        // made this run 2x fast on 120Hz displays.
        // While the ?tune panel is mounted, read its live values instead of the
        // shipped constants so a slider drag is felt on the next frame.
        const cycle = liveTune.active ? liveTune.cycleMs : GLOVE_CYCLE_MS;
        // Frozen on one frame while tuning it, otherwise the continuous sine sweep.
        // compare mode pins the 000/001 pair; hold freezes a single frame;
        // otherwise the continuous sine sweep.
        const fpos = (liveTune.active && liveTune.compare)
          ? 0
          : (liveTune.active && liveTune.hold != null)
          ? Math.min(liveTune.hold, last)
          : (Math.sin(t * TAU / cycle) * .5 + .5) * last; // continuous 0..last
        const base = Math.floor(fpos);
        const next = Math.min(base + 1, last);
        const blend = fpos - base;
        // Per-frame size/position correction rides along with the src swap, and
        // only on change, so the compositor isn't handed a fresh matrix each tick.
        // srcset BEFORE src: both assignments re-run the browser's candidate
        // selection, and setting src first would briefly select against the
        // PREVIOUS frame's ladder.
        // Each layer carries its OWN correction, so a crossfade between two
        // differently-scaled frames dissolves corrected->corrected. That is what
        // removes the pulse; interpolating one shared transform would not.
        if (base !== gBase) {
          gBase = base;
          gloveARef.current.srcset = GLOVE_SRCSET[base];
          gloveARef.current.src = GLOVE_FRAMES[base];
          gloveARef.current.style.transform = GLOVE_TRANSFORMS[base];
        }
        if (next !== gNext) {
          gNext = next;
          gloveBRef.current.srcset = GLOVE_SRCSET[next];
          gloveBRef.current.src = GLOVE_FRAMES[next];
          gloveBRef.current.style.transform = GLOVE_TRANSFORMS[next];
        }
        // Tuning only: re-apply every tick so dragging a size slider shows up
        // immediately instead of waiting for the next frame change. Production
        // keeps the change-only path above, so no per-tick matrix churn ships.
        if (liveTune.active) {
          gloveARef.current.style.transform = liveTransform(GLOVE_FRAME_IDS[base]);
          gloveBRef.current.style.transform = liveTransform(GLOVE_FRAME_IDS[next]);
        }
        // In compare mode the top layer is held at a fixed alpha so 001 ghosts over
        // 000 instead of fading out (blend would be 0 with fpos pinned to 0).
        gloveBRef.current.style.opacity = (liveTune.active && liveTune.compare)
          ? String(liveTune.compareAlpha)
          : blend.toFixed(3);
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
      {TUNING && <Suspense fallback={null}><GloveTunePanel /></Suspense>}
      {/* Suspense fallback is the Canvas2D aurora, not null: AuroraGL is lazy now,
          and the page background must never flash empty while its chunk loads. */}
      {USE_GL_AURORA
        ? <Suspense fallback={<AuroraBg lightRef={lightRef} />}><AuroraGL /></Suspense>
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
            ref={s.title === "Hand" ? handSecRef : s.title === "Skin" ? skinSecRef
              : s.title === "Eye2" ? eye2SecRef : undefined}>
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
            {USE_HOLOGLOVE && s.glove
              ? <div className="pimg holo3d">
                  {/* The flip-book frame holds the slot until the mesh is up, so
                      the scene never opens on an empty box. */}
                  {!glove3dReady && (
                    <img className="hand3d-placeholder" src={s.img}
                      alt={`6thSense ${s.title}`} draggable="false"
                      loading="eager" decoding="async" />
                  )}
                  {glove3dNear && (
                    <Suspense fallback={null}>
                      <HoloGlove
                        look="holo" hue="white" wire spin={!reduceMotion}
                        glitch={reduceMotion ? 0 : 0.6}
                        ring={false} rotZ={-0.45} rotY={4.71} trim={0.4}
                        preload="marks-only"
                        onReady={() => setGlove3dReady(true)}
                      />
                    </Suspense>
                  )}
                </div>
              : USE_HAND3D && s.title === "Hand"
              ? <div className="pimg hand3d">
                  {/* robo.webp stays on top until the 3D model has loaded + rendered */}
                  {!hand3dReady && (
                    <img className="hand3d-placeholder" src={s.img}
                      alt={`6thSense ${s.title}`} draggable="false"
                      loading="lazy" decoding="async" />
                  )}
                  {hand3dNear && (
                    <Suspense fallback={null}>
                      <Hand3D holo={USE_HOLOGLOVE} hue="white" intensity={1.75}
                        onReady={() => setHand3dReady(true)} />
                    </Suspense>
                  )}
                </div>
              : s.glove
              ? <div className="pimg glove-stack">
                  {/* bottom = current frame (opaque); top = next frame crossfading in */}
                  {/* srcSet/sizes MUST precede src. React writes DOM attributes in
                      props order, and a src set before the ladder exists makes the
                      browser start fetching the 2752px file immediately; it then
                      keeps that already-cached larger candidate even once srcSet
                      lands, so the page fetches BOTH tiers and gets heavier. */}
                  <img className="glove-layer" ref={gloveARef}
                    srcSet={GLOVE_SRCSET[0]} sizes={GLOVE_SIZES} src={GLOVE_FRAMES[0]}
                    alt={`6thSense ${s.title}`} draggable="false" loading="eager" decoding="async"
                    style={{ transform: GLOVE_TRANSFORMS[0] }} />
                  <img className="glove-layer" ref={gloveBRef}
                    srcSet={GLOVE_SRCSET[1]} sizes={GLOVE_SIZES} src={GLOVE_FRAMES[1]}
                    alt="" aria-hidden="true" draggable="false" loading="eager"
                    decoding="async" style={{ opacity: 0, transform: GLOVE_TRANSFORMS[1] }} />
                </div>
              : USE_HOLOGLOVE && s.title === "Eye2"
              ? <div className="pimg holo3d">
                  {/* The shipped render holds the slot until the CAD is up. The
                      finish swatches are dropped here on purpose — "black or
                      white" means nothing once the enclosure is a hologram. */}
                  {!eye2HoloReady && (
                    <img className="hand3d-placeholder" src={s.img}
                      alt={`6thSense ${s.title}`} draggable="false"
                      loading="lazy" decoding="async" />
                  )}
                  {eye2HoloNear && (
                    <Suspense fallback={null}>
                      <HoloTurntable src="/eye2.glb" hue="white" wire flat intensity={0.62}
                        label="6thSense Eye2 egocentric camera, rotating enclosure render"
                        glitch={reduceMotion ? 0 : 0.6}
                        spin={!reduceMotion} tiltX={qnum("e2tilt", -0.3)} rotY={qnum("e2yaw", 0)}
                        fill={qnum("e2fill", 0.95)}
                        onReady={() => setEye2HoloReady(true)} />
                    </Suspense>
                  )}
                </div>
              : s.title === "Eye2"
              ? <div className="pimg eye2-cell">
                  {/* The 2400x2400 PNG stays as the fallback src; every current
                      browser takes a WebP from srcSet instead. Rendered box was
                      measured at 330 CSS px on a 390px phone (989 device px) and
                      625 CSS px at 1440 (1250 device px), so the ladder and the
                      sizes hints below are cut to those numbers -- a phone takes
                      the 1000w (30KB vs 701KB), desktop the 1400w. */}
                  <img className={`eye2-img${eye2Light ? " light" : ""}`}
                    src={eye2Light ? "/eye2-hero.png" : "/eye2-dark.png"}
                    srcSet={eye2Light
                      ? "/eye2-hero-1000.webp 1000w, /eye2-hero-1400.webp 1400w, /eye2-hero.webp 2400w"
                      : "/eye2-dark-1000.webp 1000w, /eye2-dark-1400.webp 1400w, /eye2-dark.webp 2400w"}
                    sizes="(max-width: 720px) 85vw, 45vw"
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
