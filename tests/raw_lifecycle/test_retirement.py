import hashlib
import os
import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError


os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, str(Path(__file__).parents[2] / "infra/raw_lifecycle"))

import coordinator as c  # noqa: E402
import retirement as r  # noqa: E402


RECORDING = "ego_20260916_010203_A1B2C3"
KEY = f"sessions/session/{RECORDING}/video.mp4"


def source(version, body):
    return {
        "bucket": c.RAW,
        "key": KEY,
        "version_id": version,
        "bytes": len(body),
        "etag": f'"etag-{version}"',
        "sha256": hashlib.sha256(body).hexdigest(),
    }


def archived_item(src):
    return {
        "source": src,
        "destination": {
            "bucket": "archive",
            "key": f"originals/{src['version_id']}/video.mp4",
            "version_id": f"archive-{src['version_id']}",
            "bytes": src["bytes"],
            "sha256": src["sha256"],
        },
        "verified": True,
    }


def fixtures():
    historical = source("v1", b"historical video")
    current = source("v2", b"current video")
    items = [archived_item(historical), archived_item(current)]
    state = {
        "recording": RECORDING,
        "fingerprint": "f" * 64,
        "snapshot": [current],
        "phase": "imported",
        "archive_plan": {"archive_bucket": "archive", "objects": [historical, current]},
        "archive_receipt": {
            "bucket": "archive",
            "key": "receipts/recording/fingerprint.json",
            "version_id": "receipt-v1",
            "sha256": "receipt-sha",
        },
        "jobs": {},
    }
    receipt = {
        "schema": "6thsense-archive-receipt/1",
        "recording": RECORDING,
        "fingerprint": state["fingerprint"],
        "verified": True,
        "objects": items,
    }
    episode = {"recording": RECORDING, "deleted": False,
               "imports": [{"run_id": "clean-current", "sources": [current]}]}
    return state, receipt, episode, items


def aws_error(code):
    return ClientError({"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "test")


class RetirementS3:
    def __init__(self, items, *, newest="v2", corrupt_archive=None, already_deleted=()):
        self.items = items
        self.newest = newest
        self.corrupt_archive = corrupt_archive
        self.deleted = set(already_deleted)
        self.delete_calls = []
        self.archive_heads = []

    def head_object(self, Bucket, Key, VersionId=None):
        if Bucket == "archive":
            item = next(x for x in self.items if x["destination"]["key"] == Key)
            dst = item["destination"]
            self.archive_heads.append(dst["version_id"])
            digest = "corrupt" if dst["version_id"] == self.corrupt_archive else dst["sha256"]
            return {"VersionId": dst["version_id"], "ContentLength": dst["bytes"],
                    "Metadata": {"source-sha256": digest}}
        if VersionId is None:
            return {"VersionId": self.newest}
        if VersionId in self.deleted:
            raise aws_error("NoSuchVersion")
        return {"VersionId": VersionId}

    def delete_object(self, Bucket, Key, VersionId):
        self.delete_calls.append((Bucket, Key, VersionId))
        self.deleted.add(VersionId)
        return {"DeleteMarker": False}


def install_handler_fakes(monkeypatch, storage, state, receipt, episode):
    def read_json(bucket, key, version=None):
        if bucket == c.ARTIFACTS:
            return {"enabled": True, "retirement_enabled": True,
                    "run_deadline_epoch": 9_999_999_999}, {"sha256": "cfg"}
        if bucket == c.PROCESSED:
            return state, {"sha256": "state"}
        assert (bucket, key, version) == (
            state["archive_receipt"]["bucket"], state["archive_receipt"]["key"],
            state["archive_receipt"]["version_id"],
        )
        return receipt, {"sha256": state["archive_receipt"]["sha256"]}

    monkeypatch.setattr(c, "read_json", read_json)
    monkeypatch.setattr(c, "api", lambda *_: {"episodes": [episode]})
    monkeypatch.setattr(c, "job_status", lambda job: job["status"])
    monkeypatch.setattr(c, "now", lambda: "2026-09-16T00:00:00+00:00")
    monkeypatch.setattr(c, "s3", storage)


def test_missing_archive_member_blocks_retirement():
    state, receipt, _, _ = fixtures()
    receipt["objects"].pop()

    with pytest.raises(ValueError, match="Incomplete archive inventory"):
        r.validate_receipt(state, receipt)


@pytest.mark.parametrize("field,value", [("sha256", "0" * 64), ("bytes", 999)])
def test_clean_hash_or_size_mismatch_blocks_retirement(field, value):
    state, receipt, episode, _ = fixtures()
    episode["imports"][0]["sources"][0] = {**episode["imports"][0]["sources"][0], field: value}

    with pytest.raises(ValueError, match="not represented by imported Clean"):
        r.validate_imports(state, receipt, episode)


def test_every_archive_version_is_verified_before_any_raw_delete(monkeypatch):
    state, receipt, episode, items = fixtures()
    storage = RetirementS3(items, corrupt_archive="archive-v2")
    install_handler_fakes(monkeypatch, storage, state, receipt, episode)

    with pytest.raises(ValueError, match="Archive object is missing or changed"):
        r.handler({"recording": RECORDING, "fingerprint": state["fingerprint"]}, None)

    assert storage.archive_heads == ["archive-v1", "archive-v2"]
    assert storage.delete_calls == []


def test_new_current_source_version_prevents_any_raw_delete(monkeypatch):
    state, receipt, episode, items = fixtures()
    storage = RetirementS3(items, newest="v3")
    install_handler_fakes(monkeypatch, storage, state, receipt, episode)

    with pytest.raises(ValueError, match="New upload arrived"):
        r.handler({"recording": RECORDING, "fingerprint": state["fingerprint"]}, None)

    assert storage.delete_calls == []


def test_worker_metadata_and_partial_retry_allow_exact_version_cleanup(monkeypatch):
    state, receipt, episode, items = fixtures()
    storage = RetirementS3(items, already_deleted={"v1"})
    install_handler_fakes(monkeypatch, storage, state, receipt, episode)

    result = r.handler({"recording": RECORDING, "fingerprint": state["fingerprint"]}, None)

    assert result["retired"] is True
    assert [call[2] for call in storage.delete_calls] == ["v1", "v2"]
    assert storage.archive_heads == ["archive-v1", "archive-v2"]
