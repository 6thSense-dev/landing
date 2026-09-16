import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import threading

import pytest
from botocore.exceptions import ClientError

SPEC = importlib.util.spec_from_file_location("archive_worker", Path(__file__).parents[2] / "infra/raw_lifecycle/archive_worker.py")
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)


def error(status):
    return ClientError({"Error": {"Code": str(status)}, "ResponseMetadata": {"HTTPStatusCode": status}}, "test")


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.latest = {}
        self.uploads = {}
        self.calls = []
        self.lock = threading.RLock()
        self.denied = set()
        self.corrupt_copy = False
        self.race_copy = False
        self.versioning = "Enabled"

    def seed(self, bucket, key, body, metadata=None):
        with self.lock:
            version = f"v{len(self.objects) + 1}"
            value = {"VersionId": version, "ContentLength": len(body), "ETag": '"' + hashlib.md5(body).hexdigest() + '"', "Metadata": metadata or {}, "data": body}
            self.objects[bucket, key, version] = value
            self.latest[bucket, key] = version
            return {"bucket": bucket, "key": key, "version_id": version, "sha256": hashlib.sha256(body).hexdigest()}

    def get_bucket_versioning(self, **kwargs):
        return {"Status": self.versioning}

    def head_object(self, Bucket, Key, VersionId=None):
        self.calls.append(("head", Bucket, Key, VersionId))
        if (Bucket, Key) in self.denied:
            raise error(403)
        version = VersionId or self.latest.get((Bucket, Key))
        if (Bucket, Key, version) not in self.objects:
            raise error(404)
        return {k: copy.deepcopy(v) for k, v in self.objects[Bucket, Key, version].items() if k != "data"}

    def get_object(self, Bucket, Key, VersionId):
        self.calls.append(("get", Bucket, Key, VersionId))
        head = self.head_object(Bucket, Key, VersionId)
        return {**head, "Body": io.BytesIO(self.objects[Bucket, Key, VersionId]["data"])}

    def put_object(self, Bucket, Key, Body, Metadata=None, IfNoneMatch=None, **kwargs):
        assert IfNoneMatch == "*"
        with self.lock:
            if (Bucket, Key) in self.latest:
                raise error(412)
            self.calls.append(("put", Bucket, Key))
            ref = self.seed(Bucket, Key, Body, Metadata)
            return {"VersionId": ref["version_id"]}

    def create_multipart_upload(self, **kwargs):
        with self.lock:
            upload = f"upload-{len(self.uploads) + 1}"
            self.uploads[upload] = {**kwargs, "parts": []}
            self.calls.append(("create", kwargs["Bucket"], kwargs["Key"]))
            return {"UploadId": upload}

    def upload_part_copy(self, **kwargs):
        self.calls.append(("copy", kwargs))
        source = kwargs["CopySource"]
        obj = self.objects[source["Bucket"], source["Key"], source["VersionId"]]
        assert kwargs["CopySourceIfMatch"] == obj["ETag"]
        body = obj["data"]
        if "CopySourceRange" in kwargs:
            start, end = map(int, kwargs["CopySourceRange"].removeprefix("bytes=").split("-"))
            body = body[start:end + 1]
        self.uploads[kwargs["UploadId"]]["parts"].append(body)
        return {"CopyPartResult": {"ETag": f'"part{kwargs["PartNumber"]}"'}}

    def complete_multipart_upload(self, **kwargs):
        assert kwargs["IfNoneMatch"] == "*"
        upload = self.uploads[kwargs["UploadId"]]
        body = b"".join(upload["parts"])
        if self.corrupt_copy:
            body = bytes([body[0] ^ 1]) + body[1:]
        if self.race_copy:
            self.race_copy = False
            self.seed(kwargs["Bucket"], kwargs["Key"], body, upload["Metadata"])
        return self.put_object(Bucket=kwargs["Bucket"], Key=kwargs["Key"], Body=body, Metadata=upload["Metadata"], IfNoneMatch="*")

    def abort_multipart_upload(self, **kwargs):
        self.calls.append(("abort", kwargs["UploadId"]))


def fixture_plan():
    s3 = MemoryS3()
    objects = []
    for name, payload in [("metadata.json", b'{"duration":600}'), ("full.mp4", b"full original video bytes"), ("calibration.json", b"calibration"), ("sidecar.csv", b"1,2,3"), ("empty.bin", b"")]:
        ref = s3.seed(w.RAW_BUCKET, f"sessions/session/recording/{name}", payload)
        objects.append({**w.validate_ref(ref), "bytes": len(payload), "etag": s3.head_object(**w.api_ref(ref))["ETag"]})
    plan = {"schema": "6thsense-archive-plan/1", "recording": "recording", "fingerprint": "f" * 64, "archive_bucket": w.ARCHIVE_BUCKET, "objects": objects, "receipt_key": f"receipts/recording/{'f' * 64}.json"}
    ref = s3.seed(w.ARCHIVE_BUCKET, "plans/test.json", w.canonical(plan))
    return s3, plan, ref


def receipt_for(s3, result):
    return json.loads(w.read_json_bytes(s3, result["receipt_ref"]))


def test_all_originals_preserved_and_retry_reuses_verified_versions():
    s3, plan, ref = fixture_plan()
    first = w.run(s3, ref)
    receipt = receipt_for(s3, first)
    assert receipt["verified"] is True
    assert receipt["fingerprint"] == plan["fingerprint"]
    assert [w.validate_ref(o["source"]) for o in receipt["objects"]] == [w.validate_ref(o) for o in plan["objects"]]
    for obj in receipt["objects"]:
        source, destination = obj["source"], obj["destination"]
        assert s3.objects[tuple(w.validate_ref(source).values())]["data"] == s3.objects[tuple(w.validate_ref(destination).values())]["data"]
        key = f"source-index/{w.identity_digest(source)}.json"
        index_ref = {"bucket": w.ARCHIVE_BUCKET, "key": key, "version_id": s3.latest[w.ARCHIVE_BUCKET, key]}
        assert json.loads(w.read_json_bytes(s3, index_ref))["destination"] == destination
    writes = len([c for c in s3.calls if c[0] in {"put", "create"}])
    assert w.run(s3, ref) == first
    assert len([c for c in s3.calls if c[0] in {"put", "create"}]) == writes


@pytest.mark.parametrize("failed_operation", ["put_object", "get_object"])
def test_source_index_failure_withholds_receipt_and_retry_reuses_versions(monkeypatch, failed_operation):
    s3, plan, ref = fixture_plan()
    index_keys = [f"source-index/{w.identity_digest(obj)}.json" for obj in plan["objects"]]
    original_operation = getattr(s3, failed_operation)

    def fail_middle_index(**kwargs):
        if kwargs["Bucket"] == w.ARCHIVE_BUCKET and kwargs["Key"] == index_keys[2]:
            raise error(503)
        return original_operation(**kwargs)

    monkeypatch.setattr(s3, failed_operation, fail_middle_index)
    with pytest.raises(ClientError):
        w.run(s3, ref)

    assert (w.ARCHIVE_BUCKET, plan["receipt_key"]) not in s3.latest
    assert not any(c[0] == "put" and c[2] == plan["receipt_key"] for c in s3.calls)
    assert (w.ARCHIVE_BUCKET, index_keys[0]) in s3.latest
    existing = {key: version for key, version in s3.latest.items()
                if key[0] == w.ARCHIVE_BUCKET and key[1].startswith(("originals/", "source-index/"))}
    assert sum(key[1].startswith("originals/") for key in existing) == len(plan["objects"])

    monkeypatch.setattr(s3, failed_operation, original_operation)
    result = w.run(s3, ref)
    assert result["verified"] is True
    assert all(s3.latest[key] == version for key, version in existing.items())
    assert all((w.ARCHIVE_BUCKET, key) in s3.latest for key in index_keys)
    assert [c for c in s3.calls if c[0] == "put"][-1][2] == plan["receipt_key"]
    count = len(s3.objects)
    assert w.run(s3, ref) == result
    assert len(s3.objects) == count


def test_source_version_is_pinned_even_if_latest_changes():
    s3, plan, ref = fixture_plan()
    source = plan["objects"][1]
    s3.seed(source["bucket"], source["key"], b"newer unapproved bytes")
    receipt = receipt_for(s3, w.run(s3, ref))
    archived = receipt["objects"][1]["destination"]
    assert s3.objects[tuple(w.validate_ref(archived).values())]["data"] == b"full original video bytes"
    assert all(c[1]["CopySource"]["VersionId"] for c in s3.calls if c[0] == "copy")


@pytest.mark.parametrize("retry", [False, True])
def test_corruption_never_publishes_new_receipt(retry):
    s3, plan, ref = fixture_plan()
    if retry:
        first = w.run(s3, ref)
        dest = receipt_for(s3, first)["objects"][1]["destination"]
        obj = s3.objects[tuple(w.validate_ref(dest).values())]
        obj["data"] = b"X" * obj["ContentLength"]
    else:
        s3.corrupt_copy = True
    before = len([c for c in s3.calls if c[0] == "put" and c[2] == plan["receipt_key"]])
    with pytest.raises(w.ArchiveError, match="SHA256"):
        w.run(s3, ref)
    assert len([c for c in s3.calls if c[0] == "put" and c[2] == plan["receipt_key"]]) == before


def test_denied_destination_is_not_treated_as_missing():
    s3, plan, ref = fixture_plan()
    key = w.destination_key(plan["objects"][0])
    s3.denied.add((w.ARCHIVE_BUCKET, key))
    with pytest.raises(ClientError):
        w.run(s3, ref)
    assert not any(c[0] == "create" and c[2] == key for c in s3.calls)
    assert (w.ARCHIVE_BUCKET, plan["receipt_key"]) not in s3.latest


def test_conflicting_identity_is_not_overwritten():
    s3, plan, ref = fixture_plan()
    key = w.destination_key(plan["objects"][0])
    collision = s3.seed(w.ARCHIVE_BUCKET, key, b"conflicting")
    with pytest.raises(w.ArchiveError, match="Conflicting archive"):
        w.run(s3, ref)
    assert s3.latest[w.ARCHIVE_BUCKET, key] == collision["version_id"]


def test_concurrent_matching_copy_is_verified_and_multipart_aborted():
    s3, plan, ref = fixture_plan()
    s3.race_copy = True
    assert w.run(s3, ref)["verified"]
    assert any(c[0] == "abort" for c in s3.calls)


def test_large_copy_uses_version_pinned_bounded_ranges():
    s3 = MemoryS3()
    source = {"bucket": w.RAW_BUCKET, "key": "sessions/rec/big.mp4", "version_id": "v1", "bytes": 6 * 1024**3, "etag": '"original"'}
    requests = []
    s3.upload_part_copy = lambda **kwargs: requests.append(kwargs) or {"CopyPartResult": {"ETag": '"part"'}}
    s3.complete_multipart_upload = lambda **kwargs: {"VersionId": "copied"} if kwargs["IfNoneMatch"] == "*" else None
    w.copy_if_absent(s3, source, w.ARCHIVE_BUCKET, "originals/big", {})
    assert len(requests) == 12
    assert requests[0]["CopySourceRange"] == "bytes=0-536870911"
    assert requests[-1]["CopySourceRange"] == "bytes=5905580032-6442450943"
    assert all(r["CopySource"] == w.api_ref(source) for r in requests)


@pytest.mark.parametrize("mutation", ["hash", "null-version", "etag", "size", "versioning"])
def test_invalid_plan_or_source_fails_closed(mutation):
    s3, plan, ref = fixture_plan()
    if mutation == "hash":
        ref["sha256"] = "0" * 64
    elif mutation == "versioning":
        s3.versioning = "Suspended"
    else:
        field, value = {"null-version": ("version_id", "null"), "etag": ("etag", '"wrong"'), "size": ("bytes", 999)}[mutation]
        plan["objects"][0][field] = value
        ref = s3.seed(w.ARCHIVE_BUCKET, "plans/test.json", w.canonical(plan))
    with pytest.raises(w.ArchiveError):
        w.run(s3, ref)
    assert (w.ARCHIVE_BUCKET, plan["receipt_key"]) not in s3.latest


def test_conflicting_receipt_is_never_overwritten():
    s3, plan, ref = fixture_plan()
    old = s3.seed(w.ARCHIVE_BUCKET, plan["receipt_key"], b'{"verified":false}')
    with pytest.raises(w.ArchiveError, match="receipt"):
        w.run(s3, ref)
    assert s3.latest[w.ARCHIVE_BUCKET, plan["receipt_key"]] == old["version_id"]
