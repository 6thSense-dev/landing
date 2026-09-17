import { useMemo, useState } from "react";
import { portalFetch } from "./portalFetch.js";
import { fmt, regionOfEpisode, sourceKey } from "./opsShared.js";
import { processingLabels as labels, processingState, processingPresentation } from "./rawProcessingStatus.js";
export default function OpsOperations({ state, act, busy, readOnly = false }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [person, setPerson] = useState("");
  const [history, setHistory] = useState(false);
  const [preview, setPreview] = useState(null);
  const people = new Map((state.wearers || []).map((p) => [p.id, p]));
  const rows = useMemo(
    () =>
      (state.episodes || []).filter((e) => {
        const presentation = processingPresentation(e);
        const s = presentation.state;
        if (!history && ["clean", "rejected"].includes(s)) return false;
        return (
          (!status || s === status) &&
          (!person || sourceKey(e) === person) &&
          `${e.recording} ${e.device_id} ${e.counterparty?.name || people.get(e.wearer_id)?.name || ""} ${regionOfEpisode(e)} ${e.counterparty ? "B2B" : ""} ${presentation.label} ${e.processing?.reason || ""}`
            .toLowerCase()
            .includes(q.toLowerCase())
        );
      }),
    [state, status, person, q, history],
  );
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
          : "Automatic scanning is not enabled yet."}{" "}
        {state.processing?.worker_access_configured
          ? "Processing worker access is configured."
          : "Recovery and QC worker connection is not configured."}
      </p>
      <div className="ops-tiles">
        {[
          [
            "Pending sources",
            (state.episodes || []).filter(
              (e) => !e.deleted_at && e.raw?.pending_files > 0,
            ).length,
          ],
          [
            "Blocked / retry pending",
            (state.episodes || []).filter((e) =>
              ["blocked", "retry"].includes(processingState(e)),
            ).length,
          ],
          [
            "Recovering / processing",
            (state.episodes || []).filter((e) =>
              ["recovering", "running"].includes(processingState(e)),
            ).length,
          ],
        ].map(([l, n]) => (
          <div className="ops-tile" key={l}>
            <div className="ops-tile-n">{fmt(n)}</div>
            <div className="ops-tile-l">{l}</div>
          </div>
        ))}
      </div>
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
            {Object.entries(labels).map(([k, v]) => (
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
          <label className="ops-check">
            <input
              type="checkbox"
              checked={history}
              onChange={(e) => setHistory(e.target.checked)}
            />
            Show completed / rejected
          </label>
        </div>
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
              {rows.map((e) => {
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
                    <td>{e.counterparty?.name || people.get(e.wearer_id)?.name || "Unassigned"}{e.counterparty && <> <span className="ops-chip">B2B</span></>}</td>
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
                      {presentation.label !== labels[s] && (
                        <div className="ops-muted">{labels[s]}</div>
                      )}
                    </td>
                    <td>
                      {(s === "clean" ? presentation.nextStep : e.processing?.reason) ||
                        (s === "clean"
                          ? "Verified clean output available."
                          : "Awaiting automatic validation.")}
                      {s !== "clean" && presentation.nextStep && (
                        <div>{presentation.nextStep}</div>
                      )}
                      {s === "clean" && e.processing?.reason && e.processing.reason !== presentation.nextStep && (
                        <details>
                          <summary>Recorded status message</summary>
                          {e.processing.reason}
                        </details>
                      )}
                      <div className="ops-muted">
                        {e.raw?.pending_files || 0} pending files ·{" "}
                        {((e.raw?.raw_bytes || 0) / 1e6).toFixed(1)} MB
                      </div>
                    </td>
                    <td>
                      <button onClick={() => play(e)}>Preview</button>
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
