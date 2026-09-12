import { useMemo, useState } from "react";
import { fmt } from "./opsShared.js";

/**
 * USERS — the people who carry cameras, and nothing else.
 *
 * THESE ARE NOT PORTAL SIGN-INS. `ops_wearers` is deliberately a different
 * table from `users`: almost no camera carrier will ever log in, and the few
 * who might must not become one row with two meanings. Deleting a login must
 * never delete the payment history of the person it belonged to.
 *
 * There is no delete button, on purpose. A person is attached to episodes that
 * were reviewed and possibly paid; removing the row would leave a settled
 * payment with nobody's name on it. "Retire" clears them out of the pickers and
 * keeps every past attribution intact.
 */

/** Hours, never a decimal — a decimal reads as a headcount-derived figure. */
function hhmm(seconds) {
  const m = Math.round((seconds || 0) / 60);
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export default function OpsUsers({ state, act, busy, readOnly = false }) {
  const wearers = state?.wearers ?? [];
  const episodes = state?.episodes ?? [];

  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [workplace, setWorkplace] = useState("");
  const [location, setLocation] = useState("");
  const [hourlyRate, setHourlyRate] = useState("");
  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(null);   // wearer id being edited
  const [draft, setDraft] = useState({});
  const [showRetired, setShowRetired] = useState(false);

  // What each person has actually delivered. Accepted MINUTES, not episode
  // count: an episode is 2 to 25 minutes, so counting episodes flatters whoever
  // records in short bursts and is not the basis anything is paid on.
  const stats = useMemo(() => {
    const by = new Map();
    for (const e of episodes) {
      if (e.deleted_at || e.wearer_id == null) continue;
      let s = by.get(e.wearer_id);
      if (!s) {
        s = { episodes: 0, approvedSec: 0, unpaid: 0, devices: new Set(), last: "" };
        by.set(e.wearer_id, s);
      }
      s.episodes += 1;
      if (e.device_id) s.devices.add(e.device_id);
      if (e.started_at && e.started_at > s.last) s.last = e.started_at;
      if (e.approved) {
        s.approvedSec += (e.minutes ?? 0) * 60;
        if (!e.paid) s.unpaid += 1;
      }
    }
    return by;
  }, [episodes]);

  const unassigned = useMemo(
    () => episodes.filter((e) => !e.deleted_at && e.wearer_id == null).length,
    [episodes],
  );

  const shown = showRetired ? wearers : wearers.filter((w) => w.is_active);

  const save = async (w, patch) => {
    const ok = await act(`wearer-${w.id}`, `/api/ops/wearers/${w.id}`, patch);
    // Only leave edit mode if THIS is the row being edited. Retiring somebody
    // else used to throw away whatever was half-typed in an open editor.
    if (ok && editing === w.id) { setEditing(null); setDraft({}); }
  };

  return (
    <>
      <div className="ops-tiles">
        {[
          ["People", fmt(wearers.filter((w) => w.is_active).length)],
          ["Retired", fmt(wearers.filter((w) => !w.is_active).length)],
          ["Carrying a camera", fmt([...stats.keys()].length)],
          ["Episodes unassigned", fmt(unassigned)],
        ].map(([label, value]) => (
          <div className="ops-tile" key={label}>
            <div className="ops-tile-n">{value}</div>
            <div className="ops-tile-l">{label}</div>
          </div>
        ))}
      </div>

      <div className="ops-cols ops-cols--narrow">
        <div className="ops-panel">
          <div className="ops-filters">
            <h2 className="ops-users-title">People who carry cameras</h2>
            <label className="ops-check">
              <input type="checkbox" checked={showRetired}
                     onChange={(e) => setShowRetired(e.target.checked)} />
              show retired
            </label>
          </div>

          <div className="ops-tablewrap">
            <table className="ops-table">
              <thead>
                <tr>
                  <th>Name</th><th>Workplace / location / rate</th><th>Contact</th><th>Note</th><th>Cameras</th>
                  <th className="num">Episodes</th><th className="num">Accepted</th>
                  <th className="num">Unpaid</th><th>Last seen</th><th />
                </tr>
              </thead>
              <tbody>
                {shown.map((w) => {
                  const s = stats.get(w.id);
                  const isEd = editing === w.id;
                  return (
                    <tr key={w.id} className={w.is_active ? "" : "ops-row-deleted"}>
                      <td>
                        {isEd ? (
                          <input value={draft.name ?? w.name}
                                 onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                        ) : w.name}
                      </td>
                      <td>
                        {isEd ? <div className="ops-clean-person">
                          <input aria-label="Workplace" placeholder="Workplace" value={draft.workplace ?? w.workplace ?? ''} onChange={e => setDraft({ ...draft, workplace: e.target.value })} />
                          <input aria-label="Location" placeholder="Location" value={draft.location ?? w.location ?? ''} onChange={e => setDraft({ ...draft, location: e.target.value })} />
                          <input aria-label="KRW per approved hour" type="number" min="0" max="100000000" placeholder="KRW per approved hour" value={draft.rate_krw_hour ?? w.rate_krw_hour ?? ''} onChange={e => setDraft({ ...draft, rate_krw_hour: e.target.value })} />
                        </div> : <div className="ops-clean-person"><span>{w.workplace || '—'}</span><span>{w.location || '—'}</span><span>{w.rate_krw_hour == null ? 'Rate not set' : `₩${fmt(w.rate_krw_hour)} / hour`}</span></div>}
                      </td>
                      <td>
                        {isEd ? (
                          <input placeholder="phone or messenger"
                                 value={draft.contact ?? w.contact}
                                 onChange={(e) => setDraft({ ...draft, contact: e.target.value })} />
                        ) : (w.contact || <span className="ops-muted">—</span>)}
                      </td>
                      <td>
                        {isEd ? (
                          <input placeholder="which shop, which shift…"
                                 value={draft.note ?? w.note}
                                 onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
                        ) : (w.note || <span className="ops-muted">—</span>)}
                      </td>
                      <td className="mono">
                        {s && s.devices.size
                          ? [...s.devices].sort().join(", ")
                          : <span className="ops-muted">—</span>}
                      </td>
                      <td className="num">{s?.episodes ?? 0}</td>
                      <td className="num">{hhmm(s?.approvedSec)}</td>
                      <td className="num">{s?.unpaid ?? 0}</td>
                      <td className="mono ops-nowrap">
                        {s?.last ? s.last.replace("T", " ").slice(0, 16)
                                 : <span className="ops-muted">never</span>}
                      </td>
                      <td className="ops-del">
                        {isEd ? (
                          <>
                            <button disabled={busy === `wearer-${w.id}`}
                                    onClick={() => save(w, {
                                      name: (draft.name ?? w.name).trim() || w.name,
                                      contact: draft.contact ?? w.contact,
                                      workplace: draft.workplace ?? w.workplace,
                                      location: draft.location ?? w.location,
                                      rate_krw_hour: (draft.rate_krw_hour ?? w.rate_krw_hour) === "" ? null : (draft.rate_krw_hour ?? w.rate_krw_hour) == null ? null : Number(draft.rate_krw_hour ?? w.rate_krw_hour),
                                      note: draft.note ?? w.note,
                                    })}>save</button>
                            <button disabled={readOnly} onClick={() => { setEditing(null); setDraft({}); }}>
                              cancel
                            </button>
                          </>
                        ) : (
                          <>
                            <button disabled={readOnly} onClick={() => { setEditing(w.id); setDraft({}); }}>
                              edit
                            </button>
                            <button disabled={readOnly}
                              title={w.is_active
                                ? "Retire them: they leave the pickers, every past episode keeps their name."
                                : "Bring them back into the pickers."}
                              onClick={() => save(w, { is_active: !w.is_active })}>
                              {w.is_active ? "retire" : "restore"}
                            </button>
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {shown.length === 0 && (
            <div className="ops-empty">
              {wearers.length
                ? "Everyone is retired. Tick “show retired” to see them."
                : "Nobody yet — add the first person on the right."}
            </div>
          )}
        </div>

        <div className="ops-side">
          <div className="ops-panel">
            <div className="ops-phead"><h2>Add a person</h2></div>
            <div className="ops-pbody">
              <label htmlFor="u-name">Name</label>
              <input disabled={readOnly} id="u-name" value={name} placeholder="김민준"
                     onChange={(e) => setName(e.target.value)} />
              <label htmlFor="u-contact">Contact</label>
              <input disabled={readOnly} id="u-contact" value={contact} placeholder="010-0000-0000 / KakaoTalk"
                     onChange={(e) => setContact(e.target.value)} />
              <label htmlFor="u-workplace">Workplace</label><input disabled={readOnly} id="u-workplace" value={workplace} onChange={e => setWorkplace(e.target.value)} placeholder="Printing workshop" maxLength={200} />
              <label htmlFor="u-location">Location</label><input disabled={readOnly} id="u-location" value={location} onChange={e => setLocation(e.target.value)} placeholder="Country, city, or site" maxLength={200} />
              <label htmlFor="u-hourly">KRW per approved hour</label><input disabled={readOnly} id="u-hourly" type="number" min="0" max="100000000" value={hourlyRate} onChange={e => setHourlyRate(e.target.value)} placeholder="11000" />
              <label htmlFor="u-note">Note</label>
              <input disabled={readOnly} id="u-note" value={note} placeholder="which shop, which shift…"
                     onChange={(e) => setNote(e.target.value)} />
              <button
                disabled={readOnly || !name.trim() || busy === "wearer"}
                onClick={async () => {
                  const ok = await act("wearer", "/api/ops/wearers", {
                    name: name.trim(), contact: contact.trim(), note: note.trim(),
                    workplace: workplace.trim(), location: location.trim(), rate_krw_hour: hourlyRate === "" ? null : Number(hourlyRate),
                  });
                  if (ok) { setName(""); setContact(""); setNote(""); setWorkplace(""); setLocation(""); setHourlyRate(""); }
                }}>
                Add person
              </button>
              {/* Contact is optional on purpose: a collector is onboarded in a
                  car park with a phone, and requiring an email here would mean
                  either a blocked row or a fake one. */}
              <p className="ops-hint">
                Only the name is required. Contact is free-form because people
                are signed up on the spot.
              </p>
            </div>
          </div>

          <div className="ops-panel">
            <div className="ops-phead"><h2>What this list is</h2></div>
            <div className="ops-pbody">
              <p className="ops-hint">
                These are <b>people who carry cameras</b>, not portal sign-ins.
                Almost none of them will ever log in here, and the record has to
                outlive any account.
              </p>
              <p className="ops-hint">
                Nobody can be deleted. A person is attached to episodes that were
                reviewed and possibly paid — removing them would leave a settled
                payment with nobody's name on it. <b>Retire</b> takes them out of
                the pickers and keeps the history.
              </p>
              <p className="ops-hint">
                <b>Accepted</b> is hours of approved footage, which is what
                anything is paid on. It is not hours worked.
              </p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
