import { useEffect, useRef, useState } from "react";
import { useElementScrollProgress } from "./useElementScrollProgress.js";

/**
 * Vertical scroll-driven timeline of four research-citation quotes.
 *
 * - Central line draws top → bottom via clip-path tied to --timeline-p.
 * - Four QuoteNodes alternate L/R (zigzag from top-left), positioned at
 *   8 / 36 / 62 / 88 percent of the section's height.
 * - Each node activates via IntersectionObserver; once active, its branch
 *   scaleX-extends from the line outward and its quote card fades in.
 *
 * Lives in normal page flow between two sticky stages of <ScrollHero>.
 */

const QUOTES = [
  {
    side: "left",
    top: "0%",
    logoSrc: "/logos/amazon-robotics-logo.png",
    logoWebp: "/logos/amazon-robotics-logo.webp",
    logoAlt: "Amazon Robotics",
    attribution: "Vulcan · manipulation tasks",
    body: (
      <>
        Vision alone solves <em>30%</em> of manipulation tasks. Touch raises it
        to <em className="hero-quote-accent">90%</em>.
      </>
    )
  },
  {
    side: "right",
    top: "36%",
    logoSrc: "/logos/Columbia.png",
    logoWebp: "/logos/Columbia.webp",
    logoAlt: "Columbia Engineering · Robotic Manipulation and Mobility Lab",
    attribution: "Matei Ciocarlie",
    body: (
      <>
        Robot hands can be highly dexterous —{" "}
        <em className="hero-quote-accent">based on touch sensing alone</em>.
      </>
    )
  },
  {
    side: "left",
    top: "62%",
    logoSrc: "/logos/stanford.avif",
    logoAlt: "Stanford",
    attribution: "DenseTact · Kennedy Lab",
    body: (
      <>
        Dexterity depends on{" "}
        <em className="hero-quote-accent">continuous, soft-contact</em> touch
        feedback.
      </>
    )
  },
  {
    side: "right",
    top: "88%",
    logoSrc: "/logos/Meta.png",
    logoWebp: "/logos/Meta.webp",
    logoAlt: "Meta AI",
    attribution: "DIGIT · PyTouch",
    body: (
      <>
        Touch is how robots will{" "}
        <em className="hero-quote-accent">
          perceive, understand, and interact
        </em>{" "}
        with the physical world.
      </>
    )
  }
];

function QuoteNode({ side, top, logoSrc, logoWebp, logoAlt, attribution, body }) {
  const ref = useRef(null);
  const [active, setActive] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || active) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActive(true);
            io.disconnect();
            break;
          }
        }
      },
      { rootMargin: "0px 0px -40% 0px", threshold: 0 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [active]);

  return (
    <div
      ref={ref}
      className={`quote-timeline-node quote-timeline-node--${side}`}
      data-active={active ? "true" : "false"}
      style={{ top }}
    >
      <span className="quote-timeline-dot" aria-hidden="true" />
      <span className="quote-timeline-branch" aria-hidden="true" />
      <div className="quote-timeline-card">
        <p className="hero-quote-text">{body}</p>
        {/* WebP copy at native size via srcSet, PNG kept as the fallback src.
            The src attribute must stay the PNG regardless: scroll-hero.css keys
            per-logo scale off [src*="amazon"] / [src*="meta"]. Verified that
            every visible pixel and the whole alpha channel are bit-identical to
            the PNG — the marks are not altered. Stanford is already a 3KB AVIF
            and has no logoWebp, so it just renders from src. */}
        <img
          className="hero-quote-logo"
          src={logoSrc}
          srcSet={logoWebp}
          alt={logoAlt}
          loading="lazy"
        />
        <p className="hero-quote-attr">{attribution}</p>
      </div>
    </div>
  );
}

export function QuoteTimeline() {
  const sectionRef = useRef(null);
  const progressRef = useElementScrollProgress(sectionRef);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const el = sectionRef.current;
      if (el) {
        el.style.setProperty("--timeline-p", progressRef.current.toFixed(4));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [progressRef]);

  return (
    <section
      ref={sectionRef}
      className="quote-timeline"
      aria-label="Research citations"
    >
      <div className="quote-timeline-line" aria-hidden="true">
        <span className="quote-timeline-line-fill" />
      </div>
      {QUOTES.map((q, i) => (
        <QuoteNode key={i} {...q} />
      ))}
    </section>
  );
}
