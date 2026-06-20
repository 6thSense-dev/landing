import { useEffect, useRef } from "react";
import {
  PipelineSection,
  VideoSection
} from "./HeroSections.jsx";
import { HeroFinale } from "./HeroFinale.jsx";
import { useScrollProgress } from "./useScrollProgress.js";

const PIPELINE_START = 0.00;
const PIPELINE_END = 0.27;
const VIDEO_START = 0.27;
const VIDEO_END = 0.55;
const FORM_START = 0.55;
const FORM_END = 1.00;

const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);

function usePrefersReducedMotion() {
  const ref = useRef(false);
  useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const sync = () => { ref.current = mq.matches; };
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);
  return ref;
}

/**
 * Hero Stage 2 — the second sticky scroll stage.
 *
 * Hosts pipeline → video → finale-form. Publishes its own --pipeline-p,
 * --video-p, --form-p as scroll progresses through this stage. Also pins
 * --assemble-fade-p / --assemble-move-p to 1 so HeroFinale's dot rules
 * (which read those vars) render in their final state without depending on
 * cross-stage CSS variable inheritance.
 */
export function HeroStageTwo() {
  const ref = useRef(null);
  const progressRef = useScrollProgress(ref);
  const reducedRef = usePrefersReducedMotion();

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const el = ref.current;
      if (el) {
        const p = clamp01(progressRef.current);
        const reduce = reducedRef.current;
        const windowP = (start, end) => (p >= start && p < end ? 1 : 0);
        const pipelineP = windowP(PIPELINE_START, PIPELINE_END);
        const videoP = windowP(VIDEO_START, VIDEO_END);
        const formP = reduce
          ? (p >= FORM_START ? 1 : 0)
          : clamp01((p - FORM_START) / (FORM_END - FORM_START));

        el.style.setProperty("--pipeline-p", pipelineP.toFixed(4));
        el.style.setProperty("--video-p", videoP.toFixed(4));
        el.style.setProperty("--form-p", formP.toFixed(4));
        // A11y: only let the finale form take keyboard focus / pointer events
        // once it is actually visible (CSS gates on .hero-form-active).
        el.classList.toggle("hero-form-active", formP > 0.5);
        el.style.setProperty("--assemble-fade-p", "1");
        el.style.setProperty("--assemble-move-p", "1");
        document.body.style.setProperty("--video-p", videoP.toFixed(4));
        document.body.classList.toggle("hero-video-active", videoP > 0.5);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      document.body.style.removeProperty("--video-p");
      document.body.classList.remove("hero-video-active");
    };
  }, [progressRef, reducedRef]);

  return (
    <div className="hero-stage hero-stage-two" ref={ref}>
      <div className="hero-stage-sticky">
        <PipelineSection />
        <VideoSection />
        <HeroFinale />
      </div>
    </div>
  );
}
