import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useReducedMotion } from "framer-motion";

import { useRevealNav } from "../useRevealNav.js";
// Base .ev-home / .ev-frame / .ev-idx / .ev-footer system (DESIGN.md), then the
// people-page deltas on top.
import "../evora-home.css";
import "./people.css";

/**
 * 6thSense /people — the team page.
 *
 * Structure follows ltf.vc/team (centered hero, a 3-up grid of
 * portrait / name / role / bio cards, a "backed by" strip), rendered in the
 * 6thSense system from DESIGN.md rather than LTF's serif-on-white look:
 * General Sans + Geist Mono, warm orange #F0612A, the rounded frame floating on
 * the warm backdrop, alternating warm-light tones.
 *
 * Portraits: each card points at /people/<slug>.jpg and a shared CSS engraving
 * treatment (grayscale + contrast on a warm paper tile) unifies whatever photo
 * is dropped in into one cohesive black-and-white set — the trick that makes
 * LTF's illustrated portraits read as a single family. Until a photo exists the
 * card shows an initials-on-paper placeholder, so the page looks intentional now.
 *
 * Bios are drafted from the YC company page (ycombinator.com/companies/6thsense).
 */

const FOUNDERS = [
  {
    slug: "james",
    name: "James Baek",
    role: "Co-Founder & CEO",
    bio: "Founding engineer at Ibebu (Series C), Korea's first government-approved telemedicine platform, where he built the mobile product from zero. Scaled a paid coaching community past $50K MRR and exited a consumer brand at six figures.",
    linkedin: "",
  },
  {
    slug: "ronak",
    name: "Ronak Agarwal",
    role: "Co-Founder",
    bio: "Software engineer at DoorDash (backend platform) and Amazon (Middle-Mile optimization), and built payment-routing infrastructure at Qard. CS and Economics from Georgia Tech.",
    linkedin: "",
  },
  {
    slug: "alex",
    name: "Alex Hyungwoo Noh",
    role: "Co-Founder",
    bio: "Founded an enterprise security startup securing and monitoring MCP systems. Samsung Bio/ML scholar at 17 and served in the ROK Army. CS and Economics from the University of Chicago.",
    linkedin: "",
  },
  {
    slug: "matt",
    name: "Matt Wulff",
    role: "Co-Founder",
    bio: "Led Vision-Guided Robotics at Tesla at 20 and ran Tactile Data Capture at Mecka AI. Started his first company at 16 and builds rockets for fun. If it's hardware, he can build it.",
    linkedin: "",
  },
];

function initialsOf(name) {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? "";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

function LinkedInIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M20.45 20.45h-3.56v-5.57c0-1.33-.02-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.42v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.55V9h3.57v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.73v20.54C0 23.22.79 24 1.77 24h20.45c.98 0 1.78-.78 1.78-1.73V1.73C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

function PersonCard({ slug, name, role, bio, linkedin }) {
  return (
    <article className="pp-card">
      <div className="pp-portrait">
        {/* Placeholder sits behind; the photo (once added) covers it. If the
            file is missing the img hides itself and the placeholder shows. */}
        <div className="pp-portrait-ph" aria-hidden="true">
          <span className="pp-initials">{initialsOf(name)}</span>
        </div>
        <img
          className="pp-portrait-img"
          src={`/people/${slug}.jpg`}
          alt={`${name} — ${role}, 6thSense`}
          loading="lazy"
          onError={(e) => {
            e.currentTarget.style.display = "none";
          }}
        />
      </div>
      <div className="pp-namerow">
        <h2 className="pp-name">{name}</h2>
        {linkedin ? (
          <a
            className="pp-li"
            href={linkedin}
            target="_blank"
            rel="noreferrer noopener"
            aria-label={`${name} on LinkedIn`}
          >
            <LinkedInIcon />
          </a>
        ) : null}
      </div>
      <div className="pp-role">{role}</div>
      <p className="pp-bio">{bio}</p>
    </article>
  );
}

export default function PeoplePage() {
  const reduceMotion = useReducedMotion();
  // Same floating flagship nav as the homepage / products. No #story on this
  // page, so useRevealNav keeps it always visible.
  const { className: navClassName } = useRevealNav({ reduceMotion: !!reduceMotion });

  useEffect(() => {
    const prev = document.title;
    document.title = "People — 6thSense";
    return () => {
      document.title = prev;
    };
  }, []);

  return (
    <div className="ev-home ev-people">
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
        <section className="pp-hero">
          <div className="ev-idx">People</div>
          <h1 className="pp-title">The people building 6thSense</h1>
          <p className="pp-deck">
            A small team of hardware and software builders making the touch layer
            for dexterous robots — capture gloves and custom robot skin.
          </p>
        </section>

        <section className="pp-grid-wrap" aria-label="Team">
          <div className="pp-grid">
            {FOUNDERS.map((p) => (
              <PersonCard key={p.slug} {...p} />
            ))}
          </div>
        </section>

        <section className="pp-backed" aria-label="Backed by">
          <div className="ev-idx">Backed by</div>
          <div className="pp-backed-row">
            <img className="pp-yc" src="/logos/YC_LOGO_Keyed.png" alt="Y Combinator" />
            <p className="pp-backed-note">
              Y Combinator, partnered with Tyler Bosmeny.
            </p>
          </div>
        </section>

        <footer className="ev-footer">
          <span>6thSense · tactile hardware for dexterous robotics</span>
          <Link className="ev-footer-home" to="/">
            Hand · Nerve · Skin
          </Link>
        </footer>
      </div>
    </div>
  );
}
