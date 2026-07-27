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
        The hardware that captures it, end&nbsp;to&nbsp;end.
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
/* Smaller re-encodes of the same footage (960px wide) for phones. Same content,
   lower resolution and bitrate — nothing is re-cut. */
const DEMO_VIDEO_MOBILE = "/demo-mobile.mp4";
const CYCLING_CLIPS_MOBILE = [
  "/demo-box-mobile.mp4",
  "/demo-hammer-mobile.mp4",
  "/demo-shoe-mobile.mp4",
];
const FADE_MS = 450;

/* Phones (and anyone asking for reduced data) get poster + explicit play instead
   of autoplay: the full demo is ~14MB, and autoplaying it on a scroll beat spent
   megabytes of someone's cellular data before they chose to watch anything. */
const MOBILE_MAX_W = 720;

function detectMeteredMedia() {
  if (typeof window === "undefined") return false;
  return window.innerWidth < MOBILE_MAX_W || navigator.connection?.saveData === true;
}

function useMeteredMedia() {
  const [metered, setMetered] = useState(detectMeteredMedia);
  useEffect(() => {
    const sync = () => setMetered(detectMeteredMedia());
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, []);
  return metered;
}

export function VideoSection() {
  const demoRef = useRef(null);
  const clipsRef = useRef(null);
  const indexRef = useRef(0);
  const metered = useMeteredMedia();
  const clips = metered ? CYCLING_CLIPS_MOBILE : CYCLING_CLIPS;
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
        indexRef.current = (indexRef.current + 1) % clips.length;
        cv.src = clips[indexRef.current];
        cv.load();
        // On metered media a finished clip means the viewer chose to watch, so
        // keep the reel going; otherwise follow the scroll beat.
        if (metered || document.body.classList.contains("hero-video-active")) tryPlay(cv);
      }, FADE_MS);
    };
    const onPlaying = () => { cv.style.opacity = "1"; };
    cv.addEventListener("ended", onEnded);
    cv.addEventListener("playing", onPlaying);

    /* Metered: never start playback from scroll, so nothing downloads until a
       tap. Cycling still works once the viewer starts the reel themselves. */
    if (metered) {
      return () => {
        window.clearTimeout(fadeTimer);
        cv.removeEventListener("ended", onEnded);
        cv.removeEventListener("playing", onPlaying);
      };
    }

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
  }, [reduceMotion, metered, clips]);

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
            src={metered ? DEMO_VIDEO_MOBILE : DEMO_VIDEO}
            poster={metered ? "/demo-poster-mobile.jpg" : "/demo-poster.jpg"}
            muted
            playsInline
            loop
            /* These clips are desktop-composited multi-pane dashboards. Squeezed
               into a phone-width frame the inner text is a few pixels tall, so
               expose controls (play + native fullscreen) rather than showing a
               smear with no way to inspect it. */
            controls={metered}
            preload={metered ? "none" : "metadata"}
            aria-label="6thSense tactile capture demo"
          />
        </div>
        <div className="hero-video-frame">
          <video
            ref={clipsRef}
            className="hero-video-media"
            src={clips[0]}
            poster={metered ? "/demo-clips-poster-mobile.jpg" : undefined}
            muted
            playsInline
            controls={metered}
            preload={metered ? "none" : "metadata"}
            aria-label="6thSense tactile capture demos: box, hammer, and shoe"
          />
        </div>
      </div>
    </section>
  );
}
