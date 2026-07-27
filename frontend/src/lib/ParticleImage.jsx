import { useEffect, useRef } from "react";

/**
 * People particle-reveal.
 *
 * A transparent cutout (people + YC board, on black) is sampled into colour
 * dots. The BOARD is always fixed crisp particles. The people drift as a legible
 * cloud when idle; focus a person and their dots resolve into their real
 * (translucent, soft-feathered) photo while the other people fade out.
 *
 * The focused person is CONTROLLED by the parent via `focus`, so the same reveal
 * can be driven by the visible person list, by hover, by tap, or by the keyboard.
 * This component only reports intent (`onHover` / `onSelect`) and geometry
 * (`onLayout`); it never decides who is focused.
 *
 * @param {string}   src        transparent cutout URL
 * @param {number[]} bands      normalised x-splits, length N+1 (people), index N = board.
 *                              MUST be a stable reference (module const) — it is an effect dep.
 * @param {number}   boardTop   normalised y; dots below this are the board
 * @param {number}   [target]   particle budget
 * @param {number}   [disperse] idle scatter, px
 * @param {number|null} [focus] index of the revealed person, or null
 * @param {boolean} [zoomOnFocus] push the camera in on the focused person. Needed
 *                              on phones, where a person is only ~70px wide in the
 *                              full group shot and the reveal would be unreadable.
 * @param {(i:number|null)=>void} [onHover]  pointer (non-touch) moved onto/off a person
 * @param {(i:number|null)=>void} [onSelect] click/tap on a person, or null for empty space
 * @param {(geo:{anchors:object[],stage:object})=>void} [onLayout] viewport-space geometry,
 *                              fired on first build and on resize
 */
export default function ParticleImage({
  src,
  bands,
  boardTop = 0.6,
  target = 26000,
  disperse = 16,
  focus = null,
  zoomOnFocus = false,
  onHover,
  onSelect,
  onLayout,
  className,
}) {
  const canvasRef = useRef(null);
  const focusRef = useRef(-1);
  const zoomRef = useRef(zoomOnFocus);
  zoomRef.current = zoomOnFocus;
  const cbRef = useRef({ onHover, onSelect, onLayout });
  cbRef.current = { onHover, onSelect, onLayout };

  // Focus is owned by the parent; mirror it into a ref the animation loop reads
  // so changing it never tears down the (expensive) particle build.
  useEffect(() => {
    focusRef.current = focus == null ? -1 : focus;
  }, [focus]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    const reduce = !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const NP = bands.length - 1;   // people count
    const BOARD = NP;              // board component id

    let raf = 0, W = 0, H = 0, t = 0, N = 0, focused = -1, revealA = 0;
    let layout = { ox: 0, oy: 0, dw: 1, dh: 1 };
    let hx, hy, px, py, oa, orad, sp, ba, ca, comp, col;
    let slices = [];               // per-person feathered photo tiles (native res)
    let cam = { s: 1, x: 0, y: 0 }; // animated camera, canvas-space
    const img = new Image();
    img.crossOrigin = "anonymous";

    // The photo tiles stop just short of the board: the board's bright top edge
    // is a hard horizontal line and including it put a glowing rectangle across
    // the bottom of every revealed person.
    const PHOTO_BOTTOM = Math.max(0.1, boardTop - 0.05);

    const bandOf = (xn) => {
      for (let i = 0; i < NP; i++) if (xn < bands[i + 1]) return i;
      return NP - 1;
    };

    // One feathered photo tile per person, cut from the source image at its NATIVE
    // resolution (so it stays sharp when the camera pushes in on a phone).
    // Drawing this under the person's dots is what makes the dots read as
    // "resolving into a photo" instead of just getting denser.
    const buildSlices = () => {
      const out = [];
      const iw = img.naturalWidth || img.width;
      const ih = img.naturalHeight || img.height;
      for (let i = 0; i < NP; i++) {
        const x0 = Math.floor(bands[i] * iw);
        const x1 = Math.ceil(bands[i + 1] * iw);
        const w = Math.max(1, x1 - x0);
        const h = Math.max(1, Math.round(PHOTO_BOTTOM * ih));
        const c = document.createElement("canvas");
        c.width = w; c.height = h;
        const cx = c.getContext("2d");
        cx.drawImage(img, -x0, 0, iw, ih);
        // Feather the vertical band seams and the bottom edge, so a revealed
        // person doesn't sit in a hard rectangle. Kept narrow: too much feather
        // ate into the shoulders on the outer two bands.
        const feather = Math.max(4, Math.min(26, Math.round(w * 0.11)));
        cx.globalCompositeOperation = "destination-in";
        const gx = cx.createLinearGradient(0, 0, w, 0);
        gx.addColorStop(0, "rgba(0,0,0,0)");
        gx.addColorStop(feather / w, "rgba(0,0,0,1)");
        gx.addColorStop(1 - feather / w, "rgba(0,0,0,1)");
        gx.addColorStop(1, "rgba(0,0,0,0)");
        cx.fillStyle = gx;
        cx.fillRect(0, 0, w, h);
        // Bottom fade must be `destination-out` over just the strip: a partial
        // `destination-in` fill would erase the whole rest of the tile.
        const fadeTop = Math.floor(h * 0.74);
        cx.globalCompositeOperation = "destination-out";
        const gy = cx.createLinearGradient(0, fadeTop, 0, h);
        gy.addColorStop(0, "rgba(0,0,0,0)");
        gy.addColorStop(1, "rgba(0,0,0,1)");
        cx.fillStyle = gy;
        cx.fillRect(0, fadeTop, w, h - fadeTop);
        // Normalised placement, so the tile can be drawn at any display scale.
        out.push({ canvas: c, x0n: bands[i], x1n: bands[i + 1], y1n: PHOTO_BOTTOM });
      }
      return out;
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

      slices = buildSlices();
      cam = { s: 1, x: W / 2, y: H / 2 };
      reportLayout();
    };

    // Anchors are reported in VIEWPORT coordinates so the page can place a blurb
    // in the empty space beside a person without knowing where the canvas sits.
    const reportLayout = () => {
      const r = canvas.getBoundingClientRect();
      const { ox, oy, dw, dh } = layout;
      const anchors = [];
      for (let i = 0; i < NP; i++) {
        anchors.push({
          left: r.left + ox + bands[i] * dw,
          right: r.left + ox + bands[i + 1] * dw,
          top: r.top + oy,
          bottom: r.top + oy + boardTop * dh,
        });
      }
      cbRef.current.onLayout?.({
        anchors,
        stage: { left: r.left, top: r.top, right: r.right, bottom: r.bottom, width: r.width, height: r.height },
      });
    };

    // Screen -> image space, undoing the camera so hits still land on the right
    // person while the view is pushed in.
    const hitTest = (clientX, clientY) => {
      const r = canvas.getBoundingClientRect();
      const { ox, oy, dw, dh } = layout;
      const wx = (clientX - r.left - W / 2) / cam.s + cam.x;
      const wy = (clientY - r.top - H / 2) / cam.s + cam.y;
      const xn = (wx - ox) / dw;
      const yn = (wy - oy) / dh;
      if (xn >= 0 && xn <= 1 && yn >= 0 && yn < boardTop) return bandOf(xn);
      return null;
    };

    const tick = () => {
      raf = requestAnimationFrame(tick);
      t += 0.016;
      focused = focusRef.current;
      const { ox, oy, dw, dh } = layout;

      // Photo crossfade for the focused person.
      const rTarget = focused >= 0 ? 1 : 0;
      const rEase = reduce ? 0.5 : 0.09;
      revealA += (rTarget - revealA) * rEase;

      // Camera: on narrow layouts a person is only ~70px wide in the group shot,
      // so push in on whoever is focused. Desktop leaves the camera at 1.
      let camT = { s: 1, x: W / 2, y: H / 2 };
      if (zoomRef.current && focused >= 0) {
        const bandW = (bands[focused + 1] - bands[focused]) * dw;
        const s = Math.max(1, Math.min(2.6, (W * 0.78) / Math.max(1, bandW)));
        // Frame the head and shoulders (upper part of the person), not the middle.
        camT = {
          s,
          x: ox + ((bands[focused] + bands[focused + 1]) / 2) * dw,
          y: oy + 0.3 * dh,
        };
      }
      const cEase = reduce ? 0.5 : 0.085;
      cam.s += (camT.s - cam.s) * cEase;
      cam.x += (camT.x - cam.x) * cEase;
      cam.y += (camT.y - cam.y) * cEase;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      ctx.setTransform(
        dpr * cam.s, 0, 0, dpr * cam.s,
        dpr * (W / 2 - cam.x * cam.s),
        dpr * (H / 2 - cam.y * cam.s)
      );
      const invS = 1 / cam.s;

      if (focused >= 0 && revealA > 0.01 && slices[focused]) {
        const s = slices[focused];
        // Just under full opacity, with some of the person's dots kept alive on
        // top (see `isHit` below) so the reveal still reads as particles
        // resolving rather than a photo being swapped in.
        ctx.globalAlpha = Math.min(1, revealA) * 0.95;
        ctx.drawImage(
          s.canvas,
          ox + s.x0n * dw, oy,
          (s.x1n - s.x0n) * dw, s.y1n * dh
        );
        ctx.globalAlpha = 1;
      }

      const drift = reduce ? 0 : 1;
      for (let i = 0; i < N; i++) {
        const isBoard = comp[i] === BOARD;
        const isHit = focused >= 0 && comp[i] === focused;
        let tx = hx[i], ty = hy[i], tA;
        if (isBoard) {
          if (focused < 0) {
            // idle: the board flows with the rest of the cloud
            if (drift) { tx += Math.cos(oa[i] + t * sp[i]) * orad[i]; ty += Math.sin(oa[i] + t * sp[i]) * orad[i]; }
            tA = ba[i] * 0.72;
          } else {
            tA = ba[i];                                 // fixed + crisp while a person is focused
          }
        } else if (isHit) {
          // revealed person: dots pull home and thin out as the photo comes up,
          // leaving a light shimmer of particles over the real image
          if (drift) { tx += Math.cos(t * 2.1 + oa[i]) * 2.7; ty += Math.sin(t * 2.1 + oa[i]) * 2.7; }
          tA = Math.min(1, ba[i] * 1.1) * (1 - revealA * 0.72);
        } else if (focused >= 0) {
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
        // Divide by the camera scale so dots keep a constant on-screen size
        // while the camera pushes in.
        const sz = (isBoard ? 2.5 : isHit ? 2.4 : 2.2) * invS;
        ctx.fillRect(px[i], py[i], sz, sz);
      }
      ctx.globalAlpha = 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    img.onload = () => { build(); cancelAnimationFrame(raf); tick(); };
    img.src = src;

    // Mouse/pen: hover previews a person. Touch never reports hover.
    const onMove = (e) => {
      if (e.pointerType === "touch") return;
      const i = hitTest(e.clientX, e.clientY);
      canvas.style.cursor = i != null ? "pointer" : "default";
      cbRef.current.onHover?.(i);
    };
    const onLeave = (e) => {
      if (e.pointerType === "touch") return;
      cbRef.current.onHover?.(null);
    };
    // Tap/click on a person selects them; on empty space or the board it clears.
    // This is the primary mechanism on touch, and a way to pin on a mouse.
    const onDown = (e) => {
      cbRef.current.onSelect?.(hitTest(e.clientX, e.clientY));
    };
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerleave", onLeave);
    canvas.addEventListener("pointerdown", onDown);

    let rt = 0;
    const onResize = () => {
      clearTimeout(rt);
      rt = setTimeout(() => { if (img.complete && img.naturalWidth) build(); }, 160);
    };
    window.addEventListener("resize", onResize);
    window.addEventListener("scroll", reportLayout, { passive: true });

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(rt);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerleave", onLeave);
      canvas.removeEventListener("pointerdown", onDown);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("scroll", reportLayout);
    };
  }, [src, boardTop, target, disperse, bands]);

  return (
    <canvas
      ref={canvasRef}
      className={className}
      /* `manipulation` (not `none`) keeps taps working while still letting the
         page scroll when the canvas is a block in a scrollable mobile layout. */
      style={{ width: "100%", height: "100%", display: "block", touchAction: "manipulation" }}
    />
  );
}
