import { motion, useReducedMotion } from "framer-motion";

// One fade, used for every top-level route swap (see main.jsx's AnimatedRoutes)
// so navigating Home <-> Products <-> People <-> Partner login always reads
// the same way, instead of each page rolling its own enter/exit animation.
// AnimatePresence runs exit-then-enter (mode="wait"), so both legs sit on the
// input path: the exit is micro-short (the old page just gets out of the way)
// and the enter is the DESIGN.md "short" step, keeping total dead time ~260ms
// instead of a symmetric two-beat fade.
const EXIT_DURATION = 0.08; // micro (DESIGN.md duration scale)
const ENTER_DURATION = 0.18; // short
const ENTER_EASE = [0.22, 1, 0.36, 1]; // DESIGN.md enter curve

export default function PageTransition({ children }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{
        opacity: 0,
        transition: { duration: reduceMotion ? 0 : EXIT_DURATION, ease: "easeIn" },
      }}
      transition={{ duration: reduceMotion ? 0 : ENTER_DURATION, ease: ENTER_EASE }}
    >
      {children}
    </motion.div>
  );
}
