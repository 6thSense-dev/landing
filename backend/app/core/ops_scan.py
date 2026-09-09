"""Walk the capture bucket and report every take it holds.

THE BUCKET IS THE SYSTEM OF RECORD. Every fact here — how long a take ran, how
many frames it dropped, which camera recorded it, when it landed — comes from
S3 or from the recording's own `metadata.json`. Nothing in this module invents
anything, and nothing in it may touch an ops DECISION: an approval, a payment,
an assignment and a delete are the operator's, and a re-scan that could disturb
them would make the board unsafe to refresh.

So the merge rule is deliberately lopsided:

    a take we have never seen   -> INSERT, from the bucket
    a take we already know      -> refresh only what can GROW (bytes, files,
                                   upload time), and backfill what was missing
    a take in the DB, not in S3 -> LEFT ALONE

That last one matters. The uploader keys cannot delete, but a mis-scoped prefix
or a transient List failure would otherwise read as "these episodes are gone"
and wipe a payment record.

Ported from `tools/ledger/server.py` (scan_s3/parse_key/device_from) in the
ego-cam repo, which has been run against this bucket for weeks. Keep the two in
step; where they disagree, that file has seen more real keys than this one.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.core.ops_s3 import OpsS3Unavailable, get_settings, _client


logger = logging.getLogger(__name__)

META = "metadata.json"

#: How many metadata objects to fetch at once. The scan is one LIST pass (fast)
#: plus one GET per NEW take, and the GETs dominate a first run. Ten is enough
#: to hide the round trips without looking like a denial of service to S3.
META_WORKERS = 10

# A take's folder is recognised by its NAME, not by how deep it sits, because
# the bucket holds more than one layout and depth cannot tell them apart:
#
#   sessions/<session>/<DEVICE>/<recording>/<file>   the camera's own uploads
#   sessions/<session>/<recording>/<file>            a laptop/filter-node offload
#
# Both are live in the bucket today. Keying off depth found only the first and
# silently missed every take of the real Korea delivery. Two neighbours in the
# same tree are NOT episodes and are skipped by the leading-character rule:
# `_machine/…` (pipeline bookkeeping) and `.ego-s3-test/…` (the uploader's own
# credential probe, one per run).
REC_RE = re.compile(r"^ego_\d{8}_\d{6}_[0-9A-Za-z]{4,8}(?:_[A-Za-z0-9]+)?$")


def parse_key(key: str) -> tuple[str, str, str] | None:
    """(session, recording, take_prefix) for a file inside a take, else None."""
    parts = key.split("/")
    if len(parts) < 4 or parts[0] != "sessions":
        return None
    if any(p.startswith("_") or p.startswith(".") for p in parts[2:-1]):
        return None
    for i in range(len(parts) - 2, 1, -1):
        if REC_RE.match(parts[i]):
            return parts[1], parts[i], "/".join(parts[: i + 1])
    return None


def device_from(recording: str) -> str:
    """ego_<date>_<time>_<DEVICE>[_suffix] — the fallback when metadata has none."""
    bits = recording.split("_")
    return bits[3] if len(bits) > 3 else ""


def _parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def walk_bucket(prefix: str = "sessions/") -> dict[str, dict]:
    """Every take under `prefix`, keyed by recording id.

    One LIST pass to find the takes, then a bounded parallel fetch of each
    take's metadata.json. Raises OpsS3Unavailable if S3 cannot be reached at
    all; a single unreadable metadata object is recorded on the take and does
    not stop the scan.
    """
    cfg = get_settings()
    s3 = _client(cfg)

    takes: dict[str, dict] = {}
    for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=cfg.bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            hit = parse_key(obj["Key"])
            if not hit:
                continue
            session, recording, take_prefix = hit
            t = takes.setdefault(recording, {
                "recording": recording, "session": session,
                "prefix": take_prefix + "/", "bytes": 0, "files": 0,
                "meta_key": None, "uploaded": None, "meta": {}, "error": "",
            })
            t["bytes"] += obj.get("Size", 0)
            t["files"] += 1
            # The LAST object decides: a take is not delivered until its final
            # segment is in.
            lm = _parse_dt(obj.get("LastModified"))
            if lm and (t["uploaded"] is None or lm > t["uploaded"]):
                t["uploaded"] = lm
            if obj["Key"].rsplit("/", 1)[-1] == META:
                t["meta_key"] = obj["Key"]

    def fetch(t: dict) -> None:
        if not t["meta_key"]:
            return
        try:
            body = s3.get_object(Bucket=cfg.bucket, Key=t["meta_key"])["Body"].read()
            t["meta"] = json.loads(body)
        except Exception as exc:                # one bad object must not stop a scan
            t["error"] = f"{type(exc).__name__}: {exc}"[:200]
            logger.warning("ops_scan_metadata_unreadable",
                           extra={"ops_key": t["meta_key"], "ops_error": t["error"]})

    need = [t for t in takes.values() if t["meta_key"]]
    if need:
        with ThreadPoolExecutor(max_workers=META_WORKERS) as pool:
            list(pool.map(fetch, need))
    return takes


def facts_from(t: dict) -> dict:
    """The columns a take's own bytes justify. No ops decisions in here."""
    m = t.get("meta") or {}
    return {
        "session": t["session"],
        "prefix": t["prefix"],
        # metadata's device_id is the camera that RECORDED; the one in the key is
        # whichever camera UPLOADED. They differ when a card moves between bodies
        # — seen twice in this bucket — and the recording is the truth.
        "device_id": str(m.get("device_id") or device_from(t["recording"]))[:32],
        "started_at": _parse_dt(m.get("start_time")),
        "uploaded_at": t.get("uploaded"),
        "duration_s": float(m.get("duration_s") or 0),
        "size_bytes": int(t["bytes"]),
        "files": int(t["files"]),
        "frames": int(m.get("frame_count") or 0),
        "dropped": int(m.get("dropped_frames") or 0),
        "complete": bool(m.get("complete", True)),
        "truncated": bool(m.get("truncated", False)),
        "clock_source": str(m.get("clock_source") or "")[:16],
        "fw": str(m.get("fw") or "")[:32],
        "no_metadata": not t.get("meta_key"),
    }
