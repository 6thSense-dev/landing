import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useSession } from "./useSession.js";

export function RequireAuth() {
  const { status } = useSession();
  const location = useLocation();
  if (status === "loading") return <div className="portal-loading" aria-hidden />;
  if (status === "anon") {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  if (status === "error") {
    return (
      <div className="portal-error">
        Couldn't reach the server. Please refresh.
      </div>
    );
  }
  return <Outlet />;
}
