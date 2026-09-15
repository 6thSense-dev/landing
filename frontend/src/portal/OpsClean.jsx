import { useEffect, useMemo, useRef, useState } from 'react';
import FootageReview from './FootageReview.jsx';
import { portalFetch } from './portalFetch.js';
import { cleanTotals, groupCleanFootage } from './opsCleanGroups.js';

const time = (s) => {
  const seconds = Math.round(s || 0);
  return `${Math.floor(seconds / 3600)}h ${String(Math.floor(seconds % 3600 / 60)).padStart(2, '0')}m ${String(seconds % 60).padStart(2, '0')}s`;
};

export default function OpsClean({ onChanged }) {
  const dialog = useRef(null);
  const video = useRef(null);
  const [playbackError, setPlaybackError] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [person, setPerson] = useState('');
  const [preview, setPreview] = useState(null);
  const [message, setMessage] = useState('');
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
  useEffect(() => { load(); const timer = setInterval(load, 30000); return () => clearInterval(timer); }, []);
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
  const collections = (data?.collections || []).filter(c => !person || String(c.wearer_id) === person);
  const total = cleanTotals(runs);
  const groups = groupCleanFootage(runs, collections);
  const play = async (run, review = null) => {
    setError(''); setPlaybackError(false);
    try {
      const path = run.collection_id ? `/api/ops/clean/collections/${encodeURIComponent(run.collection_id)}/files` : `/api/ops/clean/runs/${encodeURIComponent(run.run_id)}/files`;
      const response = await portalFetch(path);
      if (!response.ok) throw new Error(response.data?.detail || 'Could not load playback.');
      const files = response.data.files || [];
      let index = review ? files.findIndex(f => f.role === 'recording_preview' && f.recording === review.recording) : files.findIndex(f => f.role === 'joined_preview');
      if (review && index < 0) index = files.findIndex(f => f.role === 'left_video' && f.recording === review.recording);
      if (review && index < 0) throw Error('A preview for this recording is not available. Review the batch before attesting to this recording.');
      setPreview({ run, path, files, index: Math.max(0, index), start: review?.clean_start_s || 0 });
    } catch (e) { setError(e.message); }
  };
  const renewVideo = async () => {
    const current = preview;
    const position = video.current?.currentTime || 0;
    const response = await portalFetch(current.path);
    if (!response.ok) { setPlaybackError(true); return; }
    const files = response.data.files || [];
    const index = files.findIndex(f => f.key === current.files[current.index].key);
    if (index < 0) { setPlaybackError(true); return; }
    setPreview({ ...current, files, index, start: position }); setPlaybackError(false);
  };
  return <section className="ops-clean" aria-label="Clean footage">
    <div className="ops-clean-intro">
      <div><h2>Clean footage & retained time</h2><p>Browse each contributor’s footage ledger and record your review before payment approval.</p></div>
      <button onClick={() => mutate('scan')} disabled={busy}>{busy ? 'Working…' : 'Refresh clean footage'}</button>
    </div>
    {error && <p className="ops-error" role="alert">{error}</p>}
    {!!data?.collection_errors && <p className="ops-error" role="alert">A combined video could not be verified against its source batches. Individual batches and payment estimates remain available.</p>}
    {!!data?.scan_errors?.length && <details className="ops-error"><summary>{data.scan_errors.length} results need attention before import</summary><ul>{data.scan_errors.map((e, i) => <li key={i}>{e.run_id || e.marker}: {e.error}</li>)}</ul></details>}
    {message && <p className="ops-note" role="status">{message}</p>}
    {!data && !error && <p className="ops-muted">Loading clean footage…</p>}
    <div>
      <div>
        <div className="ops-clean-filters"><label htmlFor="clean-person">Contributor</label><select id="clean-person" value={person} onChange={e => setPerson(e.target.value)}>
          <option value="">All contributors</option>{people.map(p => <option key={p.id} value={p.id}>{p.name}{p.workplace ? ` · ${p.workplace}` : ''}</option>)}
        </select></div>
        <div className="ops-tiles">
          {[[time(total.kept), 'Retained after QC'], [time(total.excluded), 'Excluded'], [time(total.source), 'Collected / decoded']].map(([value, label]) => <div className="ops-tile" key={label}><div className="ops-tile-n">{value}</div><div className="ops-tile-l">{label}</div></div>)}
        </div>
        {data && !groups.length && <div className="ops-panel ops-empty"><h3>No clean footage yet</h3><p>Assign a camera to a contributor, then refresh after QC finishes. Raw recordings remain available in the Raw tab.</p></div>}
        {groups.map(group => {
          const p = byId.get(group.wearer_id);
          const status = 'Footage ledger';
          const devices = [...new Set(group.runs.map(run => `EGO-${run.device_id}`))];
          const reviews = group.runs.flatMap(run => (run.review_intervals || []).map(item => ({ run, item })));
          return <article className="ops-panel ops-clean-card" key={group.key}>
            <div className="ops-clean-card-head"><div><span className="ops-clean-eyebrow">{p?.workplace || 'Workplace not set'}</span><h3>{p?.name || 'Unassigned contributor'}</h3><p>{[p?.location || 'Location not set', ...devices].join(' · ')}</p></div><span className="ops-clean-status">{status}</span></div>
            <div className="ops-clean-metrics"><div><b>{time(group.totals.kept)}</b><span>retained</span></div><div><b>{time(group.totals.excluded)}</b><span>excluded</span></div><div><b>{time(group.totals.source)}</b><span>collected / decoded</span></div></div>
            {group.collections.map(collection => {
              const includedRuns = new Set(collection.source_runs.map(run => run.run_id));
              const coversAll = group.runs.every(run => includedRuns.has(run.run_id));
              return <div className="ops-clean-actions" key={collection.collection_id}><button onClick={() => play(collection)}>{group.collections.length > 1 ? collection.label : coversAll ? 'Watch all clean footage' : 'Watch combined footage'}</button><span className="ops-muted">{time(collection.retained_seconds)} · {collection.recordings.length} recordings</span></div>;
            })}
            {!group.collections.length && group.runs.length === 1 && <div className="ops-clean-actions"><button onClick={() => play(group.runs[0])}>Watch joined footage</button></div>}
            <p className="ops-hint">{time(group.totals.source)} decoded · {group.runs.length} processing {group.runs.length === 1 ? 'batch' : 'batches'}. Time is counted once across batches.</p>
            {!!reviews.length && <details><summary>Flagged footage to review ({reviews.length})</summary><ul>{reviews.map(({ run, item }, i) => <li key={`${run.run_id}:${i}`}>{item.recording} · {time(item.start_s)}–{time(item.end_s)} · {item.reason} <button onClick={() => play(run, item)}>Review interval</button></li>)}</ul></details>}
            {!!group.runs.length && <details><summary>Batch details & source recordings ({group.runs.length})</summary>{group.runs.map((run, index) => <section className="ops-clean-batch" key={run.run_id} aria-label={`Batch ${index + 1}`}>
              <h4>Batch {index + 1} · {run.recording_count} source recordings</h4>
              <p>{time(run.retained_seconds)} retained · {time(run.rejected_seconds)} excluded</p>

              <button onClick={() => play(run)}>Watch batch {index + 1}</button>
              {!!run.warnings?.length && <details><summary>QC notes ({run.warnings.length})</summary><ul>{run.warnings.map((w, i) => <li key={i}>{typeof w === 'string' ? w : JSON.stringify(w)}</li>)}</ul></details>}
              <div className="ops-tablewrap"><table className="ops-table"><thead><tr><th>Recording</th><th>Decoded</th><th>Retained</th><th>QC</th></tr></thead><tbody>{run.recordings.map(r => <tr key={r.recording}><td className="mono">{r.recording}</td><td>{time(r.source_seconds)}</td><td>{time(r.retained_seconds)}</td><td>{r.status}</td></tr>)}</tbody></table></div>
            </section>)}</details>}
            {(data.ledger || []).filter(e => e.wearer_id === group.wearer_id).map(entry => <FootageReview key={`${entry.run_id}:${entry.recording}`} entry={entry} onChanged={load} onPlay={() => play(group.runs.find(r => r.run_id === entry.run_id), { recording: entry.recording })} />)}<p className="ops-hint">After reviewing the footage, approve the payout in Payment.</p>
          </article>;
        })}
      </div>

    </div>
    {preview && <div ref={dialog} className="ops-clean-modal" role="dialog" aria-modal="true" aria-label="Clean footage player"><div className="ops-panel"><div className="ops-phead"><h2>Clean footage</h2><button autoFocus onClick={() => setPreview(null)}>Close</button></div><div className="ops-pbody">
      {!preview.files.length ? <p>No playable output is available.</p> : <><video ref={video} key={preview.files[preview.index].url} onError={() => setPlaybackError(true)} controls playsInline preload="metadata" src={preview.files[preview.index].url} onLoadedMetadata={e => { e.currentTarget.currentTime = preview.start || 0; }} onEnded={() => { if (preview.index + 1 < preview.files.length) setPreview({ ...preview, index: preview.index + 1, start: 0 }); }} /><label htmlFor="clean-file">Video</label><select id="clean-file" value={preview.index} onChange={e => setPreview({ ...preview, index: Number(e.target.value), start: 0 })}>{preview.files.map((f, i) => <option key={f.key} value={i}>{f.label || f.key.split('/').pop()}</option>)}</select><button onClick={renewVideo}>Reload video link</button>{playbackError && <p role="alert">Playback stopped. Reload the link to resume, or try the browser preview if the original format is unsupported.</p>}<a href={preview.files[preview.index].url} target="_blank" rel="noreferrer">Open video in a new tab</a></>}
    </div></div></div>}
  </section>;
}
