import { useRef } from "react";
import { motion, useScroll, useTransform, useReducedMotion } from "framer-motion";

/**
 * ProductMorph v4 — pinned, scroll-scrubbed product sequence.
 *
 * Each stage is a full, INFORMATIVE composition: a large product on one side,
 * the real title + stats + specs + CTA on the other, alternating sides. Stages
 * crossfade near centre (no empty frames), so the hand that FEELS -> the hand
 * that GRIPS -> the eye that SEES.
 *
 * Perf: only transform + opacity animate (compositor-friendly). No per-frame
 * filters — the product glow is a static ambient layer behind the stage, and
 * pointer-events toggle so only the visible stage is interactive.
 *
 * Prototype: mounted only on /products?morph so the shipped page is untouched.
 */

const STAGES = [
  {
    src: "/hero/glove/pose-hand.webp",
    idx: "01 · The Skin",
    title: "Skin",
    line: "The hand that feels. Every touch, recorded as force.",
    side: "right",
    center: 0.16,
    stats: [
      { n: "440", l: "tactile channels" },
      { n: "0.01N", l: "resolution" },
      { n: "<1ms", l: "response" },
      { n: "200Hz", l: "sustained" },
    ],
    chips: ["6-axis IMU", "16-bit resolution", "USB-C / BLE 5.x", "µs-monotonic sync"],
  },
  {
    src: "/hero/glove/robo.webp",
    idx: "02 · The Hand",
    title: "Hand",
    line: "The same skin, molded 1:1 onto a dexterous hand, a gripper, any surface you build.",
    side: "left",
    center: 0.5,
    stats: [
      { n: "1:1", l: "molded fit" },
      { n: "Any", l: "surface" },
      { n: "Per-task", l: "touch layout" },
    ],
    chips: [],
  },
  {
    src: "/eye2-hero.png",
    idx: "03 · The Rig",
    title: "Eye2",
    line: "The eye that sees what the hand feels. First-person video, synced to touch frame for frame.",
    side: "right",
    center: 0.84,
    stats: [],
    chips: ["Egocentric mount", "RGB + depth", "Synced to touch", "Printed enclosure"],
    downloads: [
      { href: "/eye2-main-frame.stl", label: "Main frame .stl" },
      { href: "/eye2-back-case.stl", label: "Back case .stl" },
    ],
  },
];

// Neighbouring stages overlap across a 2*CW window centred on the midpoint
// between them, so there is never an empty frame.
const CW = 0.1;

function DownloadGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v12" /><path d="M7 11l5 5 5-5" /><path d="M4 20h16" />
    </svg>
  );
}

function Stage({ stage, progress, prevCenter, nextCenter, reduce, isFirst, isLast }) {
  const { center, side } = stage;
  const fromLeft = side === "left";
  const enterX = fromLeft ? "-30vw" : "30vw";
  const driftX = fromLeft ? "9vw" : "-9vw";

  const inMid = isFirst ? center : (prevCenter + center) / 2;
  const outMid = isLast ? center : (center + nextCenter) / 2;
  const range = [inMid - CW, inMid + CW, outMid - CW, outMid + CW];

  const opacity = useTransform(progress, range, [isFirst ? 1 : 0, 1, 1, isLast ? 1 : 0]);
  const x = useTransform(progress, range, [isFirst ? "0vw" : enterX, "0vw", "0vw", isLast ? "0vw" : driftX]);
  const scale = useTransform(progress, range, [0.93, 1, 1, 0.93]);
  // Only the visible stage captures clicks (CTA / downloads).
  const pointerEvents = useTransform(opacity, (v) => (v > 0.6 ? "auto" : "none"));

  const textX = useTransform(progress, range, [
    isFirst ? "0vw" : (fromLeft ? "4vw" : "-4vw"), "0vw", "0vw",
    isLast ? "0vw" : (fromLeft ? "-3vw" : "3vw"),
  ]);

  return (
    <div className={`pm-stage pm-stage--${side}`}>
      <motion.div className="pm-prod" style={reduce ? { opacity } : { x, opacity, scale }} aria-hidden="true">
        <img className="pm-img" src={stage.src} alt="" draggable="false" />
      </motion.div>

      <motion.div className="pm-cap" style={reduce ? { opacity, pointerEvents } : { x: textX, opacity, pointerEvents }}>
        <div className="pm-idx">{stage.idx}</div>
        <h2 className="pm-title">{stage.title}</h2>
        <p className="pm-line">{stage.line}</p>

        {stage.stats?.length > 0 && (
          <div className="pm-stats">
            {stage.stats.map((s) => (
              <div className="pm-stat" key={s.l}>
                <span className="pm-stat-n">{s.n}</span>
                <span className="pm-stat-l">{s.l}</span>
              </div>
            ))}
          </div>
        )}

        {stage.chips?.length > 0 && (
          <ul className="pm-chips">
            {stage.chips.map((c) => <li key={c}>{c}</li>)}
          </ul>
        )}

        <div className="pm-actions">
          <a className="ev-pill ev-solid" href="/#contact">Talk to us</a>
        </div>

        {stage.downloads?.length > 0 && (
          <div className="pm-dls">
            <span className="pm-dl-label">Download the enclosure (CAD)</span>
            <div className="pm-dl-row">
              {stage.downloads.map((d) => (
                <a className="pm-dl" href={d.href} download key={d.href}>
                  <DownloadGlyph /> {d.label}
                </a>
              ))}
            </div>
          </div>
        )}
      </motion.div>
    </div>
  );
}

export default function ProductMorph() {
  const ref = useRef(null);
  const reduce = !!useReducedMotion();
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start start", "end end"] });

  return (
    <section className="pm-track" ref={ref}>
      <div className="pm-sticky">
        <div className="pm-glow" aria-hidden="true" />
        {STAGES.map((s, i) => (
          <Stage
            key={s.title}
            stage={s}
            progress={scrollYProgress}
            prevCenter={STAGES[i - 1]?.center ?? s.center}
            nextCenter={STAGES[i + 1]?.center ?? s.center}
            reduce={reduce}
            isFirst={i === 0}
            isLast={i === STAGES.length - 1}
          />
        ))}
        <div className="pm-hint">scroll ↓</div>
      </div>
    </section>
  );
}
