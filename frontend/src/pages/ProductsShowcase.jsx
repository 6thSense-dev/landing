import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useReducedMotion } from "framer-motion";

import LeadForm from "../lib/LeadForm.jsx";
import { useRevealNav } from "../useRevealNav.js";
// Skin section: robotic image + glove photo composite (2D, no WebGL). Add
// ?align to the /products URL for the on-page alignment panel.
import SkinStage from "../lib/SkinStage.jsx";
import { TactileField } from "../TactileField.jsx";
// Reuse the homepage's approved Evora stylesheet verbatim (all .ev-* classes
// and the joint-reveal visual live there, scoped under .ev-home). This file
// only adds the small products-page deltas on top.
import "../evora-home.css";
import "./products-showcase.css";

/**
 * 6thSense /products — the designed, human-facing product page.
 * Source of truth: DESIGN.md (repo root) + .context/design-reference/evora.html.
 *
 * Same approved dark-cinematic "Evora" direction as the homepage, told as the
 * narrative spine in order Hand -> Nerve -> Skin (DESIGN.md):
 *   Hand  — the human glove, tactile + orientation only. Ships today, $1,000.
 *           Buy + Talk-to-us.
 *   Nerve — the SAME glove with a sensor at every finger joint (15, 3/finger),
 *           per-joint motion + temperature. Reserve only; price + ship window
 *           are TBD placeholders (email capture only).
 *   Skin  — that sensing molded onto a dexterous hand / gripper. Contact only;
 *           CSS render-slot placeholder until a CAD turntable render exists.
 *
 * Honesty guardrails (DESIGN.md): per-joint sensing is labelled Nerve, never
 * claimed for the shipping Hand. Nerve is not yet shipping. We never name the
 * partner hand — always "a dexterous hand". No AI-generated product photos.
 *
 * The one-glove-two-states visual is reused from the homepage: the Nerve row
 * shows the SAME glove as the Hand with the 15 joints lit as you scroll it in.
 */

/* 15 joint centres (3 per finger), identical to the homepage hero + the
   approved evora.html SVG so every joint diagram on the site stays aligned. */
const JOINTS = [
  [142, 64], [142, 102], [142, 140],
  [170, 56], [170, 98], [170, 140],
  [198, 60], [198, 102], [198, 140],
  [226, 74], [226, 110], [226, 144],
  [256, 166], [276, 154], [294, 140],
];

function prefersReducedMotion() {
  return (
    typeof window !== "undefined" &&
    window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Drives --joints-lit (0 -> 1) on `targetRef` as `sectionRef` scrolls up into
 * view — the Hand-becomes-Nerve reveal, reused from the homepage. With reduced
 * motion the joints are shown fully lit immediately (no scroll drive).
 */
function useJointReveal(sectionRef, targetRef) {
  useEffect(() => {
    const target = targetRef.current;
    if (!target) return;

    if (prefersReducedMotion()) {
      target.style.setProperty("--joints-lit", "1");
      return;
    }

    let raf = 0;
    const clamp01 = (v) => (v < 0 ? 0 : v > 1 ? 1 : v);
    const tick = () => {
      const el = sectionRef.current;
      if (el) {
        const rect = el.getBoundingClientRect();
        const vh = window.innerHeight || 1;
        // Ramp 0 -> 1 as the row travels from the bottom of the viewport up to
        // roughly its middle, so the joints are lit by the time it reads.
        const start = vh * 0.85;
        const end = vh * 0.35;
        const lit = clamp01((start - rect.top) / (start - end));
        target.style.setProperty("--joints-lit", lit.toFixed(3));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [sectionRef, targetRef]);
}

function JointCircles({ prefix }) {
  return (
    <>
      {JOINTS.map(([cx, cy], i) => (
        <g key={`${prefix}-${i}`}>
          <circle className="ev-jh" cx={cx} cy={cy} r="9" />
          <circle className="ev-j" cx={cx} cy={cy} r="4" />
        </g>
      ))}
    </>
  );
}

/**
 * Nerve reserve capture (email only — no price/ship window shown; DESIGN.md).
 * The one shared LeadForm, tagged kind="preorder", product="nerve".
 */
function ReserveForm() {
  return (
    <LeadForm
      kind="preorder"
      product="nerve"
      idPrefix="rsv"
      submitLabel="Reserve Nerve"
      successMessage="You're on the list. We'll email you when Nerve opens for pre-order."
    />
  );
}

/**
 * Skin contact capture. The one shared LeadForm, tagged kind="contact",
 * product="skin"; a message is required (the backend also enforces it).
 */
function ContactForm() {
  return (
    <LeadForm
      kind="contact"
      product="skin"
      idPrefix="ct"
      submitLabel="Talk to us"
      messageLabel="What are you building?"
      messagePlaceholder="The hand or gripper, the task, and where you need touch."
      successMessage="Thanks — we'll be in touch about custom tactile skin."
    />
  );
}

/**
 * Hand quote request. Shared LeadForm, tagged kind="contact", product="hand".
 */
function QuoteForm() {
  return (
    <LeadForm
      kind="contact"
      product="hand"
      idPrefix="quote"
      submitLabel="Request quote"
      messageLabel="What do you need?"
      messagePlaceholder="Quantity, your use case, and any timeline."
      successMessage="Thanks — we'll send a quote for the Hand shortly."
    />
  );
}

/* The three intake forms now open as pop-ups instead of living inline on the
   page, keyed by which CTA opened them. */
const MODALS = {
  quote: {
    eyebrow: "Quote · Hand",
    title: "Request a quote",
    desc: "Tell us quantity and use case and we'll get you a quote for the Hand.",
    Form: QuoteForm,
  },
  reserve: {
    eyebrow: "Reserve · Nerve",
    title: "Be first when per-joint sensing ships.",
    desc: "An email reservation only — no charge now, price and ship window still TBD. We'll reach out the moment pre-orders open.",
    Form: ReserveForm,
  },
  contact: {
    eyebrow: "Contact · Skin",
    title: "Building a dexterous hand?",
    desc: "Tell us the hand or gripper and the task. We'll figure out what tactile skin belongs on it and where.",
    Form: ContactForm,
  },
};

function Modal({ which, onClose }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const m = MODALS[which];
  if (!m) return null;
  const { Form } = m;
  return (
    <div className="ev-modal-overlay" onClick={onClose}>
      <div
        className="ev-modal"
        role="dialog"
        aria-modal="true"
        aria-label={m.title}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="ev-modal-x" onClick={onClose} aria-label="Close" type="button">
          ×
        </button>
        <div className="ev-idx">{m.eyebrow}</div>
        <h2 className="ev-modal-title">{m.title}</h2>
        <p className="ev-modal-desc">{m.desc}</p>
        <Form />
      </div>
    </div>
  );
}

export default function ProductsShowcase() {
  const nerveRowRef = useRef(null);
  const nerveStageRef = useRef(null);
  useJointReveal(nerveRowRef, nerveStageRef);

  // Which intake pop-up is open: "quote" | "reserve" | "contact" | null.
  const [modal, setModal] = useState(null);

  // Same floating flagship nav as the homepage (styles.css .nav-flagship).
  // No #story on this page, so useRevealNav keeps it always visible.
  const reduceMotion = useReducedMotion();
  const { className: navClassName } = useRevealNav({ reduceMotion: !!reduceMotion });

  useEffect(() => {
    const prev = document.title;
    document.title = "Products — Hand · Nerve · Skin | 6thSense";
    return () => {
      document.title = prev;
    };
  }, []);

  return (
    <div className="ev-home ev-products">
      {/* Same flying-dots constellation as the homepage, fixed behind the whole
          page so /products reads as one continuous dark field (DESIGN.md). */}
      <div className="ev-bg-field" aria-hidden="true">
        <TactileField />
      </div>
      {/* Same floating flagship nav as the homepage. */}
      <header className={navClassName} role="banner">
        <nav className="nav-flagship-inner" aria-label="Primary">
          <Link className="wordmark wordmark-on-dark" to="/" aria-label="6thSense home">
            <img className="nav-logo" src="/logos/Logo_Alpha.png" alt="" aria-hidden="true" />
            <span className="nav-logo-text">6THSENSE</span>
          </Link>
          <div className="nav-links nav-links-on-dark">
            <Link to="/products" className="nav-cta nav-cta-on-dark">
              Products
            </Link>
            <Link to="/login" className="nav-cta nav-cta-on-dark">
              Partner login
            </Link>
          </div>
        </nav>
      </header>

      <div className="ev-frame">
        {/* ---------- HAND — 01, available now (first section, clears the nav) ---------- */}
        <section className="ev-prow ev-plight ev-prow--first" id="hand">
          <div className="ev-pstage ev-pstage--hand">
            <span className="ev-badge ev-live">Available now</span>
            {/*
              Real photo of the Hand glove, index raised — the "1" frame from the
              glove capture sequence (public/hero/glove/pose-hand.webp, tight crop
              of /hero/glove/frame-001.webp). A genuine product photo, not a render
              or AI image (DESIGN.md "Imagery Rules"). Falls back to a "photo
              pending" panel on error.
            */}
            <img
              className="ev-pstage-img"
              src="/hero/glove/pose-hand.webp"
              alt="6thSense Hand — tactile data glove, index finger raised"
              style={{ objectFit: "contain", objectPosition: "center" }}
              onError={(e) => {
                e.currentTarget.style.display = "none";
                e.currentTarget.nextElementSibling?.removeAttribute("hidden");
              }}
            />
            <div className="ev-prod-ph" hidden aria-hidden="true">
              <div className="ev-prod-ph-mark">◍</div>
              <div className="ev-prod-ph-cap">Hand glove — photo pending</div>
            </div>
          </div>
          <div className="ev-pinfo">
            <div className="ev-idx">01 · The Hand</div>
            <h2 className="ev-ptitle">Hand</h2>
            {/* One line only, and accurate: the Hand is tactile (+ hand
                orientation). It does NOT do per-joint motion capture — that is
                Nerve. Never imply mocap here. */}
            <p className="ev-oneliner">A data glove that feels. Every touch, recorded as force.</p>
            <div className="ev-bignums">
              <div className="ev-bignum">
                <span className="ev-bignum-n">440</span>
                <span className="ev-bignum-l">tactile channels</span>
              </div>
              <div className="ev-bignum">
                <span className="ev-bignum-n">0.01<small>N</small></span>
                <span className="ev-bignum-l">resolution</span>
              </div>
              <div className="ev-bignum">
                <span className="ev-bignum-n"><span className="ev-pre">&lt;</span>1<small>ms</small></span>
                <span className="ev-bignum-l">response</span>
              </div>
              <div className="ev-bignum">
                <span className="ev-bignum-n">200<small>Hz</small></span>
                <span className="ev-bignum-l">sustained</span>
              </div>
            </div>
            {/* Supporting specs — credibility/integration detail for the
                technical buyer (see the full key-spec sheet). */}
            <ul className="ev-specs">
              <li>6-axis IMU</li>
              <li>16-bit resolution</li>
              <li>USB-C / BLE 5.x</li>
              <li>µs-monotonic sync</li>
            </ul>
            <div className="ev-actions">
              <button type="button" className="ev-pill ev-solid" onClick={() => setModal("quote")}>Get a quote</button>
              <button type="button" className="ev-pill ev-onlight" onClick={() => setModal("contact")}>Talk to us</button>
            </div>
          </div>
        </section>

        {/* ---------- NERVE (dark) — 02, reserve. Same glove, joints lit. ---------- */}
        <section className="ev-prow ev-pdark ev-flip" id="nerve" ref={nerveRowRef}>
          <div className="ev-pstage ev-pstage--nerve" ref={nerveStageRef}>
            <span className="ev-badge ev-soon">Reserve — in build</span>
            {/*
              Real photo of the SAME glove raised in a peace sign — the "2" frame
              from the glove capture sequence (public/hero/glove/pose-nerve.webp,
              tight crop of /hero/glove/frame-002.webp). Nerve is the Hand glove
              with per-joint sensing added; not yet shipping, so it stays badged
              "in build". A genuine photo, not a render or AI image.
            */}
            <div className="ev-glowdots" />
            <img
              className="ev-pstage-img"
              src="/hero/glove/pose-nerve.webp"
              alt="6thSense Nerve — the Hand glove raised in a peace sign"
              style={{ objectFit: "contain", objectPosition: "center" }}
            />
            <span className="ev-statelabel ev-statelabel--stage" aria-hidden="true">
              <span className="ev-state-hand">Hand · tactile</span>
              <span className="ev-state-nerve">Teleop glove with tactile capabilities.</span>
            </span>
          </div>
          <div className="ev-pinfo">
            <div className="ev-idx">02 · The Nerve</div>
            <h2 className="ev-ptitle">Nerve</h2>
            {/* Nerve is the mocap+tactile product, so the motion-capture wedge is
                accurate here (unlike Hand). Keep it. */}
            <p className="ev-oneliner">
              Mocap gloves track the hand but can't feel. Nerve does both —
              tactile sensing and joint tracking at every finger.
            </p>
            <div className="ev-bignums">
              <div className="ev-bignum">
                <span className="ev-bignum-n">15</span>
                <span className="ev-bignum-l">joint sensors</span>
              </div>
              <div className="ev-bignum">
                <span className="ev-bignum-n">3</span>
                <span className="ev-bignum-l">per finger</span>
              </div>
              <div className="ev-bignum">
                <span className="ev-bignum-n">440</span>
                <span className="ev-bignum-l">pressure cells</span>
              </div>
            </div>
            <div className="ev-actions">
              {/* Nerve price + ship window TBD (DESIGN.md); reserve = email capture only. */}
              <span className="ev-tbd">Price &amp; ship window: TBD</span>
              <button type="button" className="ev-pill ev-solid" onClick={() => setModal("reserve")}>Reserve Nerve</button>
            </div>
          </div>
        </section>

        {/* ---------- band: just the line, on the flying-dots background ---------- */}
        <section className="ev-band">
          <h3 className="ev-band-line">Every touch, localized.</h3>
        </section>

        {/* ---------- SKIN (light) — 03, contact ---------- */}
        <section className="ev-prow ev-plight" id="skin">
          {/* Skin: ONE hand, split down the middle — LEFT half the robotic
              dexterous-hand image, RIGHT half the tactile-skin glove photo. Both
              are flat 2D images (no WebGL), so page == aligner at any size.
              Add ?align to the URL for the on-page alignment panel. */}
          <SkinStage />
          <div className="ev-pinfo">
            <div className="ev-idx">03 · The Skin</div>
            <h2 className="ev-ptitle">Skin</h2>
            <p className="ev-oneliner">
              Custom tactile skin, molded 1:1 to a dexterous hand, a gripper,
              any surface you build.
            </p>
            <div className="ev-bignums">
              <div className="ev-bignum">
                <span className="ev-bignum-n">1:1</span>
                <span className="ev-bignum-l">molded fit</span>
              </div>
              <div className="ev-bignum">
                <span className="ev-bignum-n">Any</span>
                <span className="ev-bignum-l">surface</span>
              </div>
              <div className="ev-bignum">
                <span className="ev-bignum-n">Per-task</span>
                <span className="ev-bignum-l">touch layout</span>
              </div>
            </div>
            <div className="ev-actions">
              <button type="button" className="ev-pill ev-solid" onClick={() => setModal("contact")}>Talk to us</button>
            </div>
          </div>
        </section>

        {/* Reserve / Contact / Quote now open as pop-ups (see the Modal below),
            so they no longer live as inline sections on the page. */}

        <footer className="ev-footer">
          <span>6thSense · tactile hardware for dexterous robotics</span>
          <Link className="ev-footer-home" to="/">Hand · Nerve · Skin</Link>
        </footer>
      </div>

      {modal && <Modal which={modal} onClose={() => setModal(null)} />}
    </div>
  );
}
