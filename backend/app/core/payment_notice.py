"""Versioned payment consent for the private contributor bank register."""
import hashlib
import json

VERSION = "KR-PAYMENT-SHEET-2026-09-19-1"
NOTICE = {
    "version": VERSION,
    "locales": {
        "en": {
            "title": "How we store your payment details",
            "paragraphs": [
                "6thSense AI, Inc. collects your account holder name, bank and account number to prepare payment of your earnings and resolve payment questions. These are linked to your contributor ID and consent receipt. Contact: alex@6thsense.dev.",
                "When you submit, your details are sent over encrypted connections through 6thSense’s backend hosted by Railway and stored in a private Google spreadsheet managed by 6thSense. Authorized staff with access to that workbook can read the full account number. The website database keeps only a masked account receipt. This submission does not register a recipient with Wise or send a payment.",
                "Your details are transferred electronically to 6thSense in the United States and processed using Railway and Google’s cloud services, including processing outside South Korea. They are used to maintain the payment register and prepare your earnings payments. Any additional payment-provider registration will be explained separately.",
                "Minimal settlement records are kept for five years after the later of the end of the relationship or final settlement. Other unnecessary active payment information is deleted within 30 days of that point. You may refuse or withdraw consent and request access, correction or deletion at alex@6thsense.dev. Contact us to discuss an alternative payment method. Refusal does not cancel earned payment or prevent uploading. Never enter a banking password, PIN, resident registration number or verification code.",
            ],
            "choices": {
                "collects_details": "I agree to collection and use of my bank details for payment preparation.",
                "shares_details": "I agree to storing my full bank details in 6thSense’s private Google spreadsheet for authorized staff to review.",
                "international_transfer": "I agree to the described overseas processing through 6thSense, Railway and Google.",
                "owns_account": "This is my own bank account, and the details are accurate.",
            },
        },
        "ko": {
            "title": "지급정보 저장 및 이용 안내",
            "paragraphs": [
                "6thSense AI, Inc.는 보수 지급 준비와 지급 관련 문의 처리를 위해 예금주명, 은행명, 계좌번호를 수집합니다. 이 정보는 참여자 ID 및 동의 기록과 연결됩니다. 문의: alex@6thsense.dev.",
                "제출한 정보는 암호화 통신으로 Railway에 호스팅된 6thSense 서버를 거쳐 회사가 관리하는 비공개 Google 스프레드시트에 저장됩니다. 해당 문서에 접근 권한이 있는 담당자는 전체 계좌번호를 확인할 수 있습니다. 웹사이트 데이터베이스에는 계좌 끝자리 등 접수 내역만 저장됩니다. 이 제출만으로 Wise에 수취인이 등록되거나 송금이 실행되지는 않습니다.",
                "제출 시 정보가 미국의 6thSense로 전송되며 Railway와 Google의 클라우드 서비스를 통해 한국 외 지역에서도 처리됩니다. 지급정보 관리와 보수 지급 준비에 이용하며, 추가로 송금 서비스에 등록할 필요가 있으면 별도로 안내합니다.",
                "최소 정산 증빙은 계약 종료일과 최종 정산일 중 늦은 날부터 5년간 보관합니다. 그 밖에 불필요해진 지급정보는 해당 시점부터 30일 이내 삭제합니다. 동의를 거부·철회하거나 열람·정정·삭제를 요청하려면 alex@6thsense.dev로 연락해 주세요. 대체 지급 방식을 협의할 수 있으며, 동의 거부로 이미 발생한 보수나 업로드 권한이 없어지지 않습니다. 은행 비밀번호, PIN, 주민등록번호, 인증번호는 입력하지 마세요.",
            ],
            "choices": {
                "collects_details": "보수 지급 준비를 위한 계좌정보 수집·이용에 동의합니다.",
                "shares_details": "전체 계좌정보를 6thSense의 비공개 Google 스프레드시트에 저장하고 권한 있는 담당자가 확인하는 데 동의합니다.",
                "international_transfer": "위 안내에 따른 6thSense, Railway 및 Google을 통한 국외 처리에 동의합니다.",
                "owns_account": "본인 명의 계좌이며 입력한 정보가 정확합니다.",
            },
        },
    },
}
DIGEST = hashlib.sha256(json.dumps(NOTICE, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def public_notice():
    return {**NOTICE, "sha256": DIGEST}
