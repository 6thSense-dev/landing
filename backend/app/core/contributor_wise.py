"""Live recipient requirements. Personal details are sent to Wise, never logged.
The documented quarterly generic requirements route currently returns 404; the
supported v1 route was probed in production on 2026-09-15. No fixture fallback.
"""
import json
import re
import urllib.request
import urllib.error
from app.core.wise import WiseClient, WiseError

FIELDS = {"accountHolderName", "email", "phoneNumber", "dateOfBirth", "bankCode", "ifscCode", "accountNumber", "address.country", "address.city", "address.firstLine", "address.postCode", "address.state"}
ROUTES = {"KR": ("KRW", "south_korean_paygate"), "IN": ("INR", "indian")}

class RecipientClient(WiseClient):
    def request(self, method, path, body=None, correlation=None):
        # Only recipient onboarding uses these legacy endpoints. Payments retain
        # their separately verified quarterly adapter and idempotency contract.
        base = self.base.rsplit("/", 1)[0] + "/v1"
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None, headers={"Authorization": "Bearer " + self.token, "Content-Type": "application/json", "Accept-Minor-Version": "1"})
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)
        except Exception:
            raise WiseError("Recipient service unavailable.") from None

    def requirements(self, country, values):
        currency, route = ROUTES[country]
        payload = recipient_body(country, values, self.profile)
        data = self.request("POST", f"/account-requirements?source=USD&target={currency}&sourceAmount=100&addressRequired=true&originatorLegalEntityType=BUSINESS", payload)
        return parse_requirements(data, country)

    def create(self, country, values):
        return self.request("POST", "/accounts", recipient_body(country, values, self.profile))

def recipient_body(country, values, profile):
    currency, route = ROUTES[country]
    body = {"currency": currency, "type": route, "profile": int(profile), "ownedByCustomer": False, "accountHolderName": values.get("accountHolderName", ""), "details": {"legalType": "PRIVATE", "address": {"country": values.get("address.country", country)}}}
    for key, value in values.items():
        if key not in FIELDS:
            raise ValueError("unsupported_field")
        if key == "accountHolderName":
            continue
        if key.startswith("address."):
            body["details"]["address"][key.split(".")[1]] = value
        else:
            body["details"][key] = value
    return body

def parse_requirements(data, country):
    currency, route = ROUTES[country]
    selected = [r for r in data if r["type"] == route]
    if len(selected) != 1:
        raise ValueError("unsupported_route")
    fields = []
    for group in selected[0]["fields"]:
        for field in group.get("group", [group]):
            key = field["key"]
            if key == "legalType":
                if not any(v["key"] == "PRIVATE" for v in field.get("valuesAllowed", [])):
                    raise ValueError("private_recipient_unavailable")
                continue
            if key not in FIELDS or field["type"] not in ("text", "select", "date"):
                raise ValueError("unsupported_field")
            values = field.get("valuesAllowed")
            if field["type"] == "select" and not values:
                raise ValueError("unsupported_options")
            fields.append({"key": key, "required": bool(field["required"]) or key == "phoneNumber", "minLength": field.get("minLength"), "maxLength": field.get("maxLength"), "refresh": bool(field.get("refreshRequirementsOnChange")), "validationRegexp": field.get("validationRegexp"), **({"options": [{"value": str(v["key"]), "label": v["name"]} for v in values]} if values else {})})
    if len({f["key"] for f in fields}) != len(fields) or not {"accountHolderName", "accountNumber", "address.country"}.issubset({f["key"] for f in fields}):
        raise ValueError("incomplete_requirements")
    return {"country": country, "currency": currency, "fields": fields}

def validate(requirements, values):
    issues = []
    for f in requirements["fields"]:
        value = values.get(f["key"], "")
        if not value:
            if f["required"]:
                issues.append(f["key"])
            continue
        if len(value) < (f["minLength"] or 1) or len(value) > (f["maxLength"] or 255) or (f.get("options") and value not in {o["value"] for o in f["options"]}) or (f.get("validationRegexp") and not re.fullmatch(f["validationRegexp"], value)):
            issues.append(f["key"])
    if set(values) - {f["key"] for f in requirements["fields"]}:
        issues.append("unsupported_field")
    return issues
