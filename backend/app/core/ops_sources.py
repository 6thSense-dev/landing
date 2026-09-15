"""Operator-confirmed business provenance, separate from individual contributors.

The registry is maintenance-only. A worker cannot establish ownership by labelling
its own manifest; import must match the registered source identities exactly.
"""
import json
import re
from zoneinfo import ZoneInfo
from sqlalchemy import select
from app.models import OpsSetting

ATTRIBUTIONS_KEY = 'ops_source_attributions_v1'
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
