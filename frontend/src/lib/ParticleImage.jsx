import { useEffect, useRef } from "react";

/**
 * People particle-reveal.
 *
 * A transparent cutout (people + YC board, on black) is sampled into colour
 * dots. The BOARD is always fixed crisp particles. The people drift as a legible
 * cloud when idle; hover a person and their dots resolve into their real photo
 * (translucent, soft-feathered) while the other people fade out. `onFocus`
 * fires so the page can show that person's blurb.
 *
 * @param {string}   src        transparent cutout URL
 * @param {number[]} bands      normalised x-splits, length N+1 (people), index N = board
 * @param {number}   boardTop   normalised y; dots below this are the board
 * @param {number}   [target]   particle budget
 * @param {number}   [disperse] idle scatter, px
 * @param {(i:number|null, anchor:object|null)=>void} [onFocus]
 */
export default function ParticleImage({ src, bands, boardTop = 0.6, target = 26000, disperse = 16, onFocus, className }) {
  const canvasRef = useRef(null);
  const mouse = useRef({ x: -1e5, y: -1e5, active: false });
  // Touch has no hover: a tap on a person locks them (tap another person to
  // switch, tap the board/background to release back to the idle cloud).
  const touchLock = useRef(-1);
  const onFocusRef = useRef(onFocus);
  onFocusRef.current = onFocus;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    const reduce = !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const NP = bands.length - 1;   // people count
    const BOARD = NP;              // board component id

    let raf = 0, W = 0, H = 0, t = 0, N = 0, focus = -1;
    let layout = { ox: 0, oy: 0, dw: 1, dh: 1 };
    let hx, hy, px, py, oa, orad, sp, ba, ca, comp, col;
    const img = new Image();
    img.crossOrigin = "anonymous";

    const bandOf = (xn) => {
      for (let i = 0; i < NP; i++) if (xn < bands[i + 1]) return i;
      return NP - 1;
    };

    const build = () => {
      const rect = canvas.getBoundingClientRect();
      W = Math.max(1, Math.round(rect.width));
      H = Math.max(1, Math.round(rect.height));
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      const s = Math.min(W / img.width, H / img.height);
      const dw = img.width * s, dh = img.height * s;
      layout = { ox: (W - dw) / 2, oy: (H - dh) / 2, dw, dh };
      const { ox, oy } = layout;

      const off = document.createElement("canvas");
      off.width = Math.max(1, Math.round(dw)); off.height = Math.max(1, Math.round(dh));
      const octx = off.getContext("2d", { willReadFrequently: true });
      octx.drawImage(img, 0, 0, off.width, off.height);
      const data = octx.getImageData(0, 0, off.width, off.height).data;
      const gap = Math.max(3, Math.round(Math.sqrt((off.width * off.height) / target)));

      let count = 0;
      for (let y = (gap >> 1); y < off.height; y += gap)
        for (let x = (gap >> 1); x < off.width; x += gap)
          if (data[(y * off.width + x) * 4 + 3] > 24) count++;
      N = count;
      hx = new Float32Array(N); hy = new Float32Array(N);
      px = new Float32Array(N); py = new Float32Array(N);
      oa = new Float32Array(N); orad = new Float32Array(N); sp = new Float32Array(N);
      ba = new Float32Array(N); ca = new Float32Array(N);
      comp = new Uint8Array(N); col = new Array(N);

      let k = 0;
      for (let y = (gap >> 1); y < off.height; y += gap) {
        for (let x = (gap >> 1); x < off.width; x += gap) {
          const i = (y * off.width + x) * 4;
          const a = data[i + 3];
          if (a <= 24) continue;
          hx[k] = ox + x; hy[k] = oy + y;
          const ang = Math.random() * Math.PI * 2;
          const rr = disperse * (0.5 + Math.random() * 0.7);
          px[k] = hx[k] + Math.cos(ang) * rr; py[k] = hy[k] + Math.sin(ang) * rr;
          oa[k] = ang; orad[k] = rr; sp[k] = 0.2 + Math.random() * 0.5;
          ba[k] = a / 255; ca[k] = ba[k] * 0.72;
          comp[k] = (y / off.height) >= boardTop ? BOARD : bandOf(x / off.width);
          col[k] = `rgb(${data[i]},${data[i + 1]},${data[i + 2]})`;
          k++;
        }
      }
    };

    const anchorFor = (i) => {
      const { ox, oy, dw, dh } = layout;
      return { left: ox + bands[i] * dw, right: ox + bands[i + 1] * dw, top: oy, bottom: oy + boardTop * dh };
    };

    const tick = () => {
      raf = requestAnimationFrame(tick);
      t += 0.016;
      ctx.clearRect(0, 0, W, H);
      const m = mouse.current;
      const { ox, oy, dw, dh } = layout;

      let f = -1;
      if (touchLock.current >= 0) {
        f = touchLock.current;
      } else if (m.active) {
        const xn = (m.x - ox) / dw, yn = (m.y - oy) / dh;
        if (xn >= 0 && xn <= 1 && yn >= 0 && yn < boardTop) f = bandOf(xn);
      }
      if (f !== focus) {
        focus = f;
        onFocusRef.current?.(f >= 0 ? f : null, f >= 0 ? anchorFor(f) : null);
      }

      const drift = reduce ? 0 : 1;
      for (let i = 0; i < N; i++) {
        const isBoard = comp[i] === BOARD;
        const isHit = focus >= 0 && comp[i] === focus;
        let tx = hx[i], ty = hy[i], tA;
        if (isBoard) {
          if (focus < 0) {
            // idle: the board flows with the rest of the cloud
            if (drift) { tx += Math.cos(oa[i] + t * sp[i]) * orad[i]; ty += Math.sin(oa[i] + t * sp[i]) * orad[i]; }
            tA = ba[i] * 0.72;
          } else {
            tA = ba[i];                                 // fixed + crisp while a person is focused
          }
        } else if (isHit) {
          // revealed person: dense particles near home with a gentle live shimmer
          if (drift) { tx += Math.cos(t * 2.1 + oa[i]) * 2.7; ty += Math.sin(t * 2.1 + oa[i]) * 2.7; }
          tA = Math.min(1, ba[i] * 1.1);
        } else if (focus >= 0) {
          if (drift) { tx += Math.cos(oa[i] + t * sp[i]) * orad[i] * 2.2; ty += Math.sin(oa[i] + t * sp[i]) * orad[i] * 2.2; }
          tA = 0;                                        // other people fade away
        } else {
          if (drift) { tx += Math.cos(oa[i] + t * sp[i]) * orad[i]; ty += Math.sin(oa[i] + t * sp[i]) * orad[i]; }
          tA = ba[i] * 0.72;
        }
        const ease = isHit ? 0.2 : 0.14;
        px[i] += (tx - px[i]) * ease;
        py[i] += (ty - py[i]) * ease;
        ca[i] += (tA - ca[i]) * 0.12;
        if (ca[i] < 0.02) continue;
        ctx.globalAlpha = ca[i];
        ctx.fillStyle = col[i];
        const sz = isBoard ? 2.5 : isHit ? 2.4 : 2.2;
        ctx.fillRect(px[i], py[i], sz, sz);
      }
      ctx.globalAlpha = 1;
    };

    img.onload = () => { build(); cancelAnimationFrame(raf); tick(); };
    img.src = src;

    // Mouse/pen: continuous hover, exactly as before.
    const onMove = (e) => {
      if (e.pointerType === "touch") return;
      const r = canvas.getBoundingClientRect();
      mouse.current = { x: e.clientX - r.left, y: e.clientY - r.top, active: true };
    };
    const onLeave = (e) => {
      if (e.pointerType === "touch") return;
      mouse.current.active = false;
    };
    // Touch: tap-to-lock. A tap on a person locks them; a tap on the board or
    // anywhere else in the frame releases the lock (back to the idle cloud).
    const onDown = (e) => {
      if (e.pointerType !== "touch") return;
      const r = canvas.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      const { ox, oy, dw, dh } = layout;
      const xn = (x - ox) / dw, yn = (y - oy) / dh;
      touchLock.current = (xn >= 0 && xn <= 1 && yn >= 0 && yn < boardTop) ? bandOf(xn) : -1;
    };
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerleave", onLeave);
    canvas.addEventListener("pointerdown", onDown);
    let rt = 0;
    const onResize = () => { clearTimeout(rt); rt = setTimeout(() => { if (img.complete && img.naturalWidth) build(); }, 160); };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("pointerdown", onDown);
      window.removeEventListener("resize", onResize);
    };
  }, [src, boardTop, target, disperse, bands]);

  return <canvas ref={canvasRef} className={className} style={{ width: "100%", height: "100%", display: "block", touchAction: "none" }} />;
}
