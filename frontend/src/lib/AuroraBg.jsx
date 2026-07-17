import { useEffect, useRef } from "react";
import "./AuroraBg.css";

/**
 * AuroraBg — the shared Canvas2D aurora background.
 *
 * Extracted verbatim from the approved /products v2 aurora (design locked with
 * Ronak) so the whole site can share ONE cohesive background. Wispy weighted-
 * palette patches (brown > green), per-patch hue drift, scroll coupling, and a
 * mouse-push easing. Paints its own opaque dark base, so it doubles as the page
 * background.
 *
 * Reusable: mount it once per page as a fixed full-viewport canvas behind the
 * content (content must sit at a higher stacking level).
 *
 * Props:
 *   - lightRef: optional React ref holding a 0..1 "tone lift" the host updates
 *     per-frame (e.g. the /products Eye2 scene brightens the bg as it centers).
 *     Default: no lift (constant dark base).
 *   - className: extra class(es) appended to the canvas (e.g. z-index variants).
 */

// weighted aurora palette (h,s,l,weight): brown a bit more, green a bit less
const PAL = [[28, .55, .42, 3.0], [150, .9, .60, 1.5], [178, .92, .62, 2.0], [205, .92, .63, 2.0], [275, .90, .63, 2.0], [315, .85, .62, 2.0]];

function hsl2rgb(h, s, l) {
  h /= 360; const q = l < .5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = (t) => { t = (t + 1) % 1; return t < 1 / 6 ? p + (q - p) * 6 * t : t < .5 ? q : t < 2 / 3 ? p + (q - p) * (2 / 3 - t) * 6 : p; };
  return [Math.round(f(h + 1 / 3) * 255), Math.round(f(h) * 255), Math.round(f(h - 1 / 3) * 255)];
}

export default function AuroraBg({ lightRef = null, className = "" }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;

    let W = 0, H = 0; const RS = 0.35;
    const size = () => {
      W = cv.clientWidth; H = cv.clientHeight;
      cv.width = Math.round(W * RS); cv.height = Math.round(H * RS);
      ctx.setTransform(RS, 0, 0, RS, 0, 0);
    };
    size();

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

    let scrollY = window.scrollY, mx = -9999, my = -9999, t = 0, raf = 0;
    const onScroll = () => { scrollY = window.scrollY; };
    const onMove = (e) => { mx = e.clientX; my = e.clientY; };
    const onLeave = () => { mx = -9999; my = -9999; };
    const onResize = () => { size(); };
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pointermove", onMove, { passive: true });
    window.addEventListener("pointerleave", onLeave);
    window.addEventListener("resize", onResize);

    const worldH = () => document.documentElement.scrollHeight;

    const frame = () => {
      t += 1;
      const light = lightRef && typeof lightRef.current === "number" ? lightRef.current : 0;

      if (t % 2 === 0) {
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
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerleave", onLeave);
      window.removeEventListener("resize", onResize);
    };
  }, [lightRef]);

  return <canvas className={`aurora-bg ${className}`.trim()} ref={canvasRef} aria-hidden="true" />;
}
