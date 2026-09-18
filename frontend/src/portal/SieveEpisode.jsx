import { useEffect, useState } from 'react';
import { portalFetch } from './portalFetch.js';

const seconds = value => Number.isFinite(value) ? `${value.toFixed(2)} s` : 'Not reported';
const readable = value => String(value || '').replaceAll('_', ' ').replaceAll(':', ' · ');

function ArtifactLink({ artifact, children }) {
  return artifact?.url && <a href={artifact.url} target="_blank" rel="noreferrer">{children || `Open ${artifact.name}`} ↗</a>;
}

function JsonPanel({ title, artifact }) {
  return <section className="sieve-inspector-panel" aria-label={title}>
    <div className="sieve-inspector-heading"><h4>{title}</h4><span>{artifact?.storage || 'Sieve'}</span></div>
    {artifact?.data ? <pre tabIndex={0} aria-label={`${title} JSON`}>{JSON.stringify(artifact.data, null, 2)}</pre>
      : <p role="status">{artifact?.error || 'JSON preview unavailable.'}</p>}
    <ArtifactLink artifact={artifact} />
  </section>;
}

function ImuPlot({ rows, fields, title, unit }) {
  if (!rows.length || !fields.every(field => rows.every(row => Number.isFinite(row[field])))) return null;
  const values = rows.flatMap(row => fields.map(field => row[field]));
  const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
  const times = rows.map((row, i) => row.clean_time_us ?? i);
  const timeSpan = times.at(-1) - times[0] || 1;
  return <figure className="sieve-imu-plot">
    <figcaption>{title} <span>{unit}</span></figcaption>
    <svg viewBox="0 0 480 100" role="img" aria-label={`${title}, first ${rows.length} IMU samples`}>
      <line x1="0" x2="480" y1="50" y2="50" className="sieve-plot-grid" />
      {fields.map((field, axis) => <polyline key={field} className={`sieve-axis-${axis}`} fill="none" strokeWidth="1.8"
        points={rows.map((row, index) => `${(times[index] - times[0]) / timeSpan * 480},${92 - (row[field] - low) / span * 84}`).join(' ')} />)}
    </svg>
    <div className="sieve-plot-caption"><span>{low.toFixed(2)} to {high.toFixed(2)} {unit}</span><span>X — &nbsp; Y – – &nbsp; Z ···</span></div>
  </figure>;
}

function ImuPanel({ imu }) {
  const rows = imu.rows || [];
  return <section className="sieve-inspector-panel" aria-label="IMU">
    <div className="sieve-inspector-heading"><h4>IMU</h4><span>{imu.storage || 'Clean'}</span></div>
    {imu.status === 'available' ? <>
      <p>First {rows.length} of {imu.total_samples?.toLocaleString() || 'available'} samples.
        {rows[0]?.clean_time_us != null && ` Clean time ${seconds(rows[0].clean_time_us / 1e6)}–${seconds(rows.at(-1).clean_time_us / 1e6)}.`}</p>
      <ImuPlot rows={rows} fields={['ax_ms2', 'ay_ms2', 'az_ms2']} title="Acceleration" unit={imu.units?.acceleration || 'm/s²'} />
      <ImuPlot rows={rows} fields={['gx_degs', 'gy_degs', 'gz_degs']} title="Angular velocity" unit={imu.units?.angular_velocity || 'deg/s'} />
      <p className="sieve-inspector-note">Preview of the beginning only. The full CSV contains the retained episode’s measured IMU and timestamps.</p>
      <details className="sieve-samples"><summary>Sample values</summary><div className="sieve-table-scroll" tabIndex={0}>
        <table><thead><tr>{imu.columns.map(key => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.slice(0, 20).map((row, i) =>
          <tr key={i}>{imu.columns.map(key => <td key={key}>{Number.isInteger(row[key]) ? row[key] : row[key].toFixed(4)}</td>)}</tr>)}</tbody></table>
      </div></details>
    </> : <p role="status">{imu.status === 'absent' ? 'No separate IMU artifact is recorded for this historical episode.' : imu.error || 'IMU preview unavailable. Refresh to retry.'}</p>}
    <ArtifactLink artifact={imu}>Open full IMU CSV</ArtifactLink>
  </section>;
}

function TaskPanel({ tasks, operatorTask }) {
  return <section className="sieve-inspector-panel sieve-tasks" aria-label="Pipeline action labels">
    <div className="sieve-inspector-heading"><h4>Pipeline action labels</h4><span>{tasks.artifact?.storage || 'Clean'}</span></div>
    <p>Operator task: {operatorTask && operatorTask !== 'Unclassified' ? operatorTask : 'Not assigned'}.</p>
    {tasks.status === 'available' ? <>
      {tasks.models.map(model => <div className="sieve-task-model" key={model.model}>
        <div className="sieve-task-chips">{(model.task_labels || []).map(label => <span key={label}>{readable(label)}</span>)}</div>
        {!model.task_labels?.length && <p>No confident productive task labels in this report. Review the recorded events.</p>}
        <p>Dominant observed task: <strong>{readable(model.dominant_observed_task) || 'Not reported'}</strong>.
          {' '}Environment: {(model.environments || []).map(readable).join(', ') || 'Not reported'}.</p>
        <p className="sieve-inspector-note">{tasks.human_verified ? 'Human verification recorded.' : 'Model estimates; not human verified.'}
          {' '}{model.coverage?.full_episode ? 'Full episode sampled.' : 'Partial episode coverage.'}
          {' '}{seconds(model.coverage?.annotated_selected_seconds)} annotated of {seconds(model.coverage?.selected_seconds)} selected.
          {model.review_required && ' Review required.'} Model: {model.model}.</p>
        <details className="sieve-task-events"><summary>Task events ({model.event_count})</summary>
          <p>Source timestamps, before Clean cuts. Observed boundaries are approximate.</p>
          <div className="sieve-table-scroll" tabIndex={0}><table><thead><tr><th>Source time</th><th>Action / object</th><th>Evidence</th><th>Review</th></tr></thead>
            <tbody>{(model.events || []).map((event, i) => <tr key={i}>
              <td>{seconds(event.source_navigation_start_s)}–{seconds(event.source_navigation_end_s)}</td>
              <td>{readable(event.task_id || `${event.action}:${event.object}`)}</td><td>{event.evidence}</td>
              <td>{event.review_required ? 'Required' : 'No flag'}</td>
            </tr>)}</tbody></table></div>
          {model.event_count > model.events.length && <p>Showing the first {model.events.length} events. Open the full report for all events.</p>}
        </details>
      </div>)}
      <ArtifactLink artifact={tasks.artifact}>Open full task report</ArtifactLink>
    </> : <p role="status">{tasks.status === 'absent' ? 'No pipeline task report is linked in this Clean manifest. An unassigned operator task does not mean pipeline labels are missing.' : tasks.error || 'Task report unavailable. Refresh to retry.'}</p>}
  </section>;
}

function EpisodeContent({ data }) {
  const videos = [...(data.browser_preview ? [data.browser_preview] : []), ...data.videos];
  const [selected, setSelected] = useState(0);
  const [failed, setFailed] = useState(false);
  const video = videos[selected] || videos[0];
  return <div className="sieve-inspector-grid">
    <section className="sieve-inspector-panel" aria-label="Episode video">
      <div className="sieve-inspector-heading"><h4>Video</h4><span>{video.storage}</span></div>
      <label className="sieve-video-choice">View<select aria-label="Video view" value={selected} onChange={e => { setSelected(Number(e.target.value)); setFailed(false); }}>
        {videos.map((v, i) => <option key={v.name} value={i}>{v.name}</option>)}
      </select></label>
      <video key={video.url} controls playsInline preload="metadata" src={video.url} onError={() => setFailed(true)} aria-label="Episode video player" />
      {failed && <p role="status">This video could not play. Try the browser preview if available, open the original, or refresh expired links.</p>}
      <p className="sieve-inspector-note">{data.browser_preview ? 'Browser preview from Clean; original Sieve files are available below.' : 'Original Sieve codec. Playback depends on browser support.'}</p>
      <div className="sieve-artifact-links">{data.videos.map(v => <ArtifactLink key={v.name} artifact={v} />)}</div>
    </section>
    <ImuPanel imu={data.imu} />
    <JsonPanel title="Metadata" artifact={data.metadata} />
    <JsonPanel title="Calibration" artifact={data.calibration} />
    <TaskPanel tasks={data.tasks} operatorTask={data.operator_task} />
  </div>;
}

export default function SieveEpisode({ row, onExpired }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [expiredLinks, setExpiredLinks] = useState(false);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 35000);
    setData(null); setError(''); setExpiredLinks(false);
    portalFetch(`/api/ops/sieve/episodes/${encodeURIComponent(row.recording)}`, { signal: controller.signal }).then(response => {
      if (!active) return;
      if (response.status === 410) { onExpired?.(); return; }
      if (response.ok) setData(response.data);
      else setError(response.data?.detail || 'Could not load episode artifacts. Please retry.');
    }).finally(() => clearTimeout(timeout));
    return () => { active = false; controller.abort(); clearTimeout(timeout); };
  }, [row.recording, row.revision, attempt, onExpired]);
  useEffect(() => {
    if (!data) return;
    const timer = setTimeout(() => setExpiredLinks(true), data.expires_in * 1000);
    return () => clearTimeout(timer);
  }, [data]);
  return <div className="sieve-inspector" aria-label={`Episode ${row.recording}`}>
    <div className="sieve-inspector-toolbar"><p>Video, sensors and source documents</p>
      <button className="ops-scan" disabled={!data && !error} onClick={() => setAttempt(n => n + 1)}>{error ? 'Retry episode' : 'Refresh episode'}</button></div>
    {error ? <p role="alert">{error}</p> : !data ? <p role="status">Loading episode artifacts…</p> : <>
      {expiredLinks && <p role="status">Artifact links have expired. Refresh the episode to play or open files.</p>}
      {data.warnings?.map(w => <p key={w} role="status">{w}</p>)}
      <EpisodeContent key={attempt} data={data} />
    </>}
  </div>;
}
