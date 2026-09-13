import { useEffect, useMemo, useRef, useState } from 'react';
import { portalFetch } from './portalFetch.js';
import OpsActivityReview from './OpsActivityReview.jsx';

const time = (s) => {
  const seconds = Math.round(s || 0);
  return `${Math.floor(seconds / 3600)}h ${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}m ${String(seconds % 60).padStart(2, '0')}s`;
};
const money = (n) => n == null ? 'Rate not set' : `₩${n.toLocaleString('ko-KR')}`;

export default function OpsClean({ onChanged }) {
  const dialog = useRef(null);
  const video = useRef(null);
  const [playbackError, setPlaybackError] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [person, setPerson] = useState('');
  const [device, setDevice] = useState('');
  const [wearer, setWearer] = useState('');
  const [assignExisting, setAssignExisting] = useState(false);
  const [preview, setPreview] = useState(null);
  const [message, setMessage] = useState('');
  const [reviewRun, setReviewRun] = useState(null);
  useEffect(() => {
    if (!preview) return;
    const previous = document.activeElement;
    const onKey = e => {
      if (e.key === 'Escape') setPreview(null);
      if (e.key === 'Tab') {
        const items = dialog.current?.querySelectorAll('button, select, a[href], video');
        if (!items?.length) return;
        const first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); previous?.focus(); };
  }, [Boolean(preview)]);
  const load = async () => {
    try {
      const response = await portalFetch('/api/ops/clean/state');
      if (!response.ok) throw new Error(response.data?.detail || 'Could not load clean footage.');
      setData(response.data); setError('');
    } catch (e) { setError(e.message); }
  };
  useEffect(() => { load(); }, []);
  const mutate = async (path, body) => {
    setBusy(true); setError('');
    try {
      const response = await portalFetch(`/api/ops/clean/${path}`, { method: 'POST', body: JSON.stringify(body || {}) });
      if (!response.ok) throw new Error(response.data?.detail || 'The change could not be saved.');
      setData(response.data);
      if (response.data.scan_errors?.length) setError(`${response.data.scan_errors.length} clean result(s) could not be verified and were skipped. Their footage was not added to the estimate.`);
      onChanged?.();
      setMessage(path === 'scan' ? `${response.data.imported} new clean collection(s) imported.` : 'Camera assignment saved.');
      return true;
    } catch (e) { setError(e.message); return false; }
    finally { setBusy(false); }
  };
  const people = data?.wearers || [];
  const byId = useMemo(() => new Map(people.map(p => [p.id, p])), [people]);
  const runs = (data?.runs || []).filter(r => !person || String(r.wearer_id) === person);
  const total = runs.reduce((a, r) => ({ kept: a.kept + r.retained_seconds, excluded: a.excluded + r.rejected_seconds,
    due: a.due + (!r.paid ? r.estimated_krw || 0 : 0), missing: a.missing || (!r.paid && r.estimated_krw == null) }), { kept: 0, excluded: 0, due: 0, missing: false });
  const play = async (run, review = null) => {
    setError(''); setPlaybackError(false);
    try {
      const response = await portalFetch(`/api/ops/clean/runs/${encodeURIComponent(run.run_id)}/files`);
      if (!response.ok) throw new Error(response.data?.detail || 'Could not load playback.');
      const files = response.data.files || [];
      const index = review ? files.findIndex(f => f.role === 'recording_preview' && f.recording === review.recording) : files.findIndex(f => f.role === 'joined_preview');
      setPreview({ run, files, index: Math.max(0, index), start: review?.clean_start_s || 0 });
    } catch (e) { setError(e.message); }
  };
  const renewVideo = async () => {
    const current = preview;
    const position = video.current?.currentTime || 0;
    const response = await portalFetch(`/api/ops/clean/runs/${encodeURIComponent(current.run.run_id)}/files`);
    if (!response.ok) { setPlaybackError(true); return; }
    const files = response.data.files || [];
    const index = files.findIndex(f => f.key === current.files[current.index].key);
    if (index < 0) { setPlaybackError(true); return; }
    setPreview({ ...current, files, index, start: position }); setPlaybackError(false);
  };
  return <section className="ops-clean" aria-label="Clean footage">
    <div className="ops-clean-intro">
      <div><h2>Clean footage & retained time</h2><p>Review the retained footage, its contributor, and the estimated payment.</p></div>
      <button onClick={() => mutate('scan')} disabled={busy}>{busy ? 'Working…' : 'Refresh clean footage'}</button>
    </div>
    {error && <p className="ops-error" role="alert">{error}</p>}
    {message && <p className="ops-note" role="status">{message}</p>}
    {!data && !error && <p className="ops-muted">Loading clean footage…</p>}
    <div className="ops-clean-layout">
      <div>
        <div className="ops-clean-filters"><label htmlFor="clean-person">Contributor</label><select id="clean-person" value={person} onChange={e => setPerson(e.target.value)}>
          <option value="">All contributors</option>{people.map(p => <option key={p.id} value={p.id}>{p.name}{p.workplace ? ` · ${p.workplace}` : ''}</option>)}
        </select></div>
        <div className="ops-tiles">
          {[[time(total.kept), 'Retained after QC'], [time(total.excluded), 'Excluded'], [total.missing ? 'Rate needed' : money(total.due), 'Estimated · unpaid']].map(([value, label]) => <div className="ops-tile" key={label}><div className="ops-tile-n">{value}</div><div className="ops-tile-l">{label}</div></div>)}
        </div>
        {data && !runs.length && <div className="ops-panel ops-empty"><h3>No clean footage yet</h3><p>Assign a camera to a contributor, then refresh after QC finishes. Raw recordings remain available in the Raw tab.</p></div>}
        {runs.map(run => {
          const p = byId.get(run.wearer_id);
          return <article className="ops-panel ops-clean-card" key={run.run_id}>
            <div className="ops-clean-card-head"><div><span className="ops-clean-eyebrow">{p?.workplace || 'Workplace not set'}</span><h3>{p?.name || 'Unassigned contributor'}</h3><p>{p?.location || 'Location not set'} · EGO-{run.device_id}</p></div><span className="ops-clean-status">{run.paid ? 'Paid' : 'Unpaid'}</span></div>
            <div className="ops-clean-metrics"><div><b>{time(run.retained_seconds)}</b><span>retained</span></div><div><b>{time(run.rejected_seconds)}</b><span>excluded</span></div><div><b>{money(run.estimated_krw)}</b><span>{run.rate_krw_hour == null ? 'set a rate before approval' : `${money(run.rate_krw_hour)} / approved hour`}</span></div></div>
            <p className="ops-hint">Full intervals with neither hand visible for more than 30 seconds are excluded. Shorter absences are kept. Other idle time still needs review.</p>
            <div className="ops-clean-actions"><button onClick={() => play(run)}>Watch joined footage</button><span className="ops-muted">{run.recording_count} source recordings · {time(run.source_seconds)} decoded</span></div>
            {!!run.review_intervals?.length && <details><summary>Idle footage to review ({run.review_intervals.length})</summary><ul>{run.review_intervals.map((item, i) => <li key={i}>{item.recording} · {time(item.start_s)}–{time(item.end_s)} · {item.reason} <button onClick={() => play(run, item)}>Review interval</button></li>)}</ul></details>}
            {!!run.warnings?.length && <details><summary>QC notes ({run.warnings.length})</summary><ul>{run.warnings.map((w, i) => <li key={i}>{typeof w === 'string' ? w : JSON.stringify(w)}</li>)}</ul></details>}
            <details><summary>Source recordings and retained time</summary><div className="ops-tablewrap"><table className="ops-table"><thead><tr><th>Recording</th><th>Decoded</th><th>Retained</th><th>QC</th></tr></thead><tbody>{run.recordings.map(r => <tr key={r.recording}><td className="mono">{r.recording}</td><td>{time(r.source_seconds)}</td><td>{time(r.retained_seconds)}</td><td>{r.status}</td></tr>)}</tbody></table></div></details>
            <p className="ops-hint">Estimate only. No payment is sent or recorded by importing this collection.</p>
            <button type="button" onClick={() => setReviewRun(reviewRun === run.run_id ? null : run.run_id)}>{reviewRun === run.run_id ? 'Close task review' : 'Review task activity'}</button>
            {reviewRun === run.run_id && <OpsActivityReview key={run.run_id} runId={run.run_id} />}
          </article>;
        })}
      </div>
      <aside className="ops-side">
        <div className="ops-panel"><div className="ops-phead"><h2>Camera assignment</h2></div><form className="ops-pbody" onSubmit={async e => { e.preventDefault(); await mutate('cameras', { device_id: device, wearer_id: Number(wearer), assign_unassigned_recordings: assignExisting }); }}>
          <label htmlFor="clean-camera">Camera</label><input id="clean-camera" value={device} onChange={e => setDevice(e.target.value)} placeholder="EGO-ABC123" required maxLength={32} />
          <label htmlFor="clean-wearer">Contributor</label><select id="clean-wearer" value={wearer} onChange={e => setWearer(e.target.value)} required><option value="">Choose a person</option>{people.filter(p => p.is_active).map(p => <option value={p.id} key={p.id}>{p.name} · {p.workplace || 'Workplace not set'}</option>)}</select>
          <label className="ops-check"><input type="checkbox" checked={assignExisting} onChange={e => setAssignExisting(e.target.checked)} />Also assign existing unassigned, unpaid raw recordings</label>
          <button disabled={busy || !device || !wearer}>Save assignment</button><p className="ops-hint">Previously assigned recordings, clean collections, and payment history keep their attribution.</p>
        </form></div>
        <div className="ops-panel"><div className="ops-phead"><h2>Assigned cameras</h2></div><div className="ops-pbody">
          {(data?.cameras || []).map(camera => { const p = byId.get(camera.wearer_id); return <div className="ops-clean-person" key={camera.device_id}><b>EGO-{camera.device_id}</b><span>{p?.name || 'Unassigned'} · {p?.workplace || 'Workplace not set'}</span><span>{p?.location || 'Location not set'}</span><span>{p?.contact || 'Contact not provided'}</span><span>{p?.rate_krw_hour == null ? 'Rate not set' : `${money(p.rate_krw_hour)} / approved hour`}</span></div>; })}
          <p className="ops-hint">Edit the person’s workplace, location, contact details, and hourly rate in Users.</p>
        </div></div>
      </aside>
    </div>
    {preview && <div ref={dialog} className="ops-clean-modal" role="dialog" aria-modal="true" aria-label="Clean footage player"><div className="ops-panel"><div className="ops-phead"><h2>Clean footage</h2><button autoFocus onClick={() => setPreview(null)}>Close</button></div><div className="ops-pbody">
      {!preview.files.length ? <p>No playable output is available.</p> : <><video ref={video} key={preview.files[preview.index].url} onError={() => setPlaybackError(true)} controls playsInline preload="metadata" src={preview.files[preview.index].url} onLoadedMetadata={e => { e.currentTarget.currentTime = preview.start || 0; }} onEnded={() => { if (preview.index + 1 < preview.files.length) setPreview({ ...preview, index: preview.index + 1, start: 0 }); }} /><label htmlFor="clean-file">Video</label><select id="clean-file" value={preview.index} onChange={e => setPreview({ ...preview, index: Number(e.target.value), start: 0 })}>{preview.files.map((f, i) => <option key={f.key} value={i}>{f.label || f.key.split('/').pop()}</option>)}</select><button onClick={renewVideo}>Reload video link</button>{playbackError && <p role="alert">Playback stopped. Reload the link to resume, or try the browser preview if the original format is unsupported.</p>}<a href={preview.files[preview.index].url} target="_blank" rel="noreferrer">Open video in a new tab</a></>}
    </div></div></div>}
  </section>;
}
