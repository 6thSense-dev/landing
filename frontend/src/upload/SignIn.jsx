import { useState } from "react";
import { LockKeyhole } from "lucide-react";
import { cognito, contributorSession, phoneNumber } from "./auth.js";

export default function SignIn({ t }) {
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [mode, setMode] = useState("login");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const username = phoneNumber(phone);
      if (mode === "login") await contributorSession.signIn(username, password);
      else if (mode === "forgot") {
        await cognito("ForgotPassword", { Username: username }); setMode("reset"); setNotice(t.codeSent);
      } else {
        await cognito("ConfirmForgotPassword", { Username: username, ConfirmationCode: code, Password: password });
        setMode("login"); setPassword(""); setNotice(t.passwordChanged);
      }
    } catch (e) { setError(t.errors[e.message] || t.errors.sign_in_unavailable); }
    finally { setBusy(false); }
  };
  return <section className="upload-signin">
    <div className="upload-signin-heading"><LockKeyhole size={24} /><h2>{mode === "login" ? t.signIn : t.resetPassword}</h2></div>
    <p>{t.accountIntro}</p>
    <form onSubmit={submit}>
      <label>{t.phone}<input type="tel" autoComplete="username" inputMode="tel" placeholder="+82 10 1234 5678" required maxLength={24} value={phone} onChange={e => setPhone(e.target.value)} disabled={busy || mode === "reset"} /><span>{t.phoneHint}</span></label>
      {mode === "reset" && <label>{t.code}<input autoComplete="one-time-code" inputMode="numeric" required pattern="[0-9]{6}" value={code} onChange={e => setCode(e.target.value)} /></label>}
      {mode !== "forgot" && <label>{mode === "reset" ? t.newPassword : t.password}<input type="password" autoComplete={mode === "reset" ? "new-password" : "current-password"} required minLength={mode === "reset" ? 12 : 1} maxLength={256} value={password} onChange={e => setPassword(e.target.value)} />{mode === "reset" && <span>{t.passwordHint}</span>}</label>}
      {error && <p className="upload-error" role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <button className="upload-button" disabled={busy}>{busy ? t.working : mode === "login" ? t.signIn : mode === "forgot" ? t.sendCode : t.resetPassword}</button>
      <button type="button" className="upload-text-button" disabled={busy} onClick={() => { setMode(mode === "login" ? "forgot" : "login"); setError(""); setNotice(""); setPassword(""); }}>{mode === "login" ? t.forgotPassword : t.backToSignIn}</button>
    </form>
    <div className="upload-signin-help"><p>{t.noAccount}</p><a href="mailto:alex@6thsense.dev">alex@6thsense.dev</a></div>
  </section>;
}
