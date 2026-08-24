import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import AdminDashboard from "./AdminDashboard.jsx";
import CustomerHome from "./CustomerHome.jsx";
import FounderDashboard from "./FounderDashboard.jsx";
import InvestorHome from "./InvestorHome.jsx";
import { RequireAuth } from "./RequireAuth.jsx";
import { RequireRole } from "./RequireRole.jsx";
import { CATALOG_ROLES, roleHome } from "./roleHome.js";
import { useSession } from "./useSession.jsx";

// Lazily loaded: the catalog pulls in five tab components, a hand-rolled SVG
// chart layer and ~2900 lines of its own CSS. A founder who never opens it
// should never download it.
const CatalogPage = lazy(() => import("../catalog/CatalogPage.jsx"));

function RoleHomeRedirect() {
  const { user, status } = useSession();
  if (status === "loading") return <div className="portal-loading" aria-hidden />;
  if (!user) return <Navigate to="/login" replace />;
  // Not `/portal/${user.role}`: a guest has no dashboard of their own, and
  // sending them to /portal/guest would fall through to the `*` route below
  // and redirect to /portal/guest again — a loop, not a 404.
  return <Navigate to={roleHome(user.role)} replace />;
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
        <Route element={<RequireRole role={CATALOG_ROLES} />}>
          <Route
            path="catalog"
            element={
              <Suspense fallback={<div className="portal-loading" aria-hidden />}>
                {/* No `onRequestAccess`, deliberately. CollectionHeader builds the
                    CTA's destination itself — a mailto to `collection.vendor.contact`
                    with the collection id in the subject — and renders no button at
                    all if there is neither a handler nor a contact. Passing a no-op
                    here would put the button back and take the destination away,
                    which is the state this page shipped in once already. Pass a real
                    handler only when there is a real lead form to route to. */}
                <CatalogPage />
              </Suspense>
            }
          />
        </Route>
        <Route index element={<RoleHomeRedirect />} />
        <Route path="*" element={<RoleHomeRedirect />} />
      </Route>
    </Routes>
  );
}
