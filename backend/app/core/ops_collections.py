"""Non-payable viewing collections, pinned to the existing clean ledger."""
import json
import math
import re

from app.core.ops_clean import clean_bucket
from app.core.ops_s3 import _client, get_settings

COLLECTIONS_KEY = 'ops_clean_collections_v1'


def validate_collection(doc, runs):
    if not isinstance(doc, dict) or doc.get('schema') != '6thsense-clean-collection/1':
        raise ValueError('Invalid viewing collection')
    cid = doc.get('collection_id', '')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,120}', cid) or doc.get('payable') is not False:
        raise ValueError('Viewing collections cannot create earnings')
    if not isinstance(doc.get('label'), str) or not doc['label'].strip():
        raise ValueError('A collection label is required')
    refs = doc.get('source_runs', [])
    if len(refs) < 2 or len({r['run_id'] for r in refs}) != len(refs):
        raise ValueError('Distinct source runs are required')
    by_id = {r.run_id: r for r in runs}
    seconds = 0
    names = []
    for ref in refs:
        run = by_id.get(ref['run_id'])
        if run is None or run.manifest_sha256 != ref.get('manifest_sha256') or run.wearer_id != doc.get('wearer_id'):
            raise ValueError('Collection no longer matches its source ledger')
        seconds += run.retained_seconds
        names.extend(o['recording'] for o in json.loads(run.manifest_json)['outputs'] if o.get('role') == 'recording_preview')
    value = doc.get('retained_seconds')
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value - seconds) > .1:
        raise ValueError('Collection time does not match source runs')
    if [r['recording'] for r in doc.get('recordings', [])] != sorted(names) or len(names) != len(set(names)):
        raise ValueError('Collection must contain each retained recording once in date order')
    output = doc['output']
    if output.get('key') != f'clean/collections/{cid}/joined-preview.mp4' or output.get('version_id') in (None, '', 'null'):
        raise ValueError('Invalid collection output location')
    if not re.fullmatch(r'[a-f0-9]{64}', output.get('sha256', '')) or type(output.get('bytes')) is not int or output['bytes'] <= 0:
        raise ValueError('Pinned collection output is required')
    if doc.get('full_decode_passed') is not True:
        raise ValueError('Collection output has not been verified')
    return doc


def collection_playback(doc):
    s3 = _client(get_settings())
    item = doc['output']
    params = {'Bucket': clean_bucket(), 'Key': item['key'], 'VersionId': item['version_id']}
    head = s3.head_object(**params)
    if head['ContentLength'] != item['bytes'] or head.get('Metadata', {}).get('sha256') != item['sha256']:
        raise ValueError('Collection output differs from verified evidence')
    return [{**item, 'label': doc['label'], 'role': 'joined_preview',
             'url': s3.generate_presigned_url('get_object', Params=params, ExpiresIn=get_settings().presign_ttl)}]
