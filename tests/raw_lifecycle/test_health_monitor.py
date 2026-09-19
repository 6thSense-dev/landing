import copy
import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

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


def test_country_totals_show_hours_episodes_upload_size_and_unknown_measurements():
    india = dict(country='india', label='India', episodes=3, known_seconds=5400,
                 unknown_duration_episodes=1, uploaded_bytes=2_500_000_000, unknown_size_episodes=1)
    empty = dict(country='vietnam', label='Vietnam', episodes=0, known_seconds=0,
                 unknown_duration_episodes=0, uploaded_bytes=0, unknown_size_episodes=0)
    portal = {'accumulated_data': {'countries': [india, empty], 'totals': india}}
    text = '\n'.join(monitor.accumulation_lines(portal))
    assert 'India: 1.50 h known + 1 episodes with unknown duration · 3 episodes · 2.50 GB uploaded' in text
    assert '1 episodes with unknown size' in text
    assert 'Vietnam: 0.00 h · 0 episodes · 0.00 GB uploaded' in text
    assert 'Total: 1.50 h known' in text
    assert 'including processed and held episodes' in text
    assert 'Deleted episodes excluded' in text


def test_missing_country_summary_is_unavailable_instead_of_zero():
    assert monitor.accumulation_lines({}) == ['Accumulated data by country: unavailable.']


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


def slack_response(monkeypatch, body, status=200, *, expected_timeout=15):
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, limit):
            return body[:limit]

    Response.status = status

    def send(request, timeout):
        requests.append(request)
        assert timeout == expected_timeout
        return Response()

    monkeypatch.setattr(monitor.urllib.request, 'urlopen', send)
    return requests


def bot_secret(channel='C123ABC'):
    return json.dumps({'bot_token': 'xoxb-test-only', 'channel_id': channel})


def test_bot_delivery_targets_configured_channel_and_keeps_token_out_of_report(monkeypatch):
    requests = slack_response(monkeypatch, b'{"ok":true,"channel":"C123ABC","ts":"123.456"}')
    result = monitor.send_slack('Pipeline report', bot_secret(), bot=True)
    assert result == {'delivered': True, 'method': 'bot', 'channel_id': 'C123ABC', 'message_ts': '123.456'}
    request = requests[0]
    assert request.full_url == 'https://slack.com/api/chat.postMessage'
    assert request.get_header('Authorization') == 'Bearer xoxb-test-only'
    assert json.loads(request.data) == {'text': 'Pipeline report', 'channel': 'C123ABC', 'unfurl_links': False, 'unfurl_media': False}
    assert 'xoxb-' not in json.dumps(result)


@pytest.mark.parametrize('body,status', [
    (b'{"ok":false,"error":"not_in_channel"}', 200),
    (b'{"ok":true,"channel":"COTHER","ts":"123.456"}', 200),
    (b'{"ok":true,"channel":"C123ABC"}', 200),
    (b'{}', 429),
])
def test_slack_http_success_alone_does_not_confirm_delivery(monkeypatch, body, status):
    slack_response(monkeypatch, body, status)
    with pytest.raises(ValueError, match='Slack did not acknowledge'):
        monitor.send_slack('Pipeline report', bot_secret(), bot=True)


@pytest.mark.parametrize('credential', [
    '[]', '{}', bot_secret('D123ABC'), bot_secret('#dataops'),
    '{"bot_token":"xoxp-user-token","channel_id":"C123ABC"}',
])
def test_invalid_bot_configuration_never_sends_a_request(monkeypatch, credential):
    requests = slack_response(monkeypatch, b'{}')
    with pytest.raises(ValueError):
        monitor.send_slack('Pipeline report', credential, bot=True)
    assert requests == []


def test_existing_incoming_webhook_delivery_still_requires_acknowledgement(monkeypatch):
    requests = slack_response(monkeypatch, b'ok')
    result = monitor.send_slack('Pipeline report', 'https://hooks.slack.com/services/test-only')
    assert result == {'delivered': True, 'method': 'webhook'}
    assert requests[0].get_header('Authorization') is None
    slack_response(monkeypatch, b'invalid_token')
    with pytest.raises(ValueError):
        monitor.send_slack('Pipeline report', 'https://hooks.slack.com/services/test-only')


deploy_spec = importlib.util.spec_from_file_location('deploy_health_monitor', Path(__file__).parents[2] / 'infra/raw_lifecycle/deploy_health_monitor.py')
deployment = importlib.util.module_from_spec(deploy_spec)
deploy_spec.loader.exec_module(deployment)
SECRET_ARN = 'arn:aws:secretsmanager:us-west-2:194680606079:secret:slack-test'


@pytest.mark.parametrize('key', deployment.SLACK_KEYS)
def test_redeploy_preserves_slack_destination_and_unrelated_environment(key):
    existing = {key: SECRET_ARN, 'LOG_LEVEL': 'INFO'}
    assert deployment.notification_environment({}, existing) == existing


def test_explicit_bot_configuration_replaces_webhook_without_retaining_old_permission():
    assert deployment.notification_environment(
        {'SLACK_BOT_SECRET_ARN': SECRET_ARN},
        {'SLACK_WEBHOOK_SECRET_ARN': SECRET_ARN + '-old', 'LOG_LEVEL': 'INFO'},
    ) == {'SLACK_BOT_SECRET_ARN': SECRET_ARN, 'LOG_LEVEL': 'INFO'}


@pytest.mark.parametrize('requested,existing', [
    ({key: SECRET_ARN for key in deployment.SLACK_KEYS}, {}),
    ({}, {key: SECRET_ARN for key in deployment.SLACK_KEYS}),
    ({'SLACK_BOT_SECRET_ARN': SECRET_ARN.replace('us-west-2', 'us-east-1')}, {}),
])
def test_ambiguous_or_wrong_region_delivery_configuration_is_rejected(requested, existing):
    with pytest.raises(ValueError):
        deployment.notification_environment(requested, existing)


@pytest.mark.parametrize('conflicting', [False, True])
def test_handler_persists_failed_delivery_without_exposing_credentials(monkeypatch, capsys, conflicting):
    monkeypatch.setenv('SLACK_BOT_SECRET_ARN', SECRET_ARN)
    monkeypatch.delenv('SLACK_WEBHOOK_SECRET_ARN', raising=False)
    if conflicting:
        monkeypatch.setenv('SLACK_WEBHOOK_SECRET_ARN', SECRET_ARN + '-old')
    clients = {name: MagicMock() for name in ['s3', 'batch', 'logs', 'secretsmanager', 'cloudwatch']}
    monkeypatch.setattr(monitor.boto3, 'client', lambda name, **kwargs: clients[name])
    now = datetime.now(timezone.utc)

    def read_object(Bucket, Key):
        value = {'enabled': True, 'completion_policy': 'until_idle', 'api_url': 'https://example.invalid', 'token_secret': 'pipeline-token'} if Key.endswith('config.json') else {}
        body = json.dumps(value).encode()
        return {'Body': io.BytesIO(body), 'ContentLength': len(body), 'LastModified': now}

    clients['s3'].get_object.side_effect = read_object
    clients['batch'].get_paginator.return_value.paginate.return_value = [{'jobQueues': [], 'computeEnvironments': []}]
    clients['secretsmanager'].get_secret_value.return_value = {'SecretString': 'fake-secret-must-not-appear'}
    country = dict(country='india', label='India', episodes=3, known_seconds=5400,
                   unknown_duration_episodes=0, uploaded_bytes=2_500_000_000, unknown_size_episodes=0)
    slack_response(monkeypatch, json.dumps({'last_raw_scan': now.isoformat(), 'automatic_scan': True,
        'accumulated_data': {'countries': [country], 'totals': country}}).encode(), expected_timeout=20)
    sender = MagicMock(side_effect=RuntimeError('fake-secret-must-not-appear'))
    monkeypatch.setattr(monitor, 'send_slack', sender)
    result = monitor.handler({}, None)
    reports = [json.loads(call.kwargs['Body']) for call in clients['s3'].put_object.call_args_list]
    assert len(reports) == 2
    assert result['status'] == 'critical'
    for report in reports:
        assert report['slack']['delivered'] is False
        assert report['check_errors']['slack_delivery'] == ('ValueError' if conflicting else 'RuntimeError')
        assert any(f['code'] == 'check_failed' and f['severity'] == 'critical' and 'slack_delivery' in f['detail'] for f in report['findings'])
    assert 'fake-secret-must-not-appear' not in json.dumps(reports) + capsys.readouterr().out
    if conflicting:
        sender.assert_not_called()
    else:
        assert sender.call_args.kwargs == {'bot': True}
        assert 'India: 1.50 h · 3 episodes · 2.50 GB uploaded' in sender.call_args.args[0]
        assert 'Total: 1.50 h · 3 episodes · 2.50 GB uploaded' in sender.call_args.args[0]
        assert reports[0]['portal']['accumulated_data']['totals']['episodes'] == 3


def test_deploy_grants_only_selected_slack_secret_and_preserves_other_environment(monkeypatch):
    monkeypatch.setenv('SLACK_BOT_SECRET_ARN', SECRET_ARN)
    monkeypatch.delenv('SLACK_WEBHOOK_SECRET_ARN', raising=False)
    clients = {name: MagicMock() for name in ['sts', 'iam', 'lambda', 'events', 's3', 'cloudwatch', 'logs', 'secretsmanager']}
    session = MagicMock()
    session.client.side_effect = lambda name: clients[name]
    monkeypatch.setattr(deployment.boto3, 'Session', lambda **kwargs: session)
    clients['sts'].get_caller_identity.return_value = {'Account': deployment.ACCOUNT}
    clients['lambda'].get_function_configuration.return_value = {
        'FunctionArn': 'arn:aws:lambda:us-west-2:194680606079:function:health-test',
        'Environment': {'Variables': {'SLACK_WEBHOOK_SECRET_ARN': SECRET_ARN + '-old', 'LOG_LEVEL': 'INFO'}},
    }
    clients['s3'].get_object.return_value = {'Body': io.BytesIO(b'{"token_secret":"pipeline-token"}')}
    clients['secretsmanager'].describe_secret.return_value = {'ARN': SECRET_ARN + '-pipeline'}
    clients['iam'].create_role.return_value = {'Role': {'Arn': 'arn:aws:iam::194680606079:role/health-test'}}
    clients['events'].put_rule.return_value = {'RuleArn': 'arn:aws:events:us-west-2:194680606079:rule/health-test'}
    clients['events'].put_targets.return_value = {'FailedEntryCount': 0}
    deployment.deploy()
    policy = json.loads(clients['iam'].put_role_policy.call_args.kwargs['PolicyDocument'])
    secret_resources = {s['Resource'] for s in policy['Statement'] if s['Action'] == 'secretsmanager:GetSecretValue'}
    assert secret_resources == {SECRET_ARN, SECRET_ARN + '-pipeline'}
    assert clients['lambda'].update_function_configuration.call_args.kwargs['Environment']['Variables'] == {
        'SLACK_BOT_SECRET_ARN': SECRET_ARN, 'LOG_LEVEL': 'INFO',
    }
