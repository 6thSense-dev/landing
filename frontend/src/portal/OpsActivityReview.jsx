import { useEffect, useRef, useState } from 'react';
import { portalFetch } from './portalFetch.js';

// Decimal seconds are converted without a floating-point round trip.
export function secondsToNs(value) {
  if (!/^(0|[1-9]\d*)(\.\d{1,9})?$/.test(value)) throw new Error('Use nonnegative seconds with at most nine decimal places.');
  const [whole, fraction = ''] = value.split('.');
  const ns = (BigInt(whole) * 1000000000n + BigInt(fraction.padEnd(9, '0'))).toString();
  if (ns.length > 24) throw new Error('Time exceeds the supported source range.');
  return ns;
}
export function nsToSeconds(value) {
  if (value == null) return 'Unknown';
  const ns = BigInt(value);
  const fraction = (ns % 1000000000n).toString().padStart(9, '0').replace(/0+$/, '');
  return `${ns / 1000000000n}${fraction ? `.${fraction}` : ''}`;
}
const row = (recording = '') => ({ recording, start: '', end: '', judgment: 'unknown', reason: '' });

export default function OpsActivityReview({ runId }) {
  const [task, setTask] = useState('');
  const [projection, setProjection] = useState(null);
  const [version, setVersion] = useState('');
  const [criteria, setCriteria] = useState('');
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const generation = useRef(0);
  useEffect(() => () => { generation.current++; }, []);
  const endpoint = `/api/ops/clean/runs/${encodeURIComponent(runId)}/activity-review`;
  const validTask = /^[A-Za-z0-9_-]{1,80}$/.test(task);
  const adopt = data => {
    setProjection(data);
    setVersion(data.review?.criteria_version || '');
    setCriteria(data.review?.criteria_text || '');
    setRows((data.review?.intervals || []).map(i => ({ ...i, start: nsToSeconds(i.start_ns), end: nsToSeconds(i.end_ns) })));
  };
  const request = async (save = false) => {
    const current = ++generation.current;
    setError(''); setMessage(''); setBusy(true);
    try {
      let options;
      if (save) {
        options = { method: 'POST', body: JSON.stringify({
          task_id: projection.task_id, expected_revision: projection.revision,
          manifest_sha256: projection.manifest_sha256, criteria_version: version, criteria_text: criteria,
          intervals: rows.map(i => ({ recording: i.recording, start_ns: secondsToNs(i.start), end_ns: secondsToNs(i.end), judgment: i.judgment, reason: i.reason })),
        }) };
      }
      const response = await portalFetch(save ? endpoint : `${endpoint}?task_id=${encodeURIComponent(task)}`, options);
      if (current !== generation.current) return;
      if (!response.ok) {
        const detail = typeof response.data?.detail === 'string' ? response.data.detail : 'Review could not be saved or loaded.';
        throw new Error(response.status === 409 ? `${detail} Your draft is preserved. Load the current review before resolving the conflict.` : detail);
      }
      adopt(response.data);
      setMessage(save ? `Saved review declaration revision ${response.data.revision}. QC and collector credit were not changed.` : 'Loaded the selected task.');
    } catch (e) { if (current === generation.current) setError(e.message); }
    finally { if (current === generation.current) setBusy(false); }
  };
  const update = (index, field, value) => setRows(rows.map((i, n) => n === index ? { ...i, [field]: value } : i));

  return <section aria-label="Task activity review" className="ops-panel" style={{ padding: '1rem', marginTop: '1rem' }}>
    <h3>Task activity review</h3>
    <p className="ops-hint">Record a reviewer declaration against this run’s source timeline. These are not verified usable hours. Edited clean-video time cannot substitute for source time without a mapping.</p>
    <fieldset disabled={busy} style={{ border: 0, padding: 0 }}>
      <label>Task ID<input aria-label="Task ID" value={task} maxLength={80} onChange={e => setTask(e.target.value)} placeholder="Your task identifier" /></label>
      <button type="button" disabled={!validTask} onClick={() => request()}>Load task review</button>
      {projection && <>
        <p>Loaded task: <b>{projection.task_id}</b> · Revision {projection.revision}</p>
        <p className="ops-hint">Manifest: <code style={{ overflowWrap: 'anywhere' }}>{projection.manifest_sha256}</code></p>
        {projection.review && <p className="ops-hint">Declared by {projection.review.reviewer_email} · {projection.review.reviewed_at}</p>}
        <div className="ops-tablewrap"><table className="ops-table"><caption>Reviewer-declared duration in seconds, per recording</caption><thead><tr><th>Recording</th><th>Accepted</th><th>Excluded</th><th>Unknown</th></tr></thead><tbody>
          {projection.recordings.map(r => <tr key={r.recording}><td>{r.recording}</td><td>{nsToSeconds(r.accepted_ns)}</td><td>{nsToSeconds(r.excluded_ns)}</td><td>{nsToSeconds(r.unknown_ns)}</td></tr>)}
        </tbody></table></div>
        <p className="ops-hint">Unique usable time across cameras: unknown. Source validation, physical clocks and playback alignment are not established by this review.</p>
        <details><summary>Source evidence supplied by the imported manifest</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(projection.recordings.map(r => ({ recording: r.recording, source_duration_ns: r.source_duration_ns, sources: r.sources })), null, 2)}</pre></details>
        <form onSubmit={e => { e.preventDefault(); request(true); }}>
          <label>Criteria version<input aria-label="Criteria version" value={version} maxLength={80} onChange={e => setVersion(e.target.value)} required /></label>
          <label>Explicit task criteria<textarea aria-label="Explicit task criteria" value={criteria} maxLength={4000} onChange={e => setCriteria(e.target.value)} required /></label>
          <p className="ops-hint">Saving creates a complete replacement snapshot for this task. Omitted time becomes unknown. Previous revisions remain in history; changed criteria need a new version.</p>
          {rows.map((i, n) => <fieldset key={n} style={{ margin: '0.5rem 0', minWidth: 0 }}><legend>Interval {n + 1}</legend>
            <label>Recording<select aria-label={`Recording ${n + 1}`} value={i.recording} onChange={e => update(n, 'recording', e.target.value)} required><option value="">Choose a recording</option>{projection.recordings.map(r => <option key={r.recording} value={r.recording}>{r.recording}</option>)}</select></label>
            <label>Start seconds<input aria-label={`Start seconds ${n + 1}`} inputMode="decimal" maxLength={25} value={i.start} onChange={e => update(n, 'start', e.target.value)} required /></label>
            <label>End seconds<input aria-label={`End seconds ${n + 1}`} inputMode="decimal" maxLength={25} value={i.end} onChange={e => update(n, 'end', e.target.value)} required /></label>
            <label>Judgment<select aria-label={`Judgment ${n + 1}`} value={i.judgment} onChange={e => update(n, 'judgment', e.target.value)}><option value="unknown">Unknown</option><option value="accepted">Accepted for this task</option><option value="excluded">Excluded for this task</option></select></label>
            <label>Reason<textarea aria-label={`Reason ${n + 1}`} value={i.reason} maxLength={1000} onChange={e => update(n, 'reason', e.target.value)} required /></label>
            <button type="button" onClick={() => setRows(rows.filter((_, index) => index !== n))}>Remove interval {n + 1}</button>
          </fieldset>)}
          <button type="button" disabled={rows.length >= 1000} onClick={() => setRows([...rows, row(projection.recordings[0]?.recording)])}>Add interval</button>
          <button type="submit" disabled={task !== projection.task_id}>Save review declaration</button>
          {task !== projection.task_id && <p role="status">Load the new task before saving.</p>}
        </form>
      </>}
    </fieldset>
    {busy && <p role="status">Working…</p>}
    {error && <p className="ops-error" role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
  </section>;
}
