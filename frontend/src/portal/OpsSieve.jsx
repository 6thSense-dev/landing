import { useCallback, useEffect, useMemo, useState } from 'react';
import { portalFetch } from './portalFetch.js';
import SieveEpisode from './SieveEpisode.jsx';
import './opsSieve.css';

const hours = seconds => (Number(seconds || 0) / 3600).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const stamp = value => value ? new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : 'Not yet';
const labels = { inherited: 'Copied internally', pending: 'Copy pending', blocked: 'Copy blocked' };
const DELIVERY_TARGET_HOURS = 10;
const PAGE_SIZE = 10;
const knownNumber = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const count = value => knownNumber(value) ? value.toLocaleString() : '—';
const pipelineHours = value => knownNumber(value) ? `${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} h` : 'Not reported';
const bytes = value => knownNumber(value) ? `${(value / 1e9).toLocaleString(undefined, { maximumFractionDigits: 2 })} GB` : 'Not reported';
const ratio = (value, total) => `${count(value)} / ${count(total)}`;
const customerHoldReason = reason => ({
  historical_delivery_overlap_reserved: 'Source already belongs to an earlier delivery; held to prevent duplicate footage.',
  source_overlap_reserved: 'Source is already reserved by another delivery.',
  missing_confirmed_capture_site: 'Capture city and province need confirmation.',
  missing_matched_calibration_solve: 'Matching dated calibration solve record is missing.',
  missing_stable_operator_mapping: 'Stable anonymous operator mapping is missing.',
  missing_absolute_capture_time: 'Original absolute capture timestamp is missing.',
  no_continuous_task_meets_delivery_requirements: 'No continuous task span meets the delivery timing and length requirements.',
  legacy_clean_requires_scene_review: 'Older Clean footage needs scene and task review.',
  missing_task_annotations: 'Task annotations are missing.',
  cloud_worker_retries_exhausted: 'Cloud processing failed after three attempts; technical investigation needed.',
  eligibility_revoked_or_changed: 'Eligibility or the Clean source changed after queuing.',
  submission_response_unconfirmed: 'Cloud launch response is uncertain; held to prevent duplicate jobs.',
}[reason] || reason?.replaceAll('_', ' ') || 'Validation needs attention');
const pipelineStates = {
  PASS: 'Passed', FAILED: 'Needs attention', FAIL: 'Needs attention', ERROR: 'Needs attention',
  RUNNING: 'In progress', IN_PROGRESS: 'In progress', PREPARING: 'Preparing', PROCESSING: 'Processing',
  UPLOADING: 'Uploading', TRANSFERRING: 'Uploading', COMPLETE: 'Complete', COMPLETED: 'Complete',
  DELIVERED: 'Uploaded', SUCCEEDED: 'Complete', READY_FOR_REVIEW: 'Ready for review',
  DRAFT_PENDING_REVIEW: 'Review pending', PENDING: 'Pending', WAITING: 'Waiting',
  VALIDATING: 'Validating', PARTIAL: 'In progress', UNAVAILABLE: 'Unavailable', UNKNOWN: 'Not yet reported',
  UPLOADED_FOR_CUSTOMER_QC: 'Sent for customer QC', PACKAGING: 'Packaging', DELIVERED_CHECKSUMS_VERIFIED: 'Uploaded and checksummed', BLOCKED: 'Held', INCONSISTENT: 'Needs verification',
};

function Metric({ title, value, children, accent = false }) {
  return <article className={`sieve-metric${accent ? ' sieve-metric-accent' : ''}`} aria-label={title}>
    <h3>{title}</h3><strong>{value}</strong>{children}
  </article>;
}

function DeliveryOverview({ pipeline, collection, error, loading }) {
  const { company, delivery, validation, supplement, supplement_delivery: originals, customer_delivery: recurring } = pipeline || {};
  const initialHours = delivery?.available && delivery.complete === true && knownNumber(delivery.uploaded_hours) ? delivery.uploaded_hours : null;
  const recurringHours = recurring?.available && knownNumber(recurring.uploaded_hours) ? recurring.uploaded_hours : 0;
  const formattedHours = initialHours === null ? null : initialHours + recurringHours;
  const originalsComplete = originals?.available === true && originals.complete === true && originals.external_transfer_completed === true
    && originals.state === 'UPLOADED_FOR_CUSTOMER_QC' && originals.total_files === 604 && originals.uploaded_files === originals.total_files
    && knownNumber(originals.total_bytes) && originals.total_bytes > 0 && originals.uploaded_bytes === originals.total_bytes
    && knownNumber(originals.uploaded_hours);
  const originalsState = originals?.state === 'UPLOADED_FOR_CUSTOMER_QC' && !originalsComplete ? 'INCONSISTENT' : originals?.state;
  const uploaded = formattedHours === null ? null : formattedHours + (originalsComplete ? originals.uploaded_hours : 0);
  const extra = supplement?.available && supplement.external_delivery_performed === false ? supplement : null;
  const validationText = !validation?.available ? 'Status unavailable' : validation.state === 'PASS' ? 'Passed' :
    ['FAIL', 'FAILED', 'ERROR'].includes(validation.state) ? 'Needs attention' :
    ['RUNNING', 'IN_PROGRESS', 'VALIDATING'].includes(validation.state) ? 'In progress' : 'Result pending';
  return <section className="sieve-overview" aria-label="Delivery overview">
    {loading && !pipeline && <p className="sieve-notice" role="status">Loading delivery status…</p>}
    {error && <p className="sieve-notice" role="status">{pipeline ? 'Live update failed. Showing the last loaded delivery snapshot.' : 'Delivery status is unavailable. Collection figures are shown separately.'}</p>}
    {!error && (pipeline?.cache?.stale || pipeline?.errors?.length > 0 || [company, delivery, validation, supplement, originals, recurring].some(stage => stage?.stale)) &&
      <p className="sieve-notice" role="status">Some updates are delayed or unavailable. Last known figures are shown; expand Processing details for update times.</p>}
    <div className="sieve-metrics">
      <Metric title="Uploaded to Sieve" value={pipelineHours(uploaded)} accent>
        <p>of {DELIVERY_TARGET_HOURS} h delivery target</p>
        {uploaded !== null && <progress value={Math.min(uploaded, DELIVERY_TARGET_HOURS)} max={DELIVERY_TARGET_HOURS} aria-label="Uploaded hours toward delivery target" />}
        <small>{pipelineHours(formattedHours)} formatted{originalsComplete ? ` + ${pipelineHours(originals.uploaded_hours)} original folders for customer QC` : ' in Sieve’s customer storage'} · customer acceptance not recorded</small>
        {originalsComplete && <small>Original-folder hours are potential technical retention, not accepted hours.</small>}
      </Metric>
      <Metric title="Available in Clean" value={collection ? `${hours(collection.totals.clean_seconds)} h` : 'Not reported'}>
        <p>{collection ? `${count(collection.totals.recordings)} recordings · India & Korea` : 'Collection status unavailable'}</p>
        <small>{collection ? `${hours(collection.totals.inherited_seconds)} h copied to our Sieve bucket.` : 'Our internal collection.'} Separate from customer delivery.</small>
      </Metric>
      <Metric title="Originals transfer" value={pipelineHours(originals?.available ? originals.potential_unique_technical_hours : extra?.hours)}>
        <p>{originals?.available ? pipelineStates[originalsState] || 'Status unknown' : 'Transfer status unavailable'}</p>
        {originals?.available && <p>{ratio(originals.uploaded_files, originals.total_files)} files · {bytes(originals.uploaded_bytes)} / {bytes(originals.total_bytes)}</p>}
        {originals?.available && knownNumber(originals.uploaded_files) && originals.total_files > 0 && <progress value={Math.min(originals.uploaded_files, originals.total_files)} max={originals.total_files} aria-label="Original files uploaded to Sieve" />}
        <small>{originalsComplete ? 'Original folders sent for customer QC. Human review and acceptance pending.' : 'Potential technical hours; excluded from uploaded hours until transfer is verified.'}</small>
        {extra && <small>{count(extra.recordings)} recordings · original private staging snapshot retained</small>}
      </Metric>
    </div>
    <div className="sieve-next" aria-label="What happens next">
      <div><h3>What happens next</h3><p><strong>Technical checks: {validationText.toLowerCase()}.</strong> Formatted batch only.{validation?.available && validation.state !== 'PASS' && knownNumber(validation.clip_reports) ? ` ${ratio(validation.clip_reports, validation.total_clips)} clip reports received.` : ''} {originalsComplete ? 'Original folders are sent for customer QC; human review and acceptance remain pending.' : 'Track the originals transfer separately, then record Sieve’s customer QC and acceptance.'}</p></div>
      <a className="sieve-review-link" href="/portal/ops?tab=clean">Review footage <span aria-hidden="true">→</span></a>
    </div>
    <div className="sieve-company-strip" aria-label="Company processing">
      <span>Company processing <small>All countries</small></span>
      {company?.available ? <><span><b>{count(company.clean_complete)}</b> processed</span><span><b>{count(company.in_progress)}</b> in progress</span><span className={company.held > 0 ? 'sieve-held' : ''}><b>{count(company.held)}</b> held for review</span></> : <span>Processing status unavailable</span>}
    </div>
    <details className="sieve-disclosure sieve-processing">
      <summary>Processing details <span>Preparation, transfer, checks & storage</span></summary>
      <div className="sieve-detail-grid">
        <Stage title="Recurring customer delivery" data={recurring}>
          <p>{recurring?.enabled ? 'Automatic delivery enabled' : 'Automatic delivery paused'} · {count(recurring?.running)} running / {count(recurring?.max_parallel)} slots</p>
          <p>{pipelineHours(recurring?.uploaded_hours)} uploaded · {count(recurring?.queued)} queued · {count(recurring?.held)} held</p>
          <p>{count(recurring?.uploaded_assets)} assets · {count(recurring?.uploaded_files)} files · {bytes(recurring?.uploaded_bytes)}</p>
          <p>Only verified customer uploads count. Human review and customer acceptance remain separate.</p>
          {recurring?.recordings?.some(row => row.status === 'held') && <details>
            <summary>Recording hold reasons</summary>
            <ul>{recurring.recordings.filter(row => row.status === 'held').map(row => <li key={row.recording}>
              {row.recording}: {customerHoldReason(row.reason)}
            </li>)}</ul>
          </details>}
        </Stage>
        <Stage title="Sieve preparation" data={delivery}>
          <p>{pipelineHours(delivery?.prepared_hours)} prepared · {ratio(delivery?.recordings_processed, delivery?.recordings_expected)} recordings</p>
          <p>{count(delivery?.packaged_assets)} clips packaged</p>
        </Stage>
        <Stage title="Customer upload" data={delivery}>
          <p>{delivery?.complete === true ? 'Upload complete' : pipelineStates[delivery?.state] || 'Status unknown'}</p>
          <p>{ratio(delivery?.uploaded_files, delivery?.total_files)} files · {bytes(delivery?.uploaded_bytes)} / {bytes(delivery?.total_bytes)}</p>
          <p>{count(delivery?.uploaded_assets)} / {count(delivery?.packaged_assets)} clips uploaded</p>
          {knownNumber(delivery?.uploaded_files) && delivery?.total_files > 0 && <progress value={Math.min(delivery.uploaded_files, delivery.total_files)} max={delivery.total_files} aria-label="Files uploaded to Sieve" />}
          <p>Destination: Sieve’s customer storage</p>
        </Stage>
        <Stage title="Independent validation" data={validation}>
          <p>{validationText} · {ratio(validation?.clip_reports, validation?.total_clips)} clip reports</p>
          <p>Report counts alone do not mean the checks passed.</p>
        </Stage>
        <Stage title="Originals customer transfer" data={originals}>
          <p>{pipelineStates[originalsState] || 'Status unknown'} · {pipelineHours(originals?.potential_unique_technical_hours)} potential technical hours</p>
          <p>{ratio(originals?.uploaded_files, originals?.total_files)} files · {bytes(originals?.uploaded_bytes)} / {bytes(originals?.total_bytes)}</p>
          <p>Original folders are separate from the formatted batch’s independent validation. Human review and customer acceptance pending.</p>
        </Stage>
        <Stage title="Private extra footage" data={supplement}>
          <p>{pipelineStates[supplement?.state] || 'Status unknown'} · {bytes(supplement?.bytes)}</p>
          <p>{supplement?.external_delivery_performed === false ? 'Historical private staging snapshot. Current transfer status is shown separately above.' : 'Private staging status needs verification.'}</p>
        </Stage>
        <Stage title="Originals archive" data={company}>
          <p>{count(company?.archived)} archived / {count(company?.source_groups)} upload groups · {count(company?.deleted)} deleted groups</p>
          <p>Original uploads are preserved separately from temporary Raw storage.</p>
        </Stage>
        <Stage title="Internal Sieve copies" data={collection ? { available: true, updated_at: collection.sync?.completed_at } : null}>
          <p>{collection ? `${hours(collection.totals.inherited_seconds)} h copied · ${count(collection.totals.inherited_recordings)} recordings` : 'Not reported'}</p>
          <p>{collection ? `${collection.totals.status_counts.pending || 0} copy pending · ${collection.totals.status_counts.blocked || 0} copy blocked` : ''}</p>
          <p>{collection ? `${bytes(collection.totals.copied_bytes)} · ${collection.totals.clean_seconds ? Math.round(collection.totals.inherited_seconds / collection.totals.clean_seconds * 100) : 0}% of Clean copied` : ''}</p>
          {collection && <progress value={collection.totals.inherited_seconds} max={collection.totals.clean_seconds || 1} aria-label="Clean hours copied to internal Sieve storage" />}
          <p>Internal copies are separate from customer uploads. Original codecs are preserved; deleted recordings and previous Raw-derived copies are excluded.</p>
        </Stage>
      </div>
    </details>
  </section>;
}

function Stage({ title, data, children }) {
  return <section aria-label={title}>
    <h4>{title}{data?.stale && <span className="sieve-held"> · Stale snapshot</span>}</h4>
    {data?.available ? children : <p>Status unavailable. No count is assumed.</p>}
    <small>{data?.updated_at ? `Updated ${stamp(data.updated_at)}` : 'Update time not reported'}</small>
  </section>;
}

function Distribution({ title, rows, total }) {
  return <section className="sieve-panel" aria-label={title}>
    <h3>{title}</h3>
    {!rows.length ? <p className="ops-hint">No Clean footage yet.</p> : <ul className="sieve-bars">
      {rows.map(row => <li key={row.label}>
        <div><span>{row.label}</span><span className="sieve-number">{hours(row.seconds)} h <small>· {total ? Math.round(row.seconds / total * 100) : 0}%</small></span></div>
        <div className="sieve-track" aria-hidden="true"><span style={{ width: `${total ? row.seconds / total * 100 : 0}%` }}><i style={{ width: `${row.seconds ? row.inherited_seconds / row.seconds * 100 : 0}%` }} /></span></div>
        <small>{row.recordings} recording{row.recordings === 1 ? '' : 's'} · {hours(row.inherited_seconds)} h copied internally</small>
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
  const [pageIndex, setPageIndex] = useState(0);
  const [expanded, setExpanded] = useState(null);
  useEffect(() => setPageIndex(0), [country, status, query]);
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
  const filteredHours = rows.reduce((sum, r) => sum + r.retained_seconds, 0);
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  useEffect(() => setPageIndex(index => Math.min(index, pageCount - 1)), [pageCount]);
  const currentPage = Math.min(pageIndex, pageCount - 1);
  const visibleRows = rows.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const lastCheck = data?.sync?.completed_at || data?.sync?.started_at;
  const stale = lastCheck && Date.now() - new Date(lastCheck).getTime() > 15 * 60 * 1000;
  return <section className="sieve" aria-labelledby="sieve-title">
    <div className="sieve-heading">
      <div><p className="sieve-eyebrow">Customer delivery</p><h2 id="sieve-title">Sieve</h2><p className="sieve-subtitle">India & Korea footage · 10-hour delivery target</p></div>
      <div className="sieve-deadline"><span>Contract ends Sep 22, 2026</span><button className="ops-scan" disabled={loading || pipelineLoading} onClick={refresh}>{loading || pipelineLoading ? 'Refreshing…' : 'Refresh dashboard'}</button></div>
    </div>
    <DeliveryOverview pipeline={pipeline} collection={data} error={pipelineError} loading={pipelineLoading} />
    {error && <p className="ops-error" role="alert">{error}{data && ' Showing the last loaded snapshot.'}</p>}
    {!data && (error ? <button className="ops-scan" onClick={load}>Retry</button> : <p className="ops-muted" role="status">Loading Sieve collection…</p>)}
    {data && <>
    {(data.sync.error || stale || !data.automatic_sync) && <p className="ops-error" role="status">{data.sync.error || (stale ? 'Internal copy checks are overdue. Counts show the last verified copies.' : 'Automatic internal copying is not running.')}</p>}
    <div className="sieve-section-heading"><h3>Browse footage</h3><p>{rows.length} recordings · {hours(filteredHours)} h</p></div>
    <p className="sieve-caption">Open an episode to inspect its video, IMU, metadata, calibration and pipeline action labels. Copy status tracks our internal storage.</p>
    <p className="sieve-caption">{knownNumber(t.task_reports) ? `${t.task_reports} episodes have a linked pipeline task report.` : 'Pipeline task coverage is not reported.'} Operator task assignments are separate from these annotations.</p>
    <div className="sieve-filters">
      <label>Search<input aria-label="Search recordings" type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="Recording, source, activity or camera" /></label>
      <label>Country<select aria-label="Filter recordings by country" value={country} onChange={e => setCountry(e.target.value)}><option value="">All countries</option>{b.country.map(r => <option key={r.label}>{r.label}</option>)}</select></label>
      <label>Internal copy status<select aria-label="Filter recordings by status" value={status} onChange={e => setStatus(e.target.value)}><option value="">All copy statuses</option>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    </div>
    <div className="sieve-recordings">
      {!rows.length && <p className="sieve-empty">{data.recordings.length ? 'No recordings match these filters.' : 'New recordings will appear after they enter Clean.'}</p>}
      {visibleRows.map(row => <details className="sieve-recording" key={`${row.run_id}/${row.recording}`} open={expanded === row.recording}
        onToggle={e => { if (e.target !== e.currentTarget) return; if (e.currentTarget.open) setExpanded(row.recording); else setExpanded(current => current === row.recording ? null : current); }}>
        <summary><span className="sieve-recording-name"><strong>{row.recording}</strong><small>{row.entity.name} · {row.country}</small></span><span className="sieve-duration">{hours(row.retained_seconds)} h</span><span className={`sieve-status sieve-status-${row.status}`}>{labels[row.status] || row.status}</span></summary>
        <dl><div><dt>Operator task</dt><dd>{row.activity === 'Unclassified' ? 'Not assigned' : row.activity}</dd></div><div><dt>Pipeline action labels</dt><dd>{row.pipeline_tasks === 'linked' ? 'Task report linked in Clean' : row.pipeline_tasks === 'not_linked' ? 'No task report linked in this Clean manifest' : 'Task report status not reported'}</dd></div><div><dt>Camera / format</dt><dd>{row.camera} · {row.format}</dd></div><div><dt>Last verified</dt><dd>{stamp(row.checked_at)}</dd></div><div><dt>Clean batch</dt><dd>{row.run_id}</dd></div></dl>
        {row.reason && <p className="sieve-reason">{row.reason}</p>}
        {row.status === 'inherited' && <p className="sieve-reason">MP4, original metadata, metadata provenance, and calibration copied from versioned Clean artifacts.</p>}
        {expanded === row.recording && row.status === 'inherited' && <SieveEpisode row={row} onExpired={onExpired} />}
        {expanded === row.recording && row.status !== 'inherited' && <p className="sieve-reason">The episode viewer will be available after its Sieve copy is verified.</p>}
      </details>)}
    </div>
    {pageCount > 1 && <nav className="sieve-pagination" aria-label="Recording pages">
      <span role="status">{currentPage * PAGE_SIZE + 1}–{Math.min((currentPage + 1) * PAGE_SIZE, rows.length)} of {rows.length} recordings</span>
      <button className="ops-scan" disabled={currentPage === 0} onClick={() => setPageIndex(currentPage - 1)}>Previous</button>
      <button className="ops-scan" disabled={currentPage + 1 >= pageCount} onClick={() => setPageIndex(currentPage + 1)}>Next</button>
    </nav>}
    <details className="sieve-disclosure sieve-breakdown">
      <summary>Collection breakdown <span>{t.countries} countries · {t.entities} contributors · {t.cameras} cameras</span></summary>
      <div className="sieve-grid">
        <Distribution title="Country" rows={b.country} total={t.clean_seconds} />
        <Distribution title="Contributor / business" rows={b.entity} total={t.clean_seconds} />
        <Distribution title="Operator task" rows={b.activity.map(r => ({ ...r, label: r.label === 'Unclassified' ? 'Not assigned' : r.label }))} total={t.clean_seconds} />
        <Distribution title="Clean intake by day" rows={b.clean_date} total={t.clean_seconds} />
      </div>
      <p className="sieve-caption">Operator task counts do not measure pipeline action-label coverage. Open an episode for its pipeline annotations. Orange shows internal copies. Each recording counts once across both eyes. Intake dates use Los Angeles time.</p>
    </details>
    <footer className="sieve-footer"><span>Collection updated {stamp(data.updated_at)}</span><span>Delivery checked {stamp(pipeline?.checked_at)} · Refreshes every 30 seconds</span><span>Dashboard available through Sep 25 · Los Angeles time</span></footer>
    </>}
  </section>;
}
