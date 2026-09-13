"""Bounded, read-only discovery. Object presence is not recording acceptance."""
from collections import defaultdict
from datetime import datetime, timezone

from app.core.ops_s3 import get_settings, OpsS3Unavailable
from app.core.ops_scan import parse_key, META
from app.core.ops_inventory_sources import resolve_source

MAX_OBJECTS = 10000
MAX_EXAMPLES = 20
MAX_PAGES = 20


def build_coverage(objects, *, bucket, listing_complete, stop_reason=None, scope_prefix=''):
    prefixes = {}
    names = defaultdict(set)
    unknown = []
    bookkeeping = markers = size = count = 0
    for obj in objects:
        key = obj['Key']
        count += 1
        size += obj.get('Size', 0)
        if key.endswith('/'):
            markers += 1
        elif any(p in {'_machine', '.ego-s3-test', '_conncheck'} for p in key.split('/')[:-1]):
            bookkeeping += 1
        elif hit := parse_key(key):
            _, name, prefix = hit
            names[name].add(prefix)
            prefixes.setdefault(prefix, False)
            if key == prefix + '/' + META:
                prefixes[prefix] = True
        else:
            unknown.append(key)
    missing = sorted(p for p, present in prefixes.items() if not present and (p + '/' + META).startswith(scope_prefix))
    outside = sorted(p for p, present in prefixes.items() if not present and not (p + '/' + META).startswith(scope_prefix))
    collisions = sorted(n for n, locations in names.items() if len(locations) > 1)
    limitations = [
        'Counts describe listed current objects only; versions and concurrent changes are not reconciled.',
        'Metadata presence is not content validation. No usability, annotation quality, collector credit or payment is inferred.',
        'Recognition uses the existing Operations folder parser; unrecognized objects are not necessarily unusable.',
    ]
    if outside:
        limitations.insert(0, 'Metadata for some recognized recordings lies outside the listed prefix; its presence is unknown, not missing.')
    if not listing_complete:
        limitations.insert(0, 'Inventory is incomplete; counts are observations, not corpus totals. Missing metadata means not yet observed.')
        if count == 0:
            limitations.insert(0, 'Inventory is unknown: no objects could be observed. This does not establish an empty bucket.')
    return dict(bucket=bucket, scope_prefix=scope_prefix, observed_at=datetime.now(timezone.utc).isoformat(),
                listing_complete=listing_complete, stop_reason=stop_reason,
                objects_observed=count, bytes_observed=size,
                recognized_recording_prefixes=len(prefixes), recordings_missing_metadata=len(missing),
                recordings_metadata_outside_scope=len(outside), metadata_scope_complete=not outside,
                unrecognized_objects=len(unknown), bookkeeping_objects=bookkeeping, folder_markers=markers,
                collision_recording_names=len(collisions),
                examples=dict(unrecognized_keys=unknown[:MAX_EXAMPLES],
                              missing_metadata_prefixes=missing[:MAX_EXAMPLES], outside_scope_prefixes=outside[:MAX_EXAMPLES], collision_names=collisions[:MAX_EXAMPLES]),
                limitations=limitations)


def _inventory_client(cfg):
    # Same configured bucket and credential selection as ops_s3; finite SDK I/O budget.
    import boto3
    from botocore.config import Config
    if cfg.half_configured:
        raise OpsS3Unavailable('Incomplete Operations credentials')
    credentials = {}
    if cfg.access_key_id:
        credentials = dict(aws_access_key_id=cfg.access_key_id, aws_secret_access_key=cfg.secret_access_key)
    return boto3.session.Session(region_name=cfg.region, **credentials).client(
        's3', config=Config(connect_timeout=3, read_timeout=5, retries={'total_max_attempts': 1}))


def inventory_coverage(source_id='operations'):
    """LIST only: no imports, database access, object GETs, or external writes."""
    cfg = get_settings()
    source = resolve_source(source_id, cfg)
    objects = []
    reason = 'read_error'
    complete = False
    client = None
    try:
        client = _inventory_client(cfg)
        token = None
        seen_tokens = set()
        for _ in range(MAX_PAGES):
            kwargs = dict(Bucket=source['bucket'], Prefix=source['prefix'], MaxKeys=min(1000, MAX_OBJECTS - len(objects)))
            if source['expected_owner'] is not None:
                kwargs['ExpectedBucketOwner'] = source['expected_owner']
            if token:
                kwargs['ContinuationToken'] = token
            page = client.list_objects_v2(**kwargs)
            contents = page.get('Contents', [])
            if not isinstance(contents, list):
                raise ValueError('Invalid list response')
            remaining = MAX_OBJECTS - len(objects)
            for obj in contents[:remaining]:
                if (not isinstance(obj, dict)
                        or not isinstance(obj.get('Key'), str) or not obj['Key']
                        or not obj['Key'].startswith(source['prefix'])
                        or type(obj.get('Size')) is not int or obj['Size'] < 0):
                    raise ValueError('Invalid object metadata')
                objects.append({'Key': obj['Key'], 'Size': obj['Size']})
            if len(contents) > remaining:
                reason = 'object_limit'
                break
            if page.get('IsTruncated') is False:
                complete, reason = True, None
                break
            if page.get('IsTruncated') is not True:
                break  # Malformed response does not prove completion.
            if len(objects) == MAX_OBJECTS:
                reason = 'object_limit'
                break
            token = page.get('NextContinuationToken')
            if not token or token in seen_tokens:
                break
            seen_tokens.add(token)
    except Exception:
        # Provider errors can contain URLs, key IDs and policy details. Never echo them.
        reason = 'read_error'
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass  # Closing a socket must not replace the sanitized observation.
    report = build_coverage(objects, bucket=source['bucket'], listing_complete=complete, stop_reason=reason, scope_prefix=source['prefix'])
    report.update(source_id=source['id'], expected_owner=source['expected_owner'], scope_prefix=source['prefix'])
    if reason == 'read_error':
        report['limitations'].append('Listing could not finish within its read budget. Check configured-prefix LIST permission, expected bucket owner and Operations credentials. No access grants are made by this check.')
    return report
