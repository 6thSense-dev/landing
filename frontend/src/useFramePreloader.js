import { useEffect, useRef, useState } from "react";

// Phones get down-scaled, lossy copies of the frame sequence (the originals are
// lossless WebP, ~900KB each). Variants are sized to the PAINTED size, not the
// viewport: ScrollStage zooms the glove ~2.6x on phones, so a 390px viewport
// paints the sequence ~2000 device px wide.
//
// Resizing is geometry-safe. computePaintRect scales by min(cw/iw, ch/ih) and
// then multiplies back by iw/ih, so a proportional resize cancels out and every
// anchor constant in ScrollStage keeps its meaning.
const MOBILE_MAX_W = 720;   // keep in sync with ScrollStage's MOBILE_MAX_W

function variantDir() {
  if (typeof window === "undefined") return "";
  if (window.innerWidth >= MOBILE_MAX_W) return "";       // desktop: originals
  const saveData = navigator.connection?.saveData === true;
  const dpr = window.devicePixelRatio || 1;
  return saveData || dpr < 1.5 ? "/w1100" : "/w2000";
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
      const count = stage.frameCount;
      const arr = await Promise.all(
        Array.from({ length: count }, (_, i) => loadImage(framePath(stage, i, variant)))
      );
      if (cancelled || !aliveRef.current) return;
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
