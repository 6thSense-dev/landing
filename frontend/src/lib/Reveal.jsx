import { motion, useReducedMotion } from "framer-motion";

/**
 * Reveal — a one-shot fade + rise as the element scrolls into view.
 *
 * The tasteful, non-hijacking alternative to the scroll-morph: content is
 * always readable, animates ONCE on entry, then stays put (never fades back
 * out). Standard premium-site motion (Linear / Vercel). Only transform +
 * opacity animate, so it stays on the compositor (no scroll jank).
 *
 * Reduced-motion users get the final state instantly.
 *
 * Usage: <Reveal as="section" className="ev-prow" id="skin" delay={0.05}>…</Reveal>
 */
export default function Reveal({ as = "div", delay = 0, y = 26, children, ...rest }) {
  const reduce = useReducedMotion();
  const M = motion[as] ?? motion.div;

  if (reduce) {
    return <M {...rest}>{children}</M>;
  }

  return (
    <M
      {...rest}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-12% 0px -12% 0px" }}
      transition={{ duration: 0.62, ease: [0.22, 0.61, 0.36, 1], delay }}
    >
      {children}
    </M>
  );
}
