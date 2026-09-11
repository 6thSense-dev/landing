import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import CatalogTopBar from "../catalog/CatalogTopBar.jsx";
import { portalFetch } from "./portalFetch.js";
import { useSession } from "./useSession.jsx";
import { nsFromSeconds, secondsFromNs } from "./intakeTime.js";
import "../catalog/catalog.css";
import "../catalog/parts.header.css";
import "./intakeReview.css";
const API = import.meta.env.VITE_API_URL ?? "";
const ROOT = "/api/ops/intake-review";

export default function IntakeReview() {
  const { user } = useSession();
  // Keying by authenticated identity discards any previous user's private state.
  return <ReviewSession key={`${user?.id}:${user?.role}:${user?.email}`} />;
}

function ReviewSession() {
  const mounted = useRef(false);
  const pendingDownload = useRef(null);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; pendingDownload.current?.abort(); }; }, []);
  const [view, setView] = useState(null);
  const [candidateId, setCandidateId] = useState("");
  const [bounds, setBounds] = useState([]);
  const [video, setVideo] = useState("");
  const [reason, setReason] = useState("");
  const [evidence, setEvidence] = useState("");
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const candidate = view?.candidates.find(c => c.id === candidateId);

  useEffect(() => {
    let alive = true;
    portalFetch(`${ROOT}/activity`).then(r => {
      if (!alive) return;
      if (!r.ok) return setError(r.status === 403 ? "Internal review is not enabled for this account." : "Could not load review. Please sign in again or retry.");
      setView(r.data);
      setCandidateId(r.data.candidates[0]?.id ?? "");
    });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (!candidate) return;
    setBounds(candidate.spans.map(s => ({ span_id: s.span_id, start: secondsFromNs(s.interval_ns[0], candidate.time_origin_ns), end: secondsFromNs(s.interval_ns[1], candidate.time_origin_ns) })));
    setNote(""); setReason(""); setEvidence("");
    let alive = true, url;
    const controller = new AbortController();
    // Authenticated fetch -> blob: works with the existing cross-origin API
    // cookie flow without leaking a token in a video URL or query string.
    fetch(`${API}${ROOT}/preview`, { credentials: "include", signal: controller.signal }).then(async r => {
      if (!r.ok) throw new Error("Preview unavailable for this session.");
      const blob = await r.blob();
      if (alive) { url = URL.createObjectURL(blob); setVideo(url); }
    }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; controller.abort(); if (url) URL.revokeObjectURL(url); setVideo(""); };
  }, [candidate]);

  async function download(event) {
    event.preventDefault();
    const controller = new AbortController();
    pendingDownload.current = controller;
    setError(""); setNote(""); setBusy(true);
    try {
      const body = {
        snapshot_sha256: view.snapshot_sha256, candidate_id: candidate.id,
        current_sha256: candidate.current_sha256,
        bounds: bounds.map(b => ({ span_id: b.span_id, start_ns: nsFromSeconds(b.start, candidate.time_origin_ns), end_ns: nsFromSeconds(b.end, candidate.time_origin_ns) })),
        reason: reason.trim(), evidence_ids: evidence.split(",").map(s => s.trim()).filter(Boolean),
      };
      const r = await fetch(`${API}${ROOT}/proposal`, { method: "POST", signal: controller.signal, credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!r.ok) { const failure = await r.json(); throw new Error(failure.detail || "Proposal was refused."); }
      // Keep the native artifact byte-for-byte; JSON parsing would round ns.
      const blob = await r.blob();
      if (!mounted.current || controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = "synthetic-activity-proposal.json"; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNote("Proposal downloaded. It has not been accepted or saved to the recording. The video still shows the original selection.");
    } catch (e) { if (mounted.current && !controller.signal.aborted) setError(e.message); } finally { if (mounted.current) setBusy(false); }
  }

  return <div className="cat-page">
    <CatalogTopBar collectionName="Internal intake review" />
    <main className="intake-review">
      <nav><Link to="/portal/catalog">← Catalog</Link><Link to="/portal/ops">Collector operations</Link></nav>
      <p className="intake-review__eyebrow">Internal · synthetic test footage</p>
      <h1>Review an activity sequence</h1>
      <p>Keep useful attempts and their context together. Propose boundaries without changing the raw recording.</p>
      <p className="intake-review__notice">This is a synthetic integration check, not production validation. Collector credit, settlement, annotation quality and dataset acceptance remain separate and unchanged.</p>
      {error && <p role="alert" className="intake-review__notice">{error}</p>}
      {!view && !error && <p>Loading review…</p>}
      {candidate && <>
        <label>Candidate activity<select value={candidateId} onChange={e => setCandidateId(e.target.value)}>{view.candidates.map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></label>
        <div className="intake-review__grid">
          <section aria-label="Original recording preview">
            <video controls preload="metadata" src={video || undefined} aria-label="Synthetic original activity preview" />
            <p><strong>Concatenated preview.</strong> Player timestamps are not source boundary times. The video skips gaps between selected intervals.</p>
            <p>Source intervals: {candidate.spans.map(s => `${secondsFromNs(s.interval_ns[0], candidate.time_origin_ns)}–${secondsFromNs(s.interval_ns[1], candidate.time_origin_ns)} s`).join("; ")}.</p>
            <p>Original selection · revision {candidate.revision} · {candidate.episode_id}</p>
            <p>Playback does not establish task usefulness or verify the supplied source provenance.</p>
            {candidate.actions.map(a => <p key={a.reason}><strong>{a.title}.</strong> {a.action}</p>)}
          </section>
          <form onSubmit={download}>
            <h2>Proposed boundaries</h2>
            <p>{candidate.time_origin_label}. Waiting gaps stay excluded; failed attempts stay visible.</p>
            {bounds.map((b, i) => <fieldset key={b.span_id}><legend>{candidate.spans[i].role.replaceAll("_", " ")} · {candidate.spans[i].outcome}</legend>
              {["start", "end"].map(field => <label key={field}>{field === "start" ? "Start" : "End"} (seconds)<input required inputMode="decimal" value={b[field]} onChange={e => { const value = e.target.value; setBounds(rows => rows.map((row, j) => j === i ? { ...row, [field]: value } : row)); setNote(""); }} /></label>)}
            </fieldset>)}
            <label>Why change these boundaries?<textarea required maxLength={1000} value={reason} onChange={e => setReason(e.target.value)} /></label>
            <label>Evidence references (comma separated)<input required maxLength={2000} value={evidence} onChange={e => setEvidence(e.target.value)} /></label>
            <p>Your signed-in identity is attached by the server. Evidence references are not independently verified.</p>
            <button className="cat-topbar__logout" disabled={busy}>{busy ? "Validating…" : "Download proposed revision"}</button>
            {note && <p role="status">{note}</p>}
          </form>
        </div>
      </>}
    </main>
  </div>;
}
