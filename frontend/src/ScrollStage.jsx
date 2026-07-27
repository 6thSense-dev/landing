import { useEffect, useRef } from "react";
import { scrollStages } from "./scrollStages.js";
import { useFramePreloader } from "./useFramePreloader.js";

// Scroll-progress phase boundaries within Stage 1's ~300vh budget.
// Counting plays over the first 85% of stage 1; assemble (glove descend +
// dots fade) plays over the remaining 15%. Stage 1 owns ONLY these two
// phases — quotes / pipeline / video / form moved to QuoteTimeline and
// HeroStageTwo.
const FRAMES_END = 0.85;
const ASSEMBLE_START = 0.85;
const ASSEMBLE_END = 1.00;

// Glove canvas layout. Tip-anchored: each frame's highest visible image point
// (PIVOT_U, PER_FRAME_TIP_V[i]) is painted at viewport (PIVOT_X, PER_FRAME_TIP_Y[i]),
// so the asymmetry between the bulky fist and the tall extended-finger poses
// scales with viewport on every screen size.
const GLOVE_ZOOM_BASE = 1.8;    // base paint-time zoom (desktop)
const GLOVE_PIVOT_U = 0.5;      // image horizontal center (all frames ~= 0.5)
const GLOVE_PIVOT_X = 0.30;     // viewport x (fraction of cw)

// Mobile/portrait override: recenter horizontally and bump zoom so the hand
// fills the narrow viewport instead of sitting in a side column.
const MOBILE_MAX_W = 720;
const GLOVE_PIVOT_X_MOBILE = 0.5;
const GLOVE_ZOOM_BASE_MOBILE = 2.6;

function isMobileViewport(cw) {
  return cw < MOBILE_MAX_W;
}

function pivotsFor(cw) {
  if (isMobileViewport(cw)) {
    return {
      pivotX: GLOVE_PIVOT_X_MOBILE,
      zoomBase: GLOVE_ZOOM_BASE_MOBILE
    };
  }
  return {
    pivotX: GLOVE_PIVOT_X,
    zoomBase: GLOVE_ZOOM_BASE
  };
}
// v-coord of each frame's highest visible point. Frames 1–5 extend a finger
// to ~v=0.042 (matches HeroFinale's middle-finger tip dot); frame 0 is a fist
// whose top knuckle sits ~v=0.10.
const PER_FRAME_TIP_V = [0.10, 0.042, 0.042, 0.042, 0.042, 0.042];
// Viewport y fraction where each frame's tip is anchored. Bias the bulky
// fist a touch below center and the extended-finger poses a touch above
// center so the fist body settles into view and the finger reads as
// "reaching up" rather than dipping.
const PER_FRAME_TIP_Y = [0.58, 0.15, 0.15, 0.15, 0.15, 0.15];
// Per-frame zoom multiplier (fist was generated bigger than extended poses).
const PER_FRAME_ZOOM = [0.75, 1.0, 1.0, 1.0, 1.0, 1.0];

// Narrative beat → asset index. The hand transition plays asset frames in
// this order: pointy, +middle, +ring, +pinky, +thumb / open palm. The fist
// asset (index 0) is never painted here, and is no longer even fetched — see
// paintedIndices in scrollStages.js and the note on tipYForFrame().
// Keep this in sync with paintedIndices: a beat pointing at an asset the
// preloader was not told to fetch paints nothing.
const BEAT_TO_ASSET = [1, 2, 3, 4, 5];

// ── Mobile micro-tune knobs ────────────────────────────────────────────────
// Each is a viewport y fraction (0 = top, 1 = bottom) that locks the
// corresponding pose's tip anchor on mobile (cw < MOBILE_MAX_W). Set `null`
// to let the auto-alignment in tipYForFrame() run (which anchors the bottom
// of extended-finger frames to the bottom of the fist for a consistent
// wrist-cuff line).
//
//   MOBILE_FIST_TIP_Y      → frame 0 (fist)
//   MOBILE_EXTENDED_TIP_Y  → frames 1-5 (one through five fingers extended)
//
// Both are fractions of ch, so the responsiveness across phone sizes is
// preserved — only the y-position within the viewport changes.
const MOBILE_FIST_TIP_Y = null;
const MOBILE_EXTENDED_TIP_Y = null;
// ───────────────────────────────────────────────────────────────────────────

function usePrefersReducedMotion() {
  const ref = useRef(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => {
      ref.current = mq.matches;
    };
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return ref;
}

// Computes the destination rect (in canvas pixels) the image paints into.
// Tip-anchored: image point (PIVOT_U, tipV) lands at viewport (PIVOT_X, tipY).
function computePaintRect(iw, ih, cw, ch, zoom, tipV, tipY) {
  const { pivotX } = pivotsFor(cw);
  const scale = Math.min(cw / iw, ch / ih) * zoom;
  const dw = iw * scale;
  const dh = ih * scale;
  const dx = pivotX * cw - GLOVE_PIVOT_U * dw;
  const dy = tipY * ch - tipV * dh;
  return { dx, dy, dw, dh };
}

// Mobile-only tipY override: anchors the BOTTOM of each extended-finger frame
// (1..5) to the bottom of the fist (frame 0) so the wrist-cuff line reads
// consistently across poses on phones (where the fist's cuff sits in view but
// the taller extended-finger poses otherwise spill past the viewport bottom).
// Returns the default tipY on desktop or for the fist itself.
//
// This needs the fist's PAINTED HEIGHT, not the fist's pixels. Every frame in a
// tier is rendered on the same canvas (2752x1536 full, 1100x614 w1100), so the
// fist's intrinsic size — and therefore its min(cw/iw, ch/ih) scale factor — is
// the current frame's. The only thing that differs between the two is
// PER_FRAME_ZOOM. So dhFist is derived from `img` and the fist frame itself
// never has to be downloaded. If the frames ever stop sharing a canvas size,
// this collapses and dhFist must go back to measuring frame 0 directly.
function tipYForFrame(idx, cw, ch, img) {
  const defaultTipY = PER_FRAME_TIP_Y[idx] ?? 0.5;
  if (!isMobileViewport(cw)) return defaultTipY;
  // Honor explicit mobile overrides first. Only fall through to the
  // auto-alignment below when the override is null.
  if (idx === 0 && MOBILE_FIST_TIP_Y !== null) return MOBILE_FIST_TIP_Y;
  if (idx !== 0 && MOBILE_EXTENDED_TIP_Y !== null) return MOBILE_EXTENDED_TIP_Y;
  if (idx === 0 || !img?.naturalWidth) {
    return defaultTipY;
  }
  const { zoomBase } = pivotsFor(cw);
  const scale = Math.min(cw / img.naturalWidth, ch / img.naturalHeight);
  const dhFist = img.naturalHeight * scale * zoomBase * (PER_FRAME_ZOOM[0] ?? 1);
  const dhCur = img.naturalHeight * scale * zoomBase * (PER_FRAME_ZOOM[idx] ?? 1);
  const tipVFist = PER_FRAME_TIP_V[0] ?? 0.1;
  const tipVCur = PER_FRAME_TIP_V[idx] ?? 0.042;
  const tipYFist = PER_FRAME_TIP_Y[0] ?? 0.58;
  // bottom_fist = tipYFist*ch + (1 - tipVFist)*dhFist
  // Solve for tipYCur such that bottom_cur == bottom_fist.
  return tipYFist + ((1 - tipVFist) * dhFist - (1 - tipVCur) * dhCur) / ch;
}

function paintAnchored(ctx, img, cw, ch, alpha, zoom, tipV, tipY) {
  if (!img || !img.complete || !img.naturalWidth) return;
  const { dx, dy, dw, dh } = computePaintRect(
    img.naturalWidth, img.naturalHeight, cw, ch, zoom, tipV, tipY
  );
  const prev = ctx.globalAlpha;
  ctx.globalAlpha = alpha;
  ctx.drawImage(img, dx, dy, dw, dh);
  ctx.globalAlpha = prev;
}

const clamp01 = (v) => Math.max(0, Math.min(1, v));

export function ScrollStage({ progressRef, heroRef }) {
  const canvasRef = useRef(null);
  const reducedRef = usePrefersReducedMotion();
  const s0 = useFramePreloader(scrollStages[0], true);

  const writeVars = (vars) => {
    const root = heroRef.current;
    if (!root) return;
    for (const [k, v] of Object.entries(vars)) {
      root.style.setProperty(k, v);
    }
  };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const publishGloveRect = (w, h) => {
      const frames = s0.frames;
      if (!frames) return;
      // Dots are measured in the open-hand frame (index 5) — publish its rect.
      const refIdx = 5;
      const ref = frames[refIdx];
      if (!ref || !ref.naturalWidth) return;
      const { zoomBase } = pivotsFor(w);
      const refZoom = zoomBase * (PER_FRAME_ZOOM[refIdx] ?? 1);
      const refTipV = PER_FRAME_TIP_V[refIdx] ?? 0.042;
      // Use the same mobile-adjusted tipY as the paint loop so the dots-at-
      // fingertips CSS vars track the shifted glove position.
      const refTipY = tipYForFrame(refIdx, w, h, ref);
      const { dx, dy, dw, dh } = computePaintRect(
        ref.naturalWidth, ref.naturalHeight, w, h, refZoom, refTipV, refTipY
      );
      writeVars({
        "--glove-x": `${(dx / w * 100).toFixed(3)}%`,
        "--glove-y": `${(dy / h * 100).toFixed(3)}%`,
        "--glove-w": `${(dw / w * 100).toFixed(3)}%`,
        "--glove-h": `${(dh / h * 100).toFixed(3)}%`
      });
    };

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
      publishGloveRect(w, h);
    };
    resize();
    window.addEventListener("resize", resize);

    let raf = 0;
    const tick = () => {
      const p = clamp01(progressRef.current);
      const reduce = reducedRef.current;

      // Frame-sequence progress — counting plays over 0..FRAMES_END.
      const framesP = clamp01(p / FRAMES_END);

      // ---- Paint canvas: snap to nearest beat (no crossfade) ----
      const cw = canvas.clientWidth;
      const ch = canvas.clientHeight;
      ctx.clearRect(0, 0, cw, ch);

      const beatCount = BEAT_TO_ASSET.length;
      const beatIdx = Math.round(framesP * (beatCount - 1));

      if (s0.frames) {
        const frames = s0.frames;
        const count = frames.length;

        const { zoomBase } = pivotsFor(cw);
        const zoomFor = (idx) =>
          zoomBase * (PER_FRAME_ZOOM[idx] ?? 1);

        // Snap to the nearest narrative beat — no crossfade between adjacent
        // frames. BEAT_TO_ASSET maps narrative position (0..4) to the actual
        // asset on disk so the per-frame anchor arrays (indexed by asset)
        // can stay untouched.
        const assetIdx = BEAT_TO_ASSET[beatIdx];
        paintAnchored(
          ctx, frames[assetIdx], cw, ch, 1,
          zoomFor(assetIdx),
          PER_FRAME_TIP_V[assetIdx] ?? 0.042,
          tipYForFrame(assetIdx, cw, ch, frames[assetIdx])
        );
      }

      // ---- Assemble phase: dots fade in at fingertips first, then move
      //      while hand descends off-screen ----
      const assembleP = reduce
        ? (p >= ASSEMBLE_START ? 1 : 0)
        : clamp01((p - ASSEMBLE_START) / (ASSEMBLE_END - ASSEMBLE_START));
      // Sub-phases:
      //   0.0 → 0.3  fade:  dots materialize at fingertips, glove stationary
      //   0.3 → 1.0  move:  dots drift to logo, glove descends simultaneously
      const assembleFadeP = clamp01(assembleP / 0.3);
      const assembleMoveP = clamp01((assembleP - 0.3) / 0.7);
      const handDescendVh = assembleMoveP * 110;

      // Blurb data-indexes match narrative beats (0..4). 5 is a sentinel
      // value with no matching CSS rule — assigned during assemble so all
      // blurbs fade to opacity 0 once the counting phase ends.
      let blurb;
      if (p >= ASSEMBLE_START) blurb = 5;
      else if (s0.frames) blurb = beatIdx;
      else blurb = 0;

      writeVars({
        "--stop-progress": p.toFixed(4),
        "--frames-p": framesP.toFixed(4),
        "--assemble-p": assembleP.toFixed(4),
        "--assemble-fade-p": assembleFadeP.toFixed(4),
        "--assemble-move-p": assembleMoveP.toFixed(4),
        "--hand-descend": `${handDescendVh.toFixed(2)}vh`,
        "--active-blurb": String(blurb)
      });

      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s0.ready]);

  return <canvas ref={canvasRef} className="scroll-stage-canvas" aria-hidden="true" />;
}
