import { useEffect, useRef, useState } from "react";
import "./OpenerAnimation.css";

const SESSION_FLAG = "sixthsense.openerSeen";

function computeInitialPhase() {
  if (typeof window === "undefined") return "init";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const alreadySeen = sessionStorage.getItem(SESSION_FLAG) === "1";
  // A restored scroll position or an anchor hash (/#contact is the site's
  // single intake) means the visitor is here for a specific place on the
  // page — never make them sit through the opener to reach it.
  const deepLinked = window.scrollY > 0 || window.location.hash !== "";
  if (reduce || alreadySeen || deepLinked) return "done";
  return "init";
}

/**
 * Full-screen brand opener. Plays once per browser session — skipped on
 * in-tab refresh, re-plays in new tabs or after browser close. Also skipped
 * on deep-link arrivals (scrollY > 0 or an anchor hash) and when
 * prefers-reduced-motion is set. Any pointer or key input while it plays
 * skips ahead to the fade and releases the scroll lock — the animation is
 * for people who want it, never a gate for people who don't.
 */
export function OpenerAnimation() {
  const [phase, setPhase] = useState(computeInitialPhase);
  const bodyOverflowRef = useRef("");

  useEffect(() => {
    if (phase !== "init") {
      // Skip path — mark the flag so subsequent mounts stay consistent, then bail.
      if (typeof window !== "undefined") {
        sessionStorage.setItem(SESSION_FLAG, "1");
      }
      return;
    }

    sessionStorage.setItem(SESSION_FLAG, "1");

    // Lock body scroll for the duration of the opener.
    bodyOverflowRef.current = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    setPhase("playing");

    const removeSkipListeners = () => {
      window.removeEventListener("pointerdown", skip);
      window.removeEventListener("keydown", skip);
      window.removeEventListener("wheel", skip);
    };

    // Fade is 0.8s; restore scroll + hide overlay after it completes.
    // Overflow restore runs HERE (not in cleanup) because returning null from
    // the render keeps the component mounted — cleanup would never fire.
    const finalize = () => {
      document.body.style.overflow = bodyOverflowRef.current;
      removeSkipListeners();
      setPhase("done");
    };

    // Total: 5 trail dots (ends ~1.08s) + 6th ignite (0.95 + 1.9 = 2.85s) = hold until ~3.0s
    // The timed fade and a user skip share this one path: scroll unlocks and
    // the skip listeners drop the moment the fade begins, so the 0.8s tail is
    // purely visual on BOTH paths — late input can neither re-arm the finish
    // timer nor be swallowed by the dissolving overlay.
    let finish;
    const beginFade = () => {
      clearTimeout(startFade);
      clearTimeout(finish);
      document.body.style.overflow = bodyOverflowRef.current;
      removeSkipListeners();
      setPhase("fading");
      finish = setTimeout(finalize, 800);
    };
    const startFade = setTimeout(beginFade, 3000);

    // Interruptibility: the first pointer, key, or wheel input jumps straight
    // to the fade and releases the scroll lock IMMEDIATELY — the fade is
    // purely visual tail, input is never held for it.
    const skip = beginFade;
    window.addEventListener("pointerdown", skip);
    window.addEventListener("keydown", skip);
    window.addEventListener("wheel", skip, { passive: true });

    return () => {
      clearTimeout(startFade);
      clearTimeout(finish);
      removeSkipListeners();
      document.body.style.overflow = bodyOverflowRef.current;
    };
    // phase is only read once on mount; intentionally omitted from deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (phase === "init" || phase === "done") return null;

  return (
    <div className="opener-root" data-phase={phase} aria-hidden="true">
      <div className="opener-grid">
        <span className="opener-dot opener-dot--1" />
        <span className="opener-dot opener-dot--2" />
        <span className="opener-dot opener-dot--3" />
        <span className="opener-dot opener-dot--4" />
        <span className="opener-dot opener-dot--5" />
        <span className="opener-dot opener-dot--6" />
      </div>
    </div>
  );
}
