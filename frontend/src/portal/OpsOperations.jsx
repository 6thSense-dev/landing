import { useEffect, useMemo, useState } from "react";
import OpsIntakePreview from "./OpsIntakePreview.jsx";
import { portalFetch } from "./portalFetch.js";
import { fmt, gb, sizeChip, regionOf, dayOf, uploadLagHours } from "./opsShared.js";

/**
 * OPERATIONS — strictly the episode ledger.
 *
 * Everything about a PERSON (creating them, their contact details, retiring
 * them) lives in the Users tab. What stays here is the read of who an episode
 * is attributed to, because that is a property of the episode, not of the
 * person: reassigning an episode is an operations act.
 */
// Uploads are a nightly 02:00 batch, so the bands are sized for a ~24h delivery
// window: same day is good, a day or two is ordinary, a week is a conversation.
function lagChip(e) {
  const h = uploadLagHours(e.started_at, e.duration_s, e.uploaded_at);
  if (h === null) return null;
  if (h < 0) return null;                       // clock disagreement; the clock chip says so
  const title = `landed ${h.toFixed(1)} h after the take ended`;
  if (h < 30) return <div><span className="ops-chip ok" title={title}>same day</span></div>;
  if (h < 24 * 4) return <div><span className="ops-chip" title={title}>+{Math.round(h / 24)} d</span></div>;
  return <div><span className="ops-chip warn" title={title}>+{Math.round(h / 24)} d</span></div>;
}

export default function OpsOperations({ state, act, busy, rate }) {
  const [preview, setPreview] = useState(null);   // {recording, files, error, pick}

  // Filters. All client-side: the whole ledger arrives in one /state call, so a
  // filter is a re-render rather than a round trip.
  const [q, setQ] = useState("");
  const [region, setRegion] = useState("");
  const [sessionSel, setSessionSel] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [wearerSel, setWearerSel] = useState("");
  const [paidSel, setPaidSel] = useState("");
  const [approvedSel, setApprovedSel] = useState("");
  const [showDeleted, setShowDeleted] = useState(false);

  const [taskName, setTaskName] = useState("");
  const [taskCat, setTaskCat] = useState("other");
  const [rateDraft, setRateDraft] = useState("0");

  // The rate field is a draft until it is committed, so typing "11000" does not
  // fire four writes on the way there. Re-synced whenever the server's answer
  // changes, which is the only thing that can be authoritative about it.
  useEffect(() => {
    setRateDraft(String(rate ?? 0));
  }, [rate]);

  const openPreview = async (recording) => {
    setPreview({ recording, files: [], error: "", pick: 0, loading: true });
    const r = await portalFetch(`/api/ops/episodes/${recording}/files`);
    if (!r.ok) {
      return setPreview({ recording, files: [], pick: 0, loading: false,
                          error: `Could not list this episode (HTTP ${r.status}).` });
    }
    setPreview({ recording, files: r.data.files ?? [], pick: 0, loading: false,
                 error: r.data.ok ? "" : r.data.error });
  };

  const episodes = state?.episodes ?? [];
  const wearers = state?.wearers ?? [];
  const tasks = state?.tasks ?? [];

  const nameOf = useMemo(() => {
    const by = new Map(wearers.map((w) => [w.id, w.name]));
    return (id) => by.get(id) ?? "";
  }, [wearers]);

  const labelOf = useMemo(() => {
    const by = new Map(tasks.map((t) => [t.id, t.name]));
    return (id) => by.get(id) ?? "";
  }, [tasks]);

  const regions = useMemo(
    () => [...new Set(episodes.map((e) => regionOf(e.session)))].filter(Boolean).sort(),
    [episodes],
  );

  // Sessions narrow to the chosen region, because the two are nested in the
  // bucket and offering all thirty under "Korea" is offering the wrong thirty.
  const sessions = useMemo(
    () => [...new Set(episodes
      .filter((e) => !region || regionOf(e.session) === region)
      .map((e) => e.session))].filter(Boolean).sort(),
    [episodes, region],
  );

  // Grouped so the dropdown reads as the taxonomy it is, not a flat list of 13.
  const taskGroups = useMemo(() => {
    const by = new Map();
    for (const task of tasks) {
      if (!by.has(task.category)) by.set(task.category, []);
      by.get(task.category).push(task);
    }
    return [...by.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [tasks]);

  // Everything the filters select, deleted rows included. `rows` is this minus
  // the deleted ones unless they are being shown — kept separate so the Deleted
  // tile can say how many the current filter is hiding rather than reading 0.
  const matched = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return episodes.filter((e) => {
      if (region && regionOf(e.session) !== region) return false;
      if (sessionSel && e.session !== sessionSel) return false;
      // Both bounds inclusive, and either may stand alone — "everything since
      // the 4th" is the commonest thing to ask and needs no end date. ISO dates
      // compare correctly as plain strings, so no Date parsing is involved.
      if (from || to) {
        const d = dayOf(e);
        if (!d) return false;                     // undated cannot satisfy a range
        if (from && d < from) return false;
        if (to && d > to) return false;
      }
      if (wearerSel === "none" && e.wearer_id != null) return false;
      if (wearerSel && wearerSel !== "none" && String(e.wearer_id ?? "") !== wearerSel) return false;
      if (paidSel === "paid" && !e.paid) return false;
      if (paidSel === "unpaid" && e.paid) return false;
      if (approvedSel === "yes" && !e.approved) return false;
      if (approvedSel === "no" && e.approved) return false;
      if (needle) {
        const hay = `${e.recording} ${e.device_id} ${nameOf(e.wearer_id)} ` +
                    `${labelOf(e.task_id)} ${e.session} ${regionOf(e.session)}`;
        if (!hay.toLowerCase().includes(needle)) return false;
      }
      return true;
    });
  }, [episodes, q, region, sessionSel, from, to, wearerSel, paidSel, approvedSel,
      nameOf, labelOf]);

  const rows = useMemo(
    () => (showDeleted ? matched : matched.filter((e) => !e.deleted_at)),
    [matched, showDeleted],
  );

  // Per person, over the WHOLE live ledger rather than the filter: this panel is
  // what somebody is owed in total, and a roll-up that moved every time a date
  // box changed would not be that.
  const summary = useMemo(() => {
    const by = new Map();
    for (const e of episodes) {
      if (e.deleted_at) continue;
      // Keyed by ID, not name: 김민준 and 김민준 are two people and two
      // payments, and merging them is a wrong number on a settlement.
      const key = e.wearer_id ?? "none";
      let s = by.get(key);
      if (!s) {
        s = { key, person: nameOf(e.wearer_id) || "(unassigned)", episodes: 0,
              approved: 0, minutes: 0, paid: 0, unpaidApproved: 0, devices: new Set() };
        by.set(key, s);
      }
      s.episodes += 1;
      s.minutes += e.minutes ?? 0;
      if (e.device_id) s.devices.add(e.device_id);
      if (e.approved) {
        s.approved += 1;
        if (e.paid) s.paid += 1;
        else s.unpaidApproved += 1;
      }
    }
    return [...by.values()]
      .map((s) => ({ ...s, devices: [...s.devices].sort() }))
      .sort((a, b) => b.approved - a.approved || a.person.localeCompare(b.person));
  }, [episodes, nameOf]);

  // Retiring somebody is meant to take them out of the pickers. They must still
  // appear on a row that is ALREADY assigned to them, or that row would render
  // blank and one wrong click would silently reassign settled work.
  const pickable = useMemo(() => {
    const active = wearers.filter((w) => w.is_active);
    return (keepId) => {
      if (keepId == null || active.some((w) => w.id === keepId)) return active;
      const kept = wearers.find((w) => w.id === keepId);
      return kept ? [...active, kept] : active;
    };
  }, [wearers]);

  const payable = useMemo(
    () => rows.filter((e) => e.approved && !e.paid && !e.deleted_at),
    [rows],
  );

  const minutes = rows.reduce((a, e) => a + (e.minutes ?? 0), 0);
  const bytes = rows.reduce((a, e) => a + (e.size_bytes ?? 0), 0);
  const approvedCount = rows.filter((e) => e.approved).length;
  const commitRate = () => {
    // An emptied or unparseable field is a MISTAKE, not an instruction to set the
    // board rate to zero. Number("") is 0, so coercing here silently repriced
    // every future payment to nothing. Revert instead, and make going to zero
    // deliberate: it has to be typed.
    const raw = rateDraft.trim();
    if (raw === "" || !Number.isFinite(Number(raw))) return setRateDraft(String(rate));
    const next = Math.max(0, Math.round(Number(raw)));
    if (next !== rate) act("rate", "/api/ops/rate", { rate_krw: next });
    else setRateDraft(String(rate));
  };

  return (
    <>
        {/* Every tile counts what is on screen, not what is in the bucket. A
            filtered view whose totals still describe the whole ledger is how a
            week gets settled against the wrong number. */}
        <div className="ops-tiles">
          {[
            ["Episodes", fmt(rows.length)],
            ["Approved", fmt(approvedCount)],
            ["Minutes", fmt(Math.round(minutes))],
            ["Unpaid approved", fmt(payable.length)],
            ["Current-rate estimate (KRW)", fmt(payable.length * rate)],
            ["Clock unverified", fmt(rows.filter((e) => !e.clock_ok).length)],
            ["Stored", gb(bytes)],
            ["Unassigned", fmt(rows.filter((e) => e.wearer_id == null).length)],
            ["Unlabelled", fmt(rows.filter((e) => e.task_id == null).length)],
            ["Deleted", fmt(matched.filter((e) => e.deleted_at).length)],
          ].map(([label, value]) => (
            <div className="ops-tile" key={label}>
              <div className="ops-tile-n">{value}</div>
              <div className="ops-tile-l">{label}</div>
            </div>
          ))}
        </div>

        <OpsIntakePreview recordings={episodes.map((episode) => episode.recording)} />

        <div className="ops-cols">
          <div className="ops-panel">
            <div className="ops-filters">
              <input className="ops-q" placeholder="search camera, wearer, recording…"
                     value={q} onChange={(e) => setQ(e.target.value)} />
              <select value={region}
                      onChange={(e) => { setRegion(e.target.value); setSessionSel(""); }}>
                <option value="">all regions</option>
                {regions.map((r) => <option key={r} value={r}>{r}</option>)}
              </select>
              <select value={sessionSel} onChange={(e) => setSessionSel(e.target.value)}>
                <option value="">all sessions</option>
                {sessions.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
              <div className="ops-dategrp">
                {/* The camera's own local date, which is what attribution and the
                    payment period key off. There is no upload date in the ledger
                    to offer as an alternative, so the basis is stated, not picked. */}
                <span className="ops-sl">recorded</span>
                <input type="date" value={from} title="from (inclusive)"
                       onChange={(e) => setFrom(e.target.value)} />
                <input type="date" value={to} title="to (inclusive)"
                       onChange={(e) => setTo(e.target.value)} />
                <button title="clear the date range"
                        onClick={() => { setFrom(""); setTo(""); }}>clear</button>
              </div>
              <select value={wearerSel} onChange={(e) => setWearerSel(e.target.value)}>
                <option value="">everyone</option>
                <option value="none">unassigned</option>
                {pickable(null).map((w) => (
                  <option key={w.id} value={w.id}>{w.name}{w.is_active ? "" : " (retired)"}</option>
                ))}
              </select>
              <select value={paidSel} onChange={(e) => setPaidSel(e.target.value)}>
                <option value="">paid + unpaid</option>
                <option value="unpaid">unpaid only</option>
                <option value="paid">paid only</option>
              </select>
              <select value={approvedSel} onChange={(e) => setApprovedSel(e.target.value)}>
                <option value="">approved + not</option>
                <option value="yes">approved only</option>
                <option value="no">not approved</option>
              </select>
              <label className="ops-check">
                <input type="checkbox" checked={showDeleted}
                       onChange={(e) => setShowDeleted(e.target.checked)} />
                show deleted
              </label>
              <span className="ops-spacer" />
              <button
                disabled={!payable.length || busy === "payall"}
                title={payable.length
                  ? `Settle the ${payable.length} approved, unpaid episode(s) on screen`
                  : "Nothing on screen is both approved and unpaid"}
                onClick={() => {
                  const total = payable.length * rate;
                  if (!rate && !window.confirm(
                    "The rate is 0 KRW, so this would record payments of zero.\n\n" +
                    "Set the rate under Payment basis first. Mark them paid anyway?")) return;
                  if (!window.confirm(
                    `Mark ${payable.length} approved episode(s) as paid at ` +
                    `${fmt(rate)} KRW each?\n\nTotal ${fmt(total)} KRW.`)) return;
                  act("payall", "/api/ops/pay-bulk",
                      { recordings: payable.map((e) => e.recording), value: true });
                }}>
                Mark filtered approved as paid
              </button>
            </div>

            <div className="ops-tablewrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th /><th>Episode</th><th>Region</th><th>Camera</th>
                    <th>Wearer</th><th>Task</th><th>Started</th><th>Uploaded</th>
                    <th className="num">Min</th><th>Quality</th>
                    <th>Approved</th><th>Marked paid</th><th>Delete</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e.recording} className={e.deleted_at ? "ops-row-deleted" : ""}>
                      <td>
                        <button className="ops-play" title="Preview the video"
                                onClick={() => openPreview(e.recording)}>▶</button>
                      </td>
                      <td className="mono">
                        {e.recording}
                        <div className="ops-chip" title={e.session}>{e.session}</div>
                      </td>
                      <td>{regionOf(e.session)}</td>
                      <td className="mono">{e.device_id}</td>
                      <td>
                        <select
                          value={e.wearer_id ?? ""}
                          disabled={!!e.deleted_at}
                          onChange={(ev) =>
                            act(`assign-${e.recording}`, `/api/ops/episodes/${e.recording}/assign`,
                                { wearer_id: ev.target.value ? Number(ev.target.value) : null })}
                        >
                          <option value="">unassigned</option>
                          {pickable(e.wearer_id).map((w) => (
                            <option key={w.id} value={w.id}>
                              {w.name}{w.is_active ? "" : " (retired)"}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <select
                          value={e.task_id ?? ""}
                          disabled={!!e.deleted_at}
                          onChange={(ev) =>
                            act(`task-${e.recording}`, `/api/ops/episodes/${e.recording}/task`,
                                { task_id: ev.target.value ? Number(ev.target.value) : null })}
                        >
                          <option value="">unlabelled</option>
                          {taskGroups.map(([cat, list]) => (
                            <optgroup key={cat} label={cat.replace(/_/g, " ")}>
                              {list.map((task) => (
                                <option key={task.id} value={task.id}>{task.name}</option>
                              ))}
                            </optgroup>
                          ))}
                        </select>
                      </td>
                      <td className="mono ops-nowrap">
                        {(e.started_at || "").replace("T", " ").slice(0, 16)}
                        {!e.clock_ok && (
                          <div>
                            <span className="ops-chip warn"
                                  title={`clock source '${e.clock_source}' — the start time may be hours out, so this episode can sit in the wrong week or the wrong person's range`}>
                              clock?
                            </span>
                          </div>
                        )}
                      </td>
                      <td className="mono ops-nowrap">
                        {e.uploaded_at
                          ? e.uploaded_at.replace("T", " ").slice(0, 16)
                          : <span className="ops-chip warn"
                                  title="no upload time recorded — press Scan bucket to fill it in">
                              not scanned
                            </span>}
                        {lagChip(e)}
                      </td>
                      <td className="num">
                        {e.minutes}
                        <div className="ops-chip">{sizeChip(e.size_mb)}</div>
                      </td>
                      <td>
                        {e.no_metadata ? <span className="ops-chip bad">no metadata</span>
                          : e.truncated ? <span className="ops-chip bad">truncated</span>
                          : e.dropped > 0 ? <span className="ops-chip warn">{e.dropped} dropped</span>
                          : e.complete ? <span className="ops-chip ok">complete</span>
                          : <span className="ops-chip warn">incomplete</span>}
                      </td>
                      <td className="num">
                        <input type="checkbox" checked={e.approved} disabled={!!e.deleted_at}
                               onChange={(ev) =>
                                 act(`ap-${e.recording}`, `/api/ops/episodes/${e.recording}/approve`,
                                     { value: ev.target.checked })} />
                      </td>
                      <td className="num">
                        {/* No amount sent: the server stamps the board's rate, so
                            a payment can never be recorded at a stale number the
                            operator's page happened to be holding. */}
                        <input type="checkbox" checked={e.paid}
                               disabled={!!e.deleted_at || (!e.approved && !e.paid)}
                               title={!e.approved && !e.paid ? "approve it first" : ""}
                               onChange={(ev) =>
                                 act(`pay-${e.recording}`, `/api/ops/episodes/${e.recording}/pay`,
                                     { value: ev.target.checked })} />
                        {e.paid && e.amount_krw > 0 && (
                          <div className="ops-chip">₩{fmt(e.amount_krw)}</div>
                        )}
                      </td>
                      <td className="ops-del">
                        {e.deleted_at ? (
                          <>
                            <span className={`ops-chip ${e.delete_kind === "hard" ? "bad" : ""}`}>
                              {e.delete_kind}
                            </span>
                            {e.delete_kind === "soft" && (
                              <button onClick={() =>
                                act(`res-${e.recording}`, `/api/ops/episodes/${e.recording}/restore`)}>
                                restore
                              </button>
                            )}
                          </>
                        ) : (
                          <>
                            <button
                              title="Hide it here. Every byte stays in the bucket."
                              onClick={() =>
                                act(`sd-${e.recording}`, `/api/ops/episodes/${e.recording}/delete`,
                                    { kind: "soft", reason: "" })}>
                              soft
                            </button>
                            <button
                              className="danger"
                              title="Purge the objects from S3. Cannot be undone — the bucket denies deletes to its uploaders, so it cannot be re-uploaded either."
                              onClick={() => {
                                const reason = window.prompt(
                                  `HARD DELETE ${e.recording}\n\n` +
                                  `${e.size_mb} MB will be purged from S3 and cannot be recovered. ` +
                                  `The ledger row survives as a record.\n\nWhy is this worth deleting?`);
                                if (reason === null) return;
                                act(`hd-${e.recording}`, `/api/ops/episodes/${e.recording}/delete`,
                                    { kind: "hard", reason });
                              }}>
                              hard
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {rows.length === 0 && (
              <div className="ops-empty">
                {episodes.length
                  ? "Nothing matches that filter."
                  : "Nothing in the ledger yet — import the laptop ledger to fill it."}
              </div>
            )}
          </div>

          <div className="ops-side">
            <div className="ops-panel">
              <div className="ops-phead"><h2>Per person</h2></div>
              <table className="ops-sum">
                <tbody>
                  {summary.length ? summary.map((s) => {
                    const shown = s.devices.slice(0, 3).join(", ");
                    const more = s.devices.length > 3 ? ` +${s.devices.length - 3}` : "";
                    return (
                      <tr key={s.key}>
                        <td>
                          <div className="ops-who">{s.person}</div>
                          <div className="ops-chip ops-devs" title={s.devices.join(", ")}>
                            {shown || "—"}{more}
                          </div>
                        </td>
                        <td className="num">{s.approved}<div className="ops-tile-l">approved</div></td>
                        <td className="num">{Math.round(s.minutes)}<div className="ops-tile-l">min</div></td>
                        <td className="num">{s.unpaidApproved}<div className="ops-tile-l">unpaid</div></td>
                      </tr>
                    );
                  }) : (
                    <tr><td className="ops-empty">—</td></tr>
                  )}
                </tbody>
              </table>
            </div>

            <div className="ops-panel">
              <div className="ops-phead"><h2>Current board rate</h2></div>
              <div className="ops-pbody">
                <label htmlFor="ops-rate">Current amount per approved episode (KRW)</label>
                <input id="ops-rate" type="number" min="0" step="10" value={rateDraft}
                       onChange={(ev) => setRateDraft(ev.target.value)}
                       onBlur={commitRate}
                       onKeyDown={(ev) => { if (ev.key === "Enter") ev.currentTarget.blur(); }} />
                <p className="ops-hint">
                  This board records an amount <b>per approved episode</b>, not per hour.
                  Its estimate uses the current rate; historical agreements and transfer
                  evidence appear separately above. Changing this rate does not rewrite
                  stored marked-paid amounts. A paid checkbox does not verify settlement.
                </p>
              </div>
            </div>

            <div className="ops-panel">
              <div className="ops-phead"><h2>Task labels</h2></div>
              <div className="ops-pbody">
                <label htmlFor="ops-task">Add a task label</label>
                <div className="ops-bar" style={{ marginBottom: 0 }}>
                  <input id="ops-task" className="ops-q" placeholder="label"
                         value={taskName} onChange={(e) => setTaskName(e.target.value)} />
                  <select value={taskCat} onChange={(e) => setTaskCat(e.target.value)}
                          title="category, as used in the delivered takes catalog">
                    {[...new Set([...tasks.map((x) => x.category), "other"])]
                      .sort().map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                  <button
                    disabled={!taskName.trim() || busy === "task"}
                    onClick={async () => {
                      const ok = await act("task", "/api/ops/tasks",
                                           { name: taskName.trim(), category: taskCat });
                      if (ok) setTaskName("");
                    }}>
                    Add
                  </button>
                </div>
                <p className="ops-hint">
                  The label list is controlled on purpose — free text turns one
                  activity into four names inside a week. People are managed on
                  the <b>Users</b> tab.
                </p>
              </div>
            </div>
          </div>
        </div>
      {preview && (
        <div className="ops-modal-back" onClick={() => setPreview(null)}>
          <div className="ops-modal" onClick={(ev) => ev.stopPropagation()}>
            <header>
              <span className="mono">{preview.recording}</span>
              <button onClick={() => setPreview(null)}>close</button>
            </header>

            {preview.loading && <p className="ops-muted">Signing a link…</p>}

            {!preview.loading && preview.error && (
              <p className="ops-error">{preview.error}</p>
            )}

            {!preview.loading && !preview.error && preview.files.length === 0 && (
              <p className="ops-muted">
                <b>Nothing playable in this episode.</b> Older takes hold a raw{" "}
                <code>capture.egoc</code> container and no mp4 — the video has to be
                exported from it before anything can play it.
              </p>
            )}

            {preview.files.length > 0 && (
              <>
                {preview.files.length > 1 && (
                  <select
                    value={preview.pick}
                    onChange={(ev) => setPreview({ ...preview, pick: Number(ev.target.value) })}
                  >
                    {preview.files.map((f, i) => (
                      <option key={f.name} value={i}>
                        {f.name} · {(f.bytes / 1e6).toFixed(1)} MB
                      </option>
                    ))}
                  </select>
                )}
                {/* Streamed straight from S3 on a presigned URL, so the browser's
                    Range requests fetch only the part actually watched. */}
                <video key={preview.files[preview.pick].url}
                       src={preview.files[preview.pick].url}
                       controls playsInline preload="metadata" />
                <p className="ops-muted">
                  {preview.files[preview.pick].name} ·{" "}
                  {(preview.files[preview.pick].bytes / 1e6).toFixed(1)} MB · streamed
                  from S3, so only the part you watch is fetched.
                </p>
                <p className="ops-muted">
                  Takes are H.265 (hvc1) at 4000×1200 side-by-side. Safari plays them
                  on macOS; Chrome only where it has hardware HEVC. A black player
                  means the browser will not decode it — the file is fine.
                </p>
              </>
            )}
          </div>
        </div>
      )}

    </>
  );
}
