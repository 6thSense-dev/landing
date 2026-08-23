/**
 * Where each role lands after login, which shared routes it may reach, and
 * which `?next=` values are safe to honour.
 *
 * Before the catalog existed, "the home page for role R" was always
 * `/portal/${R}`, and "a safe next" was always "a path under it" — so
 * PortalApp, RequireRole and LoginPage each rebuilt those two rules inline and
 * always agreed. The catalog breaks both: `guest`'s home is `/portal/catalog`,
 * and that route is shared by five roles. Three inline copies of a rule that
 * now has exceptions is three chances to bounce a founder off a link a
 * colleague sent them.
 *
 * So the rules live here, once.
 */

/**
 * Roles that may reach /portal/catalog.
 *
 * MIRRORS the role gate on `GET /api/catalog`. The server's list is the one
 * that decides; this one only decides what renders. If they drift the user
 * sees an empty page instead of a 403 — annoying, never a leak.
 *
 * `investor` is in the list deliberately. The API grades a record by whether
 * the role may read *originals*, not by the role's name, and an investor may
 * not — so an investor is handed exactly the same reduced document a guest is.
 * That makes including them a one-word change with no new redaction surface,
 * and leaving them out would mean the server grants access to a route the UI
 * refuses to render, which is drift in the worse direction.
 */
export const CATALOG_ROLES = ["guest", "investor", "customer", "founder", "admin"];

/** Portal routes not owned by a single role. */
const SHARED_ROUTES = [{ path: "/portal/catalog", roles: CATALOG_ROLES }];

/** Roles whose home is not `/portal/<role>`. */
const HOME_OVERRIDES = { guest: "/portal/catalog" };

/** The path a freshly-authenticated user of `role` should land on. */
export function roleHome(role) {
  if (!role) return "/login";
  return HOME_OVERRIDES[role] || `/portal/${role}`;
}

/** Every portal path prefix `role` is allowed to be sent to. */
export function allowedPrefixes(role) {
  const prefixes = [`/portal/${role}`];
  for (const shared of SHARED_ROUTES) {
    if (shared.roles.includes(role)) prefixes.push(shared.path);
  }
  return prefixes;
}

/**
 * Validate a `?next=` value for `role`, returning a normalised in-app path or
 * null.
 *
 * The old inline version gated on `rawNext.startsWith("/portal/" + role)`,
 * which rejects `/portal/catalog` for every role — including the guest whose
 * home it is. This one asks the real question: is this an in-app portal path
 * inside a subtree this role can actually reach?
 *
 * Everything hostile is rejected by handing the string to the platform's own
 * URL parser and demanding the result still sit on the base origin. That is
 * what catches the cases a `startsWith` check misses:
 *
 *   "//evil.com"                -> origin evil.com                    -> null
 *   "/\evil.com"                -> a backslash is a slash to a URL
 *                                  parser, so this is "//evil.com"    -> null
 *   "https://evil.com/portal/x" -> origin evil.com                    -> null
 *   "javascript:alert(1)"       -> opaque origin                      -> null
 *   "/portal/../evil"           -> normalises to /evil                -> null
 *   "/portal/founderX"          -> not a segment of /portal/founder   -> null
 *   "/portal/catalog?clip=c1"   -> allowed for any catalog role
 *
 * The value returned is the parser's own `pathname + search + hash`, never the
 * caller's string, so nothing un-normalised reaches `navigate()`.
 */
export function safeNext(rawNext, role) {
  if (typeof rawNext !== "string" || rawNext === "" || !role) return null;
  // Whitespace and C0/C1 control characters appear in a `next=` only to create
  // a parser differential between us and the browser. There is no legitimate
  // one, and the WHATWG parser strips some of them before we would see them.
  if (/[\s\u0000-\u001f\u007f-\u009f]/.test(rawNext)) return null;

  let url;
  try {
    // A base that can never be a real origin, so "still on the base origin"
    // and "is a relative in-app path" mean the same thing.
    url = new URL(rawNext, "https://portal.invalid");
  } catch {
    return null;
  }
  if (url.origin !== "https://portal.invalid") return null;

  const path = url.pathname;
  if (!path.startsWith("/portal/")) return null;
  // Match whole segments: /portal/founderX must not pass as /portal/founder.
  const ok = allowedPrefixes(role).some((p) => path === p || path.startsWith(`${p}/`));
  return ok ? `${url.pathname}${url.search}${url.hash}` : null;
}
