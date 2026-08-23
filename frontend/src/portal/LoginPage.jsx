import { useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { TactileField } from "../TactileField.jsx";
import { roleHome, safeNext } from "./roleHome.js";
import { useSession } from "./useSession.jsx";

export default function LoginPage() {
  const { status, user, login } = useSession();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // Named `identifier`, not `email`, because it now legitimately holds one of
  // two things: a partner's email address, or the `guest` demo username.
  // Calling it `email` is how the next person reintroduces an email-only
  // assumption in a validator.
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (status === "authed" && user) {
    const next = safeNext(params.get("next"), user.role) || roleHome(user.role);
    return <Navigate to={next} replace />;
  }

  async function onSubmit(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const result = await login(identifier, password);
    setBusy(false);
    if (!result.ok) {
      if (result.status === 0) {
        setError("Couldn't reach the server. Please try again.");
      } else if (result.status === 429) {
        setError("Too many attempts. Please wait a minute and try again.");
      } else {
        // Says nothing about which half was wrong: the constant-time decoy
        // verify on the server exists precisely so the response does not leak
        // whether an account exists, and the copy must not undo that.
        setError("Invalid login. Check the email or username and the password.");
      }
      return;
    }
    const next = safeNext(params.get("next"), result.user.role) || roleHome(result.user.role);
    navigate(next, { replace: true });
  }

  return (
    <main className="portal-login-wrap">
      <TactileField />
      <form className="portal-login-card" onSubmit={onSubmit} noValidate>
        <h1 className="portal-login-title">Partner login</h1>
        <label htmlFor="login-identifier">Email or username</label>
        {/*
          type="text", not type="email": `guest` is a legal value here, and a
          type="email" input reports it as invalid to assistive technology and
          offers the wrong mobile keyboard. The form already carries noValidate,
          so submission was never actually blocked — the input was only lying to
          the user. inputMode="email" keeps the @-friendly keyboard for the
          common case. autoComplete="username" is the correct token for a field
          that accepts either; password managers already treat it as the account
          field, so saved logins keep working.

          autoCapitalize/autoCorrect/spellCheck are the reason this is more than
          a label swap: iOS autocapitalises the first character of a text input,
          and `Guest` would 401.
        */}
        <input
          id="login-identifier"
          type="text"
          inputMode="email"
          autoComplete="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck="false"
          value={identifier}
          onChange={(e) => setIdentifier(e.target.value)}
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
