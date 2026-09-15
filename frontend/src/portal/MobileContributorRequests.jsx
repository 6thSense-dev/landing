import { useCallback, useEffect, useRef, useState } from "react";
import { portalFetch } from "./portalFetch.js";

const recipientNumber = (value) => /^[1-9]\d*$/.test(String(value)) && Number.isSafeInteger(Number(value));
const errorMessage = (response, fallback) => typeof response.data?.detail === "string"
  ? response.data.detail : `${fallback}${response.status ? ` (HTTP ${response.status})` : " Check your connection."}`;

function CameraRequest({ claim, person, disabled, mutate }) {
  const [verified, setVerified] = useState(false);
  return <article className="ops-mobile-request" aria-label={`Camera EGO-${claim.device_id}`}>
    <h4>{person.name} <span>· contributor #{person.id}</span></h4>
    <p className="ops-mobile-reference">EGO-{claim.device_id}</p>
    <label className="ops-check">
      <input type="checkbox" checked={verified} disabled={disabled}
        onChange={(event) => setVerified(event.target.checked)} />
      I physically verified this camera with {person.name}.
    </label>
    <button disabled={disabled || !verified || !person.id || person.is_active === false}
      onClick={() => mutate(`/api/ops/contributors/cameras/${encodeURIComponent(claim.id)}/approve`,
        { physically_verified: true }, `EGO-${claim.device_id} approved for ${person.name}.`)}>
      Approve camera
    </button>
  </article>;
}

function BankRequest({ attempt, person, disabled, mutate }) {
  const [ownership, setOwnership] = useState(false);
  const [resolution, setResolution] = useState("");
  const [recipient, setRecipient] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const summary = attempt.summary || {};
  const known = recipientNumber(attempt.recipient_id);
  const canLink = known && summary.currency === "KRW";
  const canResolve = resolution && note.trim().length >= 10 && confirmed
    && (resolution === "not_created" || recipientNumber(recipient));
  const resolve = (event) => {
    event.preventDefault();
    if (!canResolve || disabled) return;
    mutate(`/api/ops/contributors/recipients/${encodeURIComponent(attempt.id)}/resolve`, {
      resolution, note: note.trim(), ...(resolution === "found"
        ? { recipient_id: Number(recipient), verified_owner: true }
        : { confirmed_not_created: true }),
    }, resolution === "found" ? "Recipient found. Review and link it separately for payments."
      : "No recipient was created. The contributor can submit their bank details again.");
  };
  return <article className="ops-mobile-request" aria-label={`Bank review for ${person.name}`}>
    <h4>{person.name} <span>· contributor #{person.id}</span></h4>
    <dl className="ops-mobile-bank-summary">
      <div><dt>Account holder</dt><dd>{summary.accountHolderName || "Not provided"}</dd></div>
      <div><dt>Bank / account</dt><dd>{summary.bankLabel || "Bank not listed"} · {summary.maskedAccount || "Not provided"}</dd></div>
      <div><dt>Currency</dt><dd>{summary.currency || "Unknown"}</dd></div>
      <div><dt>Wise recipient</dt><dd>{known ? `ID ${attempt.recipient_id}` : "Outcome needs verification"}</dd></div>
    </dl>
    <p className="ops-hint ops-mobile-reference">Submission {attempt.id}</p>
    {known ? <>
      {!canLink && <p className="ops-hint">Payment linking is currently available for KRW recipients.</p>}
      <label className="ops-check">
        <input type="checkbox" checked={ownership} disabled={disabled || !canLink}
          onChange={(event) => setOwnership(event.target.checked)} />
        I verified that Wise recipient {attempt.recipient_id} belongs to {person.name}.
      </label>
      <button disabled={disabled || !canLink || !ownership || !person.id || person.is_active === false}
        onClick={() => mutate("/api/ops/payments/recipient", {
          wearer_id: person.id, recipient_id: Number(attempt.recipient_id), confirm_recipient: true,
        }, `Recipient linked for ${person.name}. Approve footage payments in Payment.`)}>
        Verify and link recipient
      </button>
      <p className="ops-hint">Linking a recipient does not approve or send a payment.</p>
    </> : <form className="ops-mobile-recovery" onSubmit={resolve}>
      <p className="ops-hint">Check this submission with Wise before resolving it. An uncertain outcome stays held.</p>
      {attempt.status === "submitting" && <p className="ops-hint">A submission may still be in progress. Recovery is available after five minutes.</p>}
      <label htmlFor={`resolution-${attempt.id}`}>Verified outcome</label>
      <select id={`resolution-${attempt.id}`} value={resolution} required disabled={disabled}
        onChange={(event) => { setResolution(event.target.value); setConfirmed(false); setRecipient(""); setNote(""); }}>
        <option value="">Choose after checking Wise</option>
        <option value="found">Recipient found</option>
        <option value="not_created">No recipient was created</option>
      </select>
      {resolution && <>
        {resolution === "found" && <>
          <label htmlFor={`recipient-${attempt.id}`}>Found Wise recipient ID</label>
          <input id={`recipient-${attempt.id}`} type="text" inputMode="numeric" pattern="[1-9][0-9]*"
            value={recipient} disabled={disabled} required maxLength={16}
            onChange={(event) => { setRecipient(event.target.value); setConfirmed(false); }} />
        </>}
        <label htmlFor={`note-${attempt.id}`}>Verification note</label>
        <textarea id={`note-${attempt.id}`} value={note} required minLength={10} maxLength={500}
          disabled={disabled} rows={3} aria-describedby={`note-help-${attempt.id}`}
          onChange={(event) => setNote(event.target.value)} />
        <p className="ops-hint" id={`note-help-${attempt.id}`}>Record how the outcome was verified. Include at least 10 characters; leave out bank details.</p>
        <label className="ops-check">
          <input type="checkbox" checked={confirmed} disabled={disabled}
            onChange={(event) => setConfirmed(event.target.checked)} />
          {resolution === "found" ? `I verified that this recipient belongs to ${person.name}.`
            : "I confirmed with Wise that this submission created no recipient."}
        </label>
        <button disabled={disabled || !canResolve}>{resolution === "found" ? "Record found recipient" : "Allow a new bank submission"}</button>
      </>}
    </form>}
  </article>;
}

export default function MobileContributorRequests({ wearers, onChanged, parentBusy }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [revision, setRevision] = useState(0);
  const mutationInFlight = useRef(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [requests, payments] = await Promise.all([
        portalFetch("/api/ops/contributors"), portalFetch("/api/ops/payments/state"),
      ]);
      if (!requests.ok) throw Error(errorMessage(requests, "Could not load mobile contributor requests."));
      if (!payments.ok) throw Error(errorMessage(payments, "Could not verify linked recipients."));
      if (![requests.data?.accounts, requests.data?.claims, requests.data?.recipients, payments.data?.contributors].every(Array.isArray)) {
        throw Error("The request list could not be read. Refresh to try again.");
      }
      setData({ ...requests.data, payments: payments.data.contributors });
      setRevision((value) => value + 1);
      setError("");
    } catch (err) {
      setData(null);
      setError(err.message);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const mutate = async (path, body, success) => {
    if (mutationInFlight.current || parentBusy) return;
    mutationInFlight.current = true;
    setBusy(true); setError(""); setMessage("");
    try {
      const response = await portalFetch(path, { method: "POST", body: JSON.stringify(body) });
      if (!response.ok) throw Error(errorMessage(response, "The change could not be saved."));
      setMessage(success);
      await Promise.all([load(), onChanged?.()]);
    } catch (err) { setError(err.message); }
    finally { mutationInFlight.current = false; setBusy(false); }
  };
  const personFor = (subject) => {
    const account = data?.accounts.find((row) => row.subject === subject);
    const person = wearers.find((row) => row.id === account?.wearer_id);
    return person || { id: account?.wearer_id, name: account ? `Contributor ${account.wearer_id}` : "Account unavailable" };
  };
  const claims = data?.claims.filter((claim) => claim.status === "pending" && !claim.ended_at) || [];
  const recipients = data?.recipients.filter((attempt) => {
    if (!["submitting", "needs_reconciliation", "needs_review"].includes(attempt.status)) return false;
    const person = personFor(attempt.subject);
    const linked = data.payments.find((row) => row.wearer_id === person.id)?.recipient;
    return !attempt.recipient_id || !linked || String(linked.id) !== String(attempt.recipient_id);
  }) || [];
  const disabled = busy || loading || !!parentBusy;
  return <section className="ops-panel ops-mobile-requests" aria-labelledby="mobile-requests-title" aria-busy={busy || loading}>
    <div className="ops-phead">
      <h2 id="mobile-requests-title">Mobile contributor requests</h2>
      <span className="ops-spacer" />
      <button disabled={disabled} onClick={() => { setMessage(""); load(); onChanged?.(); }}>Refresh requests</button>
    </div>
    <div className="ops-pbody">
      <p className="ops-hint">Approve cameras after physical verification and current consent. Review bank submissions here; footage and payment approval stay in Clean and Payment.</p>
      {error && <p role="alert" className="ops-error">{error}</p>}
      {message && <p role="status" className="ops-note">{message}</p>}
      {loading && <p className="ops-muted" role="status">Loading contributor requests…</p>}
      {data && <div className="ops-mobile-columns">
        <div><h3>Camera requests ({claims.length})</h3>
          {!claims.length && <p className="ops-hint">No camera requests awaiting approval.</p>}
          {claims.map((claim) => <CameraRequest key={`${claim.id}-${revision}`} claim={claim}
            person={personFor(claim.subject)} disabled={disabled} mutate={mutate} />)}
        </div>
        <div><h3>Bank review ({recipients.length})</h3>
          {!recipients.length && <p className="ops-hint">No bank submissions awaiting review.</p>}
          {recipients.map((attempt) => <BankRequest key={`${attempt.id}-${revision}`} attempt={attempt}
            person={personFor(attempt.subject)} disabled={disabled} mutate={mutate} />)}
        </div>
      </div>}
    </div>
  </section>;
}
