import { useWorkspacePreview } from "./WorkspaceContext.jsx";
import { useSession } from "./useSession.jsx";

export default function InvestorHome() {
  const { user, logout } = useSession();
  const preview = useWorkspacePreview();
  return (
    <div className="portal-simple-shell">
      <header className="portal-simple-bar">
        <span className="portal-simple-name">{user?.name}</span>
        {!preview && <button onClick={logout} className="portal-logout-btn">Logout</button>}
      </header>
      <main>
        <h1>Investor portal</h1>
        <p>Welcome to the 6thSense partner portal. More coming soon.</p>
      </main>
    </div>
  );
}
