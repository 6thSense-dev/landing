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

/* Demo clips cycle in order, fading out at the end of each and fading the
   next one in. All play within the same frame — object-fit:contain handles
   any aspect-ratio differences. */
const VIDEO_CLIPS = ["/demo.mp4", "/demo-box.mp4", "/demo-hammer.mp4", "/demo-shoe.mp4"];
const FADE_MS = 450;

export function VideoSection() {
  const videoRef = useRef(null);
  const indexRef = useRef(0);
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

    /* End of a clip: fade out, swap source while invisible, fade back in. */
    let fadeTimer = 0;
    const onEnded = () => {
      v.style.opacity = "0";
      fadeTimer = window.setTimeout(() => {
        indexRef.current = (indexRef.current + 1) % VIDEO_CLIPS.length;
        v.src = VIDEO_CLIPS[indexRef.current];
        v.load();
        if (document.body.classList.contains("hero-video-active")) tryPlay();
      }, FADE_MS);
    };
    const onPlaying = () => {
      v.style.opacity = "1";
    };
    v.addEventListener("ended", onEnded);
    v.addEventListener("playing", onPlaying);

    /* Play only while the video beat is the active scroll section. */
    const sync = () => {
      const active = document.body.classList.contains("hero-video-active");
      if (active && v.paused) tryPlay();
      else if (!active && !v.paused) v.pause();
    };

    sync();

    if (typeof MutationObserver === "undefined") {
      tryPlay();
      return () => {
        window.clearTimeout(fadeTimer);
        v.removeEventListener("ended", onEnded);
        v.removeEventListener("playing", onPlaying);
      };
    }
    const mo = new MutationObserver(sync);
    mo.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    return () => {
      mo.disconnect();
      window.clearTimeout(fadeTimer);
      v.removeEventListener("ended", onEnded);
      v.removeEventListener("playing", onPlaying);
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
          src={VIDEO_CLIPS[0]}
          poster="/demo-poster.jpg"
          muted
          playsInline
          preload="metadata"
          aria-label="6thSense tactile capture demos"
        />
      </div>
    </section>
  );
}
