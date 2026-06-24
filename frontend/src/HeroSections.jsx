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

/* The three demo clips cycle in order, fading out at the end of each and
   fading the next one in. All share the same dimensions/aspect so the frame
   never reflows between them. */
const VIDEO_CLIPS = ["/demo-box.mp4", "/demo-hammer.mp4", "/demo-shoe.mp4"];
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

    /* End of a clip: fade the element out, swap in the next source while it's
       invisible (so the load/first-frame swap is never seen), then fade back in
       once the new clip has a frame ready to paint. */
    let fadeTimer = 0;
    const onEnded = () => {
      v.style.opacity = "0";
      fadeTimer = window.setTimeout(() => {
        indexRef.current = (indexRef.current + 1) % VIDEO_CLIPS.length;
        v.src = VIDEO_CLIPS[indexRef.current];
        v.load();
        // Only resume if the beat is still on-screen; otherwise leave the next
        // clip queued and let `sync` start it when the beat re-enters.
        if (document.body.classList.contains("hero-video-active")) tryPlay();
      }, FADE_MS);
    };
    const onPlaying = () => {
      v.style.opacity = "1";
    };
    v.addEventListener("ended", onEnded);
    v.addEventListener("playing", onPlaying);

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
    <section className="hero-section hero-video">
      <div className="hero-video-frame">
        <video
          ref={videoRef}
          className="hero-video-media"
          src={VIDEO_CLIPS[0]}
          poster="/demo-poster.jpg"
          muted
          playsInline
          preload="metadata"
          aria-label="6thSense tactile capture demos: box, hammer, and shoe"
        />
      </div>
    </section>
  );
}
