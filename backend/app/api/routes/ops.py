"""/api/ops/* — the collector operations area.

Gated on `ops` OR `founder`/`admin`. require_role() takes one role, so the check
is spelled out here rather than stacking three dependencies: a founder locked
out of the payment ledger of their own company is a support call, not security.

WHAT THIS DOES NOT DO
  It does not recompute the automatic quality verdict. `complete`, `truncated`,
  `dropped` and `clock_source` come off the recording's own metadata at scan
  time and are reported as found. Whether an episode is PAYABLE is a separate,
  human decision (`approved`) — deriving payment from a quality heuristic is how
  a collector stops being paid for a shoot that went fine.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth_deps import current_user
from app.core.db import get_session
from app.core.ops_s3 import OpsS3Unavailable, episode_files
from app.core.ops_scan import facts_from, walk_bucket
from app.core.ops_inventory import inventory_coverage
from app.models import Episode, OpsSetting, Task, User, Wearer


router = APIRouter(prefix="/api/ops", tags=["ops"])

#: Roles that may reach the ops area at all.
OPS_ROLES = frozenset({"ops", "founder", "admin"})


async def require_ops(user: User = Depends(current_user)) -> User:
    if user.role not in OPS_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")
    return user


def _now() -> datetime:
    return datetime.now(timezone.utc)


#: The one board setting there is. See models.OpsSetting for why it is not a
#: browser preference.
RATE_KEY = "rate_krw"


SCAN_KEY = "last_scan"


async def _setting(db: AsyncSession, key: str) -> str:
    row = (await db.execute(
        select(OpsSetting).where(OpsSetting.key == key))).scalar_one_or_none()
    return row.value if row else ""


async def _put_setting(db: AsyncSession, key: str, value: str) -> None:
    row = (await db.execute(
        select(OpsSetting).where(OpsSetting.key == key))).scalar_one_or_none()
    if row is None:
        db.add(OpsSetting(key=key, value=value))
    else:
        row.value = value


async def _rate(db: AsyncSession) -> int:
    """The current amount per approved episode, in KRW. Absent or unparseable
    reads as 0 -- a board with no rate set must still load and still count."""
    row = (await db.execute(
        select(OpsSetting).where(OpsSetting.key == RATE_KEY))).scalar_one_or_none()
    if row is None:
        return 0
    try:
        return max(0, int(row.value or 0))
    except ValueError:
        return 0


# --- serialisation ------------------------------------------------------------

def _wearer_json(w: Wearer) -> dict:
    return {"id": w.id, "name": w.name, "contact": w.contact, "note": w.note,
            "is_active": w.is_active, "workplace": w.workplace, "location": w.location, "rate_krw_hour": w.rate_krw_hour}


def _task_json(t: Task) -> dict:
    return {"id": t.id, "name": t.name, "category": t.category, "is_active": t.is_active}


def _episode_json(e: Episode) -> dict:
    return {
        "id": e.id, "recording": e.recording, "session": e.session,
        "device_id": e.device_id, "prefix": e.prefix,
        "started_at": e.started_at.isoformat() if e.started_at else None,
        "uploaded_at": e.uploaded_at.isoformat() if e.uploaded_at else None,
        "duration_s": e.duration_s, "minutes": round((e.duration_s or 0) / 60.0, 1),
        "size_bytes": e.size_bytes, "size_mb": round((e.size_bytes or 0) / 1e6, 1),
        "files": e.files, "frames": e.frames, "dropped": e.dropped,
        "complete": e.complete, "truncated": e.truncated,
        "clock_source": e.clock_source, "clock_ok": e.clock_source == "ntp",
        "fw": e.fw, "no_metadata": e.no_metadata,
        "wearer_id": e.wearer_id, "task_id": e.task_id,
        "approved": e.approved,
        "approved_at": e.approved_at.isoformat() if e.approved_at else None,
        "paid": e.paid, "paid_at": e.paid_at.isoformat() if e.paid_at else None,
        "amount_krw": e.amount_krw,
        "deleted_at": e.deleted_at.isoformat() if e.deleted_at else None,
        "delete_kind": e.delete_kind, "deleted_by": e.deleted_by,
        "delete_reason": e.delete_reason, "note": e.note,
    }


async def _state(db: AsyncSession) -> dict:
    eps = (await db.execute(
        select(Episode).order_by(Episode.started_at.desc().nullslast(),
                                 Episode.recording.desc()))).scalars().all()
    wearers = (await db.execute(
        select(Wearer).order_by(Wearer.name))).scalars().all()
    tasks = (await db.execute(
        select(Task).order_by(Task.category, Task.name))).scalars().all()
    live = [e for e in eps if e.deleted_at is None]
    return {
        "episodes": [_episode_json(e) for e in eps],
        "rate_krw": await _rate(db),
        "last_scan": await _setting(db, SCAN_KEY),
        "wearers": [_wearer_json(w) for w in wearers],
        "tasks": [_task_json(x) for x in tasks],
        "totals": {
            "episodes": len(live),
            "deleted": len(eps) - len(live),
            "minutes": round(sum((e.duration_s or 0) for e in live) / 60.0, 1),
            "bytes": sum((e.size_bytes or 0) for e in live),
            "approved": sum(1 for e in live if e.approved),
            "paid": sum(1 for e in live if e.paid),
            "unassigned": sum(1 for e in live if e.wearer_id is None),
            "unlabelled": sum(1 for e in live if e.task_id is None),
            "clock_flagged": sum(1 for e in live if e.clock_source != "ntp"),
        },
    }


@router.get("/inventory-coverage")
async def get_inventory_coverage(_: User = Depends(require_ops)) -> dict:
    return await asyncio.to_thread(inventory_coverage)


@router.get("/state")
async def get_state(_: User = Depends(require_ops),
                    db: AsyncSession = Depends(get_session)) -> dict:
    return await _state(db)



# --- scanning the bucket -------------------------------------------------------

@router.post("/scan")
async def scan_bucket(_: User = Depends(require_ops),
                      db: AsyncSession = Depends(get_session)) -> dict:
    """Read the capture bucket and merge what it holds into the ledger.

    NEVER destructive. New takes are inserted; known takes have only their
    growable facts refreshed (bytes, files, upload time) plus a backfill of
    anything that was missing; and a take that is in the ledger but NOT in the
    bucket is left completely alone. The uploader keys cannot delete, so an
    episode vanishing from a listing means a mis-scoped prefix or a transient
    failure, not a deletion — and treating it as one would erase a payment.

    Approvals, payments, assignments, labels and deletes are never touched.

    Synchronous on purpose at this size: one LIST pass plus one GET per new
    take is about a second for the ~150 takes in the bucket today. Past a few
    thousand this needs to become a background job — the fetch is already
    parallel, but an HTTP request is the wrong place to hold a minute of work.
    """
    try:
        takes = await asyncio.to_thread(walk_bucket)
    except OpsS3Unavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface the reason, never a stack
        raise HTTPException(
            status_code=502,
            detail=f"The bucket could not be read: {type(exc).__name__}: {exc}"[:300],
        ) from exc

    known = {e.recording: e for e in
             (await db.execute(select(Episode))).scalars().all()}

    added = updated = 0
    for rec, t in takes.items():
        facts = facts_from(t)
        e = known.get(rec)
        if e is None:
            db.add(Episode(recording=rec, **facts))
            added += 1
            continue
        # Refresh only what can grow, and backfill what was never set. Notably
        # NOT device_id or started_at: those came from the same metadata.json
        # last time, and letting a re-scan move them would silently re-attribute
        # settled work if a camera's metadata were ever rewritten.
        changed = False
        if facts["size_bytes"] > (e.size_bytes or 0):
            e.size_bytes = facts["size_bytes"]; changed = True
        if facts["files"] > (e.files or 0):
            e.files = facts["files"]; changed = True
        up = facts["uploaded_at"]
        if up and (e.uploaded_at is None or up > e.uploaded_at):
            e.uploaded_at = up; changed = True
        for col in ("prefix", "session", "fw", "clock_source"):
            if not getattr(e, col) and facts[col]:
                setattr(e, col, facts[col]); changed = True
        if e.started_at is None and facts["started_at"]:
            e.started_at = facts["started_at"]; changed = True
        if not e.duration_s and facts["duration_s"]:
            e.duration_s = facts["duration_s"]; changed = True
        updated += changed

    await _put_setting(db, SCAN_KEY, _now().isoformat(timespec="seconds"))
    await db.commit()
    out = await _state(db)
    out["scan"] = {"seen": len(takes), "added": added, "updated": updated,
                   "untouched": len(known) - updated}
    return out

# --- wearers ------------------------------------------------------------------

class WearerIn(BaseModel):
    workplace: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    rate_krw_hour: int | None = Field(default=None, ge=0, le=100_000_000)
    name: str = Field(min_length=1, max_length=200)
    contact: str = Field(default="", max_length=320)
    note: str = ""


@router.post("/wearers")
async def create_wearer(body: WearerIn, _: User = Depends(require_ops),
                        db: AsyncSession = Depends(get_session)) -> dict:
    db.add(Wearer(name=body.name.strip(), contact=body.contact.strip(),
                  note=body.note.strip(), workplace=body.workplace.strip(),
                  location=body.location.strip(), rate_krw_hour=body.rate_krw_hour))
    await db.commit()
    return await _state(db)


class WearerPatch(BaseModel):
    """Every field optional: the Users tab saves one field at a time."""

    workplace: str | None = Field(default=None, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    rate_krw_hour: int | None = Field(default=None, ge=0, le=100_000_000)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    contact: str | None = Field(default=None, max_length=320)
    note: str | None = None
    is_active: bool | None = None


@router.post("/wearers/{wearer_id}")
async def update_wearer(wearer_id: int, body: WearerPatch,
                        _: User = Depends(require_ops),
                        db: AsyncSession = Depends(get_session)) -> dict:
    """Edit a person's details.

    There is deliberately no DELETE. A wearer is attached to episodes that were
    reviewed and possibly paid; removing the row would orphan that history and
    leave a settled payment with nobody's name on it. `is_active = false`
    retires them from the pickers and keeps the record intact.
    """
    w = (await db.execute(
        select(Wearer).where(Wearer.id == wearer_id))).scalar_one_or_none()
    if w is None:
        raise HTTPException(status_code=404, detail="Unknown person.")
    if body.name is not None:
        w.name = body.name.strip()
    if body.contact is not None:
        w.contact = body.contact.strip()
    if body.note is not None:
        w.note = body.note.strip()
    if body.is_active is not None:
        w.is_active = body.is_active
    for field in ("workplace", "location"):
        if getattr(body, field) is not None:
            setattr(w, field, getattr(body, field).strip())
    if "rate_krw_hour" in body.model_fields_set:
        w.rate_krw_hour = body.rate_krw_hour
    await db.commit()
    return await _state(db)


# --- tasks --------------------------------------------------------------------

class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(default="other", max_length=60)


@router.post("/tasks")
async def create_task(body: TaskIn, _: User = Depends(require_ops),
                      db: AsyncSession = Depends(get_session)) -> dict:
    """Add a label. Case-insensitively unique, because "Garment Folding" and
    "garment folding" are the split this table exists to prevent."""
    name = body.name.strip()
    clash = (await db.execute(
        select(Task).where(func.lower(Task.name) == name.lower()))).scalar_one_or_none()
    if clash is not None:
        raise HTTPException(status_code=409,
                            detail=f"'{clash.name}' already exists in {clash.category}.")
    db.add(Task(name=name, category=(body.category or "other").strip() or "other"))
    await db.commit()
    return await _state(db)


# --- per-episode actions ------------------------------------------------------

async def _amount_for(db: AsyncSession, explicit: int | None) -> int:
    """The amount to stamp, or a refusal.

    A payment of zero is indistinguishable in the ledger from a shift that was
    never paid, and the UI hides the amount chip when it is 0 -- so a ₩0
    settlement renders exactly like a correct one. Migration 0011 seeds the rate
    at 0, which means the whole window between deploy and an operator setting a
    rate is a window in which every tick silently books nothing. Refuse instead.
    Paying zero deliberately is still possible: send amount_krw: 0 explicitly.
    """
    if explicit is not None:
        return int(explicit)
    rate = await _rate(db)
    if rate <= 0:
        raise HTTPException(
            status_code=409,
            detail="No payment rate is set, so this would record a payment of zero. "
                   "Set the rate under Payment basis first.")
    return rate


async def _episode_or_404(db: AsyncSession, recording: str) -> Episode:
    e = (await db.execute(
        select(Episode).where(Episode.recording == recording))).scalar_one_or_none()
    if e is None:
        raise HTTPException(status_code=404, detail="Unknown recording.")
    return e


class AssignIn(BaseModel):
    wearer_id: int | None = None


@router.post("/episodes/{recording}/assign")
async def assign_episode(recording: str, body: AssignIn,
                         _: User = Depends(require_ops),
                         db: AsyncSession = Depends(get_session)) -> dict:
    e = await _episode_or_404(db, recording)
    if body.wearer_id is not None:
        exists = (await db.execute(
            select(func.count()).select_from(Wearer)
            .where(Wearer.id == body.wearer_id))).scalar_one()
        if not exists:
            raise HTTPException(status_code=404, detail="Unknown wearer.")
    e.wearer_id = body.wearer_id
    await db.commit()
    return await _state(db)


class TaskAssignIn(BaseModel):
    task_id: int | None = None


@router.post("/episodes/{recording}/task")
async def label_episode(recording: str, body: TaskAssignIn,
                        _: User = Depends(require_ops),
                        db: AsyncSession = Depends(get_session)) -> dict:
    e = await _episode_or_404(db, recording)
    if body.task_id is not None:
        exists = (await db.execute(
            select(func.count()).select_from(Task)
            .where(Task.id == body.task_id))).scalar_one()
        if not exists:
            raise HTTPException(status_code=404, detail="Unknown task.")
    e.task_id = body.task_id
    await db.commit()
    return await _state(db)


class FlagIn(BaseModel):
    value: bool


@router.post("/episodes/{recording}/approve")
async def approve_episode(recording: str, body: FlagIn,
                          _: User = Depends(require_ops),
                          db: AsyncSession = Depends(get_session)) -> dict:
    e = await _episode_or_404(db, recording)
    e.approved = body.value
    e.approved_at = _now() if body.value else None
    await db.commit()
    return await _state(db)


class PayIn(BaseModel):
    value: bool
    #: Omitted means "the board's current rate". Explicit means exactly that,
    #: including 0. The difference matters: a client that forgot to send an
    #: amount used to record a payment of zero, which is indistinguishable in
    #: the ledger from a shift that really was unpaid.
    amount_krw: int | None = Field(default=None, ge=0, le=100_000_000)


@router.post("/episodes/{recording}/pay")
async def pay_episode(recording: str, body: PayIn,
                      _: User = Depends(require_ops),
                      db: AsyncSession = Depends(get_session)) -> dict:
    e = await _episode_or_404(db, recording)
    # Paying an unapproved episode is almost always a misclick on the wrong row.
    if body.value and not e.approved:
        raise HTTPException(status_code=409, detail="Approve the episode first.")
    amount = await _amount_for(db, body.amount_krw) if body.value else 0
    # Settling is a one-way stamp. Re-ticking an already-paid episode after the
    # rate moved would rewrite what the ledger says somebody was paid, which is
    # the one thing a payment record must never do.
    if body.value and not e.paid:
        e.paid_at = _now()
        e.amount_krw = max(0, amount)
    elif not body.value:
        e.paid_at = None
        e.amount_krw = 0
    e.paid = body.value
    await db.commit()
    return await _state(db)


class PayBulkIn(BaseModel):
    recordings: list[str] = Field(default_factory=list, max_length=2000)
    value: bool = True
    amount_krw: int | None = Field(default=None, ge=0, le=100_000_000)


@router.post("/pay-bulk")
async def pay_bulk(body: PayBulkIn, _: User = Depends(require_ops),
                   db: AsyncSession = Depends(get_session)) -> dict:
    """Settle a whole filtered batch in one write.

    ALL OR NOTHING, and deliberately so. The operator's mental model is "pay
    this week's approved episodes"; a partial run that quietly skipped four
    rows leaves them believing a person was paid who was not, and there is
    nothing in the board that would ever show the difference. So an unknown
    recording or an unapproved one fails the batch and names the count.
    """
    wanted = list(dict.fromkeys(body.recordings))       # de-dup, keep order
    if not wanted:
        raise HTTPException(status_code=422, detail="No episodes were selected.")

    eps = (await db.execute(
        select(Episode).where(Episode.recording.in_(wanted)))).scalars().all()
    if len(eps) != len(wanted):
        missing = sorted(set(wanted) - {e.recording for e in eps})
        raise HTTPException(
            status_code=404,
            detail=f"{len(missing)} of these are not in the ledger "
                   f"(e.g. {missing[0]}). Nothing was paid.")

    if body.value:
        gone = [e.recording for e in eps if e.deleted_at is not None]
        if gone:
            raise HTTPException(
                status_code=409,
                detail=f"{len(gone)} of these are deleted (e.g. {gone[0]}). Nothing was paid.")
        unapproved = [e.recording for e in eps if not e.approved]
        if unapproved:
            raise HTTPException(
                status_code=409,
                detail=f"{len(unapproved)} of these are not approved "
                       f"(e.g. {unapproved[0]}). Nothing was paid.")

    amount = await _amount_for(db, body.amount_krw) if body.value else 0
    now = _now()
    for e in eps:
        if body.value and not e.paid:
            e.paid_at = now
            e.amount_krw = max(0, amount)
        elif not body.value:
            e.paid_at = None
            e.amount_krw = 0
        e.paid = body.value
    await db.commit()
    out = await _state(db)
    out["changed"] = len(eps)
    return out


class RateIn(BaseModel):
    rate_krw: int = Field(ge=0, le=100_000_000)


@router.post("/rate")
async def set_rate(body: RateIn, _: User = Depends(require_ops),
                   db: AsyncSession = Depends(get_session)) -> dict:
    """Set the amount per approved episode.

    Changing it does NOT reprice anything already paid. Each payment carries
    the amount it was settled at, which is the only version of this number a
    collector could ever be shown and told is what they were paid.
    """
    row = (await db.execute(
        select(OpsSetting).where(OpsSetting.key == RATE_KEY))).scalar_one_or_none()
    if row is None:
        db.add(OpsSetting(key=RATE_KEY, value=str(body.rate_krw)))
    else:
        row.value = str(body.rate_krw)
    await db.commit()
    return await _state(db)


class DeleteIn(BaseModel):
    kind: str
    reason: str = ""


@router.post("/episodes/{recording}/delete")
async def delete_episode(recording: str, body: DeleteIn,
                         user: User = Depends(require_ops),
                         db: AsyncSession = Depends(get_session)) -> dict:
    """Soft hides the row; hard ALSO purges the S3 objects.

    The row survives either way. An episode that was paid for and then purged is
    exactly what a payment ledger still has to account for, and the raw bucket
    denies deletes to its uploaders, so a purge cannot be undone by re-uploading.

    NOTE: the S3 side of `hard` is not wired up yet — this records the intent and
    marks the row. It deliberately does not report bytes as freed that are still
    sitting in the bucket.
    """
    if body.kind not in ("soft", "hard"):
        raise HTTPException(status_code=422, detail="kind must be 'soft' or 'hard'.")
    e = await _episode_or_404(db, recording)
    e.deleted_at, e.delete_kind = _now(), body.kind
    e.deleted_by, e.delete_reason = user.email, body.reason.strip()
    await db.commit()
    out = await _state(db)
    out["s3_purge"] = "not_implemented" if body.kind == "hard" else None
    return out


@router.post("/episodes/{recording}/restore")
async def restore_episode(recording: str, _: User = Depends(require_ops),
                          db: AsyncSession = Depends(get_session)) -> dict:
    """Undo a delete. Only honest for `soft` — a hard delete's bytes are gone."""
    e = await _episode_or_404(db, recording)
    if e.delete_kind == "hard":
        raise HTTPException(
            status_code=409,
            detail="This episode was hard-deleted; its objects are gone from the "
                   "bucket and cannot be restored by clearing the flag.")
    e.deleted_at = e.delete_kind = None
    e.deleted_by = e.delete_reason = ""
    await db.commit()
    return await _state(db)


# --- playback ------------------------------------------------------------------

@router.get("/episodes/{recording}/files")
async def list_episode_files(recording: str, _: User = Depends(require_ops),
                             db: AsyncSession = Depends(get_session)) -> dict:
    """Presigned URLs for whatever in this episode a browser could play.

    GET, not POST, and therefore outside the Origin check -- it is a read, and
    the session cookie still gates it. The URLs it hands back are short-lived by
    construction (OPS_PRESIGN_TTL, 15 minutes) precisely because they leave the
    building.
    """
    e = await _episode_or_404(db, recording)
    try:
        files = episode_files(e.prefix)
    except OpsS3Unavailable as exc:
        # A configuration problem is not a 500: the operator can read this and
        # fix it, and the rest of the board still works without playback.
        return {"ok": False, "error": str(exc), "files": []}
    except Exception as exc:  # noqa: BLE001 - surface the reason, never a stack
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300], "files": []}
    return {"ok": True, "recording": recording, "files": files}


# --- import from the laptop ledger -------------------------------------------

class ImportIn(BaseModel):
    #: The `episodes` map out of ~/.egocam-ledger/*.json, plus its `payments`.
    episodes: dict = Field(default_factory=dict)
    payments: dict = Field(default_factory=dict)


@router.post("/import")
async def import_ledger(body: ImportIn, _: User = Depends(require_ops),
                        db: AsyncSession = Depends(get_session)) -> dict:
    """Merge the laptop ledger in. NEVER regenerates.

    Same rule the JSON tool enforced on itself: a re-import adds episodes it has
    not seen and leaves every decision already recorded here alone. Rebuilding
    the table from the source would wipe approvals and payments, which is the
    one thing this data cannot survive.
    """
    known = {r for (r,) in (await db.execute(select(Episode.recording))).all()}
    added = 0
    for rec, ep in (body.episodes or {}).items():
        if rec in known:
            continue
        started = None
        raw = (ep or {}).get("start") or ""
        if raw:
            try:
                started = datetime.fromisoformat(raw)
            except ValueError:
                started = None
        pay = (body.payments or {}).get(rec) or {}
        db.add(Episode(
            recording=rec,
            session=str(ep.get("session") or ""),
            device_id=str(ep.get("device_id") or ""),
            prefix=str(ep.get("prefix") or ""),
            started_at=started,
            duration_s=float(ep.get("duration_s") or 0),
            size_bytes=int(ep.get("bytes") or 0),
            files=int(ep.get("files") or 0),
            frames=int(ep.get("frames") or 0),
            dropped=int(ep.get("dropped") or 0),
            complete=bool(ep.get("complete")),
            truncated=bool(ep.get("truncated")),
            clock_source=str(ep.get("clock_source") or ""),
            fw=str(ep.get("fw") or ""),
            no_metadata=bool(ep.get("no_metadata")),
            # A tick in the old file means somebody was paid. Carry it, and carry
            # its amount verbatim -- including 0, which is what the old ledger
            # stored before a rate was set. Inventing a rate here would fabricate
            # a payment record.
            paid=bool(pay.get("paid")),
            amount_krw=int(pay.get("amount") or 0),
            approved=bool(pay.get("paid")),
        ))
        added += 1
    await db.commit()
    out = await _state(db)
    out["added"] = added
    return out
