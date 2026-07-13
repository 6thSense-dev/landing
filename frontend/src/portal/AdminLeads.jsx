import { useCallback, useEffect, useRef, useState } from "react";
import {
  copyLeadsForSheets,
  createLead,
  deleteLead,
  downloadLeadsCsv,
  listLeads,
  updateLead,
} from "./adminApi.js";
import LeadFormModal from "./LeadFormModal.jsx";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "pending", label: "Pending" },
  { key: "followed_up", label: "Followed up" },
];

const dateFmt = new Intl.DateTimeFormat(undefined, {
  month: "short",
  day: "numeric",
  year: "numeric",
});

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : dateFmt.format(d);
}

/**
 * The leads CRM. Its whole job: make "who still needs a reply" impossible to
 * miss. Pending count sits up top, pending leads sort first, and one click on
 * the checkmark clears a lead off the queue.
 */
export default function AdminLeads() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [leads, setLeads] = useState([]);
  const [stats, setStats] = useState({ total: 0, pending: 0, followed_up: 0 });
  const [state, setState] = useState("loading"); // loading | ready | error
  const [notice, setNotice] = useState(null); // {tone, text}
  const [editing, setEditing] = useState(null); // lead object | "new" | null
  const [confirming, setConfirming] = useState(null); // lead to delete | null

  const noticeTimer = useRef(0);
  const flash = useCallback((tone, text) => {
    setNotice({ tone, text });
    window.clearTimeout(noticeTimer.current);
    noticeTimer.current = window.setTimeout(() => setNotice(null), 3200);
  }, []);

  const load = useCallback(async () => {
    const { ok, data } = await listLeads({ q, status });
    if (ok && data) {
      setLeads(data.leads);
      setStats(data.stats);
      setState("ready");
    } else {
      setState("error");
    }
  }, [q, status]);

  // Debounce so typing in search doesn't fire a request per keystroke.
  useEffect(() => {
    const t = window.setTimeout(load, 200);
    return () => window.clearTimeout(t);
  }, [load]);

  async function toggleFollowUp(lead) {
    const next = !lead.followed_up;
    // Optimistic: flip locally, revert if the request fails.
    setLeads((cur) =>
      cur.map((l) => (l.id === lead.id ? { ...l, followed_up: next } : l))
    );
    setStats((s) => ({
      ...s,
      followed_up: s.followed_up + (next ? 1 : -1),
      pending: s.pending + (next ? -1 : 1),
    }));
    const { ok } = await updateLead(lead.id, { followed_up: next });
    if (!ok) {
      flash("error", "Couldn't update. Refreshing…");
      load();
    }
  }

  async function saveLead(form) {
    const isNew = editing === "new";
    const { ok, status: code, data } = isNew
      ? await createLead(form)
      : await updateLead(editing.id, form);
    if (ok) {
      setEditing(null);
      flash("ok", isNew ? "Lead added." : "Lead updated.");
      load();
      return { ok: true };
    }
    if (code === 409) {
      return { ok: false, error: data?.detail || "That email is already in use." };
    }
    if (code === 422) {
      return { ok: false, error: "Please check the fields and try again." };
    }
    return { ok: false, error: "Something went wrong. Please try again." };
  }

  async function confirmDelete() {
    const lead = confirming;
    setConfirming(null);
    const { ok } = await deleteLead(lead.id);
    if (ok) {
      flash("ok", "Lead deleted.");
      load();
    } else {
      flash("error", "Couldn't delete that lead.");
    }
  }

  async function onCopySheets() {
    try {
      const n = await copyLeadsForSheets(leads);
      flash("ok", `Copied ${n} lead${n === 1 ? "" : "s"} — paste into a Sheet.`);
    } catch {
      flash("error", "Clipboard blocked. Use Download CSV instead.");
    }
  }

  async function onDownloadCsv() {
    try {
      await downloadLeadsCsv({ q, status });
    } catch {
      flash("error", "Export failed. Please try again.");
    }
  }

  return (
    <section className="admin-leads">
      <header className="admin-leads-head">
        <div>
          <h1 className="admin-h1">Leads</h1>
          <p className="admin-sub">
            Every inbound from the site's Contact form. Clear each one once
            you've replied.
          </p>
        </div>
        <div className="admin-actions">
          <button className="admin-btn admin-btn--solid" onClick={() => setEditing("new")}>
            + Add lead
          </button>
          <button className="admin-btn admin-btn--ghost" onClick={onDownloadCsv}>
            Download CSV
          </button>
          <button className="admin-btn admin-btn--ghost" onClick={onCopySheets}>
            Copy for Sheets
          </button>
        </div>
      </header>

      <div className="admin-stats">
        <Stat label="Total leads" value={stats.total} />
        <Stat label="Pending follow-up" value={stats.pending} tone={stats.pending > 0 ? "alert" : "ok"} />
        <Stat label="Followed up" value={stats.followed_up} />
      </div>

      <div className="admin-toolbar">
        <input
          className="admin-search"
          type="search"
          placeholder="Search name, email, org, message…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search leads"
        />
        <div className="admin-segment" role="tablist" aria-label="Filter leads">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              role="tab"
              aria-selected={status === f.key}
              className={`admin-seg-btn${status === f.key ? " is-active" : ""}`}
              onClick={() => setStatus(f.key)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {notice && <div className={`admin-notice admin-notice--${notice.tone}`}>{notice.text}</div>}

      {state === "error" ? (
        <div className="admin-empty">Couldn't load leads. <button className="admin-linkbtn" onClick={load}>Retry</button></div>
      ) : state === "loading" ? (
        <div className="admin-empty">Loading…</div>
      ) : leads.length === 0 ? (
        <div className="admin-empty">
          {q || status !== "all" ? "No leads match this view." : "No leads yet."}
        </div>
      ) : (
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th className="admin-col-check" scope="col"><span className="admin-vh">Followed up</span></th>
                <th scope="col">Name</th>
                <th scope="col">Email</th>
                <th scope="col">Organization</th>
                <th scope="col">Message</th>
                <th scope="col">Received</th>
                <th className="admin-col-actions" scope="col"><span className="admin-vh">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {leads.map((l) => (
                <tr key={l.id} className={l.followed_up ? "is-done" : "is-pending"}>
                  <td className="admin-col-check">
                    <label className="admin-check" title={l.followed_up ? "Followed up — click to reopen" : "Mark as followed up"}>
                      <input
                        type="checkbox"
                        checked={l.followed_up}
                        onChange={() => toggleFollowUp(l)}
                      />
                      <span className="admin-check-box" aria-hidden="true" />
                    </label>
                  </td>
                  <td className="admin-cell-name">{l.name}</td>
                  <td>
                    <a className="admin-email" href={`mailto:${l.email}`}>{l.email}</a>
                  </td>
                  <td>{l.organization}</td>
                  <td className="admin-cell-msg" title={l.message}>{l.message}</td>
                  <td className="admin-cell-date">{fmtDate(l.created_at)}</td>
                  <td className="admin-col-actions">
                    <button className="admin-iconbtn" onClick={() => setEditing(l)} aria-label={`Edit ${l.name}`}>Edit</button>
                    <button className="admin-iconbtn admin-iconbtn--danger" onClick={() => setConfirming(l)} aria-label={`Delete ${l.name}`}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <LeadFormModal
          lead={editing === "new" ? null : editing}
          onSave={saveLead}
          onClose={() => setEditing(null)}
        />
      )}

      {confirming && (
        <div className="admin-modal-overlay" onClick={() => setConfirming(null)}>
          <div className="admin-modal admin-modal--sm" role="dialog" aria-modal="true" aria-label="Confirm delete" onClick={(e) => e.stopPropagation()}>
            <h2 className="admin-modal-title">Delete this lead?</h2>
            <p className="admin-modal-desc">
              {confirming.name} ({confirming.email}) will be permanently removed.
              This can't be undone.
            </p>
            <div className="admin-modal-actions">
              <button className="admin-btn admin-btn--ghost" onClick={() => setConfirming(null)}>Cancel</button>
              <button className="admin-btn admin-btn--danger" onClick={confirmDelete}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function Stat({ label, value, tone }) {
  return (
    <div className={`admin-stat${tone ? ` admin-stat--${tone}` : ""}`}>
      <span className="admin-stat-n">{value}</span>
      <span className="admin-stat-l">{label}</span>
    </div>
  );
}
