import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Landmark } from 'lucide-react';
import { paymentApi, paymentCopy } from './payment.js';

export default function PaymentDetails({ locale }) {
  const t = paymentCopy[locale];
  const [setup, setSetup] = useState(null), [phase, setPhase] = useState('closed');
  const [choices, setChoices] = useState({}), [requirements, setRequirements] = useState(null);
  const [requirementsCurrent, setRequirementsCurrent] = useState(false);
  const [values, setValues] = useState({}), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [invalid, setInvalid] = useState([]), [uncertain, setUncertain] = useState(false);
  const lifetime = useRef(null), locked = useRef(false), operation = useRef(crypto.randomUUID());
  const notice = setup?.notice, localized = notice?.locales[locale], bank = setup?.bank;
  const accepted = localized && Object.keys(localized.choices).every(key => choices[key]);
  const waiting = uncertain || ['submitting', 'needs_reconciliation'].includes(bank?.status);
  const describe = e => e.message === 'payment_notice_changed' ? t.noticeChanged
    : ['consent_required', 'enrollment_required'].includes(e.message) ? t.contract
    : e.message === 'invalid_bank_fields' ? t.invalid : t.unavailable;
  const consentBody = () => ({ ...choices, locale, notice_version: notice.version, notice_sha256: notice.sha256 });

  useEffect(() => {
    const abort = new AbortController(); lifetime.current = abort;
    paymentApi('/setup', undefined, abort.signal).then(setSetup).catch(e => {
      if (!abort.signal.aborted) setError(describe(e));
    });
    return () => abort.abort();
  }, []);

  const run = async action => {
    if (locked.current) return;
    locked.current = true; setBusy(true); setError('');
    try { await action(); }
    catch (e) { if (!lifetime.current.signal.aborted) { setError(describe(e)); setInvalid(e.fields || []); } }
    finally { locked.current = false; if (!lifetime.current.signal.aborted) setBusy(false); }
  };
  const refresh = () => run(async () => {
    const result = await paymentApi('/setup', undefined, lifetime.current.signal);
    setSetup(result); setUncertain(false);
    if (result.bank || setup?.notice?.sha256 !== result.notice?.sha256) {
      setValues({}); setRequirements(null); setChoices({}); setPhase('closed');
    }
  });
  const loadFields = async nextValues => {
    const result = await paymentApi('/web/requirements', { ...consentBody(), values: nextValues }, lifetime.current.signal);
    setRequirements(result);
    setRequirementsCurrent(true);
    setValues(Object.fromEntries(result.fields.map(field => {
      let value = nextValues[field.key] || (field.key === 'address.country' ? result.country : '');
      if (field.options && !field.options.some(option => option.value === value)) value = '';
      return [field.key, value];
    })));
  };
  const begin = e => {
    e.preventDefault();
    if (accepted) run(async () => { await loadFields({}); setPhase('fields'); });
  };
  const change = (field, value) => {
    const next = { ...values, [field.key]: value };
    setValues(next); setInvalid(current => current.filter(key => key !== field.key));
    if (field.refresh) { setRequirementsCurrent(false); run(() => loadFields(next)); }
  };
  const close = () => { setPhase('closed'); setValues({}); setRequirements(null); setChoices({}); setInvalid([]); setError(''); };
  const submit = e => {
    e.preventDefault();
    if (!accepted || uncertain || !requirementsCurrent) return;
    run(async () => {
      try {
        const result = await paymentApi('/web', { ...consentBody(), operation_id: operation.current, values: Object.fromEntries(Object.entries(values).filter(([, value]) => value.trim())) }, lifetime.current.signal);
        if (!['ready', 'needs_review', 'needs_reconciliation', 'submitting'].includes(result.status)) throw Error('payment_unavailable');
        // Clear full details as soon as the durable submission is acknowledged.
        setValues({}); setRequirements(null); setPhase('closed'); setInvalid([]);
        setSetup(previous => ({ ...previous, bank: result }));
        const updated = await paymentApi('/setup', undefined, lifetime.current.signal);
        setSetup(updated);
      } catch (error) {
        if (!error.status || error.status >= 500) {
          setUncertain(true); setValues({}); setRequirements(null); setPhase('closed');
        }
        throw error;
      }
    });
  };

  return <section className="upload-payment" id="payment-details" aria-labelledby="payment-title">
    <div className="upload-payment-heading"><Landmark size={22} aria-hidden="true" /><div><h2 id="payment-title">{t.title}</h2><p>{t.intro}</p></div>
      {setup && !bank && !uncertain && notice && phase === 'closed' && <button className="upload-button upload-button--quiet" onClick={() => { operation.current = crypto.randomUUID(); setPhase('consent'); }}>{t.add}</button>}
    </div>
    {!setup && !error && <p role="status">{t.loading}</p>}
    {error && <p className="upload-error" role="alert">{error}</p>}
    {(waiting || bank) && <div className="upload-payment-status" role="status">
      <strong>{bank?.status === 'ready' ? <><CheckCircle2 size={18} />{t.ready}</> : waiting ? t.checking : t.pending}</strong>
      {bank && <p className="upload-payment-mask">{[bank.accountHolderName, bank.bankLabel, bank.maskedAccount].filter(Boolean).join(' · ')}</p>}
      <p>{waiting ? t.checkingHint : bank.status === 'ready' ? t.readyHint : t.reviewHint}</p>
      <p>{t.partner}</p><p>{t.change}</p>
    </div>}
    {setup && !notice && !bank && <p>{t.unsupported}</p>}
    {(waiting || bank || error) && <button className="upload-text-button" disabled={busy} onClick={refresh}>{t.refresh}</button>}
    {phase === 'consent' && localized && !waiting && !bank && <form onSubmit={begin} className="upload-payment-form">
      <div className="upload-payment-notice"><h3>{localized.title}</h3>{localized.paragraphs.map(p => <p key={p}>{p}</p>)}
        <a href={notice.privacy_url} target="_blank" rel="noreferrer">{t.privacy}</a>
      </div>
      <fieldset disabled={busy} className="upload-payment-consents"><legend>{localized.title}</legend>{Object.entries(localized.choices).map(([key, label]) => <label key={key}><input type="checkbox" required checked={!!choices[key]} onChange={e => setChoices({ ...choices, [key]: e.target.checked })} /><span>{label}</span></label>)}</fieldset>
      <div className="upload-actions"><button className="upload-button" disabled={!accepted || busy}>{busy ? t.loading : t.continue}</button><button type="button" className="upload-text-button" onClick={close} disabled={busy}>{t.cancel}</button></div>
    </form>}
    {phase === 'fields' && requirements && !waiting && !bank && <form className="upload-payment-form" onSubmit={submit} autoComplete="off">
      <p>{t.hint} <a href={notice.guide_url} target="_blank" rel="noreferrer">{t.guide}</a></p>
      <fieldset disabled={busy} className="upload-payment-fields"><legend>{t.title}</legend>{requirements.fields.map(field => {
        const id = `bank-${field.key}`, label = t.fields[field.key] || field.key;
        const common = { id, name: field.key, required: field.required, value: values[field.key] || '', onChange: e => change(field, e.target.value), 'aria-invalid': invalid.includes(field.key), 'aria-describedby': invalid.includes(field.key) ? `${id}-error` : undefined };
        return <div key={field.key}><label htmlFor={id}>{label}{!field.required && <span> ({t.optional})</span>}</label>
          {field.options ? <select {...common}><option value="">{t.choose}</option>{field.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select>
            : <input {...common} type={field.key === 'dateOfBirth' ? 'date' : field.key === 'email' ? 'email' : field.key === 'phoneNumber' ? 'tel' : 'text'} inputMode={field.key === 'accountNumber' ? 'numeric' : undefined} minLength={field.minLength || undefined} maxLength={field.maxLength || 255} autoComplete="off" spellCheck={false} />}
          {invalid.includes(field.key) && <span className="upload-payment-field-error" id={`${id}-error`}>{t.fieldError}</span>}
        </div>;
      })}</fieldset>
      {!requirementsCurrent && <button type="button" className="upload-text-button" disabled={busy} onClick={() => run(() => loadFields(values))}>{t.retryFields}</button>}
      <div className="upload-actions"><button className="upload-button" disabled={busy || !requirementsCurrent}>{busy ? t.saving : t.save}</button><button type="button" className="upload-text-button" onClick={() => { setValues({}); setRequirements(null); setChoices({}); setPhase('consent'); }} disabled={busy}>{t.back}</button><button type="button" className="upload-text-button" onClick={close} disabled={busy}>{t.cancel}</button></div>
    </form>}
  </section>;
}
