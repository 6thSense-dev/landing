import { Link } from "react-router-dom";

/**
 * The one shared top nav, on every page (homepage, /products, /product/*).
 *
 * Matches the approved Evora reference (.context/design-reference/evora.html):
 * wordmark left, product/section links centre, and on the right a buyer CTA
 * plus a small Partner login. Per the brief every page must expose:
 *   - a Products link,
 *   - a buyer CTA ("Reserve Nerve" or "Talk to us"),
 *   - a small Partner login.
 *
 * @param {object}  props
 * @param {boolean} [props.wordmarkIsHome]  render the wordmark as a Link to "/"
 *                                          (false on the homepage itself, where
 *                                          it is a plain span).
 * @param {string}  [props.cta]             buyer CTA label ("Reserve Nerve"
 *                                          default, or "Talk to us").
 * @param {string}  [props.ctaHref]         where the CTA points (an in-page
 *                                          anchor on pages that have the form,
 *                                          otherwise /products#reserve).
 * @param {Array<{label:string, href:string}>} [props.links]
 *                                          centre links; each href may be an
 *                                          in-page anchor or a route.
 */
export default function SiteNav({
  wordmarkIsHome = true,
  cta = "Reserve Nerve",
  ctaHref = "/products#reserve",
  links,
}) {
  const centreLinks = links ?? [
    { label: "Products", href: "/products" },
    { label: "Hand", href: "/products#hand" },
    { label: "Nerve", href: "/products#nerve" },
    { label: "Skin", href: "/products#skin" },
  ];

  const Wordmark = (
    <>
      <img className="ev-wm-logo" src="/logos/Logo_Alpha.png" alt="" aria-hidden="true" />
      6thSense
    </>
  );

  return (
    <nav className="ev-nav" aria-label="Primary">
      {wordmarkIsHome ? (
        <Link className="ev-wm" to="/" aria-label="6thSense home">
          {Wordmark}
        </Link>
      ) : (
        <span className="ev-wm">{Wordmark}</span>
      )}

      <div className="ev-nav-c">
        {centreLinks.map((l) =>
          l.href.startsWith("/") && !l.href.includes("#") ? (
            <Link key={l.label} to={l.href}>{l.label}</Link>
          ) : (
            <a key={l.label} href={l.href}>{l.label}</a>
          )
        )}
      </div>

      <div className="ev-nav-r">
        {ctaHref.startsWith("/") && !ctaHref.includes("#") ? (
          <Link className="ev-pill ev-solid" to={ctaHref}>{cta}</Link>
        ) : (
          <a className="ev-pill ev-solid" href={ctaHref}>{cta}</a>
        )}
        {/* Small, low-emphasis Partner login (distinct from the buyer CTA). */}
        <Link className="ev-pill ev-dark ev-nav-login" to="/login">Partner login</Link>
      </div>
    </nav>
  );
}
