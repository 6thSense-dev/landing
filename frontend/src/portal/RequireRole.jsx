import { Navigate, Outlet } from "react-router-dom";
import { roleHome } from "./roleHome.js";
import { useSession } from "./useSession.jsx";

/**
 * Gate a route subtree on the session's role.
 *
 * `role` accepts a string — unchanged behaviour for every existing call site —
 * or an array, because /portal/catalog is reachable by several roles and four
 * copies of the same <Route> element would be four places to forget one.
 *
 * This is a NAVIGATION guard, not a security boundary. It decides what to
 * render; it does not decide what data exists. Every catalog route is gated
 * again server-side, and a guest's clip records are redacted before they are
 * serialised — so a guest who edits this file in devtools reaches a page with
 * nothing on it.
 */
export function RequireRole({ role }) {
  const { user } = useSession();
  if (!user) return null;
  const allowed = Array.isArray(role) ? role : [role];
  if (!allowed.includes(user.role)) {
    return <Navigate to={roleHome(user.role)} replace />;
  }
  return <Outlet />;
}
