"""Add a verified H.264 viewing copy without rewriting committed Clean evidence."""
import hashlib
import json
import os
from contextlib import ExitStack
from fractions import Fraction
from itertools import zip_longest
from pathlib import Path
from tempfile import TemporaryDirectory

import av
import boto3
from PIL import Image

BUCKET = '6thsense-processed'
TB = Fraction(1, 1_000_000)
SCHEMA = '6thsense-browser-preview/1'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest_file(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def read_pinned(s3, ref, destination=None):
    require(ref.get('version_id') not in (None, '', 'null'), 'Unversioned input')
    response = s3.get_object(Bucket=ref['bucket'], Key=ref['key'], VersionId=ref['version_id'])
    digest = hashlib.sha256()
    count = 0
    with ExitStack() as stack:
        body = response['Body']
        stack.callback(body.close)
        handle = stack.enter_context(destination.open('wb')) if destination else None
        parts = []
        while chunk := body.read(8 << 20):
            digest.update(chunk)
            count += len(chunk)
            if handle:
                handle.write(chunk)
            else:
                require(count <= 4 << 20, 'Manifest exceeds size limit')
                parts.append(chunk)
    require(count == ref['bytes'] and digest.hexdigest() == ref['sha256'], 'Input digest or size mismatch')
    return b''.join(parts) if not destination else None


def encode_preview(left, right, target, frame_count, duration_us):
    """Preserve every retained frame and its measured timestamp in stereo order."""
    pts, durations = [], []
    with ExitStack() as stack:
        sources = [stack.enter_context(av.open(str(p))) for p in (left, right)]
        for source in sources:
            require(len(source.streams.video) == 1, 'Expected one eye stream')
            stream = source.streams.video[0]
            require((stream.width, stream.height) == (1920, 1200), 'Unexpected native eye dimensions')
            stream.codec_context.thread_count = 2
        output = stack.enter_context(av.open(str(target), 'w', options={'movflags': '+faststart'}))
        stream = output.add_stream('libx264', rate=30)
        stream.width, stream.height, stream.pix_fmt = 1920, 600, 'yuv420p'
        stream.time_base = stream.codec_context.time_base = TB
        stream.codec_context.thread_count = 4
        stream.options = {'preset': 'veryfast', 'crf': '23', 'bf': '0', 'g': '60'}
        pending = {}

        def mux(packets):
            for packet in packets:
                timestamp = round(packet.pts * packet.time_base / TB)
                packet.duration = round(pending.pop(timestamp) * TB / packet.time_base)
                output.mux(packet)

        for index, pair in enumerate(zip_longest(*(s.decode(video=0) for s in sources))):
            require(all(f is not None for f in pair), 'Eye frame counts differ')
            clocks = [(round(f.pts * f.time_base / TB), round(f.duration * f.time_base / TB)) for f in pair]
            require(clocks[0] == clocks[1], 'Eye timestamps differ')
            timestamp, duration = clocks[0]
            require(duration > 0 and timestamp == (pts[-1] + durations[-1] if pts else 0), 'Discontinuous Clean timestamps')
            require(index < frame_count, 'Extra eye frames')
            canvas = Image.new('RGB', (1920, 600))
            for eye, frame in enumerate(pair):
                canvas.paste(frame.reformat(width=960, height=600, format='rgb24').to_image(), (eye * 960, 0))
            frame = av.VideoFrame.from_image(canvas)
            frame.pts, frame.time_base = timestamp, TB
            pending[timestamp] = duration
            mux(stream.encode(frame))
            pts.append(timestamp)
            durations.append(duration)
            if index and index % 3000 == 0:
                print(json.dumps({'phase': 'preview_encoding', 'frames': index, 'total': frame_count}), flush=True)
        mux(stream.encode())
        require(not pending and len(pts) == frame_count and pts[-1] + durations[-1] == duration_us, 'Preview timeline differs from Clean')
    # Reopen and decode the entire preview; compare packet durations too, including
    # the final frame, which a nominal frame rate would otherwise silently alter.
    with av.open(str(target)) as result:
        stream = result.streams.video[0]
        require(stream.codec_context.name == 'h264' and stream.codec_context.format.name == 'yuv420p', 'Preview is not browser compatible')
        decoded = [round(f.pts * f.time_base / TB) for f in result.decode(video=0)]
        require(decoded == pts, 'Preview decoded timestamps differ')
    with av.open(str(target)) as result:
        packets = [(round(p.pts * p.time_base / TB), round(p.duration * p.time_base / TB))
                   for p in result.demux(video=0) if p.pts is not None]
        require(packets == list(zip(pts, durations)), 'Preview packet timeline differs')
    return {'codec': 'h264', 'width': 1920, 'height': 600, 'frame_count': len(pts),
            'duration_us': duration_us, 'all_frames_decoded': True, 'all_timestamps_checked': True}


def put_verified(s3, key, path, content_type):
    digest = digest_file(path)
    # Content-addressed output and conditional publication make retries harmless.
    with path.open('rb') as body:
        try:
            response = s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType=content_type,
                                     Metadata={'sha256': digest}, IfNoneMatch='*')
        except s3.exceptions.ClientError as exc:
            if exc.response['Error']['Code'] != 'PreconditionFailed':
                raise
            response = s3.head_object(Bucket=BUCKET, Key=key)
    ref = {'bucket': BUCKET, 'key': key, 'version_id': response.get('VersionId'),
           'bytes': path.stat().st_size, 'sha256': digest}
    # Complete read-back, not just ETag/metadata, before publishing the supplement.
    with TemporaryDirectory(prefix='preview-verify-') as tmp:
        read_pinned(s3, ref, Path(tmp) / 'verified')
    return ref


def publish_preview(s3, doc, manifest, directory):
    require(doc['schema'] == '6thsense-clean-qc/2', 'Preview requires a multimodal Clean run')
    require(manifest['bucket'] == BUCKET and manifest['key'] == f"qc-results/{doc['run_id']}/result.json", 'Wrong manifest binding')
    receipts = []
    for recording in doc['recordings']:
        media = recording.get('media', {})
        if not media.get('retained_frame_count'):
            continue
        name = recording['recording']
        require('/' not in name and name not in ('.', '..'), 'Invalid recording identity')
        prefix = f"clean/{doc['run_id']}/{name}/"
        eyes = []
        for eye in ('left', 'right'):
            candidates = [o for o in doc['outputs'] if o.get('recording') == name and o.get('role') == eye + '_video']
            require(len(candidates) == 1, 'Missing or ambiguous eye video')
            ref = {k: candidates[0][k] for k in ('key', 'version_id', 'sha256', 'bytes')}
            require(ref['key'].startswith(f"clean/{doc['run_id']}/"), 'Eye outside Clean run')
            path = directory / (eye + '.mp4')
            if not path.exists():
                read_pinned(s3, {'bucket': BUCKET, **ref}, path)
            require(path.stat().st_size == ref['bytes'] and digest_file(path) == ref['sha256'], 'Local eye differs from committed output')
            eyes.append(ref)
        target = directory / 'browser-preview.mp4'
        verification = encode_preview(directory / 'left.mp4', directory / 'right.mp4', target,
                                      media['retained_frame_count'], round(media['retained_seconds'] * 1_000_000))
        digest = digest_file(target)
        output = put_verified(s3, prefix + f'browser-preview-{digest}.mp4', target, 'video/mp4')
        supplement = {'schema': SCHEMA, 'run_id': doc['run_id'], 'recording': name,
                      'manifest': {k: manifest[k] for k in ('key', 'version_id', 'sha256')},
                      'sources': eyes, 'output': output, 'verification': verification}
        path = directory / 'browser-preview.json'
        path.write_text(json.dumps(supplement, sort_keys=True, separators=(',', ':')) + '\n')
        receipts.append(put_verified(s3, prefix + 'browser-preview.json', path, 'application/json'))
        print(json.dumps({'phase': 'preview_published', 'recording': name, 'output': output, 'supplement': receipts[-1]}), flush=True)
    return receipts


def main():
    s3 = boto3.client('s3', region_name='us-west-2')
    manifest = json.loads(os.environ['PREVIEW_MANIFEST_REF'])
    doc = json.loads(read_pinned(s3, manifest))
    # Backfill is bounded to one explicit immutable manifest per invocation.
    require(len(doc['recordings']) == 1, 'Backfill expects one recording')
    with TemporaryDirectory(prefix='clean-preview-') as tmp:
        publish_preview(s3, doc, manifest, Path(tmp))


if __name__ == '__main__':
    main()
