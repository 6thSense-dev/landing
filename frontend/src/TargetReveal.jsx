import { useEffect, useRef, useState } from "react";
import { motion, useAnimate, useReducedMotion } from "framer-motion";

const DEFAULT_ACCENT = "#c5e063";
const SEQUENCE_GAP_MS = 400;

/**
 * In-text slider reveal for a single target word/phrase inside a hero blurb.
 *
 * Choreography (re-runs each time the blurb at `blurbIndex` becomes active):
 *   wait order * 400ms (per-blurb sequencing)
 *   0.0 -> 0.25s   line draws in:  scaleY 0 -> 1, opacity 0 -> 1.
 *   0.25 -> 1.25s  slide + reveal: line left 0% -> 100% (ease-out, 1.0s);
 *                                   letters opacity 0 -> 1 with 80ms-per-
 *                                   letter stagger and 0.2s per-letter fade
 *                                   so the bar's leading edge stays close
 *                                   to the most-recently-revealed letter.
 *   1.25 -> 1.40s  line fades:     opacity 1 -> 0 at the right edge.
 *
 * Triggering: a MutationObserver on .hero-stage-one's style attribute
 * watches --active-blurb (written there by ScrollStage's rAF tick after the
 * three-block hero refactor). Each transition into String(blurbIndex)
 * increments playKey, which the animation effect uses as its dependency.
 *
 * The reveal starts the moment its blurb activates — no deferral for the
 * brand opener. On fresh tabs blurb 0's reveal plays behind the opener
 * overlay, which is the point: by the time the overlay fades (or is
 * skipped), the headline is already whole or actively filling in, never a
 * sentence parked with a hole in it.
 *
 * Reduced motion: returns plain text in the lime accent color, no line,
 * no observer, no animation.
 */
export function TargetReveal({ text, blurbIndex, order, color = DEFAULT_ACCENT }) {
  const prefersReducedMotion = useReducedMotion();
  const [scope, animate] = useAnimate();
  const [playKey, setPlayKey] = useState(0);

  const rootRef = useRef(null);
  const lineRef = useRef(null);
  const letterRefs = useRef([]);

  // Trigger detection: watch --active-blurb on the .hero-stage-one ancestor.
  useEffect(() => {
    if (prefersReducedMotion) return;
    const root = rootRef.current?.closest(".hero-stage-one");
    if (!root) return;

    const targetValue = String(blurbIndex);
    const readActive = () =>
      root.style.getPropertyValue("--active-blurb").trim() === targetValue;

    // Seed on mount if already active (blurb 0 on a fresh load).
    if (readActive()) setPlayKey((k) => k + 1);

    let wasActive = readActive();
    const obs = new MutationObserver(() => {
      const isActive = readActive();
      if (isActive && !wasActive) setPlayKey((k) => k + 1);
      wasActive = isActive;
    });
    obs.observe(root, { attributes: true, attributeFilter: ["style"] });

    return () => obs.disconnect();
  }, [prefersReducedMotion, blurbIndex]);

  // Animation timeline: re-runs whenever playKey increments.
  useEffect(() => {
    if (playKey === 0 || prefersReducedMotion) return;
    if (!lineRef.current) return;
    const letters = letterRefs.current.filter(Boolean);
    if (letters.length === 0) return;

    let cancelled = false;

    const run = async () => {
      // Snap to initial state via direct DOM writes — synchronous and
      // unambiguous. framer-motion's duration:0 animate has a subtle race
      // for target 0 (no order delay): the snap doesn't reliably paint
      // before Phase 1's animate starts, so Phase 1 reads stale post-
      // Phase-3 values (scaleY=1, left=100%, opacity=0) and degenerates
      // to a fade-only at the right edge of the word — the bar appears
      // not to reappear at all. Target 1's 1000ms order wait masks the
      // race. Direct style writes apply atomically.
      if (lineRef.current) {
        lineRef.current.style.left = "0%";
        lineRef.current.style.opacity = "0";
        lineRef.current.style.transform = "scaleY(0)";
      }
      letters.forEach((el) => {
        if (el) el.style.opacity = "0";
      });

      // Wait for our slot in the per-blurb sequence.
      if (order > 0) {
        await new Promise((r) => setTimeout(r, order * SEQUENCE_GAP_MS));
      }
      if (cancelled) return;

      // Combined timeline: vertical bar draw, horizontal bar slide, and
      // per-letter fade-ins all run on the same animate() call so each one's
      // START TIME is independently tunable via its `at:` value (absolute
      // seconds from the start of this timeline). Durations and easings
      // are unchanged — only start offsets are knobs.
      await animate([
        // Bar's vertical draw (scaleY 0→1). Anchored at t=0.
        [
          lineRef.current,
          { scaleY: 1, opacity: 1 },
          { duration: 0.0, ease: [0.16, 1, 0.3, 1], at: 0 },
        ],
        // Bar's horizontal slide (left 0%→100%). Tweak `at:` to control
        // when the slide STARTS:
        //   at: 0.5  → starts after the vertical draw completes (old behavior)
        //   at: 0    → starts at the same instant as the vertical draw
        //   at: 0.2  → starts 200ms into the vertical draw
        [
          lineRef.current,
          { left: "100%" },
          { duration: 1.0, ease: [0.22, 1, 0.36, 1], at: 0.5 },
        ],
        // Letters fade in. `at:` is absolute timeline time:
        //   leading constant = wait before the FIRST letter
        //   i * 0.09         = 90ms stagger between consecutive letters
        ...letters.map((el, i) => [
          el,
          { opacity: 0.9 },
          { duration: 0.1, at: 0.5+i * 0.09 },
        ]),
      ]);
      if (cancelled) return;

      // Phase 3: line fades out at the right edge.
      await animate(lineRef.current, { opacity: 0 }, { duration: 0.15 });
    };

    run();

    return () => {
      cancelled = true;
    };
  }, [playKey, prefersReducedMotion, animate, order]);

  if (prefersReducedMotion) {
    return <span style={{ color: color }}>{text}</span>;
  }

  return (
    <span
      ref={(el) => {
        rootRef.current = el;
        scope.current = el;
      }}
      style={{
        position: "relative",
        display: "inline-block",
        whiteSpace: "nowrap",
      }}
    >
      <motion.span
        ref={lineRef}
        aria-hidden="true"
        style={{
          position: "absolute",
          left: 0,
          top: "0.05em",
          width: "2px",
          height: "1em",
          background: color,
          transformOrigin: "bottom",
          opacity: 0,
          scaleY: 0,
        }}
      />
      {[...text].map((char, i) => (
        <motion.span
          key={i}
          ref={(el) => {
            letterRefs.current[i] = el;
          }}
          style={{ color: color, opacity: 0 }}
        >
          {char === " " ? " " : char}
        </motion.span>
      ))}
    </span>
  );
}
