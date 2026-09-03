#!/usr/bin/env python3
"""Sync a built catalog bundle to the private S3 bucket.

The bundle is whatever ``catalog_ingest build`` produced::

    bundle/
      catalog.json
      clips/<id>.json
      posters/<id>.jpg
      previews/<id>.mp4          (optional, muted hover loop)
      video/<id>.mp4             (the encoded clip the guest actually watches)
      imu/<id>.f32               (optional, full-rate IMU sidecar)

Everything lands under ``--prefix`` (default ``v1/``) so a re-cut of the
corpus can be staged as ``v2/`` and switched over atomically by flipping
``CATALOG_S3_PREFIX`` -- no destructive overwrite of a bundle a buyer is
currently browsing. Full packages under ``media/`` or ``archives/`` belong in
the processed tier and are refused by default; the ingestion pipeline publishes
those files.

Content types matter: S3 serves what we tell it, and a video/mp4 served as
application/octet-stream will not stream in Safari.

Usage::

    python3 scripts/catalog/upload_bundle.py --bundle out/bundle --prefix v1/
    python3 scripts/catalog/upload_bundle.py --bundle out/bundle --dry-run
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
from pathlib import Path

try:
    import boto3
    from boto3.s3.transfer import TransferConfig
    from botocore.config import Config as BotoConfig
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - dependency hint
    sys.exit("boto3 is required:  python3 -m pip install boto3")


CONTENT_TYPES = {
    ".json": "application/json",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".csv": "text/csv",
    ".f32": "application/octet-stream",
    ".npz": "application/octet-stream",
    ".md": "text/markdown",
    ".txt": "text/plain",
}

# The manifest changes every rebuild; the media is content-addressed by clip id
# and effectively immutable. Cache accordingly -- but note these only reach the
# browser via presigned URLs, whose own expiry caps real-world caching.
CACHE_CONTROL = {
    ".json": "no-cache",
}
DEFAULT_CACHE_CONTROL = "public, max-age=31536000, immutable"


def _multipart_etag(path: Path, chunk: int) -> str:
    """S3's ETag for a multipart upload of `path` at `chunk` bytes per part.

    Not a plain MD5 of the file: S3 hashes each part, concatenates those digests
    and hashes THAT, then appends the part count. Reproducible only because we
    pin the chunk size in TRANSFER below -- boto3's default differs, so an object
    someone else uploaded may legitimately not match.
    """
    parts = []
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            parts.append(hashlib.md5(block).digest())  # noqa: S324 - matching an ETag
    if not parts:                                  # a zero-byte file is never multipart
        parts.append(hashlib.md5(b"").digest())     # noqa: S324
    joined = hashlib.md5(b"".join(parts)).digest()  # noqa: S324
    return f"{joined.hex()}-{len(parts)}"


def etag_matches(client, bucket: str, key: str, path: Path) -> bool:
    """True if S3 already holds this exact file.

    S3's ETag is the MD5 hex digest for a single-part upload and a digest-of-digests
    with a ``-N`` suffix for a multipart one. Both are checkable, and the multipart
    case has to be: at a 32 MB threshold every video in the bundle is multipart, so
    treating those as "unknown" meant re-uploading 6.7 GB of byte-identical media on
    every run -- over exactly the domestic uplink the TRANSFER config below exists to
    nurse. That is also the run most likely to drop objects, so the pessimistic check
    was buying risk, not safety.

    Size is checked first because it is one HEAD field against a stat, and it rejects
    almost every genuine change before we read a 400 MB file to hash it.
    """
    try:
        head = client.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "403"):
            return False
        raise
    remote = head["ETag"].strip('"')
    if head.get("ContentLength") != path.stat().st_size:
        return False
    if "-" in remote:
        return remote == _multipart_etag(path, TRANSFER.multipart_chunksize)
    digest = hashlib.md5()  # noqa: S324 - matching S3's ETag, not a security use
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest() == remote


# Tuned for a domestic uplink rather than for EC2. boto3's defaults put ten 8 MB parts in
# flight with a 60 s socket timeout and about four attempts; uploading multi-hundred-MB
# media over a home connection that lost 49 objects of this very bundle in one run --
# EndpointConnectionError and RequestTimeout, across both large mp4s and small json. Fewer
# parts in flight and a bigger chunk mean fewer sockets to time out; the retry budget is
# what rescues a transfer that stalls mid-part.
#
# The failure mode this prevents is nastier than a slow upload: catalog.json is small and
# uploads fine, so the catalog goes on advertising clips whose media 403s.
TRANSFER = TransferConfig(
    multipart_threshold=32 * 1024 * 1024,
    multipart_chunksize=32 * 1024 * 1024,
    max_concurrency=4,
    num_download_attempts=10,
    use_threads=True,
)


def upload_one(client, bucket: str, key: str, path: Path, dry_run: bool) -> str:
    if etag_matches(client, bucket, key, path):
        return "skip"
    if dry_run:
        return "would-upload"
    suffix = path.suffix.lower()
    client.upload_file(
        str(path),
        bucket,
        key,
        ExtraArgs={
            "ContentType": CONTENT_TYPES.get(suffix, "application/octet-stream"),
            "CacheControl": CACHE_CONTROL.get(suffix, DEFAULT_CACHE_CONTROL),
        },
        Config=TRANSFER,
    )
    return "upload"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", required=True, type=Path, help="directory produced by catalog_ingest build")
    ap.add_argument("--bucket", default=os.environ.get("CATALOG_S3_BUCKET", "6thsense-catalog-media"))
    ap.add_argument("--region", default=os.environ.get("CATALOG_S3_REGION", "us-west-2"))
    ap.add_argument("--prefix", default=os.environ.get("CATALOG_S3_PREFIX", "v1/"))
    ap.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--allow-media",
        action="store_true",
        help="override the package-tier guard (migration/emergency use only)",
    )
    ap.add_argument(
        "--allow-synthetic", action="store_true",
        help="permit a bundle whose collection.provenance_class is not 'recorded'. "
             "Without this flag such a bundle is REFUSED: `make -C scripts/catalog` "
             "emits colour-bar fixtures, and 'do not upload the fixtures' being a "
             "convention rather than a guard is how a buyer ends up looking at test "
             "patterns captioned as real workspaces.")
    args = ap.parse_args()

    bundle: Path = args.bundle.resolve()
    manifest_path = bundle / "catalog.json"
    if not manifest_path.is_file():
        return _fail(f"{bundle} does not look like a bundle: no catalog.json")

    guard = _provenance_guard(manifest_path, allow_synthetic=args.allow_synthetic)
    if guard is not None:
        return guard

    prefix = args.prefix.strip("/")
    prefix = f"{prefix}/" if prefix else ""

    # catalog.json LAST. It is the manifest the website reads: it is small, it uploads in
    # milliseconds, and under a plain alphabetical walk it lands before almost all of the
    # media it points at. For the rest of the run -- 6 GB over a link that lost 49 objects
    # last time -- the live catalog then advertises clips whose media 403s. Publishing the
    # index before the thing it indexes is a race with a real user on the other end, so the
    # manifest is written only once every object it names is already in the bucket.
    _all = [p for p in bundle.rglob("*") if p.is_file() and not p.name.startswith(".")]
    files = sorted(_all, key=lambda p: (p.name == "catalog.json", p.as_posix()))
    if not files:
        return _fail(f"no files under {bundle}")
    guard = _package_tier_guard(files, bundle, allow_media=args.allow_media)
    if guard is not None:
        return guard

    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    client = session.client(
        "s3",
        region_name=args.region,
        config=BotoConfig(
            retries={"max_attempts": 10, "mode": "adaptive"},
            connect_timeout=30,
            read_timeout=180,
        ),
    )

    total_bytes = sum(p.stat().st_size for p in files)
    print(f"bundle : {bundle}")
    print(f"target : s3://{args.bucket}/{prefix}  ({args.region})")
    print(f"files  : {len(files)}  ({total_bytes / 1e6:.1f} MB)")
    if args.dry_run:
        print("mode   : DRY RUN — nothing will be written")
    print()

    counts = {"upload": 0, "skip": 0, "would-upload": 0}
    failures: list[tuple[str, str]] = []

    def work(path: Path) -> tuple[Path, str | None, str | None]:
        key = prefix + path.relative_to(bundle).as_posix()
        try:
            return path, upload_one(client, args.bucket, key, path, args.dry_run), None
        except Exception as exc:  # surfaced per-file, never aborts the run
            return path, None, f"{type(exc).__name__}: {exc}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for path, status, error in pool.map(work, files):
            rel = path.relative_to(bundle).as_posix()
            if error:
                failures.append((rel, error))
                print(f"  FAIL  {rel}\n        {error}")
                continue
            counts[status] += 1
            if status != "skip":
                print(f"  {status:>13}  {rel}")

    print()
    print(f"uploaded {counts['upload']}  ·  unchanged {counts['skip']}"
          + (f"  ·  pending {counts['would-upload']}" if args.dry_run else ""))
    if failures:
        print(f"\n{len(failures)} file(s) failed:")
        for rel, err in failures:
            print(f"  {rel}: {err}")
        return 1
    return 0


def _provenance_guard(manifest_path: Path, *, allow_synthetic: bool) -> int | None:
    """Refuse a generated bundle unless the operator said so out loud.

    `collection.provenance_class` is set by the ingest from each take's own
    declaration, so this reads a fact rather than guessing from filenames. An
    unreadable or pre-provenance manifest is NOT treated as clean: it is refused with
    the same message, because "we could not tell" and "it is real" are different
    answers and only one of them is safe to publish.
    """
    try:
        manifest = json.loads(manifest_path.read_text())
        klass = (manifest.get("collection") or {}).get("provenance_class")
    except (OSError, ValueError) as exc:
        return _fail(f"{manifest_path} could not be read as JSON: {exc}")
    if klass == "recorded":
        return None
    if allow_synthetic:
        print(f"note   : provenance_class={klass!r}; uploading anyway (--allow-synthetic)\n")
        return None
    if klass is None:
        return _fail(
            f"{manifest_path} has no collection.provenance_class. This bundle predates "
            f"the provenance guard; rebuild it with the current ingest, or pass "
            f"--allow-synthetic if you have confirmed by hand that the media is real.")
    return _fail(
        f"collection.provenance_class is {klass!r}, not 'recorded': this bundle contains "
        f"generated media. Publishing it to a buyer-facing bucket without saying so is "
        f"the one mistake that ends a procurement conversation. Build from real takes, or "
        f"re-run with --allow-synthetic if a generated drop is genuinely what you intend "
        f"to ship (the catalog will banner it as such).")


def _package_tier_guard(
    files: list[Path], bundle: Path, *, allow_media: bool
) -> int | None:
    package_paths = [
        path.relative_to(bundle).as_posix()
        for path in files
        if path.relative_to(bundle).parts[0] in {"media", "archives"}
    ]
    if not package_paths or allow_media:
        return None
    examples = ", ".join(package_paths[:3])
    return _fail(
        f"refusing {len(package_paths)} package-tier file(s) ({examples}). "
        "The package tier is s3://6thsense-processed/imported/<cohort>/ and needs "
        "the pipeline, not this catalog upload script. Pass --allow-media only "
        "for an explicitly reviewed migration."
    )


def _fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
