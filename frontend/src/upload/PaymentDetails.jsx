import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Landmark } from 'lucide-react';
import { koreanBanks, paymentApi, paymentCopy } from './payment.js';

export default function PaymentDetails({ locale }) {
  const t = paymentCopy[locale];
  const [setup, setSetup] = useState(null), [phase, setPhase] = useState('closed');
  const [choices, setChoices] = useState({}), [requirements, setRequirements] = useState(null);
  const [values, setValues] = useState({}), [busy, setBusy] = useState(false);
  const [bankOption, setBankOption] = useState(''), [customBank, setCustomBank] = useState('');
  const [error, setError] = useState(''), [invalid, setInvalid] = useState([]), [uncertain, setUncertain] = useState(false);
  const lifetime = useRef(null), locked = useRef(false), operation = useRef(crypto.randomUUID());
  const notice = setup?.notice, localized = notice?.locales[locale], bank = setup?.bank;
  const accepted = localized && Object.keys(localized.choices).every(key => choices[key]);
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

  const clear = () => { setValues({}); setBankOption(''); setCustomBank(''); setRequirements(null); setChoices({}); setPhase('closed'); setInvalid([]); setUncertain(false); };
  const changeValue = (key, value) => {
    setValues(current => ({ ...current, [key]: value }));
    setInvalid(current => current.filter(invalidKey => invalidKey !== key));
  };
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
    if (result.bank) clear();
    else if (setup?.notice?.sha256 !== result.notice?.sha256) {
      // Notice changes require fresh consent but do not erase typed details.
      setChoices({}); setPhase(phase === 'closed' ? 'closed' : 'consent');
    }
  });
  const begin = e => {
    e.preventDefault();
    if (accepted) run(async () => {
      const result = await paymentApi('/web/requirements', { ...consentBody(), values: {} }, lifetime.current.signal);
      setRequirements(result); setPhase('fields');
    });
  };
  const close = () => { clear(); setError(''); };
  const submit = e => {
    e.preventDefault();
    if (!accepted || !requirements) return;
    run(async () => {
      try {
        const result = await paymentApi('/web', { ...consentBody(), operation_id: operation.current, values }, lifetime.current.signal);
        if (!['sheet_saved', 'ready', 'needs_review', 'needs_reconciliation', 'submitting'].includes(result.status)) throw Error('payment_unavailable');
        // Only an acknowledged durable receipt clears the in-memory input.
        setSetup(previous => ({ ...previous, bank: result })); clear();
      } catch (failure) {
        if (!failure.status || failure.status >= 500) setUncertain(true);
        throw failure;
      }
    });
  };

  return <section className="upload-payment" id="payment-details" aria-labelledby="payment-title">
    <div className="upload-payment-heading"><Landmark size={22} aria-hidden="true" /><div><h2 id="payment-title">{t.title}</h2><p>{t.intro}</p></div>
      {setup && !bank && notice && phase === 'closed' && <button className="upload-button upload-button--quiet" onClick={() => { operation.current = crypto.randomUUID(); setPhase('consent'); }}>{t.add}</button>}
    </div>
    {!setup && !error && <p role="status">{t.loading}</p>}
    {error && <p className="upload-error" role="alert">{error}</p>}
    {uncertain && !bank && <div className="upload-payment-status" role="status"><strong>{t.checking}</strong><p>{t.checkingHint}</p></div>}
    {bank && <div className="upload-payment-status" role="status">
      <strong>{['ready', 'sheet_saved'].includes(bank.status) ? <><CheckCircle2 size={18} />{bank.status === 'sheet_saved' ? t.saved : t.ready}</> : t.pending}</strong>
      <p className="upload-payment-mask">{[bank.accountHolderName, bank.bankLabel, bank.maskedAccount].filter(Boolean).join(' · ')}</p>
      <p>{bank.status === 'sheet_saved' ? t.reviewHint : bank.status === 'ready' ? t.readyHint : t.legacyHint}</p>
      {bank.submittedAt && <p>{t.submitted}: {new Date(bank.submittedAt).toLocaleString(locale === 'ko' ? 'ko-KR' : 'en-US')}</p>}
      {bank.submissionId && <p>{t.reference}: {bank.submissionId}</p>}
      <p>{t.change}</p>
    </div>}
    {setup && !notice && !bank && <p>{t.unsupported}</p>}
    {(uncertain || bank || error) && <button className="upload-text-button" disabled={busy} onClick={refresh}>{t.refresh}</button>}
    {phase === 'consent' && localized && !bank && <form onSubmit={begin} className="upload-payment-form">
      <div className="upload-payment-notice"><h3>{localized.title}</h3>{localized.paragraphs.map(p => <p key={p}>{p}</p>)}</div>
      <fieldset disabled={busy} className="upload-payment-consents"><legend>{localized.title}</legend>{Object.entries(localized.choices).map(([key, label]) => <label key={key}><input type="checkbox" required checked={!!choices[key]} onChange={e => setChoices({ ...choices, [key]: e.target.checked })} /><span>{label}</span></label>)}</fieldset>
      <div className="upload-actions"><button className="upload-button" disabled={!accepted || busy}>{busy ? t.loading : t.continue}</button><button type="button" className="upload-text-button" onClick={close} disabled={busy}>{t.cancel}</button></div>
    </form>}
    {phase === 'fields' && requirements && !bank && <form className="upload-payment-form" onSubmit={submit} autoComplete="off">
      <p>{t.hint}</p>
      <fieldset disabled={busy} className="upload-payment-fields"><legend>{t.title}</legend>{requirements.fields.map(field => {
        const id = `bank-${field.key}`, isInvalid = invalid.includes(field.key);
        return <div key={field.key}><label htmlFor={id}>{t.fields[field.key] || field.key}</label>
          {field.key === 'bankName' ? <>
            <select id={id} name="bankSelection" required={field.required} value={bankOption}
              aria-invalid={isInvalid} aria-describedby={isInvalid ? `${id}-error` : undefined}
              onChange={e => { setBankOption(e.target.value); changeValue('bankName', e.target.value === 'other' ? customBank : e.target.value); }}>
              <option value="" disabled>{t.selectBank}</option>
              {koreanBanks.map(name => <option key={name} value={name}>{name}</option>)}
              <option value="other">{t.otherBank}</option>
            </select>
            {bankOption === 'other' && <div className="upload-payment-custom-bank">
              <label htmlFor={`${id}-other`}>{t.customBank}</label>
              <input id={`${id}-other`} name="bankName" type="text" required={field.required} value={customBank}
                onChange={e => { setCustomBank(e.target.value); changeValue('bankName', e.target.value); }}
                aria-invalid={isInvalid} aria-describedby={isInvalid ? `${id}-error` : undefined}
                minLength={field.minLength || undefined} maxLength={field.maxLength || 100} autoComplete="off" spellCheck={false} />
            </div>}
          </> : <input id={id} name={field.key} required={field.required} value={values[field.key] || ''} onChange={e => changeValue(field.key, e.target.value)}
            aria-invalid={isInvalid} aria-describedby={isInvalid ? `${id}-error` : undefined}
            type="text" inputMode={field.key === 'accountNumber' ? 'numeric' : undefined} minLength={field.minLength || undefined} maxLength={field.maxLength || 100} autoComplete="off" spellCheck={false} />}
          {isInvalid && <span className="upload-payment-field-error" id={`${id}-error`}>{t.fieldError}</span>}
        </div>;
      })}</fieldset>
      <div className="upload-actions"><button className="upload-button" disabled={busy}>{busy ? t.saving : t.save}</button><button type="button" className="upload-text-button" onClick={() => { setChoices({}); setPhase('consent'); }} disabled={busy}>{t.back}</button><button type="button" className="upload-text-button" onClick={close} disabled={busy}>{t.cancel}</button></div>
    </form>}
  </section>;
}
