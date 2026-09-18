import { useState } from 'react';
import { cognito, contributorSession, phoneNumber } from './auth.js';
import { copy } from './copy.js';

const API = import.meta.env?.VITE_API_URL ?? '';
const labels = {
  en: {
    title: 'Sign up',
    intro: 'Sign up with the phone number you used on your contributor form.',
    phone: 'Phone number', password: 'Choose a password', start: 'Sign up',
    code: 'SMS verification code', confirm: 'Verify and continue', resend: 'Resend code',
    back: 'Back to sign in', working: 'Please wait…', sent: 'A verification code was sent to your phone.',
    resume: 'Finish phone verification',
    resumeHint: 'Enter your phone number to request a new verification code.',
    send: 'Send verification code', restart: 'Back to sign up',
    exists: 'This phone number already has an account. Sign in, or choose Finish phone verification below.',
    error: 'Account setup could not finish. Check the details and try again.',
  },
  ko: {
    title: '회원가입', intro: '참여 계약서에 적은 전화번호로 가입해 주세요.',
    phone: '전화번호', password: '비밀번호 설정', start: '회원가입',
    code: '문자 인증번호', confirm: '인증하고 계속', resend: '인증번호 다시 받기',
    back: '로그인으로 돌아가기', working: '잠시만 기다려 주세요…', sent: '휴대전화로 인증번호를 보냈습니다.',
    resume: '전화번호 인증 이어하기',
    resumeHint: '가입할 때 사용한 전화번호를 입력해 주세요. 인증번호를 다시 보내드릴게요.',
    send: '인증번호 받기', restart: '회원가입으로 돌아가기',
    exists: '이미 계정이 있는 번호입니다. 로그인하거나 아래에서 전화번호 인증을 완료해 주세요.',
    error: '가입을 완료하지 못했어요. 입력 내용을 확인하고 다시 시도해 주세요.',
  },
};

export async function linkFormContract(signal) {
  const access = await contributorSession.accessToken();
  const response = await fetch(`${API}/api/form-contracts/activate`, {
    method: 'POST', credentials: 'omit', signal, headers: { Authorization: `Bearer ${access}` },
  });
  if (!response.ok) {
    const data = await response.json();
    throw Error(data.detail || 'contract_setup_pending');
  }
  return response.json();
}

export default function Activate({ locale, back }) {
  const t = labels[locale], shared = copy[locale];
  const [phone, setPhone] = useState(''), [password, setPassword] = useState(''), [code, setCode] = useState('');
  const [step, setStep] = useState('signup'), [busy, setBusy] = useState(false);
  const [error, setError] = useState(''), [notice, setNotice] = useState('');
  const failure = e => setError(e.message === 'UsernameExistsException' ? t.exists : shared.errors[e.message] || t.error);
  const username = () => {
    const result = phoneNumber(phone);
    if (!/^\+8210[0-9]{8}$/.test(result)) throw Error('phone_format');
    return result;
  };
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      if (step === 'signup') {
        await cognito('SignUp', {
          Username: username(), Password: password,
          UserAttributes: [{ Name: 'phone_number', Value: username() }, { Name: 'custom:routing_version', Value: 'kr-2026-v1' }],
          ClientMetadata: { area_code: 'korea666' },
        });
        setPassword(''); setStep('verify'); setNotice(t.sent);
      } else if (step === 'resume') {
        await cognito('ResendConfirmationCode', { Username: username() });
        setStep('verify'); setNotice(t.sent);
      } else {
        await cognito('ConfirmSignUp', { Username: username(), ConfirmationCode: code });
        setCode(''); back(true);
      }
    } catch (e) { failure(e); } finally { setBusy(false); }
  };
  const resend = async () => {
    setBusy(true); setError(''); setNotice('');
    try { await cognito('ResendConfirmationCode', { Username: username() }); setNotice(t.sent); }
    catch (e) { failure(e); } finally { setBusy(false); }
  };
  const changeStep = next => { setStep(next); setPassword(''); setCode(''); setError(''); setNotice(''); };
  return <section className="upload-signin">
    <h2>{t.title}</h2><p>{step === 'resume' ? t.resumeHint : t.intro}</p>
    <form onSubmit={submit}>
      <label>{t.phone}<input type="tel" autoComplete="username" inputMode="tel" required maxLength={24} placeholder="+82 10 1234 5678" value={phone} onChange={e => setPhone(e.target.value)} disabled={busy || step === 'verify'} /></label>
      {step === 'signup' && <label>{t.password}<input type="password" autoComplete="new-password" minLength={12} maxLength={256} required value={password} onChange={e => setPassword(e.target.value)} disabled={busy} /><span>{shared.passwordHint}</span></label>}
      {step === 'verify' && <label>{t.code}<input autoComplete="one-time-code" inputMode="numeric" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={e => setCode(e.target.value)} disabled={busy} /></label>}
      {error && <p className="upload-error" role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
      <button className="upload-button" disabled={busy}>{busy ? t.working : step === 'signup' ? t.start : step === 'resume' ? t.send : t.confirm}</button>
      {step === 'verify' && <button type="button" className="upload-text-button" onClick={resend} disabled={busy}>{t.resend}</button>}
      {step === 'signup' && <button type="button" className="upload-text-button" onClick={() => changeStep('resume')} disabled={busy}>{t.resume}</button>}
      {step !== 'signup' && <button type="button" className="upload-text-button" onClick={() => changeStep('signup')} disabled={busy}>{t.restart}</button>}
      <button type="button" className="upload-text-button" onClick={() => back(false)} disabled={busy}>{t.back}</button>
    </form>
  </section>;
}
