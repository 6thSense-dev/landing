"""Real encoding regressions: stereo eye order, VFR timing and complete decoding."""
import importlib.util
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import av
import pytest
from botocore.exceptions import ClientError
from PIL import Image

spec = importlib.util.spec_from_file_location('browser_preview', Path(__file__).parents[2] / 'infra/raw_lifecycle/browser_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


def eye(path, color, durations=(33280, 33401, 31002, 41234)):
    with av.open(str(path), 'w') as container:
        stream = container.add_stream('libx264', rate=30)
        stream.width, stream.height, stream.pix_fmt = 1920, 1200, 'yuv420p'
        stream.time_base = stream.codec_context.time_base = preview.TB
        stream.options = {'preset': 'ultrafast', 'bf': '0'}
        pending, pts = {}, 0

        def mux(packets):
            for p in packets:
                timestamp = round(p.pts * p.time_base / preview.TB)
                p.duration = round(pending.pop(timestamp) * preview.TB / p.time_base)
                container.mux(p)

        for duration in durations:
            frame = av.VideoFrame.from_image(Image.new('RGB', (1920, 1200), color))
            frame.pts, frame.time_base = pts, preview.TB
            pending[pts] = duration
            mux(stream.encode(frame))
            pts += duration
        mux(stream.encode())
    return pts


def test_h264_preview_preserves_stereo_order_every_frame_and_irregular_final_duration(tmp_path):
    left, right, output = [tmp_path / name for name in ('left.mp4', 'right.mp4', 'preview.mp4')]
    duration = eye(left, 'red')
    eye(right, 'blue')
    result = preview.encode_preview(left, right, output, 4, duration)
    assert result == dict(codec='h264', width=1920, height=600, frame_count=4, duration_us=duration,
                          all_frames_decoded=True, all_timestamps_checked=True)
    with av.open(str(output)) as container:
        frames = list(container.decode(video=0))
    assert len(frames) == 4
    for frame in frames:
        image = frame.to_image()
        red, blue = image.getpixel((480, 300)), image.getpixel((1440, 300))
        assert red[0] > 240 and red[2] < 10
        assert blue[2] > 240 and blue[0] < 10
    data = output.read_bytes()
    assert data.index(b'moov') < data.index(b'mdat')  # Streamable metadata first.


@pytest.mark.parametrize('fault', ['short_right', 'different_clock', 'wrong_count', 'wrong_duration'])
def test_incomplete_or_differently_timed_preview_cannot_verify(tmp_path, fault):
    left, right = tmp_path / 'left.mp4', tmp_path / 'right.mp4'
    duration = eye(left, 'red')
    right_durations = (33280, 33401, 31002, 41234)
    if fault == 'short_right': right_durations = right_durations[:-1]
    if fault == 'different_clock': right_durations = (33280, 33402, 31001, 41234)
    eye(right, 'blue', right_durations)
    with pytest.raises(ValueError):
        preview.encode_preview(left, right, tmp_path / 'preview.mp4',
                               3 if fault == 'wrong_count' else 4, duration + (fault == 'wrong_duration'))


class VersionedS3:
    exceptions = SimpleNamespace(ClientError=ClientError)

    def __init__(self):
        self.objects, self.writes, self.corrupt_preview = {}, [], False

    def seed(self, key, body):
        ref = dict(bucket=preview.BUCKET, key=key, version_id=str(len(self.objects) + 1),
                   bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
        self.objects[key] = (ref, body)
        return ref

    def put_object(self, Bucket, Key, Body, ContentType, Metadata, IfNoneMatch):
        assert Bucket == preview.BUCKET and IfNoneMatch == '*'
        if Key in self.objects:
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}}, 'PutObject')
        body = Body.read()
        assert Metadata['sha256'] == hashlib.sha256(body).hexdigest()
        ref = self.seed(Key, body)
        if self.corrupt_preview and Key.endswith('.mp4'):
            self.objects[Key] = (ref, body + b'corrupt')
        self.writes.append(Key)
        return {'VersionId': ref['version_id']}

    def head_object(self, Bucket, Key):
        ref, _ = self.objects[Key]
        return {'VersionId': ref['version_id']}

    def get_object(self, Bucket, Key, VersionId):
        ref, body = self.objects[Key]
        assert Bucket == preview.BUCKET and VersionId == ref['version_id']
        return {'Body': io.BytesIO(body)}


def publication_fixture(tmp_path):
    s3 = VersionedS3()
    name, run = 'ego_20260916_110043_16A4A5', 'raw-clean-auto-test'
    outputs = []
    for side, color in [('left', 'red'), ('right', 'blue')]:
        path = tmp_path / (side + '.mp4')
        duration = eye(path, color)
        ref = s3.seed(f'clean/{run}/{name}/{side}.mp4', path.read_bytes())
        outputs.append({**ref, 'role': side + '_video', 'recording': name})
    doc = {'schema': '6thsense-clean-qc/2', 'run_id': run, 'outputs': outputs,
           'recordings': [{'recording': name, 'media': {'retained_frame_count': 4, 'retained_seconds': duration / 1e6}}]}
    ref = s3.seed(f'qc-results/{run}/result.json', json.dumps(doc).encode())
    return s3, doc, ref


@pytest.mark.parametrize('download', [False, True])
def test_publication_pins_every_input_verifies_uploads_and_retries_without_rewriting_qc(tmp_path, download):
    s3, doc, ref = publication_fixture(tmp_path)
    originals = dict(s3.objects)
    directory = tmp_path / 'download' if download else tmp_path
    directory.mkdir(exist_ok=True)
    receipts = preview.publish_preview(s3, doc, ref, directory)
    assert len(receipts) == 1 and len(s3.writes) == 2
    assert s3.writes[0].endswith('.mp4') and s3.writes[1].endswith('/browser-preview.json')
    supplement = json.loads(s3.objects[receipts[0]['key']][1])
    assert supplement['manifest'] == {k: ref[k] for k in ('key', 'version_id', 'sha256')}
    assert supplement['verification']['all_frames_decoded'] is True
    assert preview.publish_preview(s3, doc, ref, directory) == receipts
    assert len(s3.writes) == 2
    assert all(s3.objects[key] == value for key, value in originals.items())


@pytest.mark.parametrize('fault', ['input_digest', 'upload_corrupted', 'conflicting_supplement'])
def test_publication_fails_closed_before_completing_invalid_copy(tmp_path, fault):
    s3, doc, ref = publication_fixture(tmp_path)
    if fault == 'input_digest': doc['outputs'][0]['sha256'] = 'f' * 64
    if fault == 'upload_corrupted': s3.corrupt_preview = True
    key = f"clean/{doc['run_id']}/{doc['recordings'][0]['recording']}/browser-preview.json"
    if fault == 'conflicting_supplement': s3.seed(key, b'{"wrong":"binding"}')
    with pytest.raises(ValueError, match='differs|mismatch'):
        preview.publish_preview(s3, doc, ref, tmp_path)
    assert key not in s3.writes


def test_zero_retained_footage_does_not_publish_an_empty_preview(tmp_path):
    s3, doc, ref = publication_fixture(tmp_path)
    doc['recordings'][0]['media']['retained_frame_count'] = 0
    assert preview.publish_preview(s3, doc, ref, tmp_path) == []
    assert not s3.writes
