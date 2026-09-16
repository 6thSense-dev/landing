"""Sanitized, read-only progress across the company and Sieve pipelines.

All cloud reads use the existing Sieve assumed role.  This module deliberately
does not read Raw, expose object paths, or treat the presence of a validation
report as proof that the report passed.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from app.core.ops_clean import clean_bucket
from app.core.ops_sieve import BUCKET as SIEVE_BUCKET
from app.core.ops_sieve import storage_client


DEPLOY_BUCKET = "6thsense-deploy-artifacts"
LIFECYCLE_PREFIX = "raw-lifecycle/v1/"
CONFIG_KEY = LIFECYCLE_PREFIX + "config.json"
STATE_PREFIX = LIFECYCLE_PREFIX + "states/"

DEFAULT_BATCH = "sow1-20260915-batch-1"
DEFAULT_VALIDATION_RUN = "sow1-20260916-independent-v2"
DEFAULT_SUPPLEMENT_RUN = "sow1-20260916-supplement-v1"
SUPPLEMENT_TOTAL_BYTES = 25_394_461_079
SUPPLEMENT_MANIFEST_SHA256 = "ecc33fb99ae6c426e721615ff13a9cb8b886ad98bec8ae9863ef4bd87b759e2d"
VALIDATION_STATUS_SCHEMA = "sixthsense-sieve-independent-final-validation/1"

_BATCH = re.compile(r"^sow[0-9]+-[0-9]{8}-batch-[0-9]+$")
_RUN = re.compile(r"^sow[0-9]+-[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+)*-v[0-9]+$")
_RECORDING = re.compile(r"^ego_[0-9]{8}_[0-9]{6}_[A-Fa-f0-9]{6}(?:_s[0-9]{2,4})?$")
_PROOF = re.compile(r"^[0-9]{10}\.json$")
_MISSING = frozenset({"404", "NoSuchKey", "NotFound", "NoSuchVersion"})

CACHE_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 12.0
STALE_SECONDS = 15 * 60
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_STATE_OBJECTS = 2_000
MAX_PROOF_OBJECTS = 10_000
STATE_READ_WORKERS = 8

_cache_lock = asyncio.Lock()
_cache: dict | None = None
_cache_at = 0.0
_refresh_task: asyncio.Task | None = None


def _configured(name: str, default: str, pattern: re.Pattern[str]) -> str:
    value = os.getenv(name, default).strip()
    if not pattern.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value) -> str | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat()


def _latest(*values) -> str | None:
    parsed = [_iso(value) for value in values]
    return max((value for value in parsed if value), default=None)


def _stale(updated_at: str | None, *, terminal: bool) -> bool:
    if terminal:
        return False
    if not updated_at:
        return True
    updated = datetime.fromisoformat(updated_at)
    return (datetime.now(timezone.utc) - updated).total_seconds() > STALE_SECONDS


def _integer(value, field: str) -> int:
    if type(value) is not int or value < 0:  # bool is not an integer here
        raise ValueError(f"Invalid {field}")
    return value


def _number(value, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"Invalid {field}")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field}") from exc
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"Invalid {field}")
    return result


def _last_modified(response: dict) -> str | None:
    return _iso(response.get("LastModified"))


def _json(s3, bucket: str, key: str, *, optional: bool = False) -> tuple[dict | list | None, dict | None]:
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if optional and exc.response.get("Error", {}).get("Code") in _MISSING:
            return None, None
        raise
    body = response["Body"]
    try:
        size = response.get("ContentLength")
        if type(size) is not int or size < 0 or size > MAX_JSON_BYTES:
            raise ValueError("JSON artifact size is invalid")
        raw = body.read(MAX_JSON_BYTES + 1)
    finally:
        body.close()
    if len(raw) != size or len(raw) > MAX_JSON_BYTES:
        raise ValueError("JSON artifact size changed")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("JSON artifact is malformed") from exc
    return value, {"updated_at": _last_modified(response), "key": key,
                   "version_id": response.get("VersionId"),
                   "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def _list(s3, bucket: str, prefix: str, limit: int) -> list[dict]:
    rows: list[dict] = []
    token = None
    while True:
        args = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": min(1000, limit + 1 - len(rows))}
        if token:
            args["ContinuationToken"] = token
        page = s3.list_objects_v2(**args)
        contents = page.get("Contents", [])
        if not isinstance(contents, list):
            raise ValueError("Object listing is malformed")
        rows.extend(contents)
        if len(rows) > limit:
            raise ValueError("Object listing exceeds limit")
        if not page.get("IsTruncated"):
            return rows
        next_token = page.get("NextContinuationToken")
        if not isinstance(next_token, str) or not next_token or next_token == token:
            raise ValueError("Object listing pagination is malformed")
        token = next_token


def _unavailable(fields: tuple[str, ...]) -> dict:
    return {"available": False, **{field: None for field in fields}, "stale": False}


def _company(s3) -> dict:
    config, config_meta = _json(s3, DEPLOY_BUCKET, CONFIG_KEY)
    if (not isinstance(config, dict) or type(config.get("enabled")) is not bool
            or type(config.get("retirement_enabled")) is not bool):
        raise ValueError("Lifecycle config is malformed")

    objects = _list(s3, clean_bucket(), STATE_PREFIX, MAX_STATE_OBJECTS)
    state_objects = []
    for item in objects:
        key = item.get("Key")
        if not isinstance(key, str) or not key.startswith(STATE_PREFIX):
            raise ValueError("Lifecycle state listing is malformed")
        relative = key[len(STATE_PREFIX):]
        if relative.endswith(".json") and _RECORDING.fullmatch(relative[:-5]):
            state_objects.append((key, relative[:-5]))

    states: dict[str, dict] = {}
    observed: list[str | None] = [config_meta["updated_at"]]
    read_lock = threading.Lock()

    def read_state(item):
        key, key_recording = item
        value, metadata = _json(s3, clean_bucket(), key)
        if not isinstance(value, dict) or value.get("recording") != key_recording:
            raise ValueError("Lifecycle state identity is malformed")
        phase = value.get("phase")
        if not isinstance(phase, str) or len(phase) > 40:
            raise ValueError("Lifecycle phase is malformed")
        return key_recording, value, metadata["updated_at"]

    with ThreadPoolExecutor(max_workers=STATE_READ_WORKERS) as pool:
        futures = [pool.submit(read_state, item) for item in state_objects]
        for future in as_completed(futures):
            recording, value, modified = future.result()
            with read_lock:
                # The key contract permits one state per recording.  Keep this
                # explicit so a future layout change cannot multiply counts.
                if recording in states:
                    raise ValueError("Duplicate lifecycle state")
                states[recording] = value
                observed.extend((value.get("updated_at"), modified))

    rows = list(states.values())
    phases = {row["recording"]: row.get("phase") for row in rows}
    in_progress_phases = {"observed", "archiving", "converting", "processing", "queued", "running"}
    clean_phases = {"imported", "retiring", "retired"}
    updated_at = _latest(*observed)
    in_progress = sum(phase in in_progress_phases for phase in phases.values())
    clean_complete = sum(
        phase not in in_progress_phases | {"hold", "deleted"}
        and (phase in clean_phases or bool(row.get("imports")))
        for row, phase in ((item, item.get("phase")) for item in rows)
    )
    stale = any(
        _stale(_iso(row.get("updated_at")), terminal=False)
        for row in rows if row.get("phase") in in_progress_phases
    )
    return {
        "available": True,
        "source_groups": len(states),
        "archived": sum(isinstance(row.get("archive_receipt"), dict) for row in rows),
        "clean_complete": clean_complete,
        "in_progress": in_progress,
        "held": sum(phase == "hold" for phase in phases.values()),
        "deleted": sum(phase == "deleted" for phase in phases.values()),
        "updated_at": updated_at,
        "stale": stale,
    }


def _delivery(s3, batch: str) -> tuple[dict, str | None]:
    key = f"reports/{batch}/delivery/status.json"
    value, metadata = _json(s3, SIEVE_BUCKET, key)
    if (not isinstance(value, dict) or value.get("schema") != "6thsense-sieve-delivery-status/1"
            or value.get("batch_id") != batch):
        raise ValueError("Delivery status identity is malformed")
    processed = _integer(value.get("recordings_processed"), "recordings_processed")
    expected = _integer(value.get("recordings_expected"), "recordings_expected")
    packaged = _integer(value.get("packaged_assets"), "packaged_assets")
    uploaded_assets = _integer(value.get("uploaded_assets"), "uploaded_assets")
    uploaded_files = _integer(value.get("uploaded_files"), "uploaded_files")
    total_files = _integer(value.get("delivery_files"), "delivery_files")
    uploaded_bytes = _integer(value.get("uploaded_bytes"), "uploaded_bytes")
    total_bytes = _integer(value.get("delivery_bytes"), "delivery_bytes")
    prepared_hours = _number(value.get("prepared_unique_hours"), "prepared_unique_hours")
    declared_complete = value.get("external_transfer_completed") is True
    totals_match = (processed == expected and uploaded_assets == packaged
                    and uploaded_files == total_files and uploaded_bytes == total_bytes)
    monotonic = (processed <= expected and uploaded_assets <= packaged
                 and uploaded_files <= total_files and uploaded_bytes <= total_bytes)
    positive_totals = expected > 0 and packaged > 0 and total_files > 0 and total_bytes > 0
    raw_state = value.get("status")
    allowed = {"preparing", "packaging", "transferring", "delivered_checksums_verified", "blocked", "failed"}
    state = raw_state.upper() if raw_state in allowed else "UNKNOWN"
    complete = (declared_complete and raw_state == "delivered_checksums_verified"
                and positive_totals and totals_match and monotonic)
    inconsistent = not monotonic or (declared_complete and not complete)
    if inconsistent:
        state = "INCONSISTENT"
    updated_at = _latest(value.get("updated_at"), metadata["updated_at"])
    result = {
        "available": True,
        "batch_id": batch,
        "state": state,
        "recordings_processed": processed,
        "recordings_expected": expected,
        "prepared_hours": prepared_hours,
        "packaged_assets": packaged,
        "uploaded_assets": uploaded_assets,
        "uploaded_files": uploaded_files,
        "total_files": total_files,
        "uploaded_bytes": uploaded_bytes,
        "total_bytes": total_bytes,
        "uploaded_hours": prepared_hours if complete else None,
        "complete": complete,
        "updated_at": updated_at,
        "stale": _stale(updated_at, terminal=complete or state in {"BLOCKED", "FAILED"}),
        "_ref": {field: metadata[field] for field in ("key", "version_id", "sha256", "size_bytes")},
    }
    return result, "delivery_totals_mismatch" if inconsistent else None


def _validation(s3, run: str, batch: str) -> tuple[dict, str | None]:
    prefix = f"{LIFECYCLE_PREFIX}audit/sieve-validation/{run}/"
    status, status_meta = _json(s3, clean_bucket(), prefix + "FINAL-STATUS.json", optional=True)
    proofs = _list(s3, clean_bucket(), prefix + "assets/", MAX_PROOF_OBJECTS)
    report_keys = set()
    listed_updates = []
    for item in proofs:
        key = item.get("Key")
        if not isinstance(key, str) or not key.startswith(prefix + "assets/"):
            raise ValueError("Validation proof listing is malformed")
        relative = key[len(prefix + "assets/"):]
        if _PROOF.fullmatch(relative) and type(item.get("Size")) is int and item["Size"] > 0:
            report_keys.add(key)
            listed_updates.append(item.get("LastModified"))
    if status is not None and not isinstance(status, dict):
        raise ValueError("Validation status is malformed")
    raw_state = status.get("technical_status") if status else None
    allowed = {"PASS", "FAIL", "RUNNING", "PENDING_DEADLINE"}
    state = raw_state if raw_state in allowed else "UNKNOWN" if raw_state is not None else "RUNNING" if report_keys else "PENDING"
    identity_warning = None
    final = None
    assets = final_files = final_bytes = recordings = None
    final_hours = None
    delivery_ref = None
    if state == "PASS":
        final, _final_meta = _json(s3, clean_bucket(), prefix + "FINAL-VALIDATION.json", optional=True)
        try:
            if not isinstance(final, dict) or final.get("schema") != VALIDATION_STATUS_SCHEMA or final.get("technical_status") != "PASS":
                raise ValueError("Final validation identity mismatch")
            status_files = _integer(status.get("files"), "validation status files")
            status_hours = _number(status.get("unique_hours"), "validation status hours")
            assets = _integer(final.get("assets"), "validation assets")
            final_files = _integer(final.get("files"), "validation files")
            final_bytes = _integer(final.get("bytes"), "validation bytes")
            final_hours = _number(final.get("unique_hours"), "validation hours")
            recordings = _integer(final.get("recordings_processed"), "validation recordings")
            delivery_ref = final.get("delivery_status_ref")
            if (assets <= 0 or final_files <= 0 or final_bytes <= 0 or final_hours <= 0
                    or status_files != final_files or not math.isclose(status_hours, final_hours, rel_tol=0, abs_tol=1e-12)
                    or not isinstance(delivery_ref, dict)
                    or set(delivery_ref) != {"key", "version_id", "sha256", "size_bytes"}
                    or delivery_ref.get("key") != f"reports/{batch}/delivery/status.json"
                    or not isinstance(delivery_ref.get("version_id"), str)
                    or not delivery_ref["version_id"]
                    or not isinstance(delivery_ref.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", delivery_ref["sha256"])
                    or type(delivery_ref.get("size_bytes")) is not int
                    or delivery_ref["size_bytes"] <= 0):
                raise ValueError("Final validation binding mismatch")
        except ValueError:
            state = "UNKNOWN"
            identity_warning = "validation_identity_mismatch"
    updated_at = _latest(
        status.get("at") if status else None,
        status.get("checked_at") if status else None,
        status_meta["updated_at"] if status_meta else None,
        *listed_updates,
    )
    total_clips = assets if state == "PASS" else None
    result = {
        "available": True,
        "state": state,
        "clip_reports": len(report_keys),
        "total_clips": total_clips,
        "updated_at": updated_at,
        "stale": _stale(updated_at, terminal=state in {"PASS", "FAIL"}),
        "_delivery_ref": delivery_ref if state == "PASS" else None,
        "_files": final_files if state == "PASS" else None,
        "_bytes": final_bytes if state == "PASS" else None,
        "_hours": final_hours if state == "PASS" else None,
        "_recordings": recordings if state == "PASS" else None,
    }
    return result, identity_warning


def _supplement(s3, run: str) -> dict:
    key = f"originals-review/{run}/_audit/summary.json"
    value, metadata = _json(s3, SIEVE_BUCKET, key)
    if not isinstance(value, dict) or value.get("schema") != "6thsense-private-originals-summary/1":
        raise ValueError("Supplement summary identity is malformed")
    recordings = value.get("recordings")
    if not isinstance(recordings, list) or any(not isinstance(item, dict) for item in recordings):
        raise ValueError("Supplement recordings are malformed")
    names = [item.get("recording") for item in recordings]
    if any(not isinstance(name, str) or not _RECORDING.fullmatch(name) for name in names) or len(names) != len(set(names)):
        raise ValueError("Supplement recording identities are malformed")
    if value.get("external_delivery_performed") is not False:
        raise ValueError("Supplement delivery flag is unsafe")
    state = value.get("status")
    if state not in {"STAGING", "READY_FOR_REVIEW", "BLOCKED", "FAILED"}:
        state = "UNKNOWN"
    updated_at = _latest(value.get("updated_at"), metadata["updated_at"])
    return {
        "available": True,
        "state": state,
        "recordings": len(names),
        "hours": _number(value.get("retained_hours"), "retained_hours"),
        "bytes": _integer(value.get("original_bytes"), "original_bytes"),
        "external_delivery_performed": False,
        "updated_at": updated_at,
        "stale": _stale(updated_at, terminal=state in {"READY_FOR_REVIEW", "BLOCKED", "FAILED"}),
    }


def _supplement_delivery(s3, run: str) -> tuple[dict, str | None]:
    """A separate transfer receipt; the immutable private staging summary stays unchanged."""
    value, metadata = _json(s3, SIEVE_BUCKET, f"reports/{run}/delivery/status.json", optional=True)
    if value is None:
        return _unavailable(_SUPPLEMENT_DELIVERY_FIELDS), None
    if (not isinstance(value, dict)
            or value.get("schema") != "6thsense-supplement-delivery-status/1"
            or value.get("run_id") != run or value.get("batch_id") != run
            or not isinstance(value.get("manifest_sha256"), str)
            or value["manifest_sha256"] != SUPPLEMENT_MANIFEST_SHA256
            or type(value.get("external_transfer_completed")) is not bool
            or value.get("customer_accepted") is not False
            or value.get("human_review") != "PENDING"
            or not _iso(value.get("updated_at"))):
        raise ValueError("Supplement transfer identity is malformed")
    state = value.get("status")
    if state not in {"PREPARING", "UPLOADING", "UPLOADED_FOR_CUSTOMER_QC", "FAILED"}:
        raise ValueError("Supplement transfer state is malformed")
    total_files = _integer(value.get("total_files"), "total_files")
    uploaded_files = _integer(value.get("uploaded_files"), "uploaded_files")
    total_bytes = _integer(value.get("total_bytes"), "total_bytes")
    uploaded_bytes = _integer(value.get("uploaded_bytes"), "uploaded_bytes")
    potential_hours = _number(value.get("potential_unique_technical_hours"), "potential_unique_technical_hours")
    declared_complete = value["external_transfer_completed"]
    totals_valid = (total_files == 604 and total_bytes == SUPPLEMENT_TOTAL_BYTES
                    and uploaded_files <= total_files and uploaded_bytes <= total_bytes
                    and math.isclose(potential_hours, 4.696644566, rel_tol=0, abs_tol=1e-9))
    totals_match = uploaded_files == total_files and uploaded_bytes == total_bytes
    complete = (totals_valid and totals_match and declared_complete
                and state == "UPLOADED_FOR_CUSTOMER_QC")
    inconsistent = (not totals_valid or (declared_complete and not complete)
                    or (state == "UPLOADED_FOR_CUSTOMER_QC" and not complete))
    if inconsistent:
        state = "INCONSISTENT"
    updated_at = _latest(value["updated_at"], metadata["updated_at"])
    return {
        "available": True, "run_id": run, "batch_id": run,
        "manifest_sha256": value["manifest_sha256"], "state": state,
        "total_files": total_files, "uploaded_files": uploaded_files,
        "total_bytes": total_bytes, "uploaded_bytes": uploaded_bytes,
        "potential_unique_technical_hours": potential_hours if totals_valid else None,
        "uploaded_hours": potential_hours if complete else None,
        "external_transfer_completed": complete, "complete": complete,
        "customer_accepted": False, "human_review": "PENDING",
        "updated_at": updated_at,
        "stale": _stale(updated_at, terminal=complete or state == "FAILED"),
    }, "supplement_delivery_totals_mismatch" if inconsistent else None


_COMPANY_FIELDS = ("source_groups", "archived", "clean_complete", "in_progress", "held", "deleted", "updated_at")
_DELIVERY_FIELDS = ("batch_id", "state", "recordings_processed", "recordings_expected", "prepared_hours",
                    "packaged_assets", "uploaded_assets", "uploaded_files", "total_files", "uploaded_bytes",
                    "total_bytes", "uploaded_hours", "complete", "updated_at")
_VALIDATION_FIELDS = ("state", "clip_reports", "total_clips", "updated_at")
_SUPPLEMENT_FIELDS = ("state", "recordings", "hours", "bytes", "external_delivery_performed", "updated_at")
_SUPPLEMENT_DELIVERY_FIELDS = ("run_id", "batch_id", "manifest_sha256", "state", "total_files",
    "uploaded_files", "total_bytes", "uploaded_bytes", "potential_unique_technical_hours",
    "uploaded_hours", "external_transfer_completed", "complete", "customer_accepted", "human_review", "updated_at")


def _empty(*, error: str | None = None) -> dict:
    result = {
        "checked_at": _now_iso(),
        "cache": {"stale": False, "age_seconds": 0},
        "company": _unavailable(_COMPANY_FIELDS),
        "delivery": _unavailable(_DELIVERY_FIELDS),
        "validation": _unavailable(_VALIDATION_FIELDS),
        "supplement": _unavailable(_SUPPLEMENT_FIELDS),
        "supplement_delivery": _unavailable(_SUPPLEMENT_DELIVERY_FIELDS),
        "errors": [],
    }
    if error:
        result["errors"].append(error)
    return result


def _collect() -> dict:
    result = _empty()
    try:
        batch = _configured("OPS_PIPELINE_PROGRESS_BATCH_ID", DEFAULT_BATCH, _BATCH)
        validation_run = _configured("OPS_PIPELINE_PROGRESS_VALIDATION_RUN", DEFAULT_VALIDATION_RUN, _RUN)
        supplement_run = _configured("OPS_PIPELINE_PROGRESS_SUPPLEMENT_RUN", DEFAULT_SUPPLEMENT_RUN, _RUN)
        s3 = storage_client(bounded=True)
    except Exception:
        result["errors"].append("pipeline_storage_unavailable")
        return result

    calls = {
        "company": lambda: _company(s3),
        "delivery": lambda: _delivery(s3, batch),
        "validation": lambda: _validation(s3, validation_run, batch),
        "supplement": lambda: _supplement(s3, supplement_run),
        "supplement_delivery": lambda: _supplement_delivery(s3, supplement_run),
    }
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = {pool.submit(call): name for name, call in calls.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                value = future.result()
                warning = None
                if name in {"delivery", "validation", "supplement_delivery"}:
                    value, warning = value
                result[name] = value
                if warning:
                    result["errors"].append(warning)
            except Exception:
                result["errors"].append(f"{name}_unavailable")

    if result["validation"]["available"] and result["validation"]["total_clips"] is None:
        delivery = result["delivery"]
        if delivery["available"]:
            result["validation"]["total_clips"] = delivery["packaged_assets"]
    validation = result["validation"]
    delivery = result["delivery"]
    if (validation["available"] and validation["state"] == "PASS"
            and (not delivery["available"]
                 or validation["total_clips"] != delivery["packaged_assets"]
                 or validation["clip_reports"] != validation["total_clips"]
                 or validation["_files"] != delivery["total_files"]
                 or validation["_bytes"] != delivery["total_bytes"]
                 or validation["_recordings"] != delivery["recordings_processed"]
                 or not math.isclose(validation["_hours"], delivery["prepared_hours"], rel_tol=0, abs_tol=1e-12)
                 or validation["_delivery_ref"] != delivery["_ref"])):
        validation["state"] = "UNKNOWN"
        validation["stale"] = True
        result["errors"].append("validation_identity_mismatch")
    delivery.pop("_ref", None)
    for field in ("_delivery_ref", "_files", "_bytes", "_hours", "_recordings"):
        validation.pop(field, None)
    result["errors"].sort()
    result["checked_at"] = _now_iso()
    return result


async def _refresh() -> dict:
    global _cache, _cache_at
    value = await asyncio.to_thread(_collect)
    _cache = copy.deepcopy(value)
    _cache_at = time.monotonic()
    return value


async def pipeline_progress() -> dict:
    """Return one cached snapshot; a slow refresh never blocks beyond 12s."""
    global _refresh_task
    now = time.monotonic()
    if _cache is not None and now - _cache_at < CACHE_SECONDS:
        value = copy.deepcopy(_cache)
        value["cache"] = {"stale": False, "age_seconds": int(now - _cache_at)}
        return value

    async with _cache_lock:
        now = time.monotonic()
        if _cache is not None and now - _cache_at < CACHE_SECONDS:
            value = copy.deepcopy(_cache)
            value["cache"] = {"stale": False, "age_seconds": int(now - _cache_at)}
            return value
        if _refresh_task is None or _refresh_task.done():
            _refresh_task = asyncio.create_task(_refresh())
        task = _refresh_task

    try:
        value = copy.deepcopy(await asyncio.wait_for(asyncio.shield(task), REQUEST_TIMEOUT_SECONDS))
        value["cache"] = {"stale": False, "age_seconds": 0}
        return value
    except asyncio.TimeoutError:
        if _cache is None:
            return _empty(error="pipeline_refresh_timeout")
        age = max(0, int(time.monotonic() - _cache_at))
        value = copy.deepcopy(_cache)
        value["cache"] = {"stale": True, "age_seconds": age}
        if "pipeline_refresh_timeout" not in value["errors"]:
            value["errors"].append("pipeline_refresh_timeout")
            value["errors"].sort()
        return value


def reset_cache_for_tests() -> None:
    """Reset process-local cache. Tests only; production has no mutation route."""
    global _cache, _cache_at, _refresh_task
    if _refresh_task and not _refresh_task.done():
        _refresh_task.cancel()
    _cache = None
    _cache_at = 0.0
    _refresh_task = None
