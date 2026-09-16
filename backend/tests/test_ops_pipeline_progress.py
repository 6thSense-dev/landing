"""Read-only pipeline progress is scoped, honest, and safe for the ops UI."""
from __future__ import annotations

import io
import hashlib
import json
import time
from datetime import datetime, timezone

import pytest
from botocore.exceptions import ClientError

from app.core import ops_pipeline_progress as progress
from tests.test_ops_routes import app, _client, _sid  # noqa: F401 - imported pytest fixture


class Storage:
    def __init__(self):
        self.objects = {}
        self.calls = []

    def add(self, bucket, key, value, *, modified=None):
        body = json.dumps(value).encode()
        self.objects[bucket, key] = (body, modified or datetime.now(timezone.utc))

    def get_object(self, Bucket, Key):
        self.calls.append(("GET", Bucket, Key))
        assert Bucket != "6thsense-raw", "Progress endpoint attempted a Raw read"
        try:
            body, modified = self.objects[Bucket, Key]
        except KeyError as exc:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject") from exc
        return {"Body": io.BytesIO(body), "ContentLength": len(body), "LastModified": modified,
                "VersionId": "version-" + str(abs(hash((Bucket, Key))))}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys, ContinuationToken=None):
        self.calls.append(("LIST", Bucket, Prefix))
        assert Bucket != "6thsense-raw", "Progress endpoint attempted a Raw read"
        assert ContinuationToken is None
        rows = [
            {"Key": key, "Size": len(body), "LastModified": modified}
            for (bucket, key), (body, modified) in sorted(self.objects.items())
            if bucket == Bucket and key.startswith(Prefix)
        ]
        assert len(rows) <= MaxKeys
        return {"Contents": rows, "IsTruncated": False}


def add_config(storage):
    storage.add(progress.DEPLOY_BUCKET, progress.CONFIG_KEY,
                {"enabled": True, "retirement_enabled": True, "api_url": "https://private.invalid"})


def add_state(storage, recording, phase, *, archive=False, imports=False, country="korea"):
    value = {
        "recording": recording,
        "phase": phase,
        "country": country,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "private_source": "s3://6thsense-raw/do-not-expose",
    }
    if archive:
        value["archive_receipt"] = {"bucket": "private", "key": "secret"}
    if imports:
        value["imports"] = [{"run_id": "private-run"}]
    storage.add("6thsense-processed", progress.STATE_PREFIX + recording + ".json", value)


def delivery(*, complete=True, matching=True):
    return {
        "schema": "6thsense-sieve-delivery-status/1",
        "batch_id": progress.DEFAULT_BATCH,
        "status": "delivered_checksums_verified" if complete else "transferring",
        "recordings_processed": 45 if matching else 44,
        "recordings_expected": 45,
        "packaged_assets": 325,
        "uploaded_assets": 325,
        "uploaded_files": 2600,
        "delivery_files": 2600,
        "uploaded_bytes": 895_561_232_011,
        "delivery_bytes": 895_561_232_011,
        "prepared_unique_hours": 6.0326632672,
        "external_transfer_completed": complete,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "destination_url": "https://private.invalid/bearer-secret",
    }


def supplement():
    return {
        "schema": "6thsense-private-originals-summary/1",
        "status": "READY_FOR_REVIEW",
        "recordings": [
            {"recording": "ego_20260916_072659_16A4A5", "private_key": "secret"},
            {"recording": "ego_20260916_110043_16A4A5", "private_key": "secret"},
        ],
        "retained_hours": "1.25",
        "original_bytes": 123456,
        "external_delivery_performed": False,
    }


def full_storage():
    storage = Storage()
    add_config(storage)
    add_state(storage, "ego_20260901_010101_AAAAAA", "imported", archive=True, country="korea")
    storage.add("6thsense-sieve", f"reports/{progress.DEFAULT_BATCH}/delivery/status.json", delivery())
    validation_prefix = (progress.LIFECYCLE_PREFIX + "audit/sieve-validation/"
                         + progress.DEFAULT_VALIDATION_RUN + "/")
    storage.add("6thsense-processed", validation_prefix + "FINAL-STATUS.json",
                {"technical_status": "RUNNING", "at": datetime.now(timezone.utc).isoformat()})
    storage.add("6thsense-processed", validation_prefix + "assets/0000000001.json",
                {"technical_status": "FAIL", "private": "not surfaced"})
    storage.add("6thsense-processed", validation_prefix + "assets/0000000002.json",
                {"technical_status": "PASS", "private": "not surfaced"})
    storage.add("6thsense-processed", validation_prefix + "assets/README.txt", "ignored")
    storage.add("6thsense-sieve",
                f"originals-review/{progress.DEFAULT_SUPPLEMENT_RUN}/_audit/summary.json",
                supplement())
    return storage


def test_company_counts_every_country_and_keeps_categories_honest(monkeypatch):
    storage = Storage()
    add_config(storage)
    add_state(storage, "ego_20260901_010101_AAAAAA", "imported", archive=True, country="korea")
    add_state(storage, "ego_20260901_020202_BBBBBB", "hold", archive=True, country="china")
    add_state(storage, "ego_20260901_030303_CCCCCC", "processing", country="india")
    add_state(storage, "ego_20260901_040404_DDDDDD", "deleted", country="vietnam")
    add_state(storage, "ego_20260901_050505_EEEEEE", "custom-old-phase", imports=True, country="unknown")

    result = progress._company(storage)

    assert result == {
        "available": True,
        "source_groups": 5,
        "archived": 2,
        "clean_complete": 2,
        "in_progress": 1,
        "held": 1,
        "deleted": 1,
        "updated_at": result["updated_at"],
        "stale": False,
    }
    assert {bucket for _, bucket, _ in storage.calls} == {
        progress.DEPLOY_BUCKET, "6thsense-processed"
    }


@pytest.mark.parametrize("matching,expected_state,uploaded_hours,error", [
    (True, "DELIVERED_CHECKSUMS_VERIFIED", 6.0326632672, None),
    (False, "INCONSISTENT", None, "delivery_totals_mismatch"),
])
def test_uploaded_hours_require_completed_exact_totals(matching, expected_state, uploaded_hours, error):
    storage = Storage()
    storage.add("6thsense-sieve", f"reports/{progress.DEFAULT_BATCH}/delivery/status.json",
                delivery(matching=matching))
    result, warning = progress._delivery(storage, progress.DEFAULT_BATCH)
    assert result["complete"] is matching
    assert result["state"] == expected_state
    assert result["uploaded_hours"] == uploaded_hours
    assert warning == error


@pytest.mark.parametrize("mutate", [
    lambda value: value.update(status="failed"),
    lambda value: value.update(recordings_processed=0, recordings_expected=0,
                               packaged_assets=0, uploaded_assets=0,
                               uploaded_files=0, delivery_files=0,
                               uploaded_bytes=0, delivery_bytes=0),
    lambda value: value.update(uploaded_files=value["delivery_files"] + 1),
])
def test_completed_delivery_rejects_contradictory_empty_or_nonmonotonic_totals(mutate):
    storage = Storage()
    value = delivery()
    mutate(value)
    storage.add("6thsense-sieve", f"reports/{progress.DEFAULT_BATCH}/delivery/status.json", value)
    result, warning = progress._delivery(storage, progress.DEFAULT_BATCH)
    assert result["complete"] is False
    assert result["uploaded_hours"] is None
    assert result["state"] == "INCONSISTENT"
    assert warning == "delivery_totals_mismatch"


def test_validation_pass_requires_real_producer_proof_and_report_count(monkeypatch):
    storage = full_storage()
    prefix = (progress.LIFECYCLE_PREFIX + "audit/sieve-validation/"
              + progress.DEFAULT_VALIDATION_RUN + "/")
    status_key = f"reports/{progress.DEFAULT_BATCH}/delivery/status.json"
    storage.add("6thsense-sieve", status_key, delivery())
    delivery_response = storage.get_object(Bucket="6thsense-sieve", Key=status_key)
    delivery_body = storage.objects["6thsense-sieve", status_key][0]
    storage.add("6thsense-processed", prefix + "FINAL-STATUS.json",
                {"technical_status": "PASS", "human_review": "PENDING", "files": 16,
                 "unique_hours": 1.25, "at": datetime.now(timezone.utc).isoformat()})
    storage.add("6thsense-processed", prefix + "FINAL-VALIDATION.json", {
        "schema": progress.VALIDATION_STATUS_SCHEMA,
        "technical_status": "PASS",
        "delivery_status_ref": {"key": status_key,
                                "version_id": delivery_response["VersionId"],
                                "sha256": hashlib.sha256(delivery_body).hexdigest(),
                                "size_bytes": len(delivery_body)},
        "assets": 2,
        "files": 16,
        "bytes": 1234,
        "unique_hours": 1.25,
        "recordings_processed": 2,
    })
    result, warning = progress._validation(
        storage, progress.DEFAULT_VALIDATION_RUN, progress.DEFAULT_BATCH)
    assert result["state"] == "PASS"
    assert result["clip_reports"] == result["total_clips"] == 2
    assert warning is None

    bad = dict(json.loads(storage.objects["6thsense-processed", prefix + "FINAL-VALIDATION.json"][0]))
    bad["delivery_status_ref"] = {**bad["delivery_status_ref"], "key": "reports/other/delivery/status.json"}
    storage.add("6thsense-processed", prefix + "FINAL-VALIDATION.json", bad)
    result, warning = progress._validation(
        storage, progress.DEFAULT_VALIDATION_RUN, progress.DEFAULT_BATCH)
    assert result["state"] == "UNKNOWN"
    assert warning == "validation_identity_mismatch"


def test_collect_exposes_pass_only_when_producer_proof_matches_current_delivery(monkeypatch):
    storage = full_storage()
    status_key = f"reports/{progress.DEFAULT_BATCH}/delivery/status.json"
    delivered = delivery()
    delivered.update(recordings_processed=2, recordings_expected=2,
                     packaged_assets=2, uploaded_assets=2,
                     uploaded_files=16, delivery_files=16,
                     uploaded_bytes=1234, delivery_bytes=1234,
                     prepared_unique_hours=1.25)
    storage.add("6thsense-sieve", status_key, delivered)
    body = storage.objects["6thsense-sieve", status_key][0]
    version = storage.get_object(Bucket="6thsense-sieve", Key=status_key)["VersionId"]
    prefix = (progress.LIFECYCLE_PREFIX + "audit/sieve-validation/"
              + progress.DEFAULT_VALIDATION_RUN + "/")
    storage.add("6thsense-processed", prefix + "FINAL-STATUS.json",
                {"technical_status": "PASS", "human_review": "PENDING", "files": 16,
                 "unique_hours": 1.25, "at": datetime.now(timezone.utc).isoformat()})
    storage.add("6thsense-processed", prefix + "FINAL-VALIDATION.json", {
        "schema": progress.VALIDATION_STATUS_SCHEMA,
        "technical_status": "PASS",
        "delivery_status_ref": {"key": status_key, "version_id": version,
                                "sha256": hashlib.sha256(body).hexdigest(),
                                "size_bytes": len(body)},
        "assets": 2, "files": 16, "bytes": 1234, "unique_hours": 1.25,
        "recordings_processed": 2,
    })
    monkeypatch.setattr(progress, "storage_client", lambda **_kwargs: storage)
    result = progress._collect()
    assert result["validation"]["state"] == "PASS"
    assert result["validation"]["clip_reports"] == result["validation"]["total_clips"] == 2
    assert "validation_identity_mismatch" not in result["errors"]
    assert "_delivery_ref" not in json.dumps(result)


def test_collect_keeps_partial_sections_and_never_exposes_paths(monkeypatch):
    storage = full_storage()
    # A malformed private summary must affect only its section.
    storage.add("6thsense-sieve",
                f"originals-review/{progress.DEFAULT_SUPPLEMENT_RUN}/_audit/summary.json",
                {"schema": "wrong", "secret": "bearer-value"})
    monkeypatch.setattr(progress, "storage_client", lambda **_kwargs: storage)

    result = progress._collect()

    assert result["company"]["available"] is True
    assert result["delivery"]["complete"] is True
    assert result["validation"] == {
        "available": True,
        "state": "RUNNING",
        "clip_reports": 2,
        "total_clips": 325,
        "updated_at": result["validation"]["updated_at"],
        "stale": False,
    }
    assert result["supplement"]["available"] is False
    assert result["supplement"]["recordings"] is None
    assert result["errors"] == ["supplement_unavailable"]
    encoded = json.dumps(result)
    assert "s3://" not in encoded
    assert "https://" not in encoded
    assert "secret" not in encoded.lower()
    assert all(bucket != "6thsense-raw" for _, bucket, _ in storage.calls)


def test_malformed_delivery_has_nulls_instead_of_fabricated_zero(monkeypatch):
    storage = full_storage()
    storage.add("6thsense-sieve", f"reports/{progress.DEFAULT_BATCH}/delivery/status.json",
                {"schema": "wrong", "uploaded_files": 0})
    monkeypatch.setattr(progress, "storage_client", lambda **_kwargs: storage)
    result = progress._collect()
    assert result["delivery"]["available"] is False
    assert result["delivery"]["uploaded_files"] is None
    assert result["delivery"]["prepared_hours"] is None
    assert "delivery_unavailable" in result["errors"]


@pytest.mark.asyncio
async def test_cache_singleflights_concurrent_refreshes(monkeypatch):
    progress.reset_cache_for_tests()
    calls = []

    def collect():
        calls.append(1)
        time.sleep(0.05)
        return progress._empty()

    monkeypatch.setattr(progress, "_collect", collect)
    first, second = await __import__("asyncio").gather(
        progress.pipeline_progress(), progress.pipeline_progress())
    assert len(calls) == 1
    assert first == second
    progress.reset_cache_for_tests()


@pytest.mark.asyncio
async def test_pipeline_route_is_ops_only_and_returns_sanitized_snapshot(app, db_session, monkeypatch):
    expected = progress._empty()

    async def snapshot():
        return expected

    monkeypatch.setattr(progress, "pipeline_progress", snapshot)
    guest = await _sid(db_session, "guest")
    ops = await _sid(db_session, "ops")
    async with _client(app) as client:
        assert (await client.get("/api/ops/sieve/pipeline")).status_code == 401
        assert (await client.get("/api/ops/sieve/pipeline", cookies={"sid": guest})).status_code == 403
        response = await client.get("/api/ops/sieve/pipeline", cookies={"sid": ops})
    assert response.status_code == 200
    assert response.json() == expected


def supplement_delivery(**changes):
    value = {
        "schema": "6thsense-supplement-delivery-status/1",
        "run_id": progress.DEFAULT_SUPPLEMENT_RUN, "batch_id": progress.DEFAULT_SUPPLEMENT_RUN,
        "manifest_sha256": progress.SUPPLEMENT_MANIFEST_SHA256, "status": "UPLOADED_FOR_CUSTOMER_QC",
        "total_files": 604, "uploaded_files": 604,
        "total_bytes": 25394461079, "uploaded_bytes": 25394461079,
        "potential_unique_technical_hours": "4.696644566",
        "external_transfer_completed": True, "customer_accepted": False,
        "human_review": "PENDING", "updated_at": datetime.now(timezone.utc).isoformat(),
        "destination_url": "https://private.invalid/secret", "source_key": "s3://private/secret",
    }
    value.update(changes)
    return value


def add_supplement_delivery(storage, **changes):
    storage.add("6thsense-sieve", f"reports/{progress.DEFAULT_SUPPLEMENT_RUN}/delivery/status.json",
                supplement_delivery(**changes))


def test_missing_supplement_transfer_is_optional_and_does_not_change_staging(monkeypatch):
    storage = full_storage()
    monkeypatch.setattr(progress, "storage_client", lambda **_kwargs: storage)
    result = progress._collect()
    assert result["supplement_delivery"]["available"] is False
    assert result["supplement_delivery"]["uploaded_hours"] is None
    assert result["supplement"]["external_delivery_performed"] is False
    assert result["errors"] == []


@pytest.mark.parametrize("state", ["PREPARING", "UPLOADING", "FAILED"])
def test_partial_or_failed_supplement_never_counts_uploaded_hours(state):
    storage = Storage()
    add_supplement_delivery(storage, status=state, uploaded_files=20, uploaded_bytes=100,
                            external_transfer_completed=False)
    result, warning = progress._supplement_delivery(storage, progress.DEFAULT_SUPPLEMENT_RUN)
    assert result["state"] == state
    assert result["uploaded_files"] == 20
    assert result["uploaded_hours"] is None
    assert result["complete"] is result["external_transfer_completed"] is False
    assert warning is None


def test_complete_supplement_is_separate_sanitized_customer_qc_transfer(monkeypatch):
    storage = full_storage()
    add_supplement_delivery(storage)
    monkeypatch.setattr(progress, "storage_client", lambda **_kwargs: storage)
    result = progress._collect()
    transfer = result["supplement_delivery"]
    assert transfer["complete"] is transfer["external_transfer_completed"] is True
    assert transfer["uploaded_hours"] == 4.696644566
    assert transfer["customer_accepted"] is False and transfer["human_review"] == "PENDING"
    assert result["supplement"]["external_delivery_performed"] is False
    assert result["delivery"]["uploaded_hours"] == 6.0326632672
    assert not any(token in json.dumps(result) for token in ["secret", "s3://", "https://"])


@pytest.mark.parametrize("changes", [
    {"uploaded_files": 603}, {"uploaded_bytes": 1}, {"total_files": 603, "uploaded_files": 603},
    {"total_bytes": 0, "uploaded_bytes": 0}, {"total_bytes": 123, "uploaded_bytes": 123}, {"uploaded_files": 605},
    {"potential_unique_technical_hours": 50}, {"status": "FAILED"},
    {"external_transfer_completed": False},
])
def test_contradictory_supplement_receipt_cannot_claim_completion(changes):
    storage = Storage()
    add_supplement_delivery(storage, **changes)
    result, warning = progress._supplement_delivery(storage, progress.DEFAULT_SUPPLEMENT_RUN)
    assert result["state"] == "INCONSISTENT"
    assert result["complete"] is result["external_transfer_completed"] is False
    assert result["uploaded_hours"] is None
    assert warning == "supplement_delivery_totals_mismatch"


@pytest.mark.parametrize("changes", [
    {"run_id": "other"}, {"batch_id": "other"}, {"schema": "other"},
    {"manifest_sha256": "secret"}, {"manifest_sha256": "a" * 64}, {"customer_accepted": True}, {"human_review": "PASS"},
    {"uploaded_files": True}, {"uploaded_bytes": -1}, {"status": "secret/path"},
    {"external_transfer_completed": "true"}, {"updated_at": "not-time"},
    {"potential_unique_technical_hours": "NaN"},
])
def test_malformed_supplement_transfer_fails_only_its_section(monkeypatch, changes):
    storage = full_storage()
    add_supplement_delivery(storage, **changes)
    monkeypatch.setattr(progress, "storage_client", lambda **_kwargs: storage)
    result = progress._collect()
    assert result["supplement_delivery"]["available"] is False
    assert result["supplement_delivery"]["uploaded_files"] is None
    assert result["delivery"]["complete"] is True
    assert result["errors"] == ["supplement_delivery_unavailable"]


def test_denied_supplement_status_is_not_treated_as_missing():
    class Denied:
        def get_object(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
    with pytest.raises(ClientError):
        progress._supplement_delivery(Denied(), progress.DEFAULT_SUPPLEMENT_RUN)
