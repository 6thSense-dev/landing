import { motion, useReducedMotion } from "framer-motion";

// One fade, used for every top-level route swap (see main.jsx's AnimatedRoutes)
// so navigating Home <-> Products <-> People <-> Partner login always reads
// the same way, instead of each page rolling its own enter/exit animation.
const DURATION = 0.32;

export default function PageTransition({ children }) {
  const reduceMotion = useReducedMotion();
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: reduceMotion ? 0 : DURATION, ease: "easeInOut" }}
    >
      {children}
    </motion.div>
  );
}
