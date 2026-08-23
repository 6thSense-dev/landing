import React, { useCallback, useState } from "react";
import { Link } from "react-router-dom";
import { LogOut } from "lucide-react";

import { useSession } from "../portal/useSession.jsx";

/**
 * CatalogTopBar — the catalog's page chrome.
 *
 * Three jobs, left to right:
 *
 *  1. Say whose product this is. The mark + wordmark, treated exactly as
 *     SiteNav treats them on dark, linking home. Before this the catalog
 *     carried no logo at all.
 *  2. Say where you are. The collection name is the current context, which
 *     is what frees the masthead below from spending its display line on the
 *     word "Catalog".
 *  3. Say who you are, and let you stop being them. `/portal/catalog` is the
 *     only page a guest can reach and it shipped with NO way to sign out
 *     anywhere in the product. This is that way.
 *
 * Sticky at z-index 30: above the sticky filter bar (20), far below the clip
 * modal (900), so it never paints over an open clip.
 *
 * @param {string|null} [props.collectionName]     rendered as the current context.
 * @param {string|null} [props.collectionVersion]  mono chip beside the name.
 * @param {boolean}     [props.pending]  manifest still in flight — the context slot
 *   renders as a fixed-size placeholder so the bar does not resize when it lands.
 */
export default function CatalogTopBar({
  collectionName = null,
  collectionVersion = null,
  pending = false,
}) {
  const { user, logout } = useSession();
  const [busy, setBusy] = useState(false);

  /*
   * `logout()` already dispatches SESSION_CHANGED_EVENT, and
   * catalog/useCatalog.js listens for it at module scope and calls
   * bindCatalogIdentity(null) — which drops the manifest, the clip cache and
   * every live presigned URL. So there is deliberately no clearCatalogCache()
   * call here: that export DOES exist, but it also notify()s its subscribers,
   * which would push this still-mounted page into `loading` and fire one more
   * manifest GET against a session we just ended. The event path clears the
   * same state without waking anybody up.
   */
  const onLogout = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      await logout();
    } finally {
      // RequireAuth redirects to /login the moment the session goes anon, so
      // in practice this lands on an unmounted component (a no-op in React 18)
      // — it matters only when the POST fails and the page stays put.
      setBusy(false);
    }
  }, [busy, logout]);

  const who = user ? user.name || user.email : null;

  return (
    <header className="cat-topbar">
      <div className="cat-topbar__inner">
        {/* .cat-wordmark / .cat-wordmark__mark are catalog.css's shared
            component, so the bar renders the brand at exactly the size,
            tracking and weight the rest of the system does. */}
        <Link className="cat-wordmark" to="/" aria-label="6thSense home">
          {/* Same source and same sizing decision as SiteNav: the PNG is
              1024x1024 and this renders at ~23 CSS px, so the 128px webp is the
              real source and the PNG is only the fallback. 128/23 = 5.5x, so
              the dot cluster stays crisp at 2x and 3x. */}
          <img
            className="cat-wordmark__mark"
            src="/logos/Logo_Alpha.png"
            srcSet="/logos/Logo_Alpha-128.webp"
            width="24"
            height="24"
            alt=""
            aria-hidden="true"
          />
          <span>6THSENSE</span>
        </Link>

        <span className="cat-topbar__rule" aria-hidden="true" />

        <p className="cat-topbar__context">
          {pending ? (
            <span className="cat-topbar__context-pending" aria-hidden="true" />
          ) : collectionName ? (
            <>
              <span className="cat-topbar__collection" title={collectionName}>
                {collectionName}
              </span>
              {collectionVersion ? (
                <span className="cat-topbar__version">v{collectionVersion}</span>
              ) : null}
            </>
          ) : (
            <span className="cat-topbar__collection">Catalog</span>
          )}
        </p>

        <div className="cat-topbar__session">
          {user ? (
            <span className="cat-topbar__identity">
              {/* The role, not just the name: a guest and a customer see
                  materially different documents, and which one you are looking
                  at is worth stating on every screen. */}
              {user.role ? <span className="cat-topbar__role">{user.role}</span> : null}
              {who ? (
                <span className="cat-topbar__who" title={user.email || undefined}>
                  {who}
                </span>
              ) : null}
            </span>
          ) : null}

          <button
            type="button"
            className="cat-topbar__logout"
            onClick={onLogout}
            disabled={busy}
          >
            <LogOut size={15} aria-hidden="true" />
            <span>{busy ? "Signing out…" : "Log out"}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
