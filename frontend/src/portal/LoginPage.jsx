import { useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import "../catalog/catalog.css";
import "./partnerLogin.css";
import { loginDestination } from "./roleHome.js";
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
  const [showPassword, setShowPassword] = useState(false);

  if (status === "authed" && user) {
    const next = loginDestination(params.get("next"), user);
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
    const next = loginDestination(params.get("next"), result.user);
    navigate(next, { replace: true });
  }

  return (
    <main className="cat-root partner-signin">
      <header className="partner-signin__header"><Link to="/" aria-label="6thSense home">6THSENSE</Link><span>Partner access</span></header>
      <div className="partner-signin__layout">
        <section className="partner-signin__intro"><p className="partner-signin__eyebrow">Catalog · Operations · Workspace</p><h1>One sign-in.<br />Your tools.</h1><p>Browse the Catalog or manage collected recordings. Your account determines which areas you can open.</p><p className="partner-signin__hint">Already signed in? Your account opens automatically.</p></section>
      <form className="partner-signin__form" onSubmit={onSubmit}>
        <h2>Sign in to 6thSense</h2>
        <p>Use the account provided by your administrator.</p>
        <label htmlFor="login-identifier">Email or username</label>
        {/*
          type="text", not type="email": `guest` is a legal value here, and a
          type="email" input reports it as invalid to assistive technology and
          offers the wrong mobile keyboard. inputMode="email" keeps the @-friendly keyboard for the
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
          type={showPassword ? "text" : "password"}
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        <button className="partner-signin__show" type="button" aria-pressed={showPassword} onClick={() => setShowPassword(value => !value)}>{showPassword ? "Hide password" : "Show password"}</button>
        <button className="partner-signin__submit" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="portal-login-status" role="status" aria-live="polite">
          {error || " "}
        </p>
        <p className="partner-signin__help">Have a guest account? Enter <strong>guest</strong> as the username and use the password you were given.</p>
        <p className="partner-signin__help">Account creation and password resets are currently handled by your administrator.</p>
      </form>
      </div>
    </main>
  );
}
