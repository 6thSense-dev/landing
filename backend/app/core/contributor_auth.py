"""Cognito validates signature, expiry and revocation via GetUser on every request.
Decoded claims only narrow the accepted pool/client BEFORE AWS verification; they
never authenticate a caller by themselves. No token, phone or provider body logs.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import re
import boto3
from botocore.config import Config
from botocore import UNSIGNED
from fastapi import Header, HTTPException

REGIONS = json.loads(Path(__file__).with_name("contributor_regions.json").read_text())["collections"]

def cognito_user(token):
    region = os.getenv("CONTRIBUTOR_COGNITO_REGION", "us-west-2")
    return boto3.client("cognito-idp", region_name=region, config=Config(signature_version=UNSIGNED, connect_timeout=4, read_timeout=8, retries={"max_attempts": 1})).get_user(AccessToken=token)

def token_claims(token):
    try:
        parts = token.split(".")
        if len(parts) != 3 or len(token) > 8192:
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
        pool = os.getenv("CONTRIBUTOR_COGNITO_POOL", "")
        client = os.getenv("CONTRIBUTOR_COGNITO_CLIENT", "")
        region = os.getenv("CONTRIBUTOR_COGNITO_REGION", "us-west-2")
        if not pool or not client or claims.get("iss") != f"https://cognito-idp.{region}.amazonaws.com/{pool}" or claims.get("client_id") != client or claims.get("token_use") != "access" or not re.fullmatch(r"[0-9a-f-]{36}", claims.get("sub", "")):
            raise ValueError()
        return claims
    except (ValueError, TypeError, AttributeError, KeyError):
        raise HTTPException(401, "authentication_required") from None

async def contributor_identity(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "authentication_required")
    token = authorization[7:]
    claims = token_claims(token)
    try:
        user = await asyncio.to_thread(cognito_user, token)
        attrs = {a["Name"]: a["Value"] for a in user["UserAttributes"]}
    except Exception:
        raise HTTPException(401, "authentication_required") from None
    matches = [r for r in REGIONS if r["routing_version"] == attrs.get("custom:routing_version")]
    if attrs.get("sub") != claims["sub"] or attrs.get("phone_number_verified") != "true" or len(matches) != 1 or not re.fullmatch(matches[0]["phone_pattern"], attrs.get("phone_number", "")):
        raise HTTPException(403, "verified_account_required")
    # Request-local only: consent matching needs this verified attribute before
    # a Form signature is linked. It is never persisted or returned to clients.
    return {"subject": attrs["sub"], "region": matches[0], "verified_phone": attrs["phone_number"]}
