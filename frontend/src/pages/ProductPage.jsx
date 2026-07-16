import { useEffect } from "react";
import { Link } from "react-router-dom";

import { getProductPage } from "../seo/pages.js";
import "./product.css";

/**
 * Renders a secondary product page from the shared manifest (src/seo/pages.js).
 * The same manifest drives the build-time crawlable HTML (seoPrerenderPlugin.js),
 * so client and crawler see the same content.
 *
 * These pages are intentionally NOT linked from the homepage yet — they exist for
 * crawling/indexing and are reachable by URL + sitemap. Nav promotion comes later.
 */
export default function ProductPage({ slug }) {
  const page = getProductPage(slug);

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

  return (
    <div className="product-page">
      <header className="product-nav">
        <Link className="product-wordmark" to="/" aria-label="6thSense home">
          <img className="product-logo" src="/logos/Logo_Alpha.png" alt="" aria-hidden="true" />
          <span>6THSENSE</span>
        </Link>
        {/* Shared site nav (matches SiteNav): Products / People / Partner login.
            No "Reserve Nerve" — the Nerve pre-order flow is retired (DESIGN.md). */}
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
          <p className="product-intro">{page.intro}</p>

          {page.sections.map((s, i) => (
            <section className="product-section" key={i}>
              <h2 className="product-h2">{s.h2}</h2>
              {s.body && <p className="product-body">{s.body}</p>}
              {s.items && (
                <ul className="product-list">
                  {s.items.map((li, j) => (
                    <li key={j}>{li}</li>
                  ))}
                </ul>
              )}
            </section>
          ))}

          {page.cards && (
            <div className="product-cards">
              {page.cards.map((c) => (
                <Link className="product-card" to={c.href} key={c.href}>
                  <span className="product-card-title">{c.title}</span>
                  <span className="product-card-blurb">{c.blurb}</span>
                </Link>
              ))}
            </div>
          )}
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
