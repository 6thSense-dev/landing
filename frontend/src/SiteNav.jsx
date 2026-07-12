import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

const LINKS = [
  { to: "/products", label: "Products" },
  { to: "/people", label: "People" },
  { to: "/login", label: "Partner login" },
];

/**
 * The one shared top nav (wordmark + Products/People/Partner login), used by
 * the home page, /products, and /people. Below the mobile breakpoint the
 * links collapse behind a hamburger toggle instead of wrapping the pill onto
 * multiple rows.
 *
 * @param {string}  className    from useRevealNav — drives the show/hide pill state
 * @param {boolean} [homeAnchor] home page only: wordmark is a same-page "scroll
 *                                to top" anchor instead of a router Link.
 */
export default function SiteNav({ className, homeAnchor = false }) {
  const [open, setOpen] = useState(false);
  const headerRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onPointerDown = (e) => {
      if (headerRef.current && !headerRef.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  const wordmark = (
    <>
      <img className="nav-logo" src="/logos/Logo_Alpha.png" alt="" aria-hidden="true" />
      <span className="nav-logo-text">6THSENSE</span>
    </>
  );

  return (
    <header className={className} role="banner" ref={headerRef}>
      <nav className="nav-flagship-inner" aria-label="Primary">
        {homeAnchor ? (
          <a className="wordmark wordmark-on-dark" href="#top" aria-label="6thSense home">
            {wordmark}
          </a>
        ) : (
          <Link className="wordmark wordmark-on-dark" to="/" aria-label="6thSense home">
            {wordmark}
          </Link>
        )}

        <button
          type="button"
          className="nav-burger"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="nav-links-menu"
          onClick={() => setOpen((v) => !v)}
        >
          <span className="nav-burger-bar" />
          <span className="nav-burger-bar" />
          <span className="nav-burger-bar" />
        </button>

        <div
          id="nav-links-menu"
          className={`nav-links nav-links-on-dark${open ? " nav-links--open" : ""}`}
        >
          {LINKS.map((l) => (
            <Link
              key={l.to}
              to={l.to}
              className="nav-cta nav-cta-on-dark"
              onClick={() => setOpen(false)}
            >
              {l.label}
            </Link>
          ))}
        </div>
      </nav>
    </header>
  );
}
