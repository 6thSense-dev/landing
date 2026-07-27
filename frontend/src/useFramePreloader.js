import { useEffect, useRef, useState } from "react";

// The checked-in frame-XXX.webp files are LOSSY q92 at full 2752x1536 (~330KB
// each). The lossless masters they were encoded from live only in git history:
//
//   git show a53cd6a:frontend/public/hero/glove/frame-000.webp
//
// Anything that needs to re-derive a variant should start from those, not from
// the checked-in files, to avoid stacking generations of lossy encoding.
//
// Tiering: full resolution is the default everywhere, including phones. A phone
// paints the glove ~2028 device px wide (ScrollStage zooms it ~2.6x, so the
// viewport width is not the painted width), and a down-scaled tier measurably
// softens the fabric weave and grip diamonds — 9.74/255 mean error over visible
// pixels vs 1.50/255 for full-res lossy. Only low-DPR phones, which paint about
// half that, and explicit saveData get the small tier.
//
// Down-scaling is geometry-safe when it is used: computePaintRect scales by
// min(cw/iw, ch/ih) and then multiplies back by iw/ih, so a proportional resize
// cancels out and every anchor constant in ScrollStage keeps its meaning.
const MOBILE_MAX_W = 720;   // keep in sync with ScrollStage's MOBILE_MAX_W

function variantDir() {
  if (typeof window === "undefined") return "";
  if (window.innerWidth >= MOBILE_MAX_W) return "";       // desktop + tablet
  const saveData = navigator.connection?.saveData === true;
  const dpr = window.devicePixelRatio || 1;
  return saveData || dpr < 1.5 ? "/w1100" : "";
}

function framePath(stage, index, variant) {
  const padded = String(index).padStart(3, "0");
  return `${stage.frameDir}${variant}/frame-${padded}.webp`;
}

const cache = new Map();

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.decoding = "async";
    img.onload = () => resolve(img);
    img.onerror = () => resolve(img);
    img.src = src;
  });
}

// Loads a stage's frame sequence (flat layout: stage.frameDir/frame-XXX.webp).
// Results are cached in module scope so re-mounts are free.
export function useFramePreloader(stage, enabled) {
  const [ready, setReady] = useState(false);
  const [frames, setFrames] = useState(null);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    if (!enabled || !stage) {
      setReady(false);
      setFrames(null);
      return () => {
        aliveRef.current = false;
      };
    }

    // The variant is part of the identity of a cached sequence — keying on the
    // stage alone would hand a phone the desktop frames (or vice versa) after a
    // remount at a different width.
    const variant = variantDir();
    const cacheKey = `${stage.id}${variant}`;
    const cached = cache.get(cacheKey);
    if (cached?.ready) {
      setFrames(cached.frames);
      setReady(true);
      return () => {
        aliveRef.current = false;
      };
    }

    let cancelled = false;
    (async () => {
      // Only fetch the frames the stage actually paints. The returned array is
      // still frameCount long and still indexed by ASSET index — unpainted
      // slots stay null — because ScrollStage's per-frame constant arrays are
      // keyed that way. Callers already null-guard each frame before drawing.
      const indices = stage.paintedIndices
        ?? Array.from({ length: stage.frameCount }, (_, i) => i);
      const loaded = await Promise.all(
        indices.map((i) => loadImage(framePath(stage, i, variant)))
      );
      if (cancelled || !aliveRef.current) return;
      const arr = new Array(stage.frameCount).fill(null);
      indices.forEach((assetIdx, k) => { arr[assetIdx] = loaded[k]; });
      cache.set(cacheKey, { ready: true, frames: arr });
      setFrames(arr);
      setReady(true);
    })();

    return () => {
      cancelled = true;
      aliveRef.current = false;
    };
  }, [stage?.id, enabled]);

  return { ready, frames };
}
