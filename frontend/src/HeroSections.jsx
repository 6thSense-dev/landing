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

const DEMO_VIDEO = "/demo.mp4";
const CYCLING_CLIPS = ["/demo-box.mp4", "/demo-hammer.mp4", "/demo-shoe.mp4"];
const FADE_MS = 450;

export function VideoSection() {
  const demoRef = useRef(null);
  const clipsRef = useRef(null);
  const indexRef = useRef(0);
  const [reduceMotion] = useState(() =>
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    const dv = demoRef.current;
    const cv = clipsRef.current;
    if (!dv || !cv) return;

    if (reduceMotion) {
      dv.pause();
      cv.pause();
      return;
    }

    const tryPlay = (v) => {
      const p = v.play();
      if (p && typeof p.catch === "function") p.catch(() => {});
    };

    /* Cycling clips: fade out, swap source, fade back in. */
    let fadeTimer = 0;
    const onEnded = () => {
      cv.style.opacity = "0";
      fadeTimer = window.setTimeout(() => {
        indexRef.current = (indexRef.current + 1) % CYCLING_CLIPS.length;
        cv.src = CYCLING_CLIPS[indexRef.current];
        cv.load();
        if (document.body.classList.contains("hero-video-active")) tryPlay(cv);
      }, FADE_MS);
    };
    const onPlaying = () => { cv.style.opacity = "1"; };
    cv.addEventListener("ended", onEnded);
    cv.addEventListener("playing", onPlaying);

    /* Both players play/pause together with the scroll beat. */
    const sync = () => {
      const active = document.body.classList.contains("hero-video-active");
      [dv, cv].forEach((v) => {
        if (active && v.paused) tryPlay(v);
        else if (!active && !v.paused) v.pause();
      });
    };

    sync();

    if (typeof MutationObserver === "undefined") {
      tryPlay(dv);
      tryPlay(cv);
      return () => {
        window.clearTimeout(fadeTimer);
        cv.removeEventListener("ended", onEnded);
        cv.removeEventListener("playing", onPlaying);
      };
    }
    const mo = new MutationObserver(sync);
    mo.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    return () => {
      mo.disconnect();
      window.clearTimeout(fadeTimer);
      cv.removeEventListener("ended", onEnded);
      cv.removeEventListener("playing", onPlaying);
    };
  }, [reduceMotion]);

  return (
    <section id="demo" className="hero-section hero-video" aria-label="Demo video">
      <h2 className="hero-video-kicker">See it in action</h2>
      <p className="hero-video-lead">
        Tactile egocentric capture from the 6thSense rig — synchronized video and touch.
      </p>
      <div className="hero-video-row">
        <div className="hero-video-frame">
          <video
            ref={demoRef}
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
        <div className="hero-video-frame">
          <video
            ref={clipsRef}
            className="hero-video-media"
            src={CYCLING_CLIPS[0]}
            muted
            playsInline
            preload="metadata"
            aria-label="6thSense tactile capture demos: box, hammer, and shoe"
          />
        </div>
      </div>
    </section>
  );
}
