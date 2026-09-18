import { useEffect, useMemo, useState } from "react";
import { portalFetch } from "./portalFetch.js";
import { fmt, regionOfEpisode, sourceKey } from "./opsShared.js";
import { processingLabels as labels, processingGroup, processingPresentation } from "./rawProcessingStatus.js";
export default function OpsOperations({ state, act, busy, readOnly = false }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [person, setPerson] = useState("");
  const [group, setGroup] = useState("active");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [preview, setPreview] = useState(null);
  const people = new Map((state.wearers || []).map((p) => [p.id, p]));
  const rows = useMemo(
    () =>
      (state.episodes || []).filter((e) => {
        const presentation = processingPresentation(e);
        const s = presentation.state;
        if (processingGroup(e) !== group) return false;
        return (
          (!status || s === status) &&
          (!person || sourceKey(e) === person) &&
          `${e.recording} ${e.device_id} ${e.counterparty?.name || people.get(e.wearer_id)?.name || ""} ${regionOfEpisode(e)} ${e.counterparty ? "B2B" : ""} ${presentation.label} ${e.processing?.reason || ""}`
            .toLowerCase()
            .includes(q.toLowerCase())
        );
      }),
    [state, status, person, q, group],
  );
  useEffect(() => setPage(1), [status, person, q, group, pageSize]);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(page, pages);
  useEffect(() => { if (page > pages) setPage(pages); }, [page, pages]);
  const pageRows = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  const groups = [
    ["active", "Processing queue"], ["attention", "Needs action"],
    ["upload", "Waiting for upload"], ["history", "Completed / rejected"],
  ];
  const groupCounts = (state.episodes || []).reduce((counts, e) => {
    const key = processingGroup(e); counts[key] = (counts[key] || 0) + 1; return counts;
  }, {});
  const selectGroup = value => { setGroup(value); setStatus(""); setPage(1); };
  const play = async (e) => {
    setPreview({ recording: e.recording, loading: true, files: [], pick: 0 });
    try {
      const r = await portalFetch(
        `${readOnly ? "/api/workspace/ops" : "/api/ops"}/episodes/${encodeURIComponent(e.recording)}/files`,
      );
      if (!r.ok) throw Error("Playback unavailable.");
      setPreview({
        recording: e.recording,
        files: r.data.files || [],
        pick: 0,
      });
    } catch (error) {
      setPreview({
        recording: e.recording,
        files: [],
        pick: 0,
        error: error.message,
      });
    }
  };
  return (
    <section aria-label="Raw processing monitor">
      <div className="ops-clean-intro">
        <div>
          <h2>Raw processing monitor</h2>
          <p>
            Sources waiting for validation, recovery or a verified Clean result.
          </p>
        </div>
      </div>
      <p className="ops-note">
        {state.processing?.automatic_scan
          ? "Automatic bucket scans are enabled."
          : "Automatic scanning is not enabled yet."}
      </p>
      <div className="ops-tiles">
        {groups.map(([key, label]) => (
          <button type="button" className={`ops-tile ops-queue-group${group === key ? " is-selected" : ""}`} key={key}
            aria-pressed={group === key} aria-label={label} onClick={() => selectGroup(key)}>
            <div className="ops-tile-n">{fmt(groupCounts[key] || 0)}</div>
            <div className="ops-tile-l">{label}</div>
          </button>
        ))}
      </div>
      <p className="ops-hint" role="status">
        {group === "upload" ? "Uploads still arriving or folders with no footage. These are separate from processing failures; available files are checked automatically."
          : group === "attention" ? "Recordings with a specific issue to resolve. Open Details for the failure and recovery steps."
          : group === "history" ? "Completed and rejected recordings remain available here for reference."
          : "Queued jobs, active processing, recovery, and final source checks. New eligible footage enters this queue automatically."}
      </p>
      <div className="ops-panel">
        <div className="ops-filters">
          <input
            className="ops-q"
            aria-label="Search raw sources"
            placeholder="Camera, source, episode or cause"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <select
            aria-label="Processing status"
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">All statuses</option>
            {Object.entries(labels).filter(([key]) => (state.episodes || []).some(e => processingGroup(e) === group && processingPresentation(e).state === key)).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <select
            aria-label="Raw source"
            value={person}
            onChange={(e) => setPerson(e.target.value)}
          >
            <option value="">All sources</option>
            {[...people.values()].map((p) => (
              <option key={p.id} value={`wearer:${p.id}`}>
                {p.name}
              </option>
            ))}
            {[...new Map((state.episodes || []).filter(e => e.counterparty).map(e => [e.counterparty.id, e.counterparty])).values()].map(b => <option key={`business:${b.id}`} value={`business:${b.id}`}>{b.name} · B2B</option>)}
          </select>
          <label className="ops-page-size">Rows per page <select aria-label="Rows per page" value={pageSize} onChange={e => setPageSize(Number(e.target.value))}>
            {[25, 50, 100].map(size => <option key={size} value={size}>{size}</option>)}
          </select></label>
        </div>
        <nav className="ops-pagination" aria-label="Raw pagination">
          <span>{rows.length ? `${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, rows.length)} of ${rows.length}` : "0 recordings"}</span>
          <div><button disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous</button>
            <span aria-live="polite">Page {currentPage} of {pages}</span>
            <button disabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}>Next</button></div>
        </nav>
        <div className="ops-tablewrap">
          <table className="ops-table">
            <thead>
              <tr>
                <th>Episode / camera</th>
                <th>Source</th>
                <th>Uploaded</th>
                <th>Status</th>
                <th>Reason / next step</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {pageRows.map((e) => {
                const presentation = processingPresentation(e);
                const s = presentation.state;
                return (
                  <tr key={e.recording}>
                    <td className="mono">
                      {e.recording}
                      <div className="ops-muted">
                        EGO-{e.device_id} · {regionOfEpisode(e)}
                      </div>
                    </td>
                    <td>{e.counterparty?.name || people.get(e.wearer_id)?.name || "Unassigned"}{e.counterparty && <> <span className="ops-chip">B2B</span></>}{e.uploaded_by && <div className="ops-muted">Uploaded by {e.uploaded_by.name}</div>}</td>
                    <td className="mono">
                      {e.uploaded_at
                        ? new Date(e.uploaded_at).toLocaleString()
                        : "Not recorded"}
                    </td>
                    <td>
                      <span
                        className={`ops-chip ${s === "rejected" ? "bad" : ""}`}
                      >
                        {presentation.label}
                      </span>
                    </td>
                    <td>
                      {presentation.nextStep || (s === "running" ? "Processing in the cloud." : s === "queued" ? "Waiting for an available worker." : "Awaiting automatic validation.")}
                      {e.processing?.reason && e.processing.reason !== presentation.nextStep && (
                        <details>
                          <summary>{s === "clean" ? "Recorded status message" : "Details"}</summary>
                          {e.processing.reason}
                          <div className="ops-muted">{e.raw?.pending_files || 0} pending files · {((e.raw?.raw_bytes || 0) / 1e6).toFixed(1)} MB</div>
                        </details>
                      )}
                    </td>
                    <td>
                      <button disabled={s === "waiting_upload"} onClick={() => play(e)}>Preview</button>
                      {["retry", "blocked", "rejected"].includes(s) && (
                        <button
                          disabled={
                            readOnly ||
                            !!busy ||
                            !e.processing ||
                            !!e.deleted_at
                          }
                          onClick={() =>
                            act(
                              "retry",
                              `/api/ops/processing/${encodeURIComponent(e.recording)}/retry`,
                            )
                          }
                        >
                          Retry validation
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
              {!rows.length && (
                <tr>
                  <td colSpan={6} className="ops-empty">
                    No sources match this view.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
      {preview && (
        <div
          className="ops-clean-modal"
          role="dialog"
          aria-modal="true"
          aria-label="Raw preview"
        >
          <div className="ops-panel">
            <div className="ops-phead">
              <h2>{preview.recording}</h2>
              <button autoFocus onClick={() => setPreview(null)}>
                Close
              </button>
            </div>
            <div className="ops-pbody">
              {preview.loading ? (
                <p>Loading video…</p>
              ) : preview.files.length ? (
                <>
                  <video
                    controls
                    playsInline
                    preload="metadata"
                    src={preview.files[preview.pick].url}
                  />
                  <select
                    aria-label="Source file"
                    value={preview.pick}
                    onChange={(e) =>
                      setPreview({ ...preview, pick: Number(e.target.value) })
                    }
                  >
                    {preview.files.map((f, i) => (
                      <option key={f.key || f.name} value={i}>
                        {f.name}
                      </option>
                    ))}
                  </select>
                </>
              ) : (
                <p>
                  {preview.error ||
                    "No pending browser-playable media. EgoC containers require decoding."}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
