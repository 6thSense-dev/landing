import { useCallback, useEffect, useMemo, useState } from 'react';
import { portalFetch } from './portalFetch.js';
import './opsSieve.css';

const hours = seconds => (Number(seconds || 0) / 3600).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const stamp = value => value ? new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Not yet';
const labels = { inherited: 'Inherited', pending: 'Pending', blocked: 'Blocked' };

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
  useEffect(() => { load(); const timer = setInterval(load, 30000); return () => clearInterval(timer); }, [load]);
  const rows = useMemo(() => (data?.recordings || []).filter(r => (!country || r.country === country) && (!status || r.status === status)
    && `${r.recording} ${r.entity.name} ${r.activity} ${r.camera}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())), [data, country, status, query]);
  if (!data) return <section className="sieve"><h2>Sieve</h2>{error ? <><p className="ops-error" role="alert">{error}</p><button className="ops-scan" onClick={load}>Retry</button></> : <p className="ops-muted" role="status">Loading Sieve collection…</p>}</section>;
  const t = data.totals, b = data.breakdowns;
  const progress = t.clean_seconds ? t.inherited_seconds / t.clean_seconds * 100 : 0;
  const filteredHours = rows.reduce((sum, r) => sum + r.retained_seconds, 0);
  const lastCheck = data.sync.completed_at || data.sync.started_at;
  const stale = lastCheck && Date.now() - new Date(lastCheck).getTime() > 15 * 60 * 1000;
  return <section className="sieve" aria-labelledby="sieve-title">
    <div className="sieve-heading">
      <div><p className="sieve-eyebrow">Customer collection · temporary dashboard</p><h2 id="sieve-title">Sieve</h2><p className="sieve-subtitle">Clean → Sieve <span>MP4 · metadata · calibration</span></p></div>
      <div className="sieve-deadline"><strong>Contract ends Sep 22, 2026</strong><span>Dashboard through Sep 25 · Los Angeles time</span><button className="ops-scan" disabled={loading} onClick={load}>{loading ? 'Refreshing…' : 'Refresh dashboard'}</button></div>
    </div>
    {error && <p className="ops-error" role="alert">{error} Showing the last loaded snapshot.</p>}
    {(data.sync.error || stale || !data.automatic_sync) && <p className="ops-error" role="status">{data.sync.error || (stale ? 'Inheritance verification is overdue. Counts show the last verified copies.' : 'Automatic inheritance is not running.')}</p>}
    <div className="sieve-stats">
      <article><span>Hours collected in Clean</span><strong>{hours(t.clean_seconds)}<small> h</small></strong><p>{t.recordings} unique recordings · retained footage</p></article>
      <article className="sieve-stat-accent"><span>Hours inherited by Sieve</span><strong>{hours(t.inherited_seconds)}<small> h</small></strong><p>{t.inherited_recordings} verified recordings · {(t.copied_bytes / 1e9).toFixed(1)} GB</p></article>
      <article><span>Source diversity</span><strong>{t.countries}<small> countries</small></strong><p>{t.entities} contributors / businesses · {t.cameras} cameras</p></article>
      <article><span>Customer acceptance</span><strong>Not recorded</strong><p>Copied footage awaits customer acceptance.</p></article>
    </div>
    <section className="sieve-progress" aria-label="Inheritance progress">
      <div><strong>{Math.round(progress)}% inherited from Clean</strong><span>{t.status_counts.pending || 0} pending · {t.status_counts.blocked || 0} blocked</span></div>
      <progress value={t.inherited_seconds} max={t.clean_seconds || 1} aria-label="Clean hours inherited by Sieve" />
      <p>Each recording counts once across both eyes. Original codecs are preserved. Previous Raw-derived Sieve files are excluded.</p>
    </section>
    <div className="sieve-section-heading"><h3>Collection diversity</h3><p>All Clean recordings · <i className="sieve-legend" /> inherited portion</p></div>
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
    <footer className="sieve-footer"><span>Snapshot {stamp(data.updated_at)} · Last full verification {stamp(data.sync.completed_at)}</span><code>s3://{data.bucket}/{data.prefix}</code><span>Dashboard refreshes every 30 seconds. Inheritance checks run every 5 minutes.</span></footer>
  </section>;
}
