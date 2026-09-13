import { useEffect, useRef, useState } from "react";
import { portalFetch } from "./portalFetch.js";
import "./opsInventoryCoverage.css";

const count = (value) => Number.isSafeInteger(value) && value >= 0
  ? value.toLocaleString() : "Unknown";

export default function OpsInventoryCoverage() {
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function check() {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setReport(null);
    setError("");
    setBusy(true);
    const response = await portalFetch("/api/ops/inventory-coverage", { signal: request.signal });
    if (request.signal.aborted) return;
    setBusy(false);
    if (!response.ok || typeof response.data?.listing_complete !== "boolean") {
      setError("Inventory could not be checked. Coverage is unknown; try again when storage access is available.");
      return;
    }
    setReport(response.data);
  }

  return (
    <details className="ops-inventory">
      <summary>Which recordings does this board cover?</summary>
      <div className="ops-inventory-body">
        <p>The raw board recognizes recording folders under <code>sessions/</code>. Other layouts may contain footage that is not shown here. Recognizing a folder does not confirm it has been imported into the board.</p>
        <button type="button" onClick={check} disabled={busy}>
          {busy ? "Checking inventory…" : "Check inventory coverage"}
        </button>
        <p className="ops-hint">Reads up to 10,000 object entries. Does not import recordings, change approvals or calculate usable hours.</p>
        {error && <p role="alert" className="ops-error">{error}</p>}
        {report && <section aria-label="Inventory coverage result" aria-live="polite">
          <p className={report.listing_complete ? "ops-inventory-status" : "ops-inventory-warning"}>
            {report.listing_complete
              ? "Listing completed for the configured bucket."
              : report.stop_reason === "object_limit"
                ? "Partial inventory: the object limit was reached. Counts cover only the entries observed."
                : "Incomplete inventory: storage could not be fully read. Full totals are unknown."}
          </p>
          <p className="ops-hint"><code>s3://{report.bucket}/{report.scope_prefix}</code> · Checked {report.observed_at || "at an unknown time"}</p>
          <dl className="ops-inventory-counts">
            <div><dt>Objects observed</dt><dd>{count(report.objects_observed)}</dd></div>
            <div><dt>Recognized recording folders</dt><dd>{count(report.recognized_recording_prefixes)}</dd></div>
            <div><dt>{report.listing_complete ? "Folders without metadata.json" : "Metadata.json not yet observed"}</dt><dd>{count(report.recordings_missing_metadata)}</dd></div>
            <div><dt>Unrecognized object entries</dt><dd>{count(report.unrecognized_objects)}</dd></div>
            <div><dt>Recording names in multiple folders</dt><dd>{count(report.collision_recording_names)}</dd></div>
          </dl>
          <p className="ops-hint">Folder counts are not unique recording counts. A metadata file being present does not prove completeness or quality. Unrecognized entries are not automatically unusable footage.</p>
          {[
            ["Example entries outside the board’s recognized layout", report.examples?.unrecognized_keys],
            ["Example folders without observed metadata", report.examples?.missing_metadata_prefixes],
            ["Recording names requiring identity reconciliation", report.examples?.collision_names],
          ].map(([label, examples]) => Array.isArray(examples) && examples.length > 0 && (
            <details key={label}><summary>{label}</summary>
              <ul>{examples.map((value, index) => <li key={index}><code>{value}</code></li>)}</ul>
            </details>
          ))}
          {Array.isArray(report.limitations) && report.limitations.length > 0 && <ul className="ops-hint">
            {report.limitations.map((value, index) => <li key={index}>{value}</li>)}
          </ul>}
        </section>}
      </div>
    </details>
  );
}
