"""A pending-media view separate from the permanent episode/payment ledger.

Only verified receipts tied to sources in imported clean manifests can retire a
raw object. A recording name, upload date, or matching file size is insufficient:
re-deliveries can contain both processed copies and previously missing segments.
Receipts are operator-verified source/copy hashes, never supplied by cameras.
"""
import math

from app.core.ops_s3 import PLAYABLE, _client, get_settings

INVENTORY_KEY = 'raw_inventory_v1'
RECEIPTS_KEY = 'raw_source_receipts_v1'


def processed_keys(manifests, receipts):
    sources = {
        (s.get('bucket'), s['key'], s['version_id'], s['sha256'], s['size_bytes'])
        for m in manifests for r in m.get('recordings', []) for s in r.get('sources', [])
        if all(s.get(k) is not None for k in ('key', 'version_id', 'sha256', 'size_bytes'))
    }
    return {
        (r['key'], r['etag'].strip('"'), r['size_bytes'])
        for r in receipts
        if all(r.get(k) is not None for k in ('key', 'etag', 'source_key', 'source_version_id', 'sha256', 'size_bytes')) and r['etag'] and (
            r.get('bucket'), r['source_key'], r['source_version_id'], r['sha256'], r['size_bytes']
        ) in sources
    }


def is_processed(obj, verified):
    return (obj['key'], obj.get('etag', '').strip('"'), obj['bytes']) in verified


def raw_statuses(inventory, manifests, receipts):
    verified = processed_keys(manifests, receipts)
    clean = {r['recording'] for m in manifests for r in m.get('recordings', []) if r.get('sources')}
    out = {}
    for rec in inventory.keys() | clean:
        media = [o for o in inventory.get(rec, {}).get('media', []) if o['bytes'] > 0]
        done = sum(is_processed(o, verified) for o in media)
        pending = len(media) - done
        status = ('partial' if rec in clean else 'pending') if pending else (
            'processed' if rec in clean else 'unavailable')
        out[rec] = {'status': status, 'pending_files': pending, 'processed_files': done,
                    'raw_bytes': sum(o['bytes'] for o in media if not is_processed(o, verified))}
    return out


def pending_duration(episodes, raw, jobs):
    """Recorded footage still in Raw, counted once per episode, not per eye.

    Episode duration cannot tell us the length of just the outstanding segments
    of a partial Clean import. Keep those episodes in the unknown count instead
    of estimating their remaining time from file counts or bytes.
    """
    summary = dict(known_seconds=0, known_episodes=0, unknown_episodes=0,
                   partial_episodes=0, pending_episodes=0)
    for episode in episodes:
        source = raw.get(episode.recording, {})
        if (episode.deleted_at is not None
                or jobs.get(episode.recording, {}).get('state') == 'rejected'
                or source.get('pending_files', 0) <= 0):
            continue
        summary['pending_episodes'] += 1
        partial = source.get('status') == 'partial' or source.get('processed_files', 0) > 0
        duration = episode.duration_s
        if (partial or isinstance(duration, bool) or not isinstance(duration, (int, float))
                or not math.isfinite(duration) or duration <= 0):
            summary['unknown_episodes'] += 1
            summary['partial_episodes'] += int(partial)
        else:
            summary['known_seconds'] += duration
            summary['known_episodes'] += 1
    summary['known_seconds'] = round(summary['known_seconds'], 3)
    return summary


def pending_playback(recording, inventory, manifests, receipts):
    """Re-list all known delivery prefixes so purged originals cannot strand playback."""
    cfg = get_settings()
    s3 = _client(cfg)
    verified = processed_keys(manifests, receipts)
    files = []
    containers = {}
    for prefix in inventory[recording]['prefixes']:
        for page in s3.get_paginator('list_objects_v2').paginate(Bucket=cfg.bucket, Prefix=prefix):
            for obj in page.get('Contents', []):
                key = obj['Key']
                raw = {'key': key, 'bytes': obj.get('Size', 0), 'etag': obj.get('ETag', '')}
                if key.lower().endswith('.egoc') and raw['bytes'] and not is_processed(raw, verified):
                    containers[key] = raw
                if not key.lower().endswith(PLAYABLE) or not raw['bytes'] or is_processed(raw, verified):
                    continue
                files.append({'name': key[len(prefix):], 'key': key, 'bytes': raw['bytes'],
                              'url': s3.generate_presigned_url('get_object',
                                  Params={'Bucket': cfg.bucket, 'Key': key}, ExpiresIn=cfg.presign_ttl)})
    if not files and containers:
        from app.core.ops_raw_preview import decoded_playback
        return decoded_playback(recording, list(containers.values()), s3, cfg)
    return sorted(files, key=lambda f: (f['name'], f['key']))


def refresh_source_receipts(inventory, manifests, receipts):
    """Learn fingerprints from the exact source versions of future clean imports.

    Cross-prefix copies still require independently verified copy receipts. A
    missing source version is not evidence about a same-named replacement.
    """
    from botocore.exceptions import ClientError
    live_keys = {o['key'] for t in inventory.values() for o in t['media']}
    cfg = get_settings()
    known = {(r.get('source_key'), r.get('source_version_id')) for r in receipts if r.get('key') == r.get('source_key')}
    needed = [s for m in manifests for r in m.get('recordings', []) for s in r.get('sources', [])
              if s.get('bucket') == cfg.bucket and s.get('key') in live_keys
              and s.get('size_bytes') is not None and (s['key'], s['version_id']) not in known]
    if not needed:
        return receipts
    s3 = _client(cfg)
    out = list(receipts)
    for source in needed:
        try:
            head = s3.head_object(Bucket=cfg.bucket, Key=source['key'], VersionId=source['version_id'])
        except ClientError:
            continue  # Access failure or purged history: remain pending, never infer completion.
        if head.get('ContentLength') == source['size_bytes'] and head.get('ETag'):
            out.append(dict(source, source_key=source['key'], source_version_id=source['version_id'], etag=head['ETag']))
    return out
