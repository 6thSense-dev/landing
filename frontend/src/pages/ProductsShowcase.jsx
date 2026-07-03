import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";

import LeadForm from "../lib/LeadForm.jsx";
import SiteNav from "../lib/SiteNav.jsx";
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

  useEffect(() => {
    const prev = document.title;
    document.title = "Products — Hand · Nerve · Skin | 6thSense";
    return () => {
      document.title = prev;
    };
  }, []);

  return (
    <div className="ev-home ev-products">
      <div className="ev-frame">
        {/* ---------- nav + page head (dark hero band) ---------- */}
        <section className="ev-hero ev-hero--compact" aria-label="6thSense products">
          <SiteNav
            cta="Reserve Nerve"
            ctaHref="#reserve"
            links={[
              { label: "Products", href: "/products" },
              { label: "Hand", href: "#hand" },
              { label: "Nerve", href: "#nerve" },
              { label: "Skin", href: "#skin" },
            ]}
          />

          <div className="ev-phead">
            <div className="ev-idx">The hardware</div>
            <h1>
              One glove. Then the
              <br />
              robot feels it too.
            </h1>
            <div className="ev-rule" />
            <p className="ev-phead-deck">
              Capture touch on a human hand, know exactly where it lands, then
              move that sensing onto the robot. Hand ships today; Nerve adds
              per-joint sensing; Skin puts it on your hardware.
            </p>
          </div>
        </section>

        {/* ---------- HAND (light) — 01, available now ---------- */}
        <section className="ev-prow ev-plight" id="hand">
          <div className="ev-pstage">
            <span className="ev-badge ev-live">Available now</span>
            {/*
              PLACEHOLDER product image. /hand.jpg does not exist yet, so the
              <img> falls back to a labelled "photo pending" panel via onError
              (reads as intentional, not a broken asset).
              TODO(hardware): drop a real studio knockout of the Hand glove on
              the glow stage at /public/hand.jpg + a 360° turntable capture so
              it can truly spin (DESIGN.md "Imagery Rules"). Never AI-generate
              or fake this shot — technical buyers spot it instantly.
            */}
            <img
              className="ev-pstage-img"
              src="/hand.jpg"
              alt="6thSense Hand — tactile data glove, sensor module detail"
              style={{ objectPosition: "82% 56%", transform: "scale(1.75)" }}
              onError={(e) => {
                e.currentTarget.style.display = "none";
                e.currentTarget.nextElementSibling?.removeAttribute("hidden");
              }}
            />
            <div className="ev-prod-ph" hidden aria-hidden="true">
              <div className="ev-prod-ph-mark">◍</div>
              <div className="ev-prod-ph-cap">Sensor-module macro — photo pending</div>
            </div>
            <span className="ev-pstage-cap">sensor module — detail</span>
          </div>
          <div>
            <div className="ev-idx">01 · The Hand</div>
            <h2>Hand</h2>
            <div className="ev-psub">Human tactile data glove — tactile + orientation</div>
            <p className="ev-lede">
              440 pressure cells, synced and training-ready. Records force the
              instant you make contact, with hand orientation for every frame.
            </p>
            <ul className="ev-specs">
              <li>440 cells</li>
              <li>0.1–350 N</li>
              <li>16-bit</li>
              <li>&lt;1 ms</li>
              <li>≥200 Hz</li>
            </ul>
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
              One glove, two states (DESIGN.md): the SAME 15-joint diagram as the
              homepage hero, here lit on scroll to show the Hand becoming the
              Nerve. Annotated diagram until Nerve physically exists — never a
              faked photo, and per-joint sensing is labelled Nerve only.
            */}
            <svg
              className="ev-nervesvg ev-nervesvg--reveal"
              viewBox="0 0 360 250"
              width="72%"
              role="img"
              aria-label="15 joint sensors, 3 per finger — pressure + temperature"
            >
              <rect className="ev-bone" x="120" y="160" width="120" height="66" rx="20" />
              <rect className="ev-bone" x="132" y="34" width="20" height="132" rx="10" />
              <rect className="ev-bone" x="160" y="26" width="20" height="140" rx="10" />
              <rect className="ev-bone" x="188" y="32" width="20" height="134" rx="10" />
              <rect className="ev-bone" x="216" y="48" width="20" height="118" rx="10" />
              <rect className="ev-bone" x="236" y="142" width="58" height="20" rx="10" transform="rotate(28 236 142)" />
              <JointCircles prefix="nerve" />
              <text className="ev-svglbl" x="20" y="242">
                15 joint sensors · 3 per finger · pressure + temperature
              </text>
            </svg>
            <span className="ev-statelabel ev-statelabel--stage" aria-hidden="true">
              <span className="ev-state-hand">Hand · tactile</span>
              <span className="ev-state-nerve">Nerve · force in space</span>
            </span>
          </div>
          <div>
            <div className="ev-idx">02 · The Nerve</div>
            <h2>Nerve</h2>
            <div className="ev-psub">Everything the Hand feels — plus per-joint motion + temperature</div>
            <p className="ev-lede">
              The same glove, with a sensor at every finger joint. Each touch
              localized in space, with temperature. Your data knows not just how
              hard, but exactly where.
            </p>
            <ul className="ev-specs">
              <li>+ per-joint motion</li>
              <li>+ temperature</li>
              <li>15 joints</li>
              <li>Bosch BMP581</li>
            </ul>
            <div className="ev-actions">
              {/* TODO: Nerve price + ship window are TBD (DESIGN.md); reserve is
                  email capture only. */}
              <span className="ev-tbd">Price &amp; ship window: TBD</span>
              <a className="ev-pill ev-solid" href="#reserve">Reserve Nerve</a>
            </div>
          </div>
        </section>

        {/* ---------- media band ---------- */}
        <section className="ev-band">
          <div className="ev-bandmedia">
            <video
              src="/demo.mp4"
              poster="/demo-poster.jpg"
              autoPlay
              muted
              loop
              playsInline
              aria-hidden="true"
            />
            <h3>Every touch, localized.</h3>
          </div>
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
          <div>
            <div className="ev-idx">03 · The Skin</div>
            <h2>Skin</h2>
            <div className="ev-psub">Custom tactile skin for robot hands and grippers</div>
            <p className="ev-lede">
              Molded 1:1 to your hardware. Touch exactly where the task needs it
              — a dexterous hand, a gripper, any surface you build.
            </p>
            <ul className="ev-specs">
              <li>Custom-fit</li>
              <li>Any surface</li>
              <li>Per-task layout</li>
            </ul>
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
