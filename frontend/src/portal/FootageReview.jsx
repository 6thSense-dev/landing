import { useState } from "react";
import { portalFetch } from "./portalFetch.js";
export default function FootageReview({ entry, onChanged, onPlay }) {
  const [date, setDate] = useState(entry.collection_date || "");
  const [note, setNote] = useState(entry.review_note || "");
  const [watched, setWatched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const locked = entry.legacy_paid || entry.payout_id;
  async function save(decision) {
    setBusy(true);
    setError("");
    try {
      const r = await portalFetch("/api/ops/payments/review", {
        method: "POST",
        body: JSON.stringify({
          run_id: entry.run_id,
          recording: entry.recording,
          manifest_sha256: entry.manifest_sha256,
          decision,
          collection_date: date || null,
          note,
          watched_all: watched,
        }),
      });
      if (!r.ok) throw Error(r.data?.detail || "Review could not be saved.");
      await onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="ops-footage-review">
      <summary>
        {entry.recording} · {entry.review_status.replaceAll("_", " ")}
      </summary>
      <div className="ops-pbody">
        <p className="ops-hint">
          {entry.retained_seconds === 0
            ? "No retained footage. See the rejection reasons below."
            : entry.artifact_status === "complete"
            ? "Both eye videos, full frame sequences and IMU are verified."
            : entry.artifact_status === "incomplete"
              ? "Required video, frame or sensor artifacts need attention."
              : "Historical video export · separate eyes, full frames and IMU have not been verified."}
        </p>
        <button onClick={onPlay} disabled={entry.retained_seconds === 0}>Watch this recording</button>
        <p>
          Collected {(entry.source_seconds / 3600).toFixed(2)}h · retained{" "}
          {(entry.retained_seconds / 3600).toFixed(2)}h · excluded{" "}
          {(entry.rejected_seconds / 3600).toFixed(2)}h
        </p>
        <ul>
          {Object.entries(entry.rejection_reasons || {}).map(([why, s]) => (
            <li key={why}>
              {why} · {(s / 60).toFixed(1)} min
            </li>
          ))}
        </ul>
        <p className="ops-hint">
          {entry.review_intervals.length} flagged intervals · {entry.date_basis}
        </p>
        <label>
          Collection date ({({ china: 'China', korea: 'Korea', vietnam: 'Vietnam', india: 'India' })[entry.counterparty?.country] || 'Korea'})
          <input
            disabled={!!locked || busy}
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label>
          Review note
          <textarea
            disabled={!!locked || busy}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={2000}
          />
        </label>
        {!locked && (
          <>
            <label className="ops-check">
              <input
                type="checkbox"
                checked={watched}
                onChange={(e) => setWatched(e.target.checked)}
              />
              I reviewed all retained footage and flagged intervals.
            </label>
            <div className="ops-clean-actions">
              <button
                disabled={busy || !watched}
                onClick={() => save("reviewed")}
              >
                Mark reviewed
              </button>
              <button
                disabled={busy || !note.trim()}
                onClick={() => save("withheld")}
              >
                {entry.counterparty ? 'Hold for review' : 'Withhold from payment'}
              </button>
              {entry.review_status !== "needs_review" && (
                <button disabled={busy} onClick={() => save("needs_review")}>
                  Reopen review
                </button>
              )}
            </div>
          </>
        )}
        {entry.reviewer && (
          <p className="ops-muted">Reviewed by {entry.reviewer}</p>
        )}
        {error && (
          <p role="alert" className="ops-error">
            {error}
          </p>
        )}
      </div>
    </details>
  );
}
