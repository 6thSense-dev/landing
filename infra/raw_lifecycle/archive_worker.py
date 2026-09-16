#!/usr/bin/env python3
"""Archive complete, version-pinned originals; never delete or mutate jobs.

TASK_PLAN_REF is JSON {bucket,key,version_id,sha256}, pointing to immutable plan
JSON. ARCHIVE_WORKERS defaults to 2 and is limited to 2..4. Credentials come only
from boto3's default provider chain (the Batch job role in production).

Destination keys are originals/<sha256(canonical JSON {bucket,key,version_id})>/
<basename>. Every creation is conditional, including multipart completion, so a
concurrent or conflicting writer cannot be overwritten. Archive versioning must
be Enabled. Receipts are deterministic JSON, conditionally created and read back.
An operator must resolve any conflicting/corrupt object; this worker never fixes
one by overwriting it. Archive IAM should also deny deletion/overwrites to retain
these immutable versions. Hashing uses 8 MiB streaming buffers; server-side copy
parts run sequentially per object, with at most four objects active.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
import logging
import os
import re

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

ARCHIVE_BUCKET = "6thsense-archive-194680606079"
RAW_BUCKET = "6thsense-raw"
CHUNK_BYTES = 8 * 1024 * 1024
PART_BYTES = 512 * 1024 * 1024
JSON_LIMIT = 32 * 1024 * 1024
LOG = logging.getLogger(__name__)


class ArchiveError(RuntimeError):
    """Fail closed: no valid receipt may be issued."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def require_string(value, name):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ArchiveError(f"Invalid {name}")
    return value


def require_version(value):
    require_string(value, "version_id")
    if value == "null":
        raise ArchiveError("Unversioned objects are not immutable")
    return value


def validate_ref(ref):
    if not isinstance(ref, dict):
        raise ArchiveError("Object reference must be an object")
    for name in ("bucket", "key"):
        require_string(ref.get(name), name)
    require_version(ref.get("version_id"))
    return {name: ref[name] for name in ("bucket", "key", "version_id")}


def api_ref(ref):
    return {"Bucket": ref["bucket"], "Key": ref["key"], "VersionId": ref["version_id"]}


def check_response_version(response, expected):
    if response.get("VersionId") != expected:
        raise ArchiveError("S3 response did not match the pinned version")


def etag(value):
    return require_string(value, "etag").strip('"')


def read_json_bytes(s3, ref, limit=JSON_LIMIT):
    response = s3.get_object(**api_ref(ref))
    with closing(response["Body"]) as body:
        check_response_version(response, ref["version_id"])
        if response["ContentLength"] > limit:
            raise ArchiveError("JSON object exceeds size limit")
        payload = body.read(limit + 1)
    if len(payload) > limit or len(payload) != response["ContentLength"]:
        raise ArchiveError("JSON object has invalid length")
    return payload


def load_plan(s3, plan_ref):
    ref = validate_ref(plan_ref)
    expected = plan_ref.get("sha256", "")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ArchiveError("Plan reference requires lowercase sha256")
    payload = read_json_bytes(s3, ref)
    if hashlib.sha256(payload).hexdigest() != expected:
        raise ArchiveError("Plan SHA256 mismatch")
    plan = json.loads(payload)
    validate_plan(plan)
    return plan, {**ref, "sha256": expected}


def validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("schema") != "6thsense-archive-plan/1":
        raise ArchiveError("Unsupported archive plan schema")
    for name in ("recording", "fingerprint"):
        require_string(plan.get(name), name)
    if plan.get("archive_bucket") != ARCHIVE_BUCKET:
        raise ArchiveError("Unexpected archive bucket")
    if plan.get("receipt_key") != f"receipts/{plan['recording']}/{plan['fingerprint']}.json":
        raise ArchiveError("Receipt key is not bound to recording and fingerprint")
    objects = plan.get("objects")
    if not isinstance(objects, list) or not objects:
        raise ArchiveError("Plan must contain all recording objects")
    identities = set()
    for obj in objects:
        ref = validate_ref(obj)
        if ref["bucket"] != RAW_BUCKET or not ref["key"].startswith("sessions/") or ref["key"].endswith("/"):
            raise ArchiveError("Source must be an original file under Raw sessions/")
        if type(obj.get("bytes")) is not int or not 0 <= obj["bytes"] <= 5 * 1024**4:
            raise ArchiveError("Invalid source byte count")
        etag(obj.get("etag"))
        identity = tuple(ref.values())
        if identity in identities:
            raise ArchiveError("Duplicate source identity")
        identities.add(identity)


def identity_digest(source):
    """Shared resolver identity: UTF-8 sorted compact JSON of the three ref fields."""
    return hashlib.sha256(canonical(validate_ref(source))).hexdigest()


def destination_key(source):
    return f"originals/{identity_digest(source)}/{source['key'].rsplit('/', 1)[-1]}"


def head_optional(s3, bucket, key):
    try:
        return s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        # 403 can mean either denied or hidden missing: never treat it as absent.
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
            return None
        raise


def stream_hash(s3, ref, expected_bytes, expected_etag=None):
    response = s3.get_object(**api_ref(ref))
    digest = hashlib.sha256()
    count = 0
    with closing(response["Body"]) as body:
        check_response_version(response, ref["version_id"])
        if response["ContentLength"] != expected_bytes:
            raise ArchiveError("Object size differs from plan")
        if expected_etag is not None and etag(response["ETag"]) != etag(expected_etag):
            raise ArchiveError("Source ETag differs from plan")
        while True:
            chunk = body.read(CHUNK_BYTES)
            if not chunk:
                break
            count += len(chunk)
            if count > expected_bytes:
                raise ArchiveError("Object stream exceeds declared size")
            digest.update(chunk)
    if count != expected_bytes:
        raise ArchiveError("Object stream was truncated")
    return digest.hexdigest()


def source_metadata(source, digest):
    # Base64 keeps non-ASCII S3 keys safe in HTTP metadata headers.
    encode = lambda value: base64.b64encode(value.encode()).decode()
    return {
        "source-bucket": source["bucket"],
        "source-key-b64": encode(source["key"]),
        "source-version-b64": encode(source["version_id"]),
        "source-sha256": digest,
        "source-bytes": str(source["bytes"]),
    }


def copy_if_absent(s3, source, bucket, key, metadata):
    """Create atomically; return a competing winner for subsequent verification."""
    upload_id = None
    completed = False
    try:
        if source["bytes"] == 0:
            return s3.put_object(Bucket=bucket, Key=key, Body=b"", Metadata=metadata, IfNoneMatch="*")
        upload_id = s3.create_multipart_upload(Bucket=bucket, Key=key, Metadata=metadata)["UploadId"]
        # <= 10,000 parts even for the maximum permitted 5 TiB original.
        part_size = max(PART_BYTES, (source["bytes"] + 9999) // 10000)
        parts = []
        for number, start in enumerate(range(0, source["bytes"], part_size), 1):
            request = dict(
                Bucket=bucket, Key=key, UploadId=upload_id, PartNumber=number,
                CopySource=api_ref(source), CopySourceIfMatch=source["etag"],
            )
            # S3 only allows byte-range copy for source objects over 5 MiB.
            if source["bytes"] > part_size:
                request["CopySourceRange"] = f"bytes={start}-{min(start + part_size, source['bytes']) - 1}"
            copied = s3.upload_part_copy(**request)
            parts.append({"PartNumber": number, "ETag": copied["CopyPartResult"]["ETag"]})
        response = s3.complete_multipart_upload(
            Bucket=bucket, Key=key, UploadId=upload_id,
            MultipartUpload={"Parts": parts}, IfNoneMatch="*",
        )
        completed = True
        return response
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
            raise
        winner = head_optional(s3, bucket, key)
        if winner is None:
            raise ArchiveError("Conditional copy conflict without an existing object") from exc
        return winner
    finally:
        if upload_id is not None and not completed:
            try:
                s3.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)
            except ClientError:
                LOG.exception("Could not abort incomplete archive multipart upload")


def archive_object(s3, source, archive_bucket):
    digest = stream_hash(s3, source, source["bytes"], source["etag"])
    key = destination_key(source)
    metadata = source_metadata(source, digest)
    head = head_optional(s3, archive_bucket, key)
    if head is None:
        created = copy_if_absent(s3, source, archive_bucket, key, metadata)
        version = require_version(created.get("VersionId"))
        head = s3.head_object(Bucket=archive_bucket, Key=key, VersionId=version)
        check_response_version(head, version)
    version = require_version(head.get("VersionId"))
    if head.get("ContentLength") != source["bytes"] or any(head.get("Metadata", {}).get(k) != v for k, v in metadata.items()):
        raise ArchiveError("Conflicting archive destination identity or size")
    destination = {"bucket": archive_bucket, "key": key, "version_id": version}
    if stream_hash(s3, destination, source["bytes"], head["ETag"]) != digest:
        raise ArchiveError("Archive readback SHA256 mismatch")
    return {
        "source": {**validate_ref(source), "bytes": source["bytes"], "etag": source["etag"], "sha256": digest},
        "destination": {**destination, "bytes": source["bytes"], "etag": head["ETag"], "sha256": digest},
        "verified": True,
    }


def publish_receipt(s3, bucket, key, receipt):
    payload = canonical(receipt)
    if len(payload) > JSON_LIMIT:
        raise ArchiveError("Receipt exceeds JSON size limit")
    head = head_optional(s3, bucket, key)
    if head is None:
        try:
            head = s3.put_object(
                Bucket=bucket, Key=key, Body=payload, ContentType="application/json",
                Metadata={"sha256": hashlib.sha256(payload).hexdigest()}, IfNoneMatch="*",
            )
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 412:
                raise
            head = head_optional(s3, bucket, key)
            if head is None:
                raise ArchiveError("Receipt conflict without existing receipt") from exc
    ref = {"bucket": bucket, "key": key, "version_id": require_version(head.get("VersionId"))}
    if read_json_bytes(s3, ref) != payload:
        raise ArchiveError("Conflicting or corrupted archive receipt")
    return {**ref, "sha256": hashlib.sha256(payload).hexdigest()}


def publish_source_index(s3, bucket, obj, recording, receipt_key):
    key = f"source-index/{identity_digest(obj['source'])}.json"
    entry = {
        "schema": "6thsense-archive-source/1", "source": obj["source"],
        "destination": obj["destination"], "recording": recording,
        "receipt_key": receipt_key, "verified": True,
    }
    head = head_optional(s3, bucket, key)
    if head is not None:
        ref = {"bucket": bucket, "key": key, "version_id": require_version(head.get("VersionId"))}
        existing = json.loads(read_json_bytes(s3, ref))
        # An earlier complete plan can already index this exact immutable copy.
        if not isinstance(existing, dict) or any(existing.get(k) != entry[k] for k in ("schema", "source", "destination", "recording", "verified")):
            raise ArchiveError("Conflicting source resolver entry")
        require_string(existing.get("receipt_key"), "resolver receipt_key")
        return
    publish_receipt(s3, bucket, key, entry)


def run(s3, plan_ref, workers=2):
    if type(workers) is not int or not 2 <= workers <= 4:
        raise ArchiveError("ARCHIVE_WORKERS must be between 2 and 4")
    plan, pinned_plan = load_plan(s3, plan_ref)
    if s3.get_bucket_versioning(Bucket=plan["archive_bucket"]).get("Status") != "Enabled":
        raise ArchiveError("Archive bucket versioning must be Enabled")
    with ThreadPoolExecutor(max_workers=workers) as pool:
        # executor.map preserves exact input order; every planned object is required.
        objects = list(pool.map(lambda source: archive_object(s3, source, plan["archive_bucket"]), plan["objects"]))
    receipt = {
        "schema": "6thsense-archive-receipt/1", "recording": plan["recording"],
        "fingerprint": plan["fingerprint"], "plan_ref": pinned_plan,
        "objects": objects, "verified": True,
    }
    receipt_ref = publish_receipt(s3, plan["archive_bucket"], plan["receipt_key"], receipt)
    for obj in objects:
        publish_source_index(s3, plan["archive_bucket"], obj, plan["recording"], plan["receipt_key"])
    return {"verified": True, "recording": plan["recording"], "fingerprint": plan["fingerprint"], "receipt_ref": receipt_ref}


def main():
    logging.basicConfig(level=logging.INFO)
    s3 = boto3.client("s3", config=Config(retries={"mode": "standard", "max_attempts": 5}, max_pool_connections=8))
    result = run(s3, json.loads(os.environ["TASK_PLAN_REF"]), int(os.environ.get("ARCHIVE_WORKERS", "2")))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
