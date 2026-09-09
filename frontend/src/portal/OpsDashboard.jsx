import { useCallback, useEffect, useState } from "react";
import { portalFetch } from "./portalFetch.js";
import { useSession } from "./useSession.jsx";
import OpsOperations from "./OpsOperations.jsx";
import OpsUsers from "./OpsUsers.jsx";
import "./ops.css";

/**
 * The collector operations area: a shell with two tabs over one shared state.
 *
 * WHY THE STATE LIVES HERE AND NOT IN THE TABS. Every mutation endpoint returns
 * the whole new state, and both tabs read the same episodes — Users derives a
 * person's accepted hours from them. Fetching per tab would let the two screens
 * disagree about the same numbers depending on which was opened first.
 *
 * OPERATIONS is strictly the episode ledger; USERS is strictly the people who
 * carry cameras. They are separate tables for a reason (see OpsUsers.jsx) and
 * keeping them separate screens keeps that distinction visible.
 */

const TABS = [
  { key: "ops", label: "Operations" },
  { key: "users", label: "Users" },
];

export default function OpsDashboard() {
  const { user, logout } = useSession();
  const [tab, setTab] = useState("ops");
  const [state, setState] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    const r = await portalFetch("/api/ops/state");
    if (!r.ok) return setErr(`Could not load the ledger (HTTP ${r.status}).`);
    setErr("");
    setState(r.data);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Every mutation returns the whole new state, so no screen can drift from the
  // server: there is no local patching to get wrong. Returns the new state on
  // success and null on failure, so a caller can clear its form only if the
  // write actually landed.
  const act = useCallback(async (key, path, body) => {
    setBusy(key);
    const r = await portalFetch(path, { method: "POST", body: JSON.stringify(body ?? {}) });
    setBusy("");
    if (!r.ok) {
      setErr(r.data?.detail || `That did not work (HTTP ${r.status}).`);
      return null;
    }
    setErr("");
    setState(r.data);
    return r.data;
  }, []);

  const rate = state?.rate_krw ?? 0;

  return (
    <div className="ops">
      <header className="ops-head">
        <h1>Collector operations</h1>
        <nav className="ops-tabs">
          {TABS.map((t) => (
            <button
              key={t.key}
              className={`ops-tab${tab === t.key ? " is-on" : ""}`}
              aria-current={tab === t.key ? "page" : undefined}
              onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </nav>
        <span className="ops-spacer" />
        {state && tab === "ops" && (
          <span className="ops-src"><code>s3://6thsense-raw</code></span>
        )}
        {/* Who you are is next to the way out, so an operator on a shared
            machine can see at a glance whose session they are about to act in. */}
        <span className="ops-src ops-who-am-i">{user?.email}</span>
        <button className="ops-logout" onClick={logout}>Log out</button>
      </header>

      <div className="ops-main">
        {err && <p className="ops-error" role="alert">{err}</p>}

        {!state ? (
          <p className="ops-muted">{err ? "" : "Loading the ledger…"}</p>
        ) : tab === "ops" ? (
          <OpsOperations state={state} act={act} busy={busy} rate={rate} />
        ) : (
          <OpsUsers state={state} act={act} busy={busy} />
        )}
      </div>

      {busy && <div className="ops-busy" aria-live="polite">working…</div>}
    </div>
  );
}
