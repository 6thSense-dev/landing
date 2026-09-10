// frontend/src/TactileField.jsx
// Mounts the constellation background behind the hero content. Drives resize,
// pointer state, and a reduced-motion flag. Falls back to transparent (black
// hero background stays visible) if the 2D context is unavailable.

import { useEffect, useRef } from "react";
import { initTactileField } from "./tactileField.js";

const POINTER_FADE_MS = 200;

export function TactileField() {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const field = initTactileField(canvas);
    if (!field) {
      if (typeof console !== "undefined") {
        console.warn("TactileField: 2D context unavailable, skipping effect.");
      }
      return;
    }

    // Reduced-motion gate freezes the field: the rAF loop below never starts
    // and a single static frame paints instead (tactileField.js drops drift,
    // bob, and twinkle when reduced — a full-viewport background that keeps
    // moving is exactly what the preference asks to avoid). The listener at
    // the bottom starts/stops the loop live if the OS preference changes.
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    field.setReduced(mq.matches);
    const renderStatic = () => {
      field.setPointer(-9999, -9999, 0);
      field.render(0);
    };

    // Size tracking. Module handles DPR internally. While reduced, repaint the
    // static frame here — resizing the canvas buffer clears it and no loop is
    // running to repaint it.
    const resize = () => {
      field.setSize();
      if (mq.matches) renderStatic();
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    // Pointer state in CSS pixels relative to the canvas.
    let pointerX = -9999, pointerY = -9999;
    let targetPressure = 0;
    let currentPressure = 0;

    const handlePointer = (e) => {
      const rect = canvas.getBoundingClientRect();
      pointerX = e.clientX - rect.left;
      pointerY = e.clientY - rect.top;
      // Drive the node-enlargement pressure whenever the pointer is over the
      // hero region. Native cursor still shows; the field just lights up where
      // the pointer is.
      const inHero = !!(e.target && e.target.closest && e.target.closest(".scroll-hero"));
      targetPressure = inHero ? 1 : 0;
    };
    const handleLeave = () => { targetPressure = 0; };

    window.addEventListener("pointermove", handlePointer, { passive: true });
    window.addEventListener("pointerleave", handleLeave);
    window.addEventListener("pointercancel", handleLeave);

    // Render loop.
    const start = performance.now();
    let raf = 0;
    const tick = (now) => {
      const t = (now - start) / 1000;
      // Exponential ease toward targetPressure with ~200 ms half-life.
      const dt = Math.min(0.05, (now - (tick._last ?? now)) / 1000);
      tick._last = now;
      const k = 1 - Math.exp(-dt * (1000 / POINTER_FADE_MS) * Math.LN2);
      currentPressure += (targetPressure - currentPressure) * k;
      field.setPointer(pointerX, pointerY, currentPressure);
      field.render(t);
      raf = requestAnimationFrame(tick);
    };
    const applyMotionPreference = () => {
      field.setReduced(mq.matches);
      cancelAnimationFrame(raf);
      if (mq.matches) renderStatic();
      else raf = requestAnimationFrame(tick);
    };
    applyMotionPreference();
    mq.addEventListener("change", applyMotionPreference);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      mq.removeEventListener("change", applyMotionPreference);
      window.removeEventListener("pointermove", handlePointer);
      window.removeEventListener("pointerleave", handleLeave);
      window.removeEventListener("pointercancel", handleLeave);
      field.dispose();
    };
  }, []);

  return <canvas ref={canvasRef} className="tactile-field" aria-hidden="true" />;
}
