"""Operator-confirmed business provenance, separate from individual contributors.

The registry is maintenance-only. A worker cannot establish ownership by labelling
its own manifest; import must match the registered source identities exactly.
"""
import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.models import CleanRun, OpsSetting

ATTRIBUTIONS_KEY = 'ops_source_attributions_v1'
UPLOAD_SOURCES_KEY = 'ops_upload_sources_v1'
COUNTRIES = {'china': 'China', 'korea': 'Korea', 'vietnam': 'Vietnam', 'india': 'India'}
ZONES = {'china': 'Asia/Shanghai', 'korea': 'Asia/Seoul', 'vietnam': 'Asia/Ho_Chi_Minh', 'india': 'Asia/Kolkata'}


def source_timezone(party):
    return ZoneInfo(ZONES[party['country']] if party else 'Asia/Seoul')


def counterparty(value):
    if not isinstance(value, dict) or set(value) != {'kind', 'id', 'name', 'country', 'payment_model'}:
        raise ValueError('Incomplete business attribution')
    if value['kind'] != 'business' or value['payment_model'] != 'b2b_contract':
        raise ValueError('Unsupported commercial relationship')
    if not isinstance(value['id'], str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', value['id']):
        raise ValueError('Invalid business identity')
    if not isinstance(value['name'], str) or not value['name'].strip() or len(value['name']) > 200 or not isinstance(value['country'], str) or value['country'] not in COUNTRIES:
        raise ValueError('Business name and source country are required')
    return dict(value)


async def source_registry(db):
    row = (await db.execute(select(OpsSetting).where(OpsSetting.key == ATTRIBUTIONS_KEY))).scalar_one_or_none()
    result = json.loads(row.value) if row else {}
    if not isinstance(result, dict):
        raise ValueError('Invalid source attribution registry')
    return result


def business_source(episode, registry):
    entry = registry.get(episode.recording)
    if entry is None:
        return None
    if not isinstance(entry, dict) or any(entry.get(k) != getattr(episode, k) for k in ('recording', 'device_id', 'session')):
        raise ValueError('Business attribution does not match this source')
    if episode.wearer_id is not None:
        raise ValueError('Business footage cannot also belong to an individual contributor')
    return counterparty(entry.get('counterparty'))


async def register_upload_sources(db, takes, episodes, *, bucket):
    """Freeze business attribution from operator-configured upload destinations.

    Called under the scan's attribution lock, before individual owner filling.
    A folder or camera name alone cannot register a business. The channel must
    have been configured by an operator, and every observed delivery must agree.
    Existing decisions and imported financial history are never reassigned.
    """
    registry = await source_registry(db)
    setting = await db.get(OpsSetting, UPLOAD_SOURCES_KEY)
    channels = json.loads(setting.value) if setting else {}
    if not isinstance(channels, dict):
        raise ValueError('Invalid business upload destinations')
    configured = {}
    for session, channel in channels.items():
        if (not isinstance(session, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,199}', session)
                or not isinstance(channel, dict) or channel.get('bucket') != '6thsense-raw'
                or channel.get('prefix') != f'sessions/{session}/'):
            raise ValueError('Business upload destinations require an exact Raw session prefix')
        configured[session] = (channel, counterparty(channel.get('counterparty')))
    if not configured or bucket != '6thsense-raw':
        return registry
    from app.core.ops_scan import facts_from, parse_key
    imported = {}
    for run in (await db.execute(select(CleanRun))).scalars():
        doc = json.loads(run.manifest_json)
        for rec in doc['recordings']:
            imported.setdefault(rec['recording'], []).append((run, doc.get('counterparty')))
    changed = False
    for recording, take in takes.items():
        prefixes = sorted(set(take.get('prefixes') or [take['prefix']]))
        matches = [session for session, (channel, _) in configured.items()
                   if any(prefix.startswith(channel['prefix']) for prefix in prefixes)]
        if not matches:
            continue
        episode = episodes.get(recording)
        if episode and episode.deleted_at:
            continue
        if len(matches) != 1:
            raise ValueError(f'{recording}: conflicting business upload destinations')
        session = matches[0]
        channel, party = configured[session]
        for prefix in prefixes:
            parts = prefix.split('/')
            if (not prefix.startswith(channel['prefix']) or not prefix.endswith('/')
                    or any(not p or p in ('.', '..') for p in parts[:-1])
                    or parts[-2] != recording
                    or parse_key(prefix + 'metadata.json') != (session, recording, prefix[:-1])):
                raise ValueError(f'{recording}: conflicting upload provenance; review its delivery paths')
        facts = facts_from(take)
        if take['session'] != session or (episode and (
                episode.session != session or episode.device_id != facts['device_id']
                or episode.wearer_id is not None or episode.paid or episode.amount_krw)):
            raise ValueError(f'{recording}: existing source ownership or payment requires reconciliation')
        if any(run.wearer_id is not None or run.rate_krw_hour is not None or owner != party
               for run, owner in imported.get(recording, [])):
            raise ValueError(f'{recording}: imported Clean ownership requires reconciliation')
        identity = dict(recording=recording, device_id=facts['device_id'], session=session)
        existing = registry.get(recording)
        if existing and (any(existing.get(k) != v for k, v in identity.items())
                         or counterparty(existing.get('counterparty')) != party):
            raise ValueError(f'{recording}: confirmed business attribution conflicts with upload destination')
        # Keep manual attributions and their original evidence unchanged.
        if existing and 'upload_source' not in existing:
            continue
        previous = existing.get('upload_source', {}).get('recording_prefixes', []) if existing else []
        evidence = dict(bucket=bucket, prefix=channel['prefix'],
                        recording_prefixes=sorted(set(previous) | set(prefixes)))
        if existing and existing.get('upload_source') == evidence:
            continue
        registry[recording] = {**(existing or identity), 'counterparty': party,
            'upload_source': evidence,
            'confirmed_at': existing['confirmed_at'] if existing else datetime.now(timezone.utc).isoformat(),
            'basis': 'Automatically attributed from the operator-confirmed business upload destination.'}
        changed = True
    if changed:
        row = await db.get(OpsSetting, ATTRIBUTIONS_KEY)
        if row is None:
            row = OpsSetting(key=ATTRIBUTIONS_KEY)
            db.add(row)
        row.value = json.dumps(registry, sort_keys=True)
    return registry


def business_source_key(source, recording, session, entry):
    """Accept registered nested upload paths without broadening legacy imports."""
    key = source.get('key', '')
    parts = key.split('/')
    if (source.get('bucket') != '6thsense-raw' or len(parts) < 4
            or parts[:2] != ['sessions', session] or parts[-2] != recording
            or any(not p or p in ('.', '..') for p in parts)):
        return False
    upload = entry.get('upload_source')
    if upload:
        return (upload.get('bucket') == source['bucket']
                and upload.get('prefix') == f'sessions/{session}/'
                and key.rsplit('/', 1)[0] + '/' in upload.get('recording_prefixes', []))
    return len(parts) == 4 or (len(parts) == 5 and bool(re.fullmatch(r'(?:EGO-)?[A-Fa-f0-9]{6}', parts[2])))
