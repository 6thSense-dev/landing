import { useCallback, useEffect, useState } from "react";
import { portalFetch } from "./portalFetch.js";
import { useSession } from "./useSession.jsx";
import WorkspaceLink from "./WorkspaceLink.jsx";
import IntakeReviewLink from "./IntakeReviewLink.jsx";
import OpsOperations from "./OpsOperations.jsx";
import OpsUsers from "./OpsUsers.jsx";
import OpsClean from "./OpsClean.jsx";
import OpsInventoryCoverage from "./OpsInventoryCoverage.jsx";
import "./ops.css";

/** Raw and Users share the episode ledger. Clean owns its QC collection state
 * and refreshes the shared ledger after a camera assignment. */

const TABS = [
  { key: "ops", label: "Raw" },
  { key: "clean", label: "Clean" },
  { key: "users", label: "Users" },
];

export default function OpsDashboard({ readOnly = false }) {
  const { user, logout } = useSession();
  const [tab, setTab] = useState("ops");
  const [state, setState] = useState(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    const r = await portalFetch(readOnly ? "/api/workspace/ops/state" : "/api/ops/state");
    if (!r.ok) return setErr(`Could not load the ledger (HTTP ${r.status}).`);
    setErr("");
    setState(r.data);
  }, [readOnly]);

  useEffect(() => {
    load();
  }, [load]);

  // Every mutation returns the whole new state, so no screen can drift from the
  // server: there is no local patching to get wrong. Returns the new state on
  // success and null on failure, so a caller can clear its form only if the
  // write actually landed.
  const act = useCallback(async (key, path, body) => {
    if (readOnly) { setNote("Learning preview is read-only. Open Operations from Workspace to make changes."); return null; }
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
  }, [readOnly]);

  const rate = state?.rate_krw ?? 0;
  const lastScan = state?.last_scan ?? "";

  // The bucket is the system of record; this is the only thing that reads it.
  // Safe to press at any time: the scan inserts what is new and refreshes only
  // growable facts, and can never touch an approval, a payment or an assignment.
  const scan = async () => {
    const next = await act("scan", "/api/ops/scan");
    if (next?.scan) {
      const { added, updated, seen } = next.scan;
      setNote(added || updated
        ? `Scanned ${seen} takes — ${added} new, ${updated} updated.`
        : `Scanned ${seen} takes — nothing new since the last scan.`);
    }
  };

  return (
    <div className="ops">
      <header className="ops-head">
        <h1>Collector operations</h1>
        <nav className="ops-tabs">
          {TABS.filter(t => !readOnly || t.key !== "clean").map((t) => (
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
          <WorkspaceLink className="ops-intake-link" />
        {!readOnly && <IntakeReviewLink className="ops-intake-link" />}
        {state && tab === "ops" && (
          <span className="ops-src" title={lastScan
            ? `bucket last read ${lastScan.replace("T", " ").slice(0, 16)}`
            : "this board has never read the bucket"}>
            <code>s3://6thsense-raw</code>{" "}
            {lastScan ? `· scanned ${lastScan.replace("T", " ").slice(5, 16)}`
                      : "· never scanned"}
          </span>
        )}
        {state && tab === "ops" && (
          <button className="ops-scan" onClick={scan} disabled={readOnly || busy === "scan"}>
            {busy === "scan" ? "Scanning…" : "Scan bucket"}
          </button>
        )}
        {/* Who you are is next to the way out, so an operator on a shared
            machine can see at a glance whose session they are about to act in. */}
        <span className="ops-src ops-who-am-i">{user?.email}</span>
        {!readOnly && <button className="ops-logout" onClick={logout}>Log out</button>}
      </header>

      <div className="ops-main">
        {err && <p className="ops-error" role="alert">{err}</p>}
        {note && !err && (
          <p className="ops-note" role="status" onClick={() => setNote("")}>{note}</p>
        )}

        {!state ? (
          <p className="ops-muted">{err ? "" : "Loading the ledger…"}</p>
        ) : tab === "clean" && !readOnly ? (<OpsClean onChanged={load} />) : tab === "ops" ? (
          <>
            {!readOnly && <OpsInventoryCoverage />}
            <OpsOperations readOnly={readOnly} state={state} act={act} busy={busy} rate={rate} />
          </>
        ) : (
          <OpsUsers readOnly={readOnly} state={state} act={act} busy={busy} />
        )}
      </div>

      {busy && <div className="ops-busy" aria-live="polite">working…</div>}
    </div>
  );
}
