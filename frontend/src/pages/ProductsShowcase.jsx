import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useReducedMotion } from "framer-motion";

import SiteNav from "../SiteNav.jsx";
import { useRevealNav } from "../useRevealNav.js";
// Skin section: robotic image + glove photo composite (2D, no WebGL). Add
// ?align to the /products URL for the on-page alignment panel.
import SkinStage from "../lib/SkinStage.jsx";
// Rig section: Eye2 is de-emphasized to a clean "In development" card (no live
// 3D — the CAD looked weak and WebGL was flaky) until a real product photo exists.
import { TactileField } from "../TactileField.jsx";
// Prototype: pinned scroll-scrubbed "morph" hero (glove -> hand -> Eye2).
// Mounted only when the URL has ?morph so the shipped page is untouched.
import ProductMorph from "../lib/ProductMorph.jsx";
// One-shot fade+rise as each row scrolls into view (tasteful, non-hijacking).
import Reveal from "../lib/Reveal.jsx";
// v2: the new Apple-style scroll page (aurora + product scenes). /products?v2 only.
import ProductsV2 from "./ProductsV2.jsx";
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

/** Small inline download glyph (no icon-lib import needed) for the CAD links. */
function DownloadGlyph() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v12" />
      <path d="M7 11l5 5 5-5" />
      <path d="M4 20h16" />
    </svg>
  );
}

export default function ProductsShowcase() {
  // v2 preview: /products?v2 renders the new Apple-style scroll page. The query
  // param is constant for this mount, so the early return is hook-safe.
  if (typeof window !== "undefined" && new URLSearchParams(window.location.search).has("v2")) {
    return <ProductsV2 />;
  }
  // Same floating flagship nav as the homepage (styles.css .nav-flagship).
  // No #story on this page, so useRevealNav keeps it always visible.
  const reduceMotion = useReducedMotion();
  const { className: navClassName } = useRevealNav({ reduceMotion: !!reduceMotion });
  // Prototype gate: /products?morph shows the scroll-morph hero above the rows.
  const showMorph =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).has("morph");

  useEffect(() => {
    const prev = document.title;
    document.title = "Products — Skin · Hand · Eye2 | 6thSense";
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
      <SiteNav className={navClassName} />

      {/* Prototype: scroll-morph hero (glove -> hand -> Eye2). ?morph only. */}
      {showMorph && <ProductMorph />}

      <div className="ev-frame">
        {/* ---------- SKIN — 01, the wearable tactile glove (available now).
            NOTE: product NAMES were swapped per request — this glove is now
            "Skin"; the dexterous-hand composite below is now "Hand". ---------- */}
        <Reveal as="section" className="ev-prow ev-plight ev-prow--first" id="skin">
          <div className="ev-pstage ev-pstage--hand">
            <span className="ev-badge ev-live">Available now</span>
            {/*
              Product render of the glove, index raised
              (public/hero/glove/pose-hand.webp, the "1" frame). This is a CAD/
              product render — real product photos are pending a shoot
              (tasks/product-photo-shotlist.md). Do NOT label it a photo.
            */}
            <img
              className="ev-pstage-img"
              src="/hero/glove/pose-hand.webp"
              alt="6thSense Skin — tactile data glove, index finger raised"
              style={{ objectFit: "contain", objectPosition: "center" }}
            />
            <div className="ev-prod-ph" hidden aria-hidden="true">
              <div className="ev-prod-ph-mark">◍</div>
              <div className="ev-prod-ph-cap">Glove — image pending</div>
            </div>
          </div>
          <div className="ev-pinfo">
            <div className="ev-idx">01 · The Skin</div>
            <h2 className="ev-ptitle">Skin</h2>
            <p className="ev-oneliner">A data glove that feels. Every touch, recorded as force.</p>
            {/*
              Glove specs verified against the 6thSense-authored glove spec sheet
              (gbrain: drive/ronak/02-product/01-glove/2026-07-06-spec-6thSense-tactile-glove-spec-sheet):
              440 channels (20×22 grid), 16-bit (~0.01 N), <1 ms response, ~200 Hz
              over USB-C / BLE 5.x, 6-axis IMU, device-side µs-monotonic timestamp.
            */}
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
        </Reveal>

        {/* ---------- band: just the line, on the flying-dots background ---------- */}
        <Reveal as="section" className="ev-band">
          <h3 className="ev-band-line">Every touch, localized.</h3>
        </Reveal>

        {/* ---------- HAND — 02, the dexterous-hand + molded skin composite ---------- */}
        <Reveal as="section" className="ev-prow ev-plight ev-flip" id="hand">
          {/* Split composite: LEFT the robotic dexterous-hand image, RIGHT the
              tactile-skin glove render (both flat 2D). Add ?align for the panel. */}
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
        </Reveal>

        {/* ---------- band: the capture line, on the flying-dots background ---------- */}
        <Reveal as="section" className="ev-band">
          <h3 className="ev-band-line">Sees what the hand feels.</h3>
        </Reveal>

        {/* ---------- RIG — 03, the Eye2 egocentric capture camera. White+black
            enclosure render (public/eye2-hero.png), plus the raw .stl parts. ---------- */}
        <Reveal as="section" className="ev-prow ev-plight" id="rig">
          <div className="ev-pstage ev-pstage--hand">
            <span className="ev-badge ev-live">Available now</span>
            <img
              className="ev-pstage-img"
              src="/eye2-hero.png"
              alt="6thSense Eye2 — egocentric capture camera, white and black enclosure render"
              style={{ objectFit: "contain", objectPosition: "center" }}
            />
            <span className="ev-pstage-cap">Eye2 enclosure · render</span>
          </div>
          <div className="ev-pinfo">
            <div className="ev-idx">03 · The Rig</div>
            <h2 className="ev-ptitle">Eye2</h2>
            <p className="ev-oneliner">
              The egocentric camera that sees what the hand feels. First-person
              video, synced to touch frame for frame.
            </p>
            {/*
              Eye2 specs verified against the 6thSense-authored Eye2 spec sheet
              (gbrain: drive/ronak/02-product/02-camera/eye2/2026-07-15-spec-eye2-camera-wireless;
              cross-checked with the Kosha stereo-camera sales agreement). Eye2 is
              a GLOBAL-SHUTTER STEREO camera (4000×1200 @ 30fps, depth recovered
              via stereo disparity) — NOT an RGB+depth sensor. The old "RGB + depth"
              line implied a RealSense-style depth camera, which is wrong; replaced.
            */}
            <ul className="ev-specs">
              <li>Egocentric mount</li>
              <li>Global-shutter stereo</li>
              <li>Synced to touch</li>
              <li>Printed enclosure</li>
            </ul>
            <div className="ev-actions">
              <a className="ev-pill ev-solid" href="/#contact">Talk to us</a>
            </div>
            {/* Raw CAD download: the two printed enclosure halves as .stl. */}
            <div className="ev-downloads">
              <span className="ev-dl-label">Download the enclosure (CAD)</span>
              <div className="ev-dl-row">
                <a className="ev-dl" href="/eye2-main-frame.stl" download>
                  <DownloadGlyph /> Main frame .stl
                </a>
                <a className="ev-dl" href="/eye2-back-case.stl" download>
                  <DownloadGlyph /> Back case .stl
                </a>
              </div>
            </div>
          </div>
        </Reveal>

        <footer className="ev-footer">
          <span>6thSense · tactile hardware for dexterous robotics</span>
          <span className="ev-footer-legal">
            <Link to="/privacy">Privacy</Link>
            <Link to="/terms">Terms</Link>
          </span>
          <Link className="ev-footer-home" to="/">Skin · Hand · Eye2</Link>
        </footer>
      </div>
    </div>
  );
}
