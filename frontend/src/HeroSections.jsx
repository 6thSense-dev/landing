/**
 * Scrubbed beats inside HeroStageTwo's sticky window. Each is a positioned-
 * absolute layer gated by its own progress var written by HeroStageTwo's
 * rAF tick.
 *
 *   --pipeline-p   → PipelineSection
 *   --video-p      → VideoSection
 */

import { useEffect, useRef, useState } from "react";

export function PipelineSection() {
  return (
    <section className="hero-section hero-pipeline">
      <h2 className="hero-pipeline-title">
        We label tactile data end&nbsp;to&nbsp;end.
      </h2>
      <ol className="hero-pipeline-row">
        <li>Collect</li>
        <li>Synchronize</li>
        <li>Label</li>
        <li>Validate</li>
        <li>Ship</li>
      </ol>
    </section>
  );
}

/* Primary product demo — loops while the video beat is on-screen. */
const DEMO_VIDEO = "/demo.mp4";

export function VideoSection() {
  const videoRef = useRef(null);
  const [reduceMotion] = useState(() =>
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const v = videoRef.current;
    if (!v) return;

    if (reduceMotion) {
      v.pause();
      return;
    }

    const tryPlay = () => {
      const p = v.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    };

    /* Play only while the video beat is the active scroll section, and pause
       otherwise — the section stays mounted at opacity:0 during the pipeline
       and form beats, so without this the browser keeps decoding frames behind
       a hidden layer (wasted CPU/battery, worst on mobile). HeroStageTwo
       toggles `hero-video-active` on <body> as this beat enters/leaves; we
       mirror that into play/pause. Calling play() at the moment the beat
       becomes active also satisfies mobile autoplay, which can reject play()
       issued while the element sits inside an opacity:0 ancestor. */
    const sync = () => {
      const active = document.body.classList.contains("hero-video-active");
      if (active && v.paused) tryPlay();
      else if (!active && !v.paused) v.pause();
    };

    sync();
    if (typeof MutationObserver === "undefined") {
      tryPlay();
      return undefined;
    }
    const mo = new MutationObserver(sync);
    mo.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    return () => {
      mo.disconnect();
    };
  }, [reduceMotion]);

  return (
    <section id="demo" className="hero-section hero-video" aria-label="Demo video">
      <h2 className="hero-video-kicker">See it in action</h2>
      <p className="hero-video-lead">
        Tactile egocentric capture from the 6thSense rig — synchronized video and touch.
      </p>
      <div className="hero-video-frame">
        <video
          ref={videoRef}
          className="hero-video-media"
          src={DEMO_VIDEO}
          poster="/demo-poster.jpg"
          muted
          playsInline
          loop
          preload="metadata"
          aria-label="6thSense tactile capture demo"
        />
      </div>
    </section>
  );
}
