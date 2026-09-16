import { useCallback, useEffect, useMemo, useState } from 'react';
import { portalFetch } from './portalFetch.js';
import './opsSieve.css';

const hours = seconds => (Number(seconds || 0) / 3600).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const stamp = value => value ? new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Not yet';
const labels = { inherited: 'Inherited', pending: 'Pending', blocked: 'Blocked' };
const knownNumber = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const count = value => knownNumber(value) ? value.toLocaleString() : '—';
const pipelineHours = value => knownNumber(value) ? `${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} h` : 'Not reported';
const bytes = value => knownNumber(value) ? `${(value / 1e9).toLocaleString(undefined, { maximumFractionDigits: 2 })} GB` : 'Not reported';
const ratio = (value, total) => `${count(value)} / ${count(total)}`;
const pipelineStates = {
  PASS: 'Passed', FAILED: 'Needs attention', FAIL: 'Needs attention', ERROR: 'Needs attention',
  RUNNING: 'In progress', IN_PROGRESS: 'In progress', PREPARING: 'Preparing', PROCESSING: 'Processing',
  UPLOADING: 'Uploading', TRANSFERRING: 'Uploading', COMPLETE: 'Complete', COMPLETED: 'Complete',
  DELIVERED: 'Uploaded', SUCCEEDED: 'Complete', READY_FOR_REVIEW: 'Ready for review',
  DRAFT_PENDING_REVIEW: 'Review pending', PENDING: 'Pending', WAITING: 'Waiting',
  VALIDATING: 'Validating', PARTIAL: 'In progress', UNAVAILABLE: 'Unavailable', UNKNOWN: 'Not yet reported',
  PACKAGING: 'Packaging', DELIVERED_CHECKSUMS_VERIFIED: 'Uploaded and checksummed', BLOCKED: 'Held', INCONSISTENT: 'Needs verification',
};

function PipelineCard({ title, data, className = '', children, state }) {
  const available = data?.available === true;
  return <article className={`sieve-pipeline-card ${className}`} aria-label={title}>
    <div className="sieve-pipeline-card-heading"><h4>{title}</h4>
      <span className={`sieve-pipeline-state${data?.stale ? ' sieve-pipeline-stale' : ''}`}>{!available ? 'Unavailable' : data.stale ? 'Stale snapshot' : state || 'Latest snapshot'}</span>
    </div>
    {available ? children : <p className="sieve-pipeline-unavailable">Status unavailable. No count is assumed.</p>}
    <p className="sieve-pipeline-updated">{data?.updated_at ? `Updated ${stamp(data.updated_at)}` : 'Update time not reported'}</p>
  </article>;
}

function PipelineProgress({ data, error, loading }) {
  const company = data?.company, delivery = data?.delivery, validation = data?.validation, supplement = data?.supplement;
  const filesKnown = knownNumber(delivery?.uploaded_files) && knownNumber(delivery?.total_files) && delivery.total_files > 0;
  const validationState = validation?.state === 'PASS' ? 'Passed' : ({ FAILED: 'Needs attention', FAIL: 'Needs attention', ERROR: 'Needs attention', RUNNING: 'In progress', IN_PROGRESS: 'In progress', VALIDATING: 'In progress', PENDING: 'Pending', WAITING: 'Waiting' }[validation?.state] || 'Result not yet reported');
  return <section className="sieve-pipeline" aria-labelledby="sieve-pipeline-title">
    <div className="sieve-pipeline-heading"><div><p className="sieve-eyebrow">Processing and delivery</p><h3 id="sieve-pipeline-title">Live pipeline progress</h3>
      <p>Company processing, customer uploads and private review footage are counted separately.</p></div>
      <p className="sieve-pipeline-checked">{data?.checked_at ? `Checked ${stamp(data.checked_at)}` : 'Awaiting first update'}<span>Refreshes every 30 seconds</span></p>
    </div>
    {loading && !data && <p className="sieve-pipeline-notice" role="status">Loading pipeline status…</p>}
    {error && <p className="sieve-pipeline-notice" role="status">{data ? 'Live update failed. Showing the last loaded pipeline snapshot.' : 'Live pipeline status is unavailable. Collection figures are shown separately below.'}</p>}
    {!error && (data?.cache?.stale || data?.errors?.length > 0) && <p className="sieve-pipeline-notice" role="status">{data?.cache?.stale ? 'Pipeline updates are delayed. These are the last available figures.' : 'Some pipeline updates are unavailable. Check each stage’s status below.'}</p>}
    <div className="sieve-pipeline-grid">
      <PipelineCard title="Company Raw → Clean" data={company} className="sieve-pipeline-company">
        <p className="sieve-pipeline-context">All countries · company processing</p>
        <dl className="sieve-pipeline-counts">{[['Source groups', company?.source_groups], ['Archived', company?.archived], ['Clean complete', company?.clean_complete], ['In progress', company?.in_progress], ['Held', company?.held], ['Deleted', company?.deleted]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{count(value)}</dd></div>)}</dl>
      </PipelineCard>
      <PipelineCard title="Sieve preparation" data={delivery} state={pipelineStates[delivery?.state] || 'Status not yet reported'}>
        <p className="sieve-pipeline-value">{pipelineHours(delivery?.prepared_hours)}<span>prepared</span></p>
        <dl className="sieve-pipeline-details"><div><dt>Recordings processed</dt><dd>{ratio(delivery?.recordings_processed, delivery?.recordings_expected)}</dd></div><div><dt>Packaged assets</dt><dd>{count(delivery?.packaged_assets)}</dd></div></dl>
        <p className="sieve-pipeline-context">Preparation does not confirm customer upload.</p>
      </PipelineCard>
      <PipelineCard title="Uploaded to Sieve" data={delivery} className="sieve-pipeline-upload" state={delivery?.complete === true ? 'Upload complete' : pipelineStates[delivery?.state] || 'Status not yet reported'}>
        <p className="sieve-pipeline-value">{pipelineHours(delivery?.uploaded_hours)}<span>uploaded hours</span></p>
        <p className="sieve-pipeline-context">Customer delivery location · OCI</p>
        <dl className="sieve-pipeline-details"><div><dt>Uploaded assets</dt><dd>{count(delivery?.uploaded_assets)}</dd></div><div><dt>Uploaded files</dt><dd>{ratio(delivery?.uploaded_files, delivery?.total_files)}</dd></div><div><dt>Uploaded data</dt><dd>{bytes(delivery?.uploaded_bytes)} / {bytes(delivery?.total_bytes)}</dd></div></dl>
        {filesKnown && <progress value={Math.min(delivery.uploaded_files, delivery.total_files)} max={delivery.total_files} aria-label="Files uploaded to Sieve" aria-valuetext={`${count(delivery.uploaded_files)} of ${count(delivery.total_files)} files`} />}
        {!knownNumber(delivery?.uploaded_hours) && <p className="sieve-pipeline-context">Uploaded hours are not yet confirmed.</p>}
      </PipelineCard>
      <PipelineCard title="Independent validation" data={validation} state={validationState}>
        <p className={`sieve-pipeline-value sieve-pipeline-verdict${validation?.state === 'PASS' ? ' sieve-pipeline-pass' : ''}`}>{validationState}</p>
        <dl className="sieve-pipeline-details"><div><dt>Clip reports found</dt><dd>{ratio(validation?.clip_reports, validation?.total_clips)}</dd></div></dl>
        <p className="sieve-pipeline-context">Report counts do not mean every clip passed. Technical checks do not record customer acceptance.</p>
      </PipelineCard>
      <PipelineCard title="Private originals supplement" data={supplement} state={pipelineStates[supplement?.state] || 'Status not yet reported'}>
        <p className="sieve-pipeline-value">{pipelineHours(supplement?.hours)}<span>potential technical hours</span></p>
        <dl className="sieve-pipeline-details"><div><dt>Recordings</dt><dd>{count(supplement?.recordings)}</dd></div><div><dt>Original data</dt><dd>{bytes(supplement?.bytes)}</dd></div></dl>
        <p className="sieve-pipeline-context">{supplement?.external_delivery_performed === false ? 'Privately staged · not uploaded to Sieve. Excluded from uploaded hours.' : 'External delivery status needs verification. Excluded from the main batch’s uploaded hours.'}</p>
      </PipelineCard>
    </div>
  </section>;
}

function Distribution({ title, rows, total }) {
  return <section className="sieve-panel" aria-label={title}>
    <h3>{title}</h3>
    {!rows.length ? <p className="ops-hint">No Clean footage yet.</p> : <ul className="sieve-bars">
      {rows.map(row => <li key={row.label}>
        <div><span>{row.label}</span><span className="sieve-number">{hours(row.seconds)} h <small>· {total ? Math.round(row.seconds / total * 100) : 0}%</small></span></div>
        <div className="sieve-track" aria-hidden="true"><span style={{ width: `${total ? row.seconds / total * 100 : 0}%` }}><i style={{ width: `${row.seconds ? row.inherited_seconds / row.seconds * 100 : 0}%` }} /></span></div>
        <small>{row.recordings} recording{row.recordings === 1 ? '' : 's'} · {hours(row.inherited_seconds)} h inherited</small>
      </li>)}
    </ul>}
  </section>;
}

export default function OpsSieve({ onExpired }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [pipeline, setPipeline] = useState(null);
  const [pipelineError, setPipelineError] = useState(false);
  const [pipelineLoading, setPipelineLoading] = useState(false);
  const [country, setCountry] = useState('');
  const [status, setStatus] = useState('');
  const [query, setQuery] = useState('');
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await portalFetch('/api/ops/sieve/state');
      if (response.status === 410) { onExpired?.(); return; }
      if (!response.ok) throw Error('Could not refresh Sieve. Please try again.');
      setData(response.data); setError('');
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }, [onExpired]);
  const loadPipeline = useCallback(async () => {
    setPipelineLoading(true);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await portalFetch('/api/ops/sieve/pipeline', { signal: controller.signal });
      if (response.status === 410) { onExpired?.(); return; }
      if (!response.ok || !response.data || typeof response.data !== 'object') throw Error('Unavailable');
      setPipeline(response.data); setPipelineError(false);
    } catch { setPipelineError(true); }
    finally { clearTimeout(timeout); setPipelineLoading(false); }
  }, [onExpired]);
  const refresh = useCallback(() => { load(); loadPipeline(); }, [load, loadPipeline]);
  useEffect(() => { refresh(); const timer = setInterval(refresh, 30000); return () => clearInterval(timer); }, [refresh]);
  const rows = useMemo(() => (data?.recordings || []).filter(r => (!country || r.country === country) && (!status || r.status === status)
    && `${r.recording} ${r.entity.name} ${r.activity} ${r.camera}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())), [data, country, status, query]);
  const t = data?.totals, b = data?.breakdowns;
  const progress = t?.clean_seconds ? t.inherited_seconds / t.clean_seconds * 100 : 0;
  const filteredHours = rows.reduce((sum, r) => sum + r.retained_seconds, 0);
  const lastCheck = data?.sync?.completed_at || data?.sync?.started_at;
  const stale = lastCheck && Date.now() - new Date(lastCheck).getTime() > 15 * 60 * 1000;
  return <section className="sieve" aria-labelledby="sieve-title">
    <div className="sieve-heading">
      <div><p className="sieve-eyebrow">Customer collection · temporary dashboard</p><h2 id="sieve-title">Sieve</h2><p className="sieve-subtitle">Delivery and internal collection <span>MP4 · metadata · calibration</span></p></div>
      <div className="sieve-deadline"><strong>Contract ends Sep 22, 2026</strong><span>Dashboard through Sep 25 · Los Angeles time</span><button className="ops-scan" disabled={loading || pipelineLoading} onClick={refresh}>{loading || pipelineLoading ? 'Refreshing…' : 'Refresh dashboard'}</button></div>
    </div>
    <PipelineProgress data={pipeline} error={pipelineError} loading={pipelineLoading} />
    {error && <p className="ops-error" role="alert">{error}{data && ' Showing the last loaded snapshot.'}</p>}
    {!data && (error ? <button className="ops-scan" onClick={load}>Retry</button> : <p className="ops-muted" role="status">Loading Sieve collection…</p>)}
    {data && <>
    {(data.sync.error || stale || !data.automatic_sync) && <p className="ops-error" role="status">{data.sync.error || (stale ? 'Inheritance verification is overdue. Counts show the last verified copies.' : 'Automatic inheritance is not running.')}</p>}
    <div className="sieve-section-heading"><h3>Internal collection</h3><p>These copies are internal storage, not customer delivery.</p></div>
    <div className="sieve-stats">
      <article><span>Hours collected in Clean</span><strong>{hours(t.clean_seconds)}<small> h</small></strong><p>{t.recordings} unique recordings · retained footage</p></article>
      <article className="sieve-stat-accent"><span>Copied to internal Sieve storage</span><strong>{hours(t.inherited_seconds)}<small> h</small></strong><p>{t.inherited_recordings} verified recordings · {(t.copied_bytes / 1e9).toFixed(1)} GB</p></article>
      <article><span>Source diversity</span><strong>{t.countries}<small> countries</small></strong><p>{t.entities} contributors / businesses · {t.cameras} cameras</p></article>
      <article><span>Customer acceptance</span><strong>Not recorded</strong><p>Copied footage awaits customer acceptance.</p></article>
    </div>
    <section className="sieve-progress" aria-label="Inheritance progress">
      <div><strong>{Math.round(progress)}% inherited from Clean</strong><span>{t.status_counts.pending || 0} pending · {t.status_counts.blocked || 0} blocked</span></div>
      <progress value={t.inherited_seconds} max={t.clean_seconds || 1} aria-label="Clean hours inherited by Sieve" />
      <p>Each recording counts once across both eyes. Original codecs are preserved. Deleted recordings and previous Raw-derived Sieve files are excluded.</p>
    </section>
    <div className="sieve-section-heading"><h3>Collection diversity</h3><p>Active Clean recordings · <i className="sieve-legend" /> inherited portion</p></div>
    <div className="sieve-grid">
      <Distribution title="Country" rows={b.country} total={t.clean_seconds} />
      <Distribution title="Contributor / business" rows={b.entity} total={t.clean_seconds} />
      <Distribution title="Activity" rows={b.activity} total={t.clean_seconds} />
      <Distribution title="Clean intake by day" rows={b.clean_date} total={t.clean_seconds} />
    </div>
    <p className="sieve-caption">Activity uses operator labels; unclassified footage stays visible. Intake dates show when footage entered Clean, in Los Angeles time.</p>
    <div className="sieve-section-heading"><h3>Recordings</h3><p>{rows.length} shown · {hours(filteredHours)} h</p></div>
    <div className="sieve-filters">
      <label>Search<input aria-label="Search recordings" type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Recording, source, activity or camera" /></label>
      <label>Country<select aria-label="Filter recordings by country" value={country} onChange={e => setCountry(e.target.value)}><option value="">All countries</option>{b.country.map(r => <option key={r.label}>{r.label}</option>)}</select></label>
      <label>Status<select aria-label="Filter recordings by status" value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    </div>
    <div className="sieve-recordings">
      {!rows.length && <p className="sieve-empty">{data.recordings.length ? 'No recordings match these filters.' : 'New recordings will appear after they enter Clean.'}</p>}
      {rows.map(row => <details className="sieve-recording" key={`${row.run_id}/${row.recording}`}>
        <summary><span className="sieve-recording-name"><strong>{row.recording}</strong><small>{row.entity.name} · {row.country}</small></span><span className="sieve-duration">{hours(row.retained_seconds)} h</span><span className={`sieve-status sieve-status-${row.status}`}>{labels[row.status] || row.status}</span></summary>
        <dl><div><dt>Activity</dt><dd>{row.activity}</dd></div><div><dt>Camera / format</dt><dd>{row.camera} · {row.format}</dd></div><div><dt>Clean batch</dt><dd>{row.run_id}</dd></div><div><dt>Last verified</dt><dd>{stamp(row.checked_at)}</dd></div></dl>
        {row.reason && <p className="sieve-reason">{row.reason}</p>}
        {row.status === 'inherited' && <p className="sieve-reason">MP4, original metadata, metadata provenance, and calibration copied from versioned Clean artifacts.</p>}
      </details>)}
    </div>
    <footer className="sieve-footer"><span>Snapshot {stamp(data.updated_at)} · Last full verification {stamp(data.sync.completed_at)}</span><span>Dashboard refreshes every 30 seconds. Internal copy checks run every 5 minutes.</span></footer>
    </>}
  </section>;
}
