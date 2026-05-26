import { useSession } from "./useSession.jsx";

export default function CustomerHome() {
  const { user, logout } = useSession();
  return (
    <div className="portal-simple-shell">
      <header className="portal-simple-bar">
        <span className="portal-simple-name">{user?.name}</span>
        <button onClick={logout} className="portal-logout-btn">Logout</button>
      </header>
      <main>
        <h1>Customer portal</h1>
        <p>Welcome to the 6thSense partner portal. More coming soon.</p>
      </main>
    </div>
  );
}
