import { useEffect } from "react";
import { Link } from "react-router-dom";

import { getLegalPage, legalContactEmail } from "../seo/legal.js";
import "./product.css";

/**
 * Renders a legal page (/privacy, /terms) from the shared manifest
 * (src/seo/legal.js). The same manifest drives the build-time crawlable HTML
 * (scripts/seoPrerenderPlugin.js), so client and crawler see the same content.
 *
 * Reuses the light-paper product-page layout (product.css) — same nav, type,
 * and spacing as the secondary product pages — so no new styling system is
 * introduced. A section `body` may be a string or an array of paragraphs;
 * `contact: true` renders the ops@6thsense.dev mailto affordance.
 */
export default function LegalPage({ slug }) {
  const page = getLegalPage(slug);

  useEffect(() => {
    if (!page) return;
    const prevTitle = document.title;
    document.title = page.title;
    return () => {
      document.title = prevTitle;
    };
  }, [page]);

  if (!page) {
    return (
      <main className="product-page product-page--empty">
        <p>Page not found.</p>
        <Link to="/">Back to home</Link>
      </main>
    );
  }

  const paragraphs = (body) => (Array.isArray(body) ? body : [body]);

  return (
    <div className="product-page">
      <header className="product-nav">
        <Link className="product-wordmark" to="/" aria-label="6thSense home">
          <img className="product-logo" src="/logos/Logo_Alpha.png" alt="" aria-hidden="true" />
          <span>6THSENSE</span>
        </Link>
        {/* Same three affordances every page carries (matches SiteNav / ProductPage). */}
        <nav className="product-navlinks" aria-label="Primary">
          <Link className="product-navlink" to="/products">Products</Link>
          <Link className="product-navlink" to="/people">People</Link>
          <Link className="product-login" to="/login">Partner login</Link>
        </nav>
      </header>

      <main className="product-main">
        <article className="product-article">
          <p className="product-kicker">{page.kicker}</p>
          <h1 className="product-h1">{page.h1}</h1>
          {page.updated && (
            <p className="product-updated">Last updated {page.updated}</p>
          )}
          <p className="product-intro">{page.intro}</p>

          {page.sections.map((s, i) => (
            <section className="product-section" key={i}>
              <h2 className="product-h2">{s.h2}</h2>
              {s.body &&
                paragraphs(s.body).map((p, k) => (
                  <p className="product-body" key={k}>
                    {p}
                  </p>
                ))}
              {s.items && (
                <ul className="product-list">
                  {s.items.map((li, j) => (
                    <li key={j}>{li}</li>
                  ))}
                </ul>
              )}
              {s.contact && (
                <p className="product-body">
                  <a className="product-related-link" href={`mailto:${legalContactEmail}`}>
                    {legalContactEmail}
                  </a>
                </p>
              )}
            </section>
          ))}
        </article>

        {page.related && page.related.length > 0 && (
          <nav className="product-related" aria-label="Related pages">
            {page.related.map((r) => (
              <Link className="product-related-link" to={r.href} key={r.href}>
                {r.label}
              </Link>
            ))}
          </nav>
        )}
      </main>
    </div>
  );
}
