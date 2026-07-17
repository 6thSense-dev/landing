import { useRef } from "react";
import { useReducedMotion } from "framer-motion";

/**
 * Subtle pointer-driven 3D tilt applied DIRECTLY to an element (keeps its own
 * layout/CSS — no wrapper divs). DESIGN.md Motion "hover-tilt"; spring easing
 * per DESIGN.md. Gated on prefers-reduced-motion.
 *
 * No scale/zoom — the TILT is the effect. Stronger perspective for real depth.
 *
 * @param {number} max peak tilt in degrees.
 */
export function useTilt(max = 14) {
  const ref = useRef(null);
  const reduce = useReducedMotion();

  const onPointerMove = (e) => {
    const el = ref.current;
    if (reduce || !el) return;
    const host = el.parentElement || el;
    const r = host.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5; // -0.5 .. 0.5
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.willChange = "transform";
    el.style.transition = "transform 70ms linear";
    el.style.transform =
      `perspective(850px) rotateY(${px * max * 2}deg) rotateX(${-py * max * 2}deg)`;
  };

  const onPointerLeave = () => {
    const el = ref.current;
    if (!el) return;
    el.style.transition = "transform 500ms cubic-bezier(.34,1.56,.64,1)";
    el.style.transform = "perspective(850px) rotateY(0deg) rotateX(0deg)";
  };

  return { ref, onPointerMove, onPointerLeave };
}

export default useTilt;
