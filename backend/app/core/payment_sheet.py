"""Authenticated, idempotent bank-instruction storage in the contractor workbook.

Full account numbers cross this adapter only in memory. The Apps Script bridge
serializes writes and keeps one receipt per contributor, so a lost response can
be recovered by lookup or by repeating the same submission without another row.
"""
from datetime import datetime
import hashlib
import hmac
import json
import os
import re
import time
import urllib.request
from urllib.parse import urlparse
from uuid import UUID


class PaymentSheetError(RuntimeError):
    pass


FIELDS = (
    {"key": "accountHolderName", "required": True, "minLength": 1, "maxLength": 100},
    {"key": "bankName", "required": True, "minLength": 1, "maxLength": 100},
    {"key": "accountNumber", "required": True, "minLength": 6, "maxLength": 50},
)


def requirements():
    return {"country": "KR", "currency": "KRW", "fields": list(FIELDS)}


def clean_values(values):
    allowed = {field["key"] for field in FIELDS}
    clean, issues = {}, []
    if set(values) - allowed:
        issues.append("unsupported_field")
    for field in FIELDS:
        key = field["key"]
        value = values.get(key, "").strip()
        if not value or len(value) > field["maxLength"] or any(ord(c) < 32 for c in value):
            issues.append(key)
        clean[key] = value
    account = clean["accountNumber"]
    if not re.fullmatch(r"[0-9 -]+", account):
        issues.append("accountNumber")
    else:
        clean["accountNumber"] = re.sub(r"[ -]", "", account)
        if not 6 <= len(clean["accountNumber"]) <= 34:
            issues.append("accountNumber")
    return clean, sorted(set(issues))


class PaymentSheetClient:
    def __init__(self):
        self.url = os.getenv("CONTRIBUTOR_PAYMENT_SHEET_URL", "")
        self.secret = os.getenv("CONTRIBUTOR_PAYMENT_SHEET_SECRET", "")
        parsed = urlparse(self.url)
        if (parsed.scheme != "https" or parsed.netloc != "script.google.com"
                or not re.fullmatch(r"/macros/s/[A-Za-z0-9_-]+/exec", parsed.path)
                or parsed.query or parsed.fragment or len(self.secret) < 32):
            raise PaymentSheetError("payment_sheet_unavailable")

    def request(self, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        stamp = str(int(time.time()))
        signature = hmac.new(self.secret.encode(), (stamp + "." + body).encode(), hashlib.sha256).hexdigest()
        envelope = json.dumps({"timestamp": stamp, "payload": body, "signature": signature}).encode()
        request = urllib.request.Request(self.url, data=envelope, method="POST",
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if urlparse(response.url).hostname not in {"script.google.com", "script.googleusercontent.com"}:
                    raise ValueError()
                raw = response.read(32769)
                if len(raw) > 32768:
                    raise ValueError()
                result = json.loads(raw)
            if not isinstance(result, dict) or result.get("ok") is not True:
                raise ValueError()
            return result
        except Exception:
            # Provider bodies can contain personal data. Never copy them into
            # logs, exceptions, HTTP responses, or a database error column.
            raise PaymentSheetError("payment_sheet_unavailable") from None

    def lookup(self, wearer_id):
        return self.receipt(self.request({"action": "lookup", "contributorId": wearer_id}), wearer_id)

    def delete(self, wearer_id):
        result = self.request({"action": "delete", "contributorId": wearer_id})
        if result.get("deleted") is not True or result.get("contributorId") != wearer_id:
            raise PaymentSheetError("payment_sheet_unavailable")

    def submit(self, wearer_id, name, operation_id, values, consent):
        result = self.request({"action": "submit", "contributorId": wearer_id,
                               "contributorName": name, "operationId": operation_id,
                               "values": values, "consent": consent})
        receipt = self.receipt(result, wearer_id)
        if receipt is None:
            raise PaymentSheetError("payment_sheet_unavailable")
        return receipt

    @staticmethod
    def receipt(result, wearer_id):
        bank = result.get("bank")
        if bank is None:
            return None
        try:
            if (bank["contributorId"] != wearer_id or bank["status"] != "sheet_saved"
                    or not re.fullmatch(r"•••• [0-9]{4}", bank["maskedAccount"])):
                raise ValueError()
            UUID(bank["submissionId"])
            for key in ("accountHolderName", "bankLabel", "submittedAt"):
                if not isinstance(bank[key], str) or not bank[key] or len(bank[key]) > 100:
                    raise ValueError()
            if datetime.fromisoformat(bank["submittedAt"].replace("Z", "+00:00")).tzinfo is None:
                raise ValueError()
            # Explicit allowlist: a misconfigured bridge must not send raw
            # numbers or other spreadsheet columns back to the browser.
            return {key: bank[key] for key in ("status", "submissionId", "accountHolderName",
                                               "bankLabel", "maskedAccount", "submittedAt")}
        except (KeyError, TypeError, ValueError):
            raise PaymentSheetError("payment_sheet_unavailable") from None
