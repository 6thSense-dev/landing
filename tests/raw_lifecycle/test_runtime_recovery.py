"""Exercise the deployment's generated runtime without importing its AWS setup."""
import ast
import copy
from fractions import Fraction
import hashlib
import io
import json
import sys
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

DEPLOY = Path(__file__).parents[2] / 'infra/raw_lifecycle/deploy.py'
# Exact guard expressions from the hash-pinned upstream stage_worker.py. These
# small executable excerpts keep this deployment test independent of PyAV/CUDA.
STAGE = """
TASK='raw-h265-all-20260915'
def source_period(rate):
 assert rate and 10<=rate<=120
 return 1/rate

def presentation_duration(current,following):
 p=current['display_pts'];duration=(following['display_pts']-p) if following else current['nominal_period'];assert 0<duration<1000000
 return duration

def sensor_is_continuous(previous_sensor,exp_start):
 return previous_sensor is None or 0<exp_start-previous_sensor<1000000
"""
WORKER = """import stage_worker as sw
def check(report,spec,rec):
 assert report['recording']==spec['recording']==rec and spec['kind']=='stereo_video' and spec['source_complete_flag'] is True
def publish(canary):
 if not canary:
  marker=json.dumps({'complete':True})
"""


def definitions():
    tree = ast.parse(DEPLOY.read_text())
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in ('adapt_stage_runtime', 'adapt_clean_runtime', 'runtime', 'update_processing')]
    namespace = dict(hashlib=hashlib, io=io, tarfile=tarfile, copy=copy, json=json)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(DEPLOY), 'exec'), namespace)
    return namespace


def patched_stage():
    source = definitions()['adapt_stage_runtime'](STAGE)
    namespace = {}
    exec(compile(source, 'patched_stage_worker', 'exec'), namespace)
    return namespace


def test_one_fps_container_keeps_source_clock_instead_of_inventing_30_fps():
    stage = patched_stage()
    # Actual ffprobe rate of pinned video_live_0000.mp4: 901 frames / 900.033333s.
    period = stage['source_period'](Fraction(27030, 27001))
    assert period == Fraction(27001, 27030)
    pts = [0, 1_000_000, 2_000_000]
    rows = [dict(display_pts=p, nominal_period=round(period * 1_000_000)) for p in pts]
    assert [stage['presentation_duration'](a, b) for a, b in zip(rows, rows[1:])] == [1_000_000, 1_000_000]
    assert [r['display_pts'] for r in rows] == pts
    assert stage['presentation_duration'](rows[-1], None) == round(period * 1_000_000)
    # Source presentation seconds do not redefine measured sensor cadence.
    assert stage['sensor_is_continuous'](20_925_106, 20_958_386)
    assert not stage['sensor_is_continuous'](20_925_106, 21_925_106)


def test_normal_30_fps_behavior_is_unchanged():
    stage = patched_stage()
    assert stage['source_period'](Fraction(30)) == Fraction(1, 30)
    assert stage['presentation_duration']({'display_pts':0}, {'display_pts':33333}) == 33333


@pytest.mark.parametrize('rate', [None, Fraction(0), Fraction(-1), Fraction(999, 1000), Fraction(121)])
def test_unsupported_container_rates_still_fail_closed(rate):
    with pytest.raises(AssertionError):
        patched_stage()['source_period'](rate)


@pytest.mark.parametrize('duration', [-1, 0, 1_000_001])
def test_nonpositive_or_over_one_second_presentation_interval_still_fails(duration):
    with pytest.raises(AssertionError):
        patched_stage()['presentation_duration']({'display_pts':0}, {'display_pts':duration})


@pytest.mark.parametrize('changed', [STAGE.replace('10<=rate', '11<=rate'), STAGE + STAGE])
def test_upstream_runtime_drift_fails_before_building_runtime(changed):
    with pytest.raises(RuntimeError, match='anchor changed'):
        definitions()['adapt_stage_runtime'](changed)


def test_runtime_assembly_patches_shared_stage_for_conversion_and_final_clean(tmp_path):
    namespace = definitions()
    upstream = io.BytesIO()
    with tarfile.open(fileobj=upstream, mode='w:gz') as archive:
        for name, value in [('stage_worker.py', STAGE), ('worker.py', WORKER)]:
            body = value.encode()
            info = tarfile.TarInfo(name)
            info.size = len(body)
            archive.addfile(info, io.BytesIO(body))
    source = upstream.getvalue()
    pin = dict(bucket='artifacts', key='runtime.tar.gz', version_id='pinned-version', sha256=hashlib.sha256(source).hexdigest())

    class S3:
        def get_object(self, **kwargs):
            assert kwargs == dict(Bucket=pin['bucket'], Key=pin['key'], VersionId=pin['version_id'])
            return {'Body': io.BytesIO(source)}

    (tmp_path / 'archive_worker.py').write_text('# archive worker fixture\n')
    (tmp_path / 'browser_preview.py').write_text('# browser preview fixture\n')
    published = []
    namespace.update(SOURCE_RUNTIME=pin, s3=S3(), ROOT=tmp_path,
                     upload=lambda key, body: published.append((key, body)))
    namespace['runtime']()
    key, body = published[0]
    assert key.endswith(hashlib.sha256(body).hexdigest() + '.tar.gz')
    with tarfile.open(fileobj=io.BytesIO(body), mode='r:gz') as archive:
        stage = archive.extractfile('stage_worker.py').read().decode()
        clean = archive.extractfile('worker.py').read().decode()
    assert 'import stage_worker as sw' in clean
    assert "Conversion receipt source versions differ from plan" in clean
    assert clean.index('publish_preview(s3,doc,ref,out)') < clean.index('marker=json.dumps(')
    assert 'assert rate and 1<=rate<=120' in stage
    assert 'assert 0<duration<=1000000' in stage
    assert '0<exp_start-previous_sensor<1000000' in stage
    assert "TASK=os.environ.get('PIPELINE_TASK','raw-h265-all-20260915')" in stage


@pytest.mark.parametrize('changed', [WORKER.replace(' if not canary:', ' if canary:'), WORKER + WORKER])
def test_clean_publication_drift_cannot_silently_skip_browser_preview(changed):
    with pytest.raises(RuntimeError, match='publication anchor changed'):
        definitions()['adapt_clean_runtime'](changed)


def test_preview_failure_prevents_clean_completion_marker(monkeypatch):
    namespace = definitions()
    source = namespace['adapt_clean_runtime'](WORKER)
    events = []
    def fail(*args):
        events.append('preview')
        raise ValueError('Preview failed verification')
    monkeypatch.setitem(sys.modules, 'stage_worker', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'browser_preview', SimpleNamespace(publish_preview=fail))
    environment = dict(s3=None, doc=None, ref=None, out=None,
                       json=SimpleNamespace(dumps=lambda value: events.append('marker')))
    exec(compile(source, 'patched_clean', 'exec'), environment)
    with pytest.raises(ValueError, match='Preview failed'):
        environment['publish'](False)
    assert events == ['preview']
    events.clear()
    environment['publish'](True)
    assert events == []  # A limited-frame canary never publishes complete footage.


def processing_fakes():
    namespace = definitions()
    initial = dict(conversion_definition='conversion:4', clean_definition='clean:4',
                   clean_runtime={'sha256':'old'}, enabled=True, retirement_enabled=False,
                   archive_definition='archive:5', archive_runtime={'sha256':'archive'},
                   run_deadline_epoch=123456, compute_budget_usd=100, jobs={'existing':'job-id'})
    current = copy.deepcopy(initial)
    calls = []
    policy = {'Statement':[{'Effect':'Allow', 'Action':['batch:SubmitJob','batch:TagResource'],
                           'Resource':['queue', 'conversion:4', 'clean:4', 'archive:5']} ]}
    old_container = {'command':['old'], 'environment':[{'name':'PIPELINE_TASK','value':'old'},
                     {'name':'CLEAN_CPU','value':'1'}], 'resourceRequirements':[{'type':'VCPU','value':'4'}],
                     'jobRoleArn':'existing-role', 'image':'pinned-image'}

    class S3:
        def get_object(self, **kwargs):
            calls.append(('get_config', kwargs))
            return {'Body':io.BytesIO(json.dumps(current).encode()), 'ETag':'current-etag'}

        def put_object(self, **kwargs):
            assert kwargs['IfMatch'] == 'current-etag'
            calls.append(('put_config', json.loads(kwargs['Body'])))

    class Batch:
        def describe_job_definitions(self, **kwargs):
            return {'jobDefinitions':[{'containerProperties':copy.deepcopy(old_container),
                    'timeout':{'attemptDurationSeconds':21600}, 'retryStrategy':{'attempts':1}}]}

        def register_job_definition(self, **kwargs):
            calls.append(('register', kwargs))
            lane = kwargs['jobDefinitionName'].removeprefix('test-')
            return {'jobDefinitionArn':lane + ':5'}

    class IAM:
        def get_role_policy(self, **kwargs):
            return {'PolicyDocument':copy.deepcopy(policy)}

        def put_role_policy(self, **kwargs):
            calls.append(('put_policy', json.loads(kwargs['PolicyDocument'])))

    def propagation(seconds):
        assert seconds == 60
        calls.append(('wait', seconds))
        current['enabled'] = False  # Simulate watchdog shutdown during propagation.
        current['run_deadline_epoch'] = 120000

    namespace.update(s3=S3(), batch=Batch(), iam=IAM(), NAME='test', ARTIFACTS='artifacts',
                     time=SimpleNamespace(sleep=propagation), runtime=lambda:{'sha256':'new'},
                     bootstrap=lambda ref, name:'bootstrap ' + name)
    return namespace, initial, current, calls, policy, old_container


def test_processing_update_preserves_jobs_budget_flags_and_old_permissions():
    namespace, initial, current, calls, _, container = processing_fakes()
    namespace['update_processing']()
    assert [name for name, _ in calls] == ['get_config','register','register','put_policy','wait','get_config','put_config']
    updated = calls[-1][1]
    assert updated == dict(current, conversion_definition='conversion:5', clean_definition='clean:5', clean_runtime={'sha256':'new'})
    assert updated['enabled'] is False
    assert updated['jobs'] == initial['jobs']
    assert updated['compute_budget_usd'] == initial['compute_budget_usd']
    resources = next(data for name, data in calls if name == 'put_policy')['Statement'][0]['Resource']
    assert resources == ['queue','conversion:4','clean:4','archive:5','conversion:5','clean:5']
    for name, registration in calls:
        if name != 'register':
            continue
        new = registration['containerProperties']
        assert new['resourceRequirements'] == container['resourceRequirements']
        assert new['jobRoleArn'] == container['jobRoleArn']
        assert new['image'] == container['image']
        assert {'name':'PIPELINE_TASK','value':'raw-lifecycle-v1'} in new['environment']
        assert registration['retryStrategy'] == {'attempts':1}


def test_processing_update_does_not_activate_definitions_without_tag_permission():
    namespace, _, _, calls, policy, _ = processing_fakes()
    policy['Statement'][0]['Action'] = ['batch:SubmitJob']
    with pytest.raises(RuntimeError, match='policy not recognized'):
        namespace['update_processing']()
    assert not any(name in ('put_config','put_policy','wait') for name, _ in calls)


def test_processing_update_does_not_overwrite_concurrent_definition_change():
    namespace, _, current, calls, _, _ = processing_fakes()
    namespace['time'].sleep = lambda seconds:current.update(clean_definition='other:9')
    with pytest.raises(RuntimeError, match='changed concurrently'):
        namespace['update_processing']()
    assert not any(name == 'put_config' for name, _ in calls)
