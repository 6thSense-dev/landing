import { useEffect, useRef, useState } from "react";
import { portalFetch } from "./portalFetch.js";
import { SESSION_CHANGED_EVENT } from "./useSession.jsx";

const words = (value) => String(value ?? "unknown").replaceAll("_", " ");
// Money never passes through Number, parseFloat or a locale formatter.
const won = (value) => typeof value === "string" && /^-?\d+$/.test(value)
  ? `${value.replace(/\B(?=(\d{3})+(?!\d))/g, ",")} KRW` : "Unknown";

export default function OpsIntakePreview({ recordings = [] }) {
  const [preview, setPreview] = useState(null);
  const [message, setMessage] = useState("Loading supplied intake evidence…");
  const generation = useRef(0);
  const load = async () => {
    const request = ++generation.current;
    setPreview(null);
    setMessage("Loading supplied intake evidence…");
    const response = await portalFetch("/api/ops/intake-preview");
    if (request !== generation.current) return;
    if (!response.ok || response.data?.schema !== "6thsense.ops-intake-preview/1") {
      setMessage(response.status === 403 || response.status === 401
        ? "Intake evidence requires an Operations session."
        : "Intake evidence is unavailable. No earlier values are retained.");
      return;
    }
    const data = response.data;
    if (!Array.isArray(data.rows) || (data.status !== "unknown" && data.status !== "supplied_preview")) {
      setMessage("The supplied evidence response was not recognized."); return;
    }
    if (data.status === "unknown") {
      setMessage((data.reasons ?? ["unknown"]).map(words).join(" · "));
      return;
    }
    if (!Number.isSafeInteger(data.valid_for_ms) || data.valid_for_ms <= 0) {
      setMessage("Snapshot expired. Reload to check for a newer export."); return;
    }
    setPreview(data); setMessage("");
  };
  useEffect(() => {
    load();
    const clear = () => { ++generation.current; setPreview(null); setMessage("Session changed. Reload with the current Operations session."); };
    window.addEventListener(SESSION_CHANGED_EVENT, clear);
    return () => { ++generation.current; window.removeEventListener(SESSION_CHANGED_EVENT, clear); };
  }, []);
  useEffect(() => {
    if (!preview) return undefined;
    const remaining = preview.valid_for_ms;
    const timer = window.setTimeout(() => {
      ++generation.current; setPreview(null); setMessage("Snapshot expired. Reload to check for a newer export.");
    }, Math.min(Math.max(0, remaining), 2147483647));
    return () => window.clearTimeout(timer);
  }, [preview]);
  const known = new Set(recordings);
  return (
    <section className="ops-panel ops-intake" aria-labelledby="ops-intake-title">
      <div className="ops-phead ops-intake-head">
        <div><h2 id="ops-intake-title">Intake evidence</h2><p className="ops-muted">Capture, credit and acceptance are separate decisions.</p></div>
        {preview && <span className="ops-chip warn">{preview.synthetic ? "SYNTHETIC · NOT LIVE" : "SUPPLIED EXPORT"}</span>}
        <button type="button" onClick={load}>Reload evidence</button>
      </div>
      <div className="ops-pbody">
        <p className="ops-hint">Read-only preview. The paid checkbox is a legacy assertion, not transfer proof. The current board rate does not establish historical terms.</p>
        {message && <p role="status" className="ops-muted">{message}</p>}
        {preview && <>
          <p className="ops-muted">Export {preview.generated_at} · expires {preview.expires_at}</p>
          <p className="ops-intake-caution">Authenticity and current recording bytes are unverified. Amounts below are reported by the pinned Catalog export.</p>
          <div className="ops-intake-table"><table>
            <thead><tr><th>Recording / source</th><th>Capture usability</th><th>Agreed episode credit</th><th>Settlement evidence</th><th>Outstanding</th><th>Annotation</th><th>Dataset acceptance</th></tr></thead>
            <tbody>{preview.rows.map((row) => <tr key={row.episode_id}>
              <td><strong>{row.recording_id}</strong><small>{known.has(row.recording_id) ? "Recording ID appears in this ledger" : "Not linked to the current ledger"}</small><small>{words(row.source_binding)}</small><code title={row.source_sha256}>{row.source_sha256}</code></td>
              <td><Judgment value={row.judgments.capture} /></td>
              <td className="ops-intake-amount">{won(row.credit_minor)}<small>Historical per-episode terms</small><small>Legacy marked-paid: {row.legacy_paid == null ? "unknown" : row.legacy_paid ? "yes" : "no"}</small><small>{row.correction_count == null ? "Correction history: unknown" : `${row.correction_count} reported assertion corrections`}</small></td>
              <td className="ops-intake-amount">{won(row.settled_minor)}<small>Observed subset: {won(row.observed_settled_minor)}</small></td>
              <td className="ops-intake-amount">{won(row.outstanding_minor)}</td>
              <td><Judgment value={row.judgments.annotation} /></td>
              <td><Judgment value={row.judgments.dataset} /></td>
            </tr>)}</tbody>
          </table></div>
          {!preview.rows.length && <p className="ops-muted">The supplied export contains no episodes. No live total is inferred.</p>}
          <details className="ops-intake-details"><summary>Evidence references and unresolved reasons</summary>
            <p>Catalog report <code>{preview.report_sha256}</code></p>
            {(preview.reasons ?? []).map((reason) => <p key={reason}>{words(reason)}</p>)}
            {preview.rows.map((row) => <div key={row.episode_id}><strong>{row.recording_id}</strong>
              {row.reasons.map((reason) => <p key={reason}>{words(reason)}</p>)}
              {Object.entries(row.judgments).map(([kind, value]) => <p key={kind}>{kind}: {value.evidence_ids.length ? value.evidence_ids.join(", ") : "no evidence references supplied"}</p>)}
            </div>)}
          </details>
        </>}
      </div>
    </section>
  );
}

function Judgment({ value }) {
  return <><span className={`ops-chip ${value.status === "unknown" || value.status === "pending" ? "warn" : ""}`}>{words(value.status)}</span><small>{words(value.reason)}</small></>;
}
