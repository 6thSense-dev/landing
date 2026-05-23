import { NavLink, Route, Routes } from "react-router-dom";
import { ComingSoon } from "./ComingSoon.jsx";
import { FounderOverview } from "./FounderOverview.jsx";
import { FounderSettings } from "./FounderSettings.jsx";
import { useSession } from "./useSession.jsx";

export default function FounderDashboard() {
  const { user, logout } = useSession();
  return (
    <div className="portal-shell">
      <aside className="portal-sidebar">
        <div className="portal-sidebar-brand">6THSENSE</div>
        <div className="portal-sidebar-greeting">Hi, {user?.name}</div>
        <nav>
          <NavLink end to="/portal/founder">Overview</NavLink>
          <NavLink to="/portal/founder/meetings">Meetings</NavLink>
          <NavLink to="/portal/founder/followups">Followups</NavLink>
          <NavLink to="/portal/founder/whiteboard">Whiteboard</NavLink>
          <NavLink to="/portal/founder/settings">Settings</NavLink>
        </nav>
        <button onClick={logout} className="portal-logout-btn">Logout</button>
      </aside>
      <main className="portal-main">
        <Routes>
          <Route index element={<FounderOverview />} />
          <Route path="meetings" element={<ComingSoon name="Meetings" />} />
          <Route path="followups" element={<ComingSoon name="Followups" />} />
          <Route path="whiteboard" element={<ComingSoon name="Whiteboard" />} />
          <Route path="settings" element={<FounderSettings />} />
        </Routes>
      </main>
    </div>
  );
}
