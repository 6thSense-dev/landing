import { Navigate, Outlet } from "react-router-dom";
import { useSession } from "./useSession.jsx";

export function RequireRole({ role }) {
  const { user } = useSession();
  if (!user) return null;
  if (user.role !== role) {
    return <Navigate to={`/portal/${user.role}`} replace />;
  }
  return <Outlet />;
}
