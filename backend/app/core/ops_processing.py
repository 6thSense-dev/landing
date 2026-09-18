"""Automatic intake diagnosis and durable worker queue. No raw deletion."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.models import Episode, OpsCamera, ProcessingJob
from app.core.ops_raw import raw_statuses
from app.core.ops_sources import source_registry, business_source


def diagnose(take, now):
    if take.get('upload_source_conflict'):
        return 'blocked', 'Conflicting completed upload locations. Operator source review required.'
    media = [o for o in take.get("media", []) if o.get("bytes", 0) > 0]
    updated = take.get("uploaded")
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated)
    if not updated:
        return "uploading", "Waiting to verify when the latest source file was uploaded."
    if now - updated < timedelta(minutes=10):
        return "uploading", "Waiting for 10 minutes without new or updated source files before processing."
    if not media:
        return (
            "waiting_upload",
            "Waiting for source footage. Recovery checks alternate deliveries and source versions; completed uploads automatically re-enter validation.",
        )
    if take.get("error"):
        return (
            "retry",
            "Metadata could not be read. Retry storage access; do not reject the recording.",
        )
    meta = take.get("meta") or {}
    if not isinstance(meta, dict):
        return (
            "recovering",
            "Malformed metadata: recover facts from the media and matching camera evidence.",
        )
    if not meta or not meta.get("duration_s") or meta.get("truncated"):
        return (
            "recovering",
            "Probe and recover media-derived duration, frame mapping and missing metadata before QC.",
        )
    names = {o["key"].rsplit("/", 1)[-1] for o in media}
    if ("left.mp4" in names) != ("right.mp4" in names):
        return (
            "recovering",
            "Stereo eye is missing. Recover from the matching container or source version before QC.",
        )
    if any(n.endswith(".egoc") for n in names):
        return (
            "queued",
            "Validate and decode the EgoC container, preserving sensor timing, then run QC.",
        )
    return (
        "queued",
        "Validate the complete media timeline and key data, repair if possible, then run QC.",
    )


async def reconcile(db, takes, manifests, receipts):
    from app.core.contributor_deletion import pending_wearers
    held_wearers = await pending_wearers(db)
    now = datetime.now(timezone.utc)
    registry = await source_registry(db)
    statuses = raw_statuses(takes, manifests, receipts)
    jobs = {j.recording: j for j in (await db.execute(select(ProcessingJob))).scalars()}
    episodes = {e.recording: e for e in (await db.execute(select(Episode))).scalars()}
    cameras = {
        c.device_id: c.wearer_id
        for c in (await db.execute(select(OpsCamera))).scalars()
    }
    for rec, t in takes.items():
        snapshot = {
            k: t.get(k) for k in ("prefixes", "media", "meta", "error", "uploaded")
        }
        if t.get('upload_source_conflict'):
            snapshot['upload_source_conflict'] = True
        encoded = json.dumps(snapshot, sort_keys=True, default=str)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        j = jobs.get(rec)
        e = episodes.get(rec)
        try:
            party = business_source(e, registry) if e else None
            attribution_error = False
        except ValueError:
            party, attribution_error = None, True
        if e and rec not in registry and not e.wearer_id and not e.paid and not e.deleted_at:
            e.wearer_id = cameras.get(e.device_id.upper().removeprefix("EGO-"))
        if e and e.wearer_id in held_wearers:
            if not j:
                j = ProcessingJob(recording=rec, attempts=0, fingerprint=digest, input_json=encoded)
                db.add(j)
                jobs[rec] = j
            j.state, j.reason = 'blocked', 'Contributor account deletion requested.'
            j.lease_token = j.lease_until = None
            continue
        same_input = bool(j and j.fingerprint == digest)
        if j and e and e.deleted_at:
            j.state = "rejected"
            j.reason = "Previously removed by an operator: " + (
                e.delete_reason or "No reason recorded"
            )
            j.lease_token = None
            j.lease_until = None
            continue
        if t.get('upload_source_conflict'):
            if not j:
                j = ProcessingJob(recording=rec, attempts=0)
                db.add(j)
                jobs[rec] = j
            j.fingerprint, j.input_json = digest, encoded
            j.state, j.reason = diagnose(t, now)
            j.lease_token = j.lease_until = None
            continue
        if j and json.loads(j.input_json).get('upload_source_conflict'):
            # A rescan after source resolution must clear the hold even when
            # existing Clean receipts take the fast path below.
            j.fingerprint, j.input_json = digest, encoded
        if j and statuses.get(rec, {}).get("status") == "processed":
            j.state = "clean"
            j.reason = "Committed clean outputs and exact source receipts verified."
            j.lease_token = None
            j.lease_until = None
            continue
        if (
            j
            and j.fingerprint == digest
            and j.state in ("running", "rejected", "clean")
        ):
            if j.state != "running" or (j.lease_until and j.lease_until > now):
                continue
        if not j:
            j = ProcessingJob(recording=rec, attempts=0)
            db.add(j)
            jobs[rec] = j
        elif j.fingerprint != digest:
            j.attempts = 0
            j.lease_token = None
            j.lease_until = None
        j.fingerprint = digest
        j.input_json = encoded
        if e and e.deleted_at:
            j.state = "rejected"
            j.reason = "Previously removed by an operator: " + (
                e.delete_reason or "No reason recorded"
            )
        elif statuses.get(rec, {}).get("status") == "processed":
            j.state = "clean"
            j.reason = "Committed clean outputs and exact source receipts verified."
        elif not t.get('media') and not t.get('upload_source_conflict'):
            j.state, j.reason = diagnose(t, now)
        elif (
            j.state == "blocked"
            and same_input
            and not j.reason.startswith("Assign the source camera")
            and j.reason != "Contributor or business attribution required"
        ):
            continue
        elif attribution_error or not e or (not e.wearer_id and not party):
            j.state = "blocked"
            j.reason = "Assign the source camera to a contributor in Users or resolve its business attribution."
        elif j.attempts >= 3:
            j.state = "blocked"
            j.reason = "Worker retry limit reached. Source preserved for investigation."
        else:
            j.state, j.reason = diagnose(t, now)
    return jobs
