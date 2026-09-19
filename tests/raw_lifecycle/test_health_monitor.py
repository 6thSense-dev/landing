import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('health_monitor', Path(__file__).parents[2] / 'infra/raw_lifecycle/health_monitor.py')
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)


def healthy():
    return {'controller_enabled': True, 'controller_age_seconds': 180,
            'raw_scan_age_seconds': 90,
            'portal': {'automatic_scan': True, 'processing_counts': {}},
            'queues': [{'name': 'cpu', 'counts': {'RUNNABLE': 2, 'RUNNING': 16}, 'oldest_runnable_seconds': 600}],
            'running_jobs': [{'name': 'job', 'progress_age_seconds': 10}],
            'compute': [{'name': 'cpu', 'status': 'VALID', 'reason': ''}]}


def test_recent_progress_and_short_queue_are_healthy():
    assert monitor.evaluate(healthy()) == []


def test_missing_health_inputs_never_look_healthy():
    findings = monitor.evaluate({})
    assert {f['code'] for f in findings} == {'controller_disabled', 'coordinator_stale', 'raw_scan_stale', 'raw_scan_disabled', 'queues_missing', 'compute_missing'}
    assert all(f['severity'] == 'critical' for f in findings)


@pytest.mark.parametrize('active,severity,code', [(16, 'warning', 'capacity_backlog'), (0, 'critical', 'queue_not_starting')])
def test_capacity_backlog_is_distinct_from_jobs_not_starting(active, severity, code):
    report = healthy()
    report['queues'][0].update(counts={'RUNNABLE': 109, 'RUNNING': active}, oldest_runnable_seconds=7200)
    before = copy.deepcopy(report)
    findings = monitor.evaluate(report)
    assert len(findings) == 1 and findings[0]['code'] == code and findings[0]['severity'] == severity
    assert report == before  # monitoring must never mutate job state


def test_source_holds_are_reported_without_calling_them_worker_failure():
    report = healthy()
    report['portal']['processing_counts']['blocked'] = 154
    findings = monitor.evaluate(report)
    assert len(findings) == 1
    assert findings[0]['code'] == 'recordings_need_action'
    assert findings[0]['severity'] == 'warning'


def test_stale_scan_coordinator_and_worker_are_independent_findings():
    report = healthy()
    report.update(controller_age_seconds=1201, raw_scan_age_seconds=1801)
    report['running_jobs'][0]['progress_age_seconds'] = 2701
    assert {f['code'] for f in monitor.evaluate(report)} == {'coordinator_stale', 'raw_scan_stale', 'worker_progress_stale'}


def test_failed_checks_and_invalid_capacity_require_attention():
    report = healthy()
    report['check_errors'] = {'portal_health': 'HTTPError'}
    report['compute'][0].update(status='INVALID', reason='Capacity unavailable')
    findings = monitor.evaluate(report)
    assert {f['code'] for f in findings} == {'check_failed', 'compute_invalid'}
    assert all(f['severity'] == 'critical' for f in findings)


def test_timestamp_age_handles_utc_and_future_clock_skew():
    assert monitor.age_seconds('1970-01-01T00:01:00Z', 120) == 60
    assert monitor.age_seconds('1970-01-01T00:01:00+00:00', 30) == 0
    assert monitor.age_seconds(None, 120) is None


def test_disabled_configured_queue_and_expired_window_cannot_look_healthy():
    report = healthy()
    report['deadline_expired'] = True
    report['queues'][0].update(required=True, state='DISABLED', status='VALID')
    report['compute'][0].update(required=True, state='DISABLED')
    assert {f['code'] for f in monitor.evaluate(report)} == {'processing_window_expired', 'queue_unavailable', 'compute_disabled'}


def test_missing_required_queue_or_environment_is_critical_even_with_other_workers():
    report = healthy()
    report.update(missing_queues=['gpu'], missing_compute=['gpu-capacity'])
    assert {f['code'] for f in monitor.evaluate(report)} == {'queues_missing', 'compute_missing'}


@pytest.mark.parametrize('phase', ['SUBMITTED', 'PENDING', 'STARTING'])
def test_long_pre_running_wait_never_looks_healthy(phase):
    report = healthy()
    report['queues'][0]['oldest_wait_seconds'] = {phase: 1801}
    findings = monitor.evaluate(report)
    assert len(findings) == 1
    assert findings[0]['code'] == ('job_start_delayed' if phase == 'STARTING' else 'job_admission_delayed')
    assert findings[0]['severity'] == 'warning'
