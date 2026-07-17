import { useEffect, useRef } from "react";
import { useReducedMotion } from "framer-motion";
import SiteNav from "../SiteNav.jsx";
import AuroraGL from "./AuroraGL.jsx";
import Hand3D from "./Hand3D.jsx";
import { useRevealNav } from "../useRevealNav.js";
import "./products-v2.css";

// Phase 2 feature flag: GLSL aurora is opt-in via ?v2&gl (or ?v2&aurora=gl) while
// the Canvas2D aurora stays the verified default. Flip the default once the shader
// is confirmed in a real (non-swiftshader) browser.
const USE_GL_AURORA = (() => {
  if (typeof window === "undefined") return false;
  const q = new URLSearchParams(window.location.search);
  return q.has("gl") || q.get("aurora") === "gl";
})();

// Phase 3a feature flag: opt-in static 3D Aero-hand render on the Hand scene via
// ?v2&hand3d. Off by default, so the Hand scene keeps the robo.webp image.
const USE_HAND3D = (() => {
  if (typeof window === "undefined") return false;
  return new URLSearchParams(window.location.search).has("hand3d");
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
    stats: [["440", "tactile channels"], ["0.01N", "resolution"], ["<1ms", "response"], ["200Hz", "sustained"]],
  },
  {
    idx: "02 · Eye2", title: "Eye2",
    line: "The egocentric camera that sees what the hand feels. First-person video, synced to touch.",
    img: "/eye2-dark.png", cta: "Request a demo",
    stats: [["4000×1200", "stereo capture"], ["30fps", "global shutter"], ["Wireless", "onboard compute"], ["Printed", "enclosure"]],
  },
  {
    idx: "03 · Hand", title: "Hand",
    line: "Custom tactile skin, molded 1:1 to a dexterous hand, a gripper, any surface you build.",
    img: "/hero/glove/robo.webp", cta: "Build with us",
    stats: [["162", "sensing points"], ["200k", "impacts at 3MPa"], ["Any", "robot, custom-cut"]],
  },
];

const GLOVE_FRAMES = ["000", "001", "002", "003", "004", "005"].map((n) => `/hero/glove/frame-${n}.webp`);

// weighted aurora palette (h,s,l,weight): brown a bit more, green a bit less
const PAL = [[28, .55, .42, 3.0], [150, .9, .60, 1.5], [178, .92, .62, 2.0], [205, .92, .63, 2.0], [275, .90, .63, 2.0], [315, .85, .62, 2.0]];

function hsl2rgb(h, s, l) {
  h /= 360; const q = l < .5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < .5 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
  return [Math.round(f(h + 1 / 3) * 255), Math.round(f(h) * 255), Math.round(f(h - 1 / 3) * 255)];
}

export default function ProductsV2() {
  const rootRef = useRef(null);
  const canvasRef = useRef(null);
  const gloveRef = useRef(null);
  // reuse the site's real flagship navbar (keep the main site chrome; replace only the products content)
  const reduceMotion = useReducedMotion();
  const { className: navClassName } = useRevealNav({ reduceMotion: !!reduceMotion });

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;
    // When the GLSL aurora is active there is no 2D canvas; the scene-reveal /
    // sidenav / glove logic below must still run, so only the Canvas2D aurora
    // painting is gated on `ctx`.
    const cv = USE_GL_AURORA ? null : canvasRef.current;
    const ctx = cv ? cv.getContext("2d") : null;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let W = 0, H = 0; const RS = 0.35;
    const size = () => {
      if (!ctx) { W = window.innerWidth; H = window.innerHeight; return; }
      W = cv.clientWidth; H = cv.clientHeight; cv.width = Math.round(W * RS); cv.height = Math.round(H * RS); ctx.setTransform(RS, 0, 0, RS, 0, 0);
    };
    size();

    const sceneEls = [...root.querySelectorAll(".scene")].map((el) => ({ el, txt: [...el.querySelectorAll(".idx,h1,.oneliner,.stats,.cta")], img: el.querySelector(".pimg"), top: 0, h: 0 }));
    const measure = () => { for (const s of sceneEls) { s.top = s.el.offsetTop; s.h = s.el.offsetHeight; } };
    measure();
    const navEls = [...root.querySelectorAll(".sidenav a")];
    const onNav = (e) => { e.preventDefault(); const i = +e.currentTarget.dataset.i; sceneEls[i]?.el.scrollIntoView({ behavior: "smooth", block: "center" }); };
    navEls.forEach((a) => a.addEventListener("click", onNav));

    // preload glove frames
    GLOVE_FRAMES.forEach((src) => { const im = new Image(); im.src = src; });

    const PALT = PAL.reduce((a, x) => a + x[3], 0);
    const pick = () => { let r = Math.random() * PALT; for (const x of PAL) { if ((r -= x[3]) < 0) return x; } return PAL[0]; };
    const N = 14, blobs = [];
    for (let i = 0; i < N; i++) {
      const col = pick();
      blobs.push({
        fx: Math.random(), fy: (i + (Math.random() - .5)) / N, r: .30 + Math.random() * .22,
        ex: 1.3 + Math.random() * .9, ey: .6 + Math.random() * .4, rot: (Math.random() * .6 - .3),
        col, a: .15 + Math.random() * .09, px: 0, py: 0,
        ph: Math.random() * 6.28, fr: .25 + Math.random() * .5, ax: .04 + Math.random() * .05, ay: 12 + Math.random() * 26,
        // hue drifts over time so colors visibly cycle; brown stays brown (small amp)
        hamp: col[0] < 60 ? 10 : 42, hrate: .002 + Math.random() * .002,
      });
    }

    let scrollY = 0, mx = -9999, my = -9999, t = 0, curActive = -1, isLight = false, gFrame = -1, raf = 0;
    const onScroll = () => { scrollY = window.scrollY; };
    const onMove = (e) => { mx = e.clientX; my = e.clientY; };
    const onLeave = () => { mx = -9999; my = -9999; };
    const onResize = () => { size(); measure(); };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerleave", onLeave);
    window.addEventListener("resize", onResize);

    const worldH = () => document.documentElement.scrollHeight;

    const frame = () => {
      t += 1;
      const c1 = sceneEls[1] ? (sceneEls[1].top + sceneEls[1].h / 2 - scrollY) : 9e9;
      const light = Math.max(0, Math.min(1, 1 - Math.abs(c1 - H / 2) / (H * .62)));

      if (ctx && t % 2 === 0) {
        ctx.setTransform(RS, 0, 0, RS, 0, 0);
        ctx.globalCompositeOperation = "source-over";
        ctx.fillStyle = `rgb(${(7 + 15 * light) | 0},${(7 + 11 * light) | 0},${(10 + 27 * light) | 0})`;
        ctx.fillRect(0, 0, W, H);
        ctx.globalCompositeOperation = "lighter";
        const wh = worldH();
        for (const b of blobs) {
          const drift = Math.sin(t * .006 * b.fr + b.ph) * b.ax;
          let x = (b.fx + drift) * W;
          let y = b.fy * wh - scrollY + Math.cos(t * .005 * b.fr + b.ph) * b.ay;
          const dx = x - mx, dy = y - my, d = Math.hypot(dx, dy), R = 460;
          if (d < R && d > 0) { const k = 1 - d / R, f = k * k * 130; b.px += (dx / d * f - b.px) * .035; b.py += (dy / d * f - b.py) * .035; }
          else { b.px += (0 - b.px) * .035; b.py += (0 - b.py) * .035; }
          x += b.px; y += b.py;
          if (y < -H * 1.1 || y > H * 2.1) continue;
          const hue = b.col[0] + Math.sin(t * b.hrate + b.ph) * b.hamp;
          const c = hsl2rgb(hue, b.col[1], b.col[2]);
          const aa = b.a * (1 - light * 0.12);
          const RAD = b.r * Math.min(W, H);
          ctx.save();
          ctx.translate(x, y); ctx.rotate(b.rot); ctx.scale(b.ex, b.ey);
          const g = ctx.createRadialGradient(0, 0, 0, 0, 0, RAD);
          g.addColorStop(0, `rgba(${c[0]},${c[1]},${c[2]},${aa})`);
          g.addColorStop(.6, `rgba(${c[0]},${c[1]},${c[2]},${aa * .5})`);
          g.addColorStop(1, `rgba(${c[0]},${c[1]},${c[2]},0)`);
          ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, RAD, 0, 7); ctx.fill();
          ctx.restore();
        }
      }

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

      if (gloveRef.current) {
        const gi = Math.round((Math.sin(t * 0.012) * .5 + .5) * 5);
        if (gi !== gFrame) { gFrame = gi; gloveRef.current.src = GLOVE_FRAMES[gi]; }
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerleave", onLeave);
      window.removeEventListener("resize", onResize);
      navEls.forEach((a) => a.removeEventListener("click", onNav));
    };
  }, []);

  return (
    <div className="pv2" ref={rootRef}>
      {USE_GL_AURORA
        ? <AuroraGL />
        : <canvas className="aurora-canvas" ref={canvasRef} aria-hidden="true" />}
      {/* the site's real flagship navbar (same as the rest of 6thsense.dev) */}
      <SiteNav className={navClassName} />
      <nav className="sidenav" aria-label="Products">
        {STAGES.map((s, i) => (
          <a key={s.title} data-i={i} href={`#${s.title.toLowerCase()}`}><i />{s.title}</a>
        ))}
      </nav>

      <div className="page">
        {STAGES.map((s, i) => (
          <section className="scene" id={s.title.toLowerCase()} key={s.title}>
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
              ? <div className="pimg hand3d"><Hand3D /></div>
              : <img className="pimg" src={s.img} alt={`6thSense ${s.title}`}
                  ref={s.glove ? gloveRef : undefined} draggable="false" />}
          </section>
        ))}
      </div>

      <div className="hint"><span className="hint-scroll">scroll ↓</span><span className="hint-mouse"> &nbsp;·&nbsp; move your mouse through the aurora</span></div>
    </div>
  );
}
