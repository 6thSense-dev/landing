import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useSession } from "./useSession.jsx";

function safeNext(rawNext, role) {
  if (!rawNext) return null;
  if (!rawNext.startsWith("/portal/")) return null;
  if (!rawNext.startsWith(`/portal/${role}`)) return null;
  return rawNext;
}

export default function LoginPage() {
  const { status, user, login } = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (status === "authed" && user) {
    const next = safeNext(params.get("next"), user.role) || `/portal/${user.role}`;
    return <Navigate to={next} replace />;
  }

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const result = await login(email, password);
    setBusy(false);
    if (!result.ok) {
      if (result.status === 0) {
        setError("Couldn't reach the server. Please try again.");
      } else if (result.status === 429) {
        setError("Too many attempts. Please wait a minute and try again.");
      } else {
        setError("Invalid email or password.");
      }
      return;
    }
    const next = safeNext(params.get("next"), result.user.role) || `/portal/${result.user.role}`;
    navigate(next, { replace: true });
  }

  return (
    <main className="portal-login-wrap">
      <form className="portal-login-card" onSubmit={onSubmit} noValidate>
        <h1 className="portal-login-title">Partner login</h1>
        <label htmlFor="login-email">Email</label>
        <input
          id="login-email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <label htmlFor="login-password">Password</label>
        <input
          id="login-password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="portal-login-status" role="status" aria-live="polite">
          {error || " "}
        </p>
      </form>
    </main>
  );
}
