"""Only complete browser copies of the exact stored QC run may be signed."""
import copy
import io
import json
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from app.core import ops_clean
from tests.test_ops_artifacts import multimodal_manifest
from tests.test_ops_clean import manifest


def fixture():
    doc = multimodal_manifest()
    name = doc['recordings'][0]['recording']
    ref = {'key': 'qc-results/factory-test/result.json', 'version_id': 'qc-v1', 'sha256': 'a' * 64}
    output = dict(bucket='6thsense-processed', key=f"clean/factory-test/{name}/browser-preview-{'c' * 64}.mp4",
                  version_id='preview-v1', bytes=1000, sha256='c' * 64)
    supplement = dict(schema='6thsense-browser-preview/1', run_id=doc['run_id'], recording=name, manifest=ref,
                      sources=[{k: o[k] for k in ('key','version_id','sha256','bytes')} for o in doc['outputs'][:2]],
                      output=output, verification=dict(codec='h264', width=1920, height=600, frame_count=1800,
                          duration_us=60_000_000, all_frames_decoded=True, all_timestamps_checked=True))
    return doc, ref, supplement


class S3:
    def __init__(self, supplement, fault=None):
        self.supplement, self.fault, self.signed = supplement, fault, []

    def get_object(self, **kwargs):
        if self.fault in ('NoSuchKey', 'AccessDenied'):
            raise ClientError({'Error': {'Code': self.fault}}, 'GetObject')
        assert kwargs['Key'].endswith('/browser-preview.json')
        data = json.dumps(self.supplement).encode()
        return dict(Body=io.BytesIO(data), ContentLength=len(data), VersionId='supplement-v1')

    def head_object(self, **kwargs):
        assert kwargs['VersionId'] == 'preview-v1'
        return dict(ContentLength=999 if self.fault == 'size' else 1000,
                    Metadata={'sha256': 'd' * 64 if self.fault == 'metadata' else 'c' * 64})

    def generate_presigned_url(self, method, Params, ExpiresIn):
        self.signed.append(Params)
        return f"https://test.invalid/{Params['Key']}?versionId={Params['VersionId']}"


def setup(monkeypatch, supplement, fault=None):
    s3 = S3(supplement, fault)
    monkeypatch.setattr(ops_clean, '_client', lambda _: s3)
    monkeypatch.setattr(ops_clean, 'get_settings', lambda: SimpleNamespace(presign_ttl=300))
    return s3


def test_default_playback_uses_verified_h264_without_changing_qc_or_native_files(monkeypatch):
    doc, ref, supplement = fixture()
    original = copy.deepcopy(doc)
    s3 = setup(monkeypatch, supplement)
    files = ops_clean.playback(doc, ref)
    assert [f['role'] for f in files] == ['recording_preview', 'left_video', 'right_video']
    assert files[0]['recording'] == doc['recordings'][0]['recording']
    assert s3.signed[0]['VersionId'] == 'preview-v1'
    assert doc == original


@pytest.mark.parametrize('fault', ['manifest', 'source_version', 'source_hash', 'codec', 'frame_count',
                                   'duration', 'not_verified', 'foreign_key', 'unpinned', 'size', 'metadata', 'NoSuchKey'])
def test_unverified_optional_copy_never_gets_signed(monkeypatch, fault):
    doc, ref, supplement = fixture()
    supplement = copy.deepcopy(supplement)
    if fault == 'manifest': supplement['manifest']['sha256'] = 'd' * 64
    if fault == 'source_version': supplement['sources'][0]['version_id'] = 'different'
    if fault == 'source_hash': supplement['sources'][0]['sha256'] = 'd' * 64
    if fault == 'codec': supplement['verification']['codec'] = 'hevc'
    if fault == 'frame_count': supplement['verification']['frame_count'] -= 1
    if fault == 'duration': supplement['verification']['duration_us'] += 1
    if fault == 'not_verified': supplement['verification']['all_frames_decoded'] = False
    if fault == 'foreign_key': supplement['output']['key'] = 'clean/other/preview.mp4'
    if fault == 'unpinned': supplement['output']['version_id'] = 'null'
    s3 = setup(monkeypatch, supplement, fault)
    assert [f['role'] for f in ops_clean.playback(doc, ref)] == ['left_video', 'right_video']
    assert len(s3.signed) == 2


def test_access_denial_is_an_error_and_legacy_playback_needs_no_supplement(monkeypatch):
    doc, ref, supplement = fixture()
    setup(monkeypatch, supplement, 'AccessDenied')
    with pytest.raises(ClientError): ops_clean.playback(doc, ref)
    assert len(ops_clean.playback(manifest(), ref)) == 1


@pytest.mark.asyncio
async def test_files_route_binds_preview_to_stored_manifest(monkeypatch):
    from app.api.routes import ops_clean as route
    doc, ref, _ = fixture()
    run = SimpleNamespace(manifest_json=json.dumps(doc), manifest_key=ref['key'],
                          manifest_version=ref['version_id'], manifest_sha256=ref['sha256'])
    class DB:
        async def get(self, model, key): return run
    calls = []
    monkeypatch.setattr(route, 'playback', lambda body, binding: calls.append((body, binding)) or [])
    assert await route.files(doc['run_id'], None, DB()) == {'files': []}
    assert calls == [(doc, ref)]
