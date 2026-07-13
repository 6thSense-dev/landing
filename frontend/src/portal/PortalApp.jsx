import { Navigate, Route, Routes } from "react-router-dom";
import AdminDashboard from "./AdminDashboard.jsx";
import CustomerHome from "./CustomerHome.jsx";
import FounderDashboard from "./FounderDashboard.jsx";
import InvestorHome from "./InvestorHome.jsx";
import { RequireAuth } from "./RequireAuth.jsx";
import { RequireRole } from "./RequireRole.jsx";
import { useSession } from "./useSession.jsx";

function RoleHomeRedirect() {
  const { user, status } = useSession();
  if (status === "loading") return <div className="portal-loading" aria-hidden />;
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={`/portal/${user.role}`} replace />;
}

export default function PortalApp() {
  return (
    <Routes>
      <Route element={<RequireAuth />}>
        <Route element={<RequireRole role="admin" />}>
          <Route path="admin/*" element={<AdminDashboard />} />
        </Route>
        <Route element={<RequireRole role="founder" />}>
          <Route path="founder/*" element={<FounderDashboard />} />
        </Route>
        <Route element={<RequireRole role="customer" />}>
          <Route path="customer" element={<CustomerHome />} />
        </Route>
        <Route element={<RequireRole role="investor" />}>
          <Route path="investor" element={<InvestorHome />} />
        </Route>
        <Route index element={<RoleHomeRedirect />} />
        <Route path="*" element={<RoleHomeRedirect />} />
      </Route>
    </Routes>
  );
}
