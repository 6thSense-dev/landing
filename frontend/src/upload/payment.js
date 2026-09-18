import { contributorSession } from './auth.js';

const API = import.meta.env.VITE_API_URL ?? '';

// Banking writes are never retried after network errors or ambiguous responses.
// The server durably deduplicates recipient creation and owns reconciliation.
export async function paymentApi(path, body, signal) {
  const timeout = AbortSignal.timeout(65000);
  const requestSignal = signal ? AbortSignal.any([signal, timeout]) : timeout;
  for (let attempt = 0; attempt < 2; attempt++) {
    const access = await contributorSession.accessToken(attempt > 0);
    const response = await fetch(`${API}/api/contributor/bank${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'omit', cache: 'no-store', signal: requestSignal,
      headers: { Authorization: `Bearer ${access}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (response.status === 401 && attempt === 0) continue;
    const data = await response.json();
    if (!response.ok) {
      const error = Error(typeof data.detail === 'string' ? data.detail : data.detail?.code || 'payment_unavailable');
      error.fields = data.detail?.fields || [];
      error.status = response.status;
      throw error;
    }
    return data;
  }
}

export const paymentCopy = {
  en: {
    title: 'Payment details', intro: 'Add your own bank account here to receive payment. You can keep uploading while we check it.',
    add: 'Add bank details', loading: 'Loading payment details…', continue: 'Continue to bank details',
    cancel: 'Cancel', save: 'Submit payment details', saving: 'Submitting…', refresh: 'Refresh status',
    optional: 'optional', choose: 'Select…', back: 'Back to consent', retryFields: 'Reload bank fields',
    hint: 'Use your legal name in Latin letters and your own Korean bank account. Virtual accounts are not supported.',
    privacy: 'Wise privacy notice', guide: 'KRW payment guide',
    pending: 'Details received — awaiting verification', ready: 'Payment account verified',
    checking: 'Checking your submission', checkingHint: 'We are confirming the result. You can keep uploading. Refresh the status before submitting again.',
    reviewHint: '6thSense will verify your recipient before payment. You do not need to email your bank details.',
    readyHint: 'This account is linked for payment. Footage review and the agreed payment schedule still apply.',
    partner: 'PayGate may contact you separately for bank verification when a payment is sent.',
    change: 'Need to correct something? Contact alex@6thsense.dev without including your account number.',
    unavailable: 'Payment setup is temporarily unavailable. You can keep uploading and try again later.',
    contract: 'Complete your contributor contract before adding payment details.',
    unsupported: 'Online payment setup is not available for your region yet. Contact alex@6thsense.dev.',
    noticeChanged: 'The payment notice has changed. Refresh this page and review it again.',
    invalid: 'Please check the highlighted details and submit again.', fieldError: 'Please check this value.',
    fields: { accountHolderName: 'Legal name in Latin letters', email: 'Email', phoneNumber: 'Phone number', dateOfBirth: 'Date of birth', bankCode: 'Bank', accountNumber: 'Account number', ifscCode: 'IFSC code', 'address.country': 'Country of residence', 'address.city': 'City', 'address.firstLine': 'Street address', 'address.state': 'State / province', 'address.postCode': 'Postal code' },
  },
  ko: {
    title: '지급정보', intro: '보수를 받을 본인 명의 계좌를 등록해 주세요. 확인을 기다리는 동안에도 업로드할 수 있어요.',
    add: '계좌 등록하기', loading: '지급정보를 불러오는 중…', continue: '계좌정보 입력하기',
    cancel: '취소', save: '지급정보 제출하기', saving: '제출 중…', refresh: '상태 새로고침',
    optional: '선택', choose: '선택해 주세요', back: '동의 화면으로', retryFields: '계좌 입력 항목 다시 불러오기',
    hint: '영문 법적 성명과 본인 명의 한국 은행 계좌를 입력해 주세요. 가상계좌는 사용할 수 없어요.',
    privacy: 'Wise 개인정보 안내', guide: '원화 수취 안내',
    pending: '접수 완료 · 확인 대기', ready: '지급 계좌 확인 완료',
    checking: '제출 결과 확인 중', checkingHint: '등록 결과를 확인하고 있어요. 업로드는 계속할 수 있으며, 다시 제출하기 전에 상태를 새로고침해 주세요.',
    reviewHint: '6thSense가 지급 전에 수취인을 확인합니다. 계좌정보를 이메일로 다시 보내지 않아도 돼요.',
    readyHint: '지급용 계좌가 연결되었어요. 촬영물 검토와 계약상 지급 일정에 따라 보수가 지급됩니다.',
    partner: '송금 시 PayGate에서 별도로 본인 확인을 요청할 수 있어요.',
    change: '수정이 필요하면 계좌번호를 적지 말고 alex@6thsense.dev로 문의해 주세요.',
    unavailable: '지금은 지급정보를 불러올 수 없어요. 업로드를 계속하고 잠시 후 다시 시도해 주세요.',
    contract: '참여 계약을 완료한 후 지급정보를 등록해 주세요.',
    unsupported: '아직 이 지역의 온라인 지급정보 등록을 지원하지 않습니다. alex@6thsense.dev로 문의해 주세요.',
    noticeChanged: '지급정보 안내가 변경되었어요. 페이지를 새로고침하고 다시 확인해 주세요.',
    invalid: '표시된 정보를 확인하고 다시 제출해 주세요.', fieldError: '입력한 내용을 확인해 주세요.',
    fields: { accountHolderName: '영문 법적 성명', email: '이메일', phoneNumber: '전화번호', dateOfBirth: '생년월일', bankCode: '은행', accountNumber: '계좌번호', ifscCode: 'IFSC 코드', 'address.country': '거주 국가', 'address.city': '도시', 'address.firstLine': '도로명 주소', 'address.state': '시·도', 'address.postCode': '우편번호' },
  },
};
