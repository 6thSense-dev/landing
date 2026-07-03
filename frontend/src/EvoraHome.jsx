import { useEffect, useRef } from "react";

import LeadForm from "./lib/LeadForm.jsx";
import SiteNav from "./lib/SiteNav.jsx";
import "./evora-home.css";

/**
 * 6thSense homepage — the approved dark-cinematic "Evora" direction.
 * Source of truth: DESIGN.md (repo root) + .context/design-reference/evora.html.
 *
 * Narrative spine (DESIGN.md): Hand -> Nerve -> Skin.
 *   Hand  — the human glove, tactile + orientation only. Ships today, $1,000.
 *   Nerve — the SAME glove with a sensor at every finger joint (15, 3/finger).
 *           Reserve only; price + ship window are TBD placeholders.
 *   Skin  — that sensing molded onto a robot hand/gripper. In development.
 *
 * Signature interaction — one glove, two states: the hero shows ONE glove
 * (real photo). As you scroll the hero, the 15 joint sensors light up and the
 * on-image label crossfades Hand -> Nerve. Honesty guardrail: per-joint
 * sensing is labelled Nerve, never claimed for the shipping Hand.
 */

/* 15 joint centres (3 per finger), copied from the approved evora.html SVG so
   the hero overlay and the Nerve product diagram stay pixel-identical. */
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
 * Drives --joints-lit (0 -> 1) on `targetRef` as `sectionRef` scrolls through
 * the first part of the viewport. This is the Hand -> Nerve reveal. With
 * reduced motion, joints are shown fully lit immediately (no scroll drive).
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
        // 0 while the hero fills the viewport; ramps to 1 across the first
        // ~65% of a viewport-height of upward scroll, so the transformation
        // completes early and holds.
        const scrolled = -rect.top;
        const lit = clamp01(scrolled / (vh * 0.65));
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
 * Homepage Nerve reserve capture — the one shared LeadForm, tagged
 * kind="preorder", product="nerve" (email capture only; DESIGN.md guardrail:
 * no price/ship window shown). Identical form client + states as /products.
 */
function ReserveForm() {
  return (
    <LeadForm
      kind="preorder"
      product="nerve"
      idPrefix="home-rsv"
      submitLabel="Reserve Nerve"
      successMessage="You're on the list. We'll email you when Nerve opens for pre-order."
    />
  );
}

export default function EvoraHome() {
  const heroRef = useRef(null);
  const stageRef = useRef(null);
  useJointReveal(heroRef, stageRef);

  return (
    <div className="ev-home">
      <div className="ev-frame">
        {/* ---------- HERO (dark) — one glove, two states ---------- */}
        <section className="ev-hero" ref={heroRef} aria-label="6thSense">
          <SiteNav
            wordmarkIsHome={false}
            cta="Reserve Nerve"
            ctaHref="#reserve"
            links={[
              { label: "Products", href: "/products" },
              { label: "Hand", href: "#hand" },
              { label: "Nerve", href: "#nerve" },
              { label: "Skin", href: "#skin" },
            ]}
          />

          <div className="ev-hero-grid">
            <div>
              <h1>
                Force, in space,
                <br />
                at every joint.
              </h1>
              <div className="ev-rule" />
              <div className="ev-hero-foot">
                <span className="ev-welcome">
                  <span className="ev-dot" />
                  Welcome
                </span>
                <div>
                  <p>
                    Well-made touch sensing that ships. Half the price of the
                    {" "}
                    {/* TODO: verify current Manus price before launch — DESIGN.md notes "typically over $2K". */}
                    typically-over-$2K gloves, and it actually feels.
                  </p>
                  <a className="ev-pill ev-solid" href="#reserve">Reserve Nerve</a>
                </div>
              </div>
            </div>

            <div className="ev-stage" ref={stageRef}>
              <div className="ev-glow" />
              <div className="ev-prod">
                {/*
                  PLACEHOLDER product image. /hand.jpg does not exist yet, so
                  the <img> falls back to a labelled "photo pending" panel via
                  onError (reads as intentional, not a broken asset).
                  TODO(hardware): drop a real studio knockout of the Hand glove
                  on the glow stage at /public/hand.jpg + a 360° turntable
                  capture so it can truly spin (DESIGN.md "Imagery Rules").
                  Never AI-generate or fake this shot — technical buyers spot
                  it instantly.
                */}
                <img
                  src="/hand.jpg"
                  alt="6thSense Hand — tactile data glove"
                  onError={(e) => {
                    e.currentTarget.style.display = "none";
                    e.currentTarget.nextElementSibling?.removeAttribute("hidden");
                  }}
                />
                <div className="ev-prod-ph" hidden aria-hidden="true">
                  <div className="ev-prod-ph-mark">◍</div>
                  <div className="ev-prod-ph-cap">Hand — studio photo pending</div>
                </div>
                {/* 15-joint overlay: lights up on scroll = Hand becoming Nerve. */}
                <svg
                  className="ev-joints"
                  viewBox="0 0 360 250"
                  aria-hidden="true"
                  preserveAspectRatio="xMidYMid meet"
                >
                  <JointCircles prefix="hero" />
                </svg>
                <div className="ev-statelabel" aria-hidden="true">
                  <span className="ev-state-hand">Hand · tactile</span>
                  <span className="ev-state-nerve">Nerve · force in space</span>
                </div>
              </div>
              {/* TODO(hardware): enable once 360° capture exists. */}
              <span className="ev-tt">◍ 360° · turntable (pending capture)</span>
            </div>
          </div>
        </section>

        {/* ---------- LIGHT stats band ---------- */}
        <section className="ev-light">
          <p className="ev-intro">
            At 6thSense, we build the touch layer for dexterous robots — the
            sensing that vision and motion capture can't give you.
          </p>
          <div className="ev-stats">
            <div className="ev-stat">
              <div className="ev-lab"><span className="ev-dot" />Pressure cells</div>
              <div className="ev-num">440</div>
              <div className="ev-substat">Across fingertips, pads, and palm.</div>
            </div>
            <div className="ev-stat">
              <div className="ev-lab"><span className="ev-dot" />Force range</div>
              <div className="ev-num">0.1–350<small> N</small></div>
              <div className="ev-substat">From a feather-touch to a firm grip.</div>
            </div>
            <div className="ev-stat">
              <div className="ev-lab"><span className="ev-dot" />Response</div>
              <div className="ev-num">&lt;1<small> ms</small></div>
              <div className="ev-substat">Contact the instant it happens.</div>
            </div>
            <div className="ev-stat">
              <div className="ev-lab"><span className="ev-dot" />Refresh</div>
              <div className="ev-num">≥200<small> Hz</small></div>
              <div className="ev-substat">Wired, zero-drop sustained.</div>
            </div>
          </div>
        </section>

        {/* ---------- HAND (light) — 01 ---------- */}
        <section className="ev-prow ev-plight" id="hand">
          <div className="ev-pstage">
            <span className="ev-badge ev-live">Available now</span>
            {/*
              PLACEHOLDER detail shot. TODO(hardware): real macro of the sensor
              module on the glove (studio knockout). Do NOT fake it.
            */}
            <img
              className="ev-pstage-img"
              src="/hand.jpg"
              alt="Hand — sensor module detail"
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
              <a className="ev-pill ev-onlight" href="#reserve">Talk to us</a>
            </div>
          </div>
        </section>

        {/* ---------- NERVE (dark) — 02 ---------- */}
        <section className="ev-prow ev-pdark ev-flip" id="nerve">
          <div className="ev-pstage">
            <span className="ev-badge ev-soon">Reserve — in build</span>
            <div className="ev-glowdots" />
            {/* Annotated diagram until Nerve physically exists (DESIGN.md). */}
            <svg
              className="ev-nervesvg"
              viewBox="0 0 360 250"
              width="72%"
              role="img"
              aria-label="15 joint sensors, 3 per finger"
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
          </div>
          <div>
            <div className="ev-idx">02 · The Nerve</div>
            <h2>Nerve</h2>
            <div className="ev-psub">Everything the Hand feels — plus where and how it moves</div>
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
              {/* TODO: Nerve price + ship window are TBD (DESIGN.md). */}
              <span className="ev-tbd">Price & ship window: TBD</span>
              <a className="ev-pill ev-solid" href="#reserve">Reserve Nerve</a>
              <a className="ev-pill ev-dark" href="#reserve">Notify me</a>
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

        {/* ---------- SKIN (light) — 03 ---------- */}
        <section className="ev-prow ev-plight" id="skin">
          <div className="ev-pstage">
            <span className="ev-badge ev-soon">In development</span>
            {/* TODO(hardware): CAD turntable render of skin on a dexterous hand. */}
            <div className="ev-skin-ph">
              <div className="ev-skin-mark">◑</div>
              <div className="ev-skin-cap">
                CAD turntable render
                <br />
                skin conforming to a dexterous hand
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
              <a className="ev-pill ev-solid" href="#reserve">Talk to us</a>
            </div>
          </div>
        </section>

        {/* ---------- RESERVE capture (dark) ---------- */}
        <section className="ev-reserve" id="reserve">
          <div className="ev-reserve-grid">
            <div>
              <div className="ev-idx">Reserve</div>
              <h2>Give your robot a sixth sense.</h2>
              <p>
                Buy the Hand today, or reserve Nerve to be first when per-joint
                sensing ships. Tell us what you're building and we'll follow up.
              </p>
            </div>
            <ReserveForm />
          </div>
        </section>

        <footer className="ev-footer">
          <span>6thSense · tactile hardware for dexterous robotics</span>
          <span>Hand · Nerve · Skin</span>
        </footer>
      </div>
    </div>
  );
}
