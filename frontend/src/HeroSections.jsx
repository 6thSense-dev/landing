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

    /* On mobile, autoplay can silently fail when the video element is rendered
       inside an opacity:0 ancestor (the hero section is gated by --video-p).
       Retry play() whenever the video element actually enters the viewport —
       mobile Safari/Chrome accept play() calls in that context. */
    const tryPlay = () => {
      const p = v.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    };

    tryPlay();

    if (typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && v.paused) tryPlay();
        }
      },
      { threshold: 0.01 },
    );
    io.observe(v);
    return () => io.disconnect();
  }, [reduceMotion]);

  return (
    <section className="hero-section hero-video">
      <div className="hero-video-frame">
        <video
          ref={videoRef}
          className="hero-video-media"
          src="/Demo_1.mp4"
          poster="/Demo_1_poster.jpg"
          {...(reduceMotion ? {} : { autoPlay: true })}
          muted
          loop
          playsInline
          preload="auto"
          aria-label="Tactile sensor data preview"
        />
      </div>
    </section>
  );
}
