import { Link } from "react-router-dom";
import WorkspaceLink from "./WorkspaceLink.jsx";
import IntakeReviewLink from "./IntakeReviewLink.jsx";
import AdminLeads from "./AdminLeads.jsx";
import { useSession } from "./useSession.jsx";
import "./admin.css";

/**
 * Admin dashboard shell. The whole admin area is the leads CRM, so this is a
 * lightweight header (brand + who's signed in + logout) over the CRM screen.
 * Styled to DESIGN.md (dark cinematic, General Sans, Geist Mono, orange).
 */
export default function AdminDashboard() {
  const { user, logout } = useSession();
  return (
    <div className="admin-shell">
      <header className="admin-topbar">
        <div className="admin-topbar-brand">
          <span className="admin-wordmark">6THSENSE</span>
          <span className="admin-topbar-tag">Leads</span>
        </div>
        <div className="admin-topbar-right">
          <WorkspaceLink className="admin-btn admin-btn--ghost" />
          <Link className="admin-btn admin-btn--ghost" to="/portal/catalog">Catalog</Link>
          <Link className="admin-btn admin-btn--ghost" to="/portal/ops">Operations</Link>
          <IntakeReviewLink className="admin-btn admin-btn--ghost" />
          <span className="admin-topbar-user" title={user?.email}>
            {user?.name}
          </span>
          <button onClick={logout} className="admin-btn admin-btn--ghost">
            Sign out
          </button>
        </div>
      </header>
      <main className="admin-main">
        <AdminLeads />
      </main>
    </div>
  );
}
