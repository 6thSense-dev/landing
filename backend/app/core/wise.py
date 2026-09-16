"""Wise 2026Q3 adapter. Fixed KRW receive amount; no token or bank data in logs."""

import json
import os
import urllib.request
import urllib.error


class WiseError(RuntimeError):
    pass


class WiseClient:
    def __init__(self):
        self.token = os.getenv("WISE_API_TOKEN", "")
        self.profile = os.getenv("WISE_PROFILE_ID", "")
        self.environment = os.getenv("WISE_ENVIRONMENT", "sandbox")
        if not self.token or not self.profile.isdigit():
            raise WiseError("Wise connection is not configured.")
        if self.environment not in ("sandbox", "production"):
            raise WiseError("Invalid Wise environment.")
        self.base = (
            "https://api.wise.com"
            if self.environment == "production"
            else "https://api.wise-sandbox.com"
        ) + "/2026Q3"

    def request(self, method, path, body=None, correlation=None):
        headers = {
            "Authorization": "Bearer " + self.token,
            "Content-Type": "application/json",
        }
        if correlation:
            headers["X-External-Correlation-Id"] = correlation
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            raise WiseError(
                f"Wise returned HTTP {e.code}; reconcile the transfer before retrying."
            ) from None
        except (OSError, ValueError):
            raise WiseError(
                "Wise request outcome is unknown; retry with the same transfer identity."
            ) from None

    def recipient(self, recipient_id):
        return self.request("GET", f"/accounts/{int(recipient_id)}")

    def quote(self, p):
        return self.request(
            "POST",
            f"/profiles/{self.profile}/quotes",
            {
                "sourceCurrency": p.source_currency,
                "targetCurrency": "KRW",
                "targetAmount": p.amount_krw,
                "targetAccount": int(p.recipient_id),
                "preferredPayIn": "BALANCE",
            },
            p.id,
        )

    def transfer(self, p):
        return self.request(
            "POST",
            "/transfers",
            {
                "targetAccount": int(p.recipient_id),
                "quoteUuid": p.quote_id,
                "customerTransactionId": p.id,
                "details": {"reference": "6thSense footage " + p.id[:8]},
            },
            p.id,
        )

    def status(self, p):
        return self.request("GET", f"/transfers/{int(p.transfer_id)}", correlation=p.id)

    def fund(self, p):
        return self.request(
            "POST",
            f"/profiles/{self.profile}/transfers/{int(p.transfer_id)}/payments",
            {"type": "BALANCE"},
            p.id,
        )


def recipient_confirmation_required(info):
    """Do not link a recipient while Wise requires explicit customer acceptance."""
    def pending(value):
        if isinstance(value, dict):
            return value.get("requiresCustomerAcceptance") is True or any(pending(v) for v in value.values())
        if isinstance(value, list):
            return any(pending(v) for v in value)
        return False
    return pending(info.get("confirmations"))
