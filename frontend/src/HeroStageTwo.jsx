import { useEffect, useRef } from "react";
import {
  PipelineSection,
  VideoSection
} from "./HeroSections.jsx";
import { HeroFinale } from "./HeroFinale.jsx";
import { useScrollProgress } from "./useScrollProgress.js";

const PIPELINE_START = 0.00;
const PIPELINE_END = 0.16;
const VIDEO_START = 0.16;
const VIDEO_END = 0.62;
const FORM_START = 0.62;
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

  // /#contact — the site's single intake, targeted by every product CTA —
  // anchors on the finale formwrap, whose static position is the TOP of this
  // 340vh stage (progress ≈ 0, where --form-p is 0 and the form is still
  // visibility:hidden). Land hash arrivals at the END of the stage's travel
  // instead: that is where --form-p reaches 1 and the form is actually
  // visible. Covers full-page arrivals (mount) and in-page hash changes.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const scrollToForm = () => {
      const el = ref.current;
      if (!el) return;
      // Document-space stage top: offsetTop would be relative to the
      // positioned .scroll-hero ancestor, not the page.
      const stageTop = window.scrollY + el.getBoundingClientRect().top;
      // "instant" overrides the global scroll-behavior:smooth — a deep link
      // should land, not animate through nine viewports of hero.
      window.scrollTo({
        top: stageTop + el.offsetHeight - window.innerHeight,
        behavior: "instant"
      });
    };
    const onHashContact = () => {
      if (window.location.hash === "#contact") scrollToForm();
    };
    // Correct once after mount and once more at load: the browser retries its
    // own fragment scroll (to the broken static anchor position) while the
    // document is still loading.
    const raf = requestAnimationFrame(onHashContact);
    window.addEventListener("load", onHashContact);
    window.addEventListener("hashchange", onHashContact);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("load", onHashContact);
      window.removeEventListener("hashchange", onHashContact);
    };
  }, []);

  useEffect(() => {
    let raf = 0;
    // Everything written below derives from (p, reduce) — an unchanged pair
    // means identical output, so skip the style writes and keep the loop
    // cheap while the page idles between scrolls.
    let lastP = -1;
    let lastReduce = null;
    const tick = () => {
      const el = ref.current;
      if (el) {
        const p = clamp01(progressRef.current);
        const reduce = reducedRef.current;
        if (p === lastP && reduce === lastReduce) {
          raf = requestAnimationFrame(tick);
          return;
        }
        lastP = p;
        lastReduce = reduce;
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
