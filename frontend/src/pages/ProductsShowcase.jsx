import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { useReducedMotion } from "framer-motion";

import LeadForm from "../lib/LeadForm.jsx";
import { useRevealNav } from "../useRevealNav.js";
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

export default function ProductsShowcase() {
  const nerveRowRef = useRef(null);
  const nerveStageRef = useRef(null);
  useJointReveal(nerveRowRef, nerveStageRef);

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
            <Link to="/people" className="nav-cta nav-cta-on-dark">
              People
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
          <div className="ev-pstage">
            <span className="ev-badge ev-live">Available now</span>
            {/*
              hand-studio.png is an AI-CLEANED studio rendition generated from the
              real glove reference (public/hand.jpg): background removed, relit on
              the site palette, sensor module kept blank/unbranded. Honest — based
              on the real product, no fake brand or invented features — but it is a
              rendition, not a literal photo of the exact unit.
              TODO(hardware): replace with a real studio knockout of the Hand glove
              + a 360° turntable capture so it can truly spin (DESIGN.md "Imagery
              Rules"). Falls back to a "photo pending" panel on error.
            */}
            <img
              className="ev-pstage-img"
              src="/hand-studio.png"
              alt="6thSense Hand — tactile data glove"
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
                <span className="ev-bignum-l">pressure cells</span>
              </div>
              <div className="ev-bignum">
                <span className="ev-bignum-n">200<small>Hz</small></span>
                <span className="ev-bignum-l">sustained</span>
              </div>
              <div className="ev-bignum">
                <span className="ev-bignum-n">&lt;1<small>ms</small></span>
                <span className="ev-bignum-l">response</span>
              </div>
            </div>
            <div className="ev-actions">
              <span className="ev-price">$1,000</span>
              <a className="ev-pill ev-solid" href="#reserve">Buy the Hand</a>
              <a className="ev-pill ev-onlight" href="#skin-contact">Talk to us</a>
            </div>
          </div>
        </section>

        {/* ---------- NERVE (dark) — 02, reserve. Same glove, joints lit. ---------- */}
        <section className="ev-prow ev-pdark ev-flip" id="nerve" ref={nerveRowRef}>
          <div className="ev-pstage ev-pstage--nerve" ref={nerveStageRef}>
            <span className="ev-badge ev-soon">Reserve — in build</span>
            <div className="ev-glowdots" />
            {/*
              Nerve CONCEPT render generated from the real Hand glove
              (public/nerve-concept.png): the SAME glove with glowing per-joint
              sensors — the Hand upgraded to Nerve, one glove two states.
              It is a concept, NOT a shipping product photo: Nerve isn't shipping
              and the sensor count/placement is illustrative (the real sensors
              sit palm-side). Stays badged "in build" + captioned "concept render".
            */}
            <img
              className="ev-pstage-img"
              src="/nerve-concept.png"
              alt="6thSense Nerve concept render — the Hand glove with per-joint sensors"
              style={{ objectFit: "contain", objectPosition: "center" }}
            />
            <span className="ev-statelabel ev-statelabel--stage" aria-hidden="true">
              <span className="ev-state-hand">Hand · tactile</span>
              <span className="ev-state-nerve">Nerve · force in space</span>
            </span>
            <span className="ev-pstage-cap">concept render · sensors illustrative</span>
          </div>
          <div className="ev-pinfo">
            <div className="ev-idx">02 · The Nerve</div>
            <h2 className="ev-ptitle">Nerve</h2>
            {/* Nerve is the mocap+tactile product, so the motion-capture wedge is
                accurate here (unlike Hand). Keep it. */}
            <p className="ev-oneliner">
              Mocap gloves track the hand but can't feel. Nerve does both —
              touch at every finger joint, plus temperature.
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
              <a className="ev-pill ev-solid" href="#reserve">Reserve Nerve</a>
            </div>
          </div>
        </section>

        {/* ---------- band: just the line, on the flying-dots background ---------- */}
        <section className="ev-band">
          <h3 className="ev-band-line">Every touch, localized.</h3>
        </section>

        {/* ---------- SKIN (light) — 03, contact ---------- */}
        <section className="ev-prow ev-plight" id="skin">
          <div className="ev-pstage">
            <span className="ev-badge ev-soon">In development</span>
            {/* CSS render-slot placeholder. TODO(hardware): CAD turntable render
                of skin conforming to a dexterous hand. Never fake it, and never
                name the partner hand — always "a dexterous hand". */}
            <div className="ev-skin-slot" aria-hidden="true">
              <div className="ev-skin-ring" />
              <div className="ev-skin-ph">
                <div className="ev-skin-mark">◑</div>
                <div className="ev-skin-cap">
                  CAD turntable render
                  <br />
                  skin conforming to a dexterous hand
                </div>
              </div>
            </div>
          </div>
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
              <a className="ev-pill ev-solid" href="#skin-contact">Talk to us</a>
            </div>
          </div>
        </section>

        {/* ---------- RESERVE (dark) — Nerve pre-order email capture ---------- */}
        <section className="ev-reserve" id="reserve">
          <div className="ev-reserve-grid">
            <div>
              <div className="ev-idx">Reserve · Nerve</div>
              <h2>Be first when per-joint sensing ships.</h2>
              <p>
                Reserve Nerve to hold your place in the first build. It's an email
                reservation only — no charge now, and price and ship window are
                still TBD. We'll reach out the moment pre-orders open.
              </p>
            </div>
            <ReserveForm />
          </div>
        </section>

        {/* ---------- CONTACT (dark) — Skin enquiry ---------- */}
        <section className="ev-reserve ev-reserve--alt" id="skin-contact">
          <div className="ev-reserve-grid">
            <div>
              <div className="ev-idx">Contact · Skin</div>
              <h2>Building a dexterous hand?</h2>
              <p>
                Tell us the hand or gripper and the task. We'll figure out what
                tactile skin belongs on it and where.
              </p>
            </div>
            <ContactForm />
          </div>
        </section>

        <footer className="ev-footer">
          <span>6thSense · tactile hardware for dexterous robotics</span>
          <Link className="ev-footer-home" to="/">Hand · Nerve · Skin</Link>
        </footer>
      </div>
    </div>
  );
}
