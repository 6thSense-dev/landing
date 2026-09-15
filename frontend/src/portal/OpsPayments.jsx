import { useEffect, useState } from "react";
import { portalFetch } from "./portalFetch.js";
const hours = (s) => {
  const total = Math.round(s || 0);
  return `${Math.floor(total / 3600)}h ${String(Math.floor(total % 3600 / 60)).padStart(2, '0')}m ${String(total % 60).padStart(2, '0')}s`;
};
const money = (n) =>
  n == null ? "Rate needed" : `₩${n.toLocaleString("ko-KR")}`;
export default function OpsPayments({ onReview }) {
  const [data, setData] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [recipient, setRecipient] = useState({}),
    [confirm, setConfirm] = useState({});
  const load = async () => {
    try {
      const r = await portalFetch("/api/ops/payments/state");
      if (!r.ok) throw Error(r.data?.detail || "Could not load payments.");
      setData(r.data);
      setConfirm({});
    } catch (e) {
      setError(e.message);
    }
  };
  useEffect(() => {
    load();
  }, []);
  async function mutate(path, body) {
    setBusy(true);
    setError("");
    try {
      const r = await portalFetch(`/api/ops/payments/${path}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      if (!r.ok) throw Error(r.data?.detail || "Payment change failed.");
      setData(r.data);
      setConfirm({});
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label="Payment ledger">
      <div className="ops-clean-intro">
        <div>
          <h2>Payment</h2>
          <p>
            Review the contributor’s footage breakdown, then approve an exact
            payout.
          </p>
        </div>
        <button onClick={load} disabled={busy}>
          Refresh
        </button>
      </div>
      {error && (
        <p role="alert" className="ops-error">
          {error}
        </p>
      )}
      {!data ? (
        <p>Loading payment ledger…</p>
      ) : (
        <>
          <p className="ops-note">
            Friday 18:00 Korea · more than 4 hours of{" "}
            {data.configuration.threshold_basis === "weekly"
              ? "reviewed, retained footage in the previous Monday–Sunday week"
              : "accumulated unpaid reviewed footage"}
            . Eligible payouts include older unpaid reviewed footage. Unreviewed
            footage and uncertain collection dates stay pending.
          </p>
          <p>
            {data.configuration.wise_configured
              ? "Wise credentials configured"
              : "Wise connection needed"}{" "}
            ·{" "}
            {data.configuration.automatic_payouts_enabled
              ? "Scheduled payouts enabled after approval"
              : "Scheduled payouts disabled"}{" "}
            ·{" "}
            {data.configuration.automatic_funding_enabled
              ? "Automatic funding enabled after approval"
              : "Automatic funding disabled"}{" "}
            ·{" "}
            {data.configuration.wise_environment === "production"
              ? "Production"
              : "Sandbox — test transfers only"}
          </p>
          <p className="ops-muted">
            Allow up to five business days after initiation; Wise’s status
            confirms progress. Payment initiation:{" "}
            {new Date(data.scheduled_for).toLocaleString("en-GB", {
              timeZone: "Asia/Seoul",
            })}{" "}
            KST · collection week {data.collection_week[0]} to{" "}
            {data.collection_week[1]} (end exclusive)
          </p>
          {data.contributors.map((p) => (
            <article className="ops-panel ops-clean-card" key={p.wearer_id}>
              <div className="ops-clean-card-head">
                <div>
                  <h3>{p.name}</h3>
                  <p>{p.workplace}</p>
                </div>
                <b>{money(p.due_krw)} awaiting approval estimate</b>
              </div>
              <div className="ops-clean-metrics">
                <div>
                  <b>
                    {hours(p.entries.reduce((s, e) => s + e.source_seconds, 0))}
                  </b>
                  <span>collected / decoded</span>
                </div>
                <div>
                  <b>
                    {hours(
                      p.entries.reduce((s, e) => s + e.retained_seconds, 0),
                    )}
                  </b>
                  <span>retained</span>
                </div>
                <div>
                  <b>{hours(p.qualifying_seconds)}</b>
                  <span>qualifying reviewed time</span>
                </div>
              </div>
              <button onClick={onReview}>Review footage in Clean</button>
              <details>
                <summary>
                  Footage and exclusion breakdown ({p.entries.length})
                </summary>
                <div className="ops-tablewrap">
                  <table className="ops-table">
                    <thead>
                      <tr>
                        <th>Recording / date</th>
                        <th>Collected</th>
                        <th>Retained</th>
                        <th>Excluded / reasons</th>
                        <th>Review</th>
                        <th>Payment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {p.entries.map((e) => (
                        <tr key={`${e.run_id}:${e.recording}`}>
                          <td className="mono">
                            {e.recording}
                            <div>
                              {e.collection_date || "Confirm date in Clean"}
                            </div>
                          </td>
                          <td>{hours(e.source_seconds)}</td>
                          <td>{hours(e.retained_seconds)}</td>
                          <td>
                            {hours(e.rejected_seconds)}
                            <ul>
                              {Object.entries(e.rejection_reasons).map(
                                ([why, s]) => (
                                  <li key={why}>
                                    {why}: {hours(s)}
                                  </li>
                                ),
                              )}
                            </ul>
                          </td>
                          <td>{e.review_status.replaceAll("_", " ")}</td>
                          <td>{e.payment_status.replaceAll("_", " ")}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
              <div className="ops-payout-recipient">
                <p>
                  Wise recipient:{" "}
                  {p.recipient
                    ? `${p.recipient.name} · ID ${p.recipient.id}`
                    : "Not connected"}
                </p>
                <details>
                  <summary>Connect / change recipient</summary>
                  <label>
                    Existing KRW Wise recipient ID
                    <input
                      type="number"
                      min="1"
                      value={recipient[p.wearer_id] || ""}
                      onChange={(e) =>
                        setRecipient({
                          ...recipient,
                          [p.wearer_id]: e.target.value,
                        })
                      }
                    />
                  </label>
                  <label className="ops-check">
                    <input
                      type="checkbox"
                      checked={!!confirm[`recipient-${p.wearer_id}`]}
                      onChange={(e) =>
                        setConfirm({
                          ...confirm,
                          [`recipient-${p.wearer_id}`]: e.target.checked,
                        })
                      }
                    />
                    This recipient belongs to {p.name}.
                  </label>
                  <button
                    disabled={
                      busy ||
                      !data.configuration.wise_configured ||
                      !recipient[p.wearer_id] ||
                      !confirm[`recipient-${p.wearer_id}`]
                    }
                    onClick={() =>
                      mutate("recipient", {
                        wearer_id: p.wearer_id,
                        recipient_id: Number(recipient[p.wearer_id]),
                        confirm_recipient: true,
                      })
                    }
                  >
                    Verify and save recipient
                  </button>
                </details>
              </div>
              <p>
                {p.eligible_entries.length} recordings eligible ·{" "}
                {money(p.eligible_krw)}
              </p>
              <label className="ops-check">
                <input
                  type="checkbox"
                  checked={!!confirm[p.wearer_id]}
                  onChange={(e) =>
                    setConfirm({ ...confirm, [p.wearer_id]: e.target.checked })
                  }
                />
                I approve {money(p.eligible_krw)} for this reviewed footage and
                the recipient shown above.
              </label>
              <button
                disabled={
                  busy ||
                  !confirm[p.wearer_id] ||
                  !p.recipient ||
                  !p.recipient.revision ||
                  !p.is_active ||
                  !p.eligible_entries.length ||
                  !data.configuration.source_currency
                }
                onClick={() =>
                  mutate("approve", {
                    wearer_id: p.wearer_id,
                    entries: p.eligible_entries,
                    expected_amount_krw: p.eligible_krw,
                    expected_recipient_revision: p.recipient.revision,
                    approve_payment: true,
                  })
                }
              >
                Approve Payment
              </button>
            </article>
          ))}
          <div className="ops-panel">
            <div className="ops-phead">
              <h2>Payout history</h2>
            </div>
            <div className="ops-tablewrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Contributor</th>
                    <th>Amount</th>
                    <th>Scheduled (KST)</th>
                    <th>Status</th>
                    <th>Approved by</th>
                    <th>Wise reference</th>
                  </tr>
                </thead>
                <tbody>
                  {data.payouts.map((p) => (
                    <tr key={p.id}>
                      <td>
                        {
                          data.contributors.find(
                            (c) => c.wearer_id === p.wearer_id,
                          )?.name
                        }
                      </td>
                      <td>{money(p.amount_krw)}</td>
                      <td>{new Date(p.scheduled_for).toLocaleString('en-GB', { timeZone: 'Asia/Seoul' })}</td>
                      <td>
                        {p.status}
                        {p.error && <div role="alert">{p.error}</div>}
                      </td>
                      <td>{p.approved_by}</td>
                      <td>{p.transfer_id || "Not sent"}</td>
                    </tr>
                  ))}
                  {!data.payouts.length && (
                    <tr>
                      <td colSpan={6}>No payments approved or sent.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
