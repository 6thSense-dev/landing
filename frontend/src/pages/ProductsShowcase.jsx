import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useReducedMotion } from "framer-motion";

import { useRevealNav } from "../useRevealNav.js";
// Skin section: robotic image + glove photo composite (2D, no WebGL). Add
// ?align to the /products URL for the on-page alignment panel.
import SkinStage from "../lib/SkinStage.jsx";
import { TactileField } from "../TactileField.jsx";
// Reuse the homepage's approved Evora stylesheet verbatim (all .ev-* classes
// live there, scoped under .ev-home). This file only adds the small
// products-page deltas on top.
import "../evora-home.css";
import "./products-showcase.css";

/**
 * 6thSense /products — the designed, human-facing product page.
 * Source of truth: DESIGN.md (repo root) + .context/design-reference/evora.html.
 *
 * Same approved dark-cinematic "Evora" direction as the homepage. Two products:
 *   Skin — the wearable tactile data glove. Ships / available now.
 *   Hand — custom tactile skin molded 1:1 onto a dexterous hand or gripper.
 *
 * There is no intake form on this page. The single Contact Us form lives at the
 * bottom of the home page (#contact); every CTA here links there.
 *
 * Honesty guardrails (DESIGN.md): we never name the partner hand — always
 * "a dexterous hand". No AI-generated product photos.
 */

export default function ProductsShowcase() {
  // Same floating flagship nav as the homepage (styles.css .nav-flagship).
  // No #story on this page, so useRevealNav keeps it always visible.
  const reduceMotion = useReducedMotion();
  const { className: navClassName } = useRevealNav({ reduceMotion: !!reduceMotion });

  useEffect(() => {
    const prev = document.title;
    document.title = "Products — Skin · Hand | 6thSense";
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
            {/* LOCAL-ONLY: People is hidden from the shipped nav (removed in the
                commit) but kept here for local dev. Remove before committing. */}
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
        {/* ---------- SKIN — 01, the wearable tactile glove (available now).
            NOTE: product NAMES were swapped per request — this glove is now
            "Skin"; the dexterous-hand composite below is now "Hand". ---------- */}
        <section className="ev-prow ev-plight ev-prow--first" id="skin">
          <div className="ev-pstage ev-pstage--hand">
            <span className="ev-badge ev-live">Available now</span>
            {/*
              Real photo of the glove, index raised (public/hero/glove/pose-hand.webp,
              the "1" frame). A genuine product photo, not a render or AI image
              (DESIGN.md "Imagery Rules"). Falls back to a "photo pending" panel.
            */}
            <img
              className="ev-pstage-img"
              src="/hero/glove/pose-hand.webp"
              alt="6thSense Skin — tactile data glove, index finger raised"
              style={{ objectFit: "contain", objectPosition: "center" }}
              onError={(e) => {
                e.currentTarget.style.display = "none";
                e.currentTarget.nextElementSibling?.removeAttribute("hidden");
              }}
            />
            <div className="ev-prod-ph" hidden aria-hidden="true">
              <div className="ev-prod-ph-mark">◍</div>
              <div className="ev-prod-ph-cap">Glove — photo pending</div>
            </div>
          </div>
          <div className="ev-pinfo">
            <div className="ev-idx">01 · The Skin</div>
            <h2 className="ev-ptitle">Skin</h2>
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
            <ul className="ev-specs">
              <li>6-axis IMU</li>
              <li>16-bit resolution</li>
              <li>USB-C / BLE 5.x</li>
              <li>µs-monotonic sync</li>
            </ul>
            <div className="ev-actions">
              {/* Single contact path: the Contact Us form on the home page. */}
              <a className="ev-pill ev-solid" href="/#contact">Talk to us</a>
            </div>
          </div>
        </section>

        {/* ---------- band: just the line, on the flying-dots background ---------- */}
        <section className="ev-band">
          <h3 className="ev-band-line">Every touch, localized.</h3>
        </section>

        {/* ---------- HAND — 02, the dexterous-hand + molded skin composite ---------- */}
        <section className="ev-prow ev-plight ev-flip" id="hand">
          {/* Split composite: LEFT the robotic dexterous-hand image, RIGHT the
              tactile-skin glove photo (both flat 2D). Add ?align for the panel. */}
          <SkinStage />
          <div className="ev-pinfo">
            <div className="ev-idx">02 · The Hand</div>
            <h2 className="ev-ptitle">Hand</h2>
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
              <a className="ev-pill ev-solid" href="/#contact">Talk to us</a>
            </div>
          </div>
        </section>

        <footer className="ev-footer">
          <span>6thSense · tactile hardware for dexterous robotics</span>
          <Link className="ev-footer-home" to="/">Skin · Hand</Link>
        </footer>
      </div>
    </div>
  );
}
