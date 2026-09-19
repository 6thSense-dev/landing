import { contributorSession } from './auth.js';

const API = import.meta.env.VITE_API_URL ?? '';

// A user may retry a save: the spreadsheet deduplicates by authenticated contributor.
// Refresh recovers the receipt if the previous response was lost.
export async function paymentApi(path, body, signal) {
  const timeout = AbortSignal.timeout(25000);
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
    title: 'Payment details', intro: 'Register your own bank account for your earnings. You can keep uploading while staff review it.',
    add: 'Add bank details', loading: 'Loading payment details…', continue: 'Continue to bank details',
    cancel: 'Cancel', save: 'Save bank details', saving: 'Saving…', refresh: 'Check saved status',
    optional: 'optional', back: 'Back to consent',
    hint: 'Enter the account holder name as it appears at your bank, your bank name and your Korean account number.',
    pending: 'Details received — awaiting review', ready: 'Payment account verified', saved: 'Bank details saved',
    checking: 'Save not confirmed', checkingHint: 'We could not confirm the save. Your entries are still here. Check the saved status or submit again; retrying will not create a duplicate.',
    legacyHint: 'Staff need to review your earlier submission. Contact alex@6thsense.dev.',
    reviewHint: 'Your details are saved in 6thSense’s private payment spreadsheet for staff review. Saving does not send a payment.',
    readyHint: 'This account is linked for payment. Footage review and the agreed payment schedule still apply.',
    change: 'Need a correction? Contact alex@6thsense.dev without including your account number.',
    unavailable: 'We could not confirm your payment details. Please try again. Your entries have been kept on this page.',
    contract: 'Complete your contributor contract before adding payment details.',
    unsupported: 'Online payment setup is not available for your region yet. Contact alex@6thsense.dev.',
    noticeChanged: 'The payment notice has changed. Check the saved status, then review the new notice before submitting. Your entries will be kept.',
    invalid: 'Please check the highlighted details and submit again.', fieldError: 'Please check this value.',
    reference: 'Submission', submitted: 'Saved at',
    fields: { accountHolderName: 'Account holder name', bankName: 'Bank name', accountNumber: 'Account number' },
  },
  ko: {
    title: '지급정보', intro: '보수를 받을 본인 명의 계좌를 등록해 주세요. 담당자 확인 중에도 업로드할 수 있어요.',
    add: '계좌 등록하기', loading: '지급정보를 불러오는 중…', continue: '계좌정보 입력하기',
    cancel: '취소', save: '계좌정보 저장하기', saving: '저장 중…', refresh: '저장 상태 확인',
    optional: '선택', back: '동의 화면으로',
    hint: '은행에 등록된 예금주명, 은행명, 본인 명의 한국 계좌번호를 입력해 주세요.',
    pending: '접수 완료 · 확인 대기', ready: '지급 계좌 확인 완료', saved: '계좌정보 저장 완료',
    checking: '저장 여부를 확인하지 못했어요', checkingHint: '입력 내용은 이 화면에 남아 있어요. 저장 상태를 확인하거나 다시 제출해 주세요. 다시 제출해도 중복으로 등록되지 않아요.',
    legacyHint: '이전 제출 건에 대한 담당자 확인이 필요해요. alex@6thsense.dev로 문의해 주세요.',
    reviewHint: '6thSense의 비공개 지급정보 스프레드시트에 저장되었어요. 담당자가 확인할 예정이며, 저장만으로 송금되지는 않아요.',
    readyHint: '지급용 계좌가 연결되었어요. 촬영물 검토와 계약상 지급 일정에 따라 보수가 지급됩니다.',
    change: '수정이 필요하면 계좌번호를 적지 말고 alex@6thsense.dev로 문의해 주세요.',
    unavailable: '지급정보를 확인하지 못했어요. 잠시 후 다시 시도해 주세요. 입력 내용은 이 화면에 남아 있어요.',
    contract: '참여 계약을 완료한 후 지급정보를 등록해 주세요.',
    unsupported: '아직 이 지역의 온라인 지급정보 등록을 지원하지 않습니다. alex@6thsense.dev로 문의해 주세요.',
    noticeChanged: '지급정보 안내가 변경되었어요. 저장 상태를 확인한 후 새 안내에 동의해 주세요. 입력 내용은 유지돼요.',
    invalid: '표시된 정보를 확인하고 다시 제출해 주세요.', fieldError: '입력한 내용을 확인해 주세요.',
    reference: '접수번호', submitted: '저장 시각',
    fields: { accountHolderName: '예금주명', bankName: '은행명', accountNumber: '계좌번호' },
  },
};
