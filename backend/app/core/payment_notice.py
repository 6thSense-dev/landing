"""Versioned, bilingual notice for the Korean individual payment-details page.

Freeze the notice and separate consent choices with the masked recipient attempt.
Do not put raw banking/contact details in the receipt.
"""
import hashlib
import json

VERSION = "KR-PAYMENT-WEB-2026-09-18-1"
NOTICE = {
    "version": VERSION,
    "locales": {
        "en": {
            "title": "How we use your payment details",
            "paragraphs": [
                "6thSense AI, Inc. uses your legal name, birth date, email, phone number, address, bank and account number to set up your payment recipient, verify ownership, pay your earnings and resolve transfer issues. Contact: alex@6thsense.dev.",
                "When you continue and submit, these details are sent over encrypted connections to 6thSense in the United States and Wise US Inc. (United States; privacy@wise.com). For Korean payouts, necessary identity, contact, account and transfer details are provided to PayGate Co., Ltd. (South Korea; support@paygate.net) and your selected receiving bank for verification and settlement.",
                "6thSense forwards full account details to Wise without storing them in its database or the contractor Sheet. Authorized payout staff see your name, bank, account ending and payment status. Minimal settlement records are kept for five years after the later of the end of the relationship or final settlement; other unnecessary active payment information is deleted within 30 days of that point. Wise and receiving financial institutions retain their own records under applicable financial laws; Wise generally retains records for 5–10 years after account closure under its privacy notice, which also describes its international processing.",
                "You may refuse or withdraw consent and request access, correction or deletion at alex@6thsense.dev. This may delay this payment method; contact us to discuss an alternative. It does not cancel earned payment or prevent uploading. Never enter a banking password, PIN, resident registration number or verification code here.",
            ],
            "choices": {
                "collects_details": "I agree to collection and use of my payment details as described above.",
                "shares_details": "I agree to sharing the necessary details with Wise, PayGate and my receiving bank for payment.",
                "international_transfer": "I agree to the described transfer of my payment details to 6thSense and Wise in the United States.",
                "owns_account": "This is my own bank account, and the details I submit are accurate.",
            },
        },
        "ko": {
            "title": "지급정보 이용 안내",
            "paragraphs": [
                "6thSense AI, Inc.는 지급 대상 등록, 예금주 확인, 보수 지급 및 송금 오류 해결을 위해 법적 성명, 생년월일, 이메일, 전화번호, 주소, 은행 및 계좌번호를 이용합니다. 문의: alex@6thsense.dev.",
                "계속 진행하고 제출하면 입력한 정보가 암호화 통신으로 미국의 6thSense와 Wise US Inc.(미국, privacy@wise.com)에 전송됩니다. 한국 지급 시 필요한 본인·연락처·계좌·송금 정보는 확인 및 입금을 위해 PayGate Co., Ltd.(대한민국, support@paygate.net)와 본인이 선택한 수취 은행에 제공됩니다.",
                "6thSense는 전체 계좌정보를 Wise에 전달하며 회사 데이터베이스나 계약자 Sheet에 저장하지 않습니다. 권한 있는 지급 담당자는 성명, 은행, 계좌 끝자리 및 지급 상태를 확인합니다. 최소 정산 증빙은 계약 종료일과 최종 정산일 중 늦은 날부터 5년간 보관하며, 그 밖에 불필요해진 활동 지급정보는 그 시점부터 30일 이내 삭제합니다. Wise와 수취 금융기관은 금융 법령에 따라 별도로 보관합니다. Wise는 개인정보 안내에 따라 통상 계정 종료 후 5~10년간 보관하며, 자체 국제 처리에 관한 내용도 해당 안내에서 확인할 수 있습니다.",
                "동의를 거부·철회하거나 열람·정정·삭제를 요청하려면 alex@6thsense.dev로 연락해 주세요. 이 지급 방식은 지연될 수 있으며 대체 방식을 협의할 수 있습니다. 이미 발생한 보수 청구권과 업로드는 유지됩니다. 은행 비밀번호, PIN, 주민등록번호 또는 인증번호는 입력하지 마세요.",
            ],
            "choices": {
                "collects_details": "위 안내에 따른 지급정보 수집·이용에 동의합니다.",
                "shares_details": "지급을 위한 Wise, PayGate 및 수취 은행에 대한 필요 정보 제공에 동의합니다.",
                "international_transfer": "위 안내에 따른 미국 6thSense 및 Wise로의 지급정보 국외 이전에 동의합니다.",
                "owns_account": "본인 명의 계좌이며 제출 정보가 정확함을 확인합니다.",
            },
        },
    },
    "privacy_url": "https://wise.com/gb/legal/privacy-notice-business-en",
    "guide_url": "https://wise.com/help/articles/2932331/guide-to-krw-transfers",
}
DIGEST = hashlib.sha256(json.dumps(NOTICE, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def public_notice():
    return {**NOTICE, "sha256": DIGEST}
