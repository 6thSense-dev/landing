"""Server-owned recording locations. Configuration grants no AWS permissions."""
import ipaddress
import json
import os
import re
from app.core.ops_s3 import get_settings

class InvalidInventorySources(ValueError):
    pass

class UnknownInventorySource(LookupError):
    pass


def _bucket_valid(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', value):
        return False
    if '..' in value or value.startswith(('xn--', 'sthree-', 'amzn-s3-demo-')) or value.endswith(('-s3alias', '--ol-s3', '.mrap', '--x-s3', '--table-s3')):
        return False
    try:
        ipaddress.ip_address(value)
        return False
    except ValueError:
        return True


def inventory_sources(cfg=None):
    """Read a bounded registry without network access. Never echo bad config."""
    try:
        cfg = cfg or get_settings()
        raw = os.environ.get('OPS_INVENTORY_SOURCES', '[]')
        if len(raw.encode('utf-8')) > 32768:
            raise ValueError()
        extra = json.loads(raw)
        if not isinstance(extra, list) or len(extra) > 10:
            raise ValueError()
        result = [dict(id='operations', label='Operations raw', bucket=cfg.bucket, prefix='', expected_owner=None)]
        ids = {'operations'}
        fields = {'id', 'label', 'bucket', 'prefix', 'expected_owner'}
        for source in extra:
            if not isinstance(source, dict) or set(source) != fields:
                raise ValueError()
            sid, label, prefix = source['id'], source['label'], source['prefix']
            if not isinstance(sid, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', sid) or sid in ids:
                raise ValueError()
            if not isinstance(label, str) or not label.strip() or len(label) > 120 or any(ord(c) < 32 for c in label):
                raise ValueError()
            if not _bucket_valid(source['bucket']):
                raise ValueError()
            owner = source['expected_owner']
            if not isinstance(owner, str) or not re.fullmatch(r'[0-9]{12}', owner):
                raise ValueError()
            if (not isinstance(prefix, str) or len(prefix.encode('utf-8')) > 1024
                    or (prefix and not prefix.endswith('/')) or '\\' in prefix
                    or any(ord(c) < 32 or ord(c) == 127 for c in prefix)
                    or any(p in ('.', '..') for p in prefix.split('/'))):
                raise ValueError()
            ids.add(sid)
            result.append(dict(source))
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise InvalidInventorySources('Recording source configuration is invalid.') from None


def resolve_source(source_id, cfg=None):
    for source in inventory_sources(cfg):
        if source['id'] == source_id:
            return source
    raise UnknownInventorySource('Unknown recording source.')


def source_registry():
    return {'sources': inventory_sources(), 'limitations': [
        'Sources are configured locations, not a verified inventory or automatic cross-account permission grant.',
        'Expected owner is a configured account constraint; access is checked only when a listing is requested.',
        'All sources use existing Operations credentials and region. Some sources may be inaccessible.',
    ]}
