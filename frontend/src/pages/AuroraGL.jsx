import { useEffect, useRef } from "react";
import * as THREE from "three";

/**
 * AuroraGL — Phase 2 of /products v2.
 *
 * A fullscreen fragment-shader port of the approved Canvas2D aurora. Same blob
 * model (weighted random palette, per-patch slow hue drift, scroll coupling,
 * mouse-push, subtle per-scene tone lift), but the expensive per-frame radial
 * gradient rasterization runs on the GPU instead of Canvas2D — so it stays
 * smooth at full viewport size and doesn't fight the scroll thread.
 *
 * The CPU still owns the cheap part (14 blob transforms + hue + push easing) so
 * the look matches the Canvas2D version pixel-for-pixel. It reuses the exact
 * shared `.aurora-bg` CSS (fixed, behind content, blur(30px)) as the fallback.
 *
 * Feature-flagged in ProductsV2 (Canvas2D remains the default fallback).
 */

// weighted aurora palette (h,s,l,weight) — IDENTICAL to ProductsV2: brown more, green less
const PAL = [[28, .55, .42, 3.0], [150, .9, .60, 1.5], [178, .92, .62, 2.0], [205, .92, .63, 2.0], [275, .90, .63, 2.0], [315, .85, .62, 2.0]];
const N = 14;

function hsl2rgb(h, s, l) {
  h /= 360; const q = l < .5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < .5 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
  return [f(h + 1 / 3), f(h), f(h - 1 / 3)]; // 0..1 for GL
}

const VERT = `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }
`;

// Per pixel: accumulate 14 elliptical radial gradients additively over a dark base.
// Falloff replicates the Canvas2D radial stops: (0 -> aa), (.6 -> aa*.5), (1 -> 0).
const FRAG = `
precision highp float;
varying vec2 vUv;
uniform vec2 uRes;
uniform vec3 uBase;
uniform vec2 uPos[${N}];   // blob center, normalized 0..1, y-down (incl scroll+drift+push)
uniform vec3 uRGB[${N}];   // blob color 0..1 (hue drift already applied on CPU)
uniform vec4 uParam[${N}]; // x: radius frac of min(W,H), y: alpha, z: ellipseX, w: ellipseY
uniform float uRot[${N}];  // rotation (radians)
void main() {
  vec2 uv = vec2(vUv.x, 1.0 - vUv.y); // to y-down screen space
  vec2 frag = uv * uRes;
  float minD = min(uRes.x, uRes.y);
  vec3 col = uBase;
  for (int i = 0; i < ${N}; i++) {
    vec2 d = frag - uPos[i] * uRes;
    float cs = cos(-uRot[i]), sn = sin(-uRot[i]);
    d = vec2(d.x * cs - d.y * sn, d.x * sn + d.y * cs);
    d /= vec2(uParam[i].z, uParam[i].w);
    float u = clamp(length(d) / (uParam[i].x * minD), 0.0, 1.0);
    float aa = uParam[i].y;
    float a = u < 0.6 ? mix(aa, aa * 0.5, u / 0.6) : mix(aa * 0.5, 0.0, (u - 0.6) / 0.4);
    col += uRGB[i] * a;
  }
  gl_FragColor = vec4(col, 1.0);
}
`;

export default function AuroraGL() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;

    let renderer;
    try {
      // preserveDrawingBuffer:true is REQUIRED here. The shared `.aurora-bg` CSS
      // applies `filter: blur(30px)`, which forces this canvas onto its own
      // compositor layer. With the default preserveDrawingBuffer:false, the
      // compositor snapshots the *cleared* (black) buffer for that filter layer
      // instead of the just-rendered frame — so the aurora renders correctly in
      // the framebuffer but displays as solid black on real GPUs (Canvas2D is
      // immune because its bitmap always persists). Keeping the buffer alive
      // makes the blur read the real rendered frame. Perf impact is negligible.
      renderer = new THREE.WebGLRenderer({ canvas: cv, antialias: false, alpha: false, powerPreference: "low-power", preserveDrawingBuffer: true });
    } catch (e) {
      // WebGL unavailable — ProductsV2 keeps the Canvas2D fallback, so just bail quietly.
      console.warn("AuroraGL: WebGL unavailable, no GL aurora.", e);
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));

    const scene = new THREE.Scene();
    const camera = new THREE.Camera(); // fullscreen clip-space quad; no projection needed

    // preallocate uniform objects (mutated each frame, no per-frame GC)
    const uPos = Array.from({ length: N }, () => new THREE.Vector2());
    const uRGB = Array.from({ length: N }, () => new THREE.Vector3());
    const uParam = Array.from({ length: N }, () => new THREE.Vector4());
    const uRot = new Float32Array(N);
    const uniforms = {
      uRes: { value: new THREE.Vector2(1, 1) },
      uBase: { value: new THREE.Vector3() },
      uPos: { value: uPos }, uRGB: { value: uRGB }, uParam: { value: uParam }, uRot: { value: uRot },
    };
    const material = new THREE.ShaderMaterial({ vertexShader: VERT, fragmentShader: FRAG, uniforms, depthTest: false, depthWrite: false });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), material);
    scene.add(mesh);

    // --- blob model: identical constants to the Canvas2D aurora ---
    const PALT = PAL.reduce((a, x) => a + x[3], 0);
    const pick = () => { let r = Math.random() * PALT; for (const x of PAL) { if ((r -= x[3]) < 0) return x; } return PAL[0]; };
    const blobs = [];
    for (let i = 0; i < N; i++) {
      const col = pick();
      blobs.push({
        fx: Math.random(), fy: (i + (Math.random() - .5)) / N, r: .30 + Math.random() * .22,
        ex: 1.3 + Math.random() * .9, ey: .6 + Math.random() * .4, rot: (Math.random() * .6 - .3),
        col, a: .15 + Math.random() * .09, px: 0, py: 0,
        ph: Math.random() * 6.28, fr: .25 + Math.random() * .5, ax: .04 + Math.random() * .05, ay: 12 + Math.random() * 26,
        hamp: col[0] < 60 ? 10 : 42, hrate: .002 + Math.random() * .002,
      });
    }

    let W = 0, H = 0, scrollY = 0, mx = -9999, my = -9999, t = 0, raf = 0;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const size = () => {
      W = window.innerWidth; H = window.innerHeight;
      renderer.setSize(W, H, false);
      uniforms.uRes.value.set(W, H);
    };
    size();

    // Scene-1 (Eye2) proximity drives a subtle bg tone lift, same as Canvas2D.
    const sceneEl = () => document.querySelectorAll(".pv2 .scene")[1] || null;

    const onScroll = () => { scrollY = window.scrollY; };
    const onMove = (e) => { mx = e.clientX; my = e.clientY; };
    const onLeave = () => { mx = -9999; my = -9999; };
    const onResize = () => size();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerleave", onLeave);
    window.addEventListener("resize", onResize);

    const worldH = () => document.documentElement.scrollHeight;

    const frame = () => {
      if (!reduce) t += 1;

      const s1 = sceneEl();
      let light = 0;
      if (s1) {
        const c1 = s1.offsetTop + s1.offsetHeight / 2 - scrollY;
        light = Math.max(0, Math.min(1, 1 - Math.abs(c1 - H / 2) / (H * .62)));
      }
      uniforms.uBase.value.set((7 + 15 * light) / 255, (7 + 11 * light) / 255, (10 + 27 * light) / 255);

      const wh = worldH();
      for (let i = 0; i < N; i++) {
        const b = blobs[i];
        const drift = Math.sin(t * .006 * b.fr + b.ph) * b.ax;
        let x = (b.fx + drift) * W;
        let y = b.fy * wh - scrollY + Math.cos(t * .005 * b.fr + b.ph) * b.ay;
        const dx = x - mx, dy = y - my, d = Math.hypot(dx, dy), R = 460;
        if (d < R && d > 0) { const k = 1 - d / R, f = k * k * 130; b.px += (dx / d * f - b.px) * .035; b.py += (dy / d * f - b.py) * .035; }
        else { b.px += (0 - b.px) * .035; b.py += (0 - b.py) * .035; }
        x += b.px; y += b.py;

        const hue = b.col[0] + Math.sin(t * b.hrate + b.ph) * b.hamp;
        const c = hsl2rgb(hue, b.col[1], b.col[2]);
        const aa = b.a * (1 - light * 0.12);

        uPos[i].set(x / W, y / H);
        uRGB[i].set(c[0], c[1], c[2]);
        uParam[i].set(b.r, aa, b.ex, b.ey);
        uRot[i] = b.rot;
      }
      material.uniformsNeedUpdate = true;
      renderer.render(scene, camera);
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerleave", onLeave);
      window.removeEventListener("resize", onResize);
      mesh.geometry.dispose(); material.dispose(); renderer.dispose();
    };
  }, []);

  return <canvas className="aurora-bg" ref={canvasRef} aria-hidden="true" />;
}
