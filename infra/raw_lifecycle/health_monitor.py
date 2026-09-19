"""Read-only half-hour pipeline checks; writes reports, never retries or changes QA."""
import concurrent.futures
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timezone

import boto3
from botocore.config import Config

PREFIX = 'raw-lifecycle/v1/health/'
BUCKET = '6thsense-processed'
ARTIFACTS = '6thsense-deploy-artifacts'
ACTIVE = ('SUBMITTED', 'PENDING', 'RUNNABLE', 'STARTING', 'RUNNING')


def send_slack(text, credential, *, bot=False):
    """Acknowledge delivery without putting credentials or response bodies in reports."""
    headers = {'Content-Type': 'application/json; charset=utf-8'}
    payload = {'text': text}
    if bot:
        config = json.loads(credential)
        if not isinstance(config, dict):
            raise ValueError('Expected a Slack bot secret object')
        token, channel = config.get('bot_token'), config.get('channel_id')
        if (not isinstance(token, str) or not token.startswith('xoxb-')
                or not isinstance(channel, str) or not re.fullmatch(r'[CG][A-Z0-9]+', channel)):
            raise ValueError('Expected a bot token and channel ID')
        url = 'https://slack.com/api/chat.postMessage'
        headers['Authorization'] = 'Bearer ' + token
        payload.update(channel=channel, unfurl_links=False, unfurl_media=False)
    else:
        if not credential.startswith('https://hooks.slack.com/services/'):
            raise ValueError('Expected a Slack incoming webhook')
        url = credential
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers)
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise ValueError('Slack did not acknowledge the report')
        body = response.read(65536)
    if bot:
        result = json.loads(body)
        if (not isinstance(result, dict) or result.get('ok') is not True
                or result.get('channel') != channel or not result.get('ts')):
            raise ValueError('Slack did not acknowledge delivery to the configured channel')
        return {'delivered': True, 'method': 'bot', 'channel_id': channel, 'message_ts': result['ts']}
    if body.strip() != b'ok':
        raise ValueError('Slack did not acknowledge the report')
    return {'delivered': True, 'method': 'webhook'}


def age_seconds(timestamp, now):
    if timestamp is None:
        return None
    return max(0, now - datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp())


def evaluate(report):
    """Separate source holds, expected capacity backlog, and stalled infrastructure."""
    findings = []

    def add(code, severity, detail):
        findings.append({'code': code, 'severity': severity, 'detail': detail})

    for component, error in report.get('check_errors', {}).items():
        add('check_failed', 'critical', f'{component}: {error}')
    if not report.get('controller_enabled'):
        add('controller_disabled', 'critical', 'Raw intake coordinator is disabled.')
    if report.get('deadline_expired'):
        add('processing_window_expired', 'critical', 'The configured processing window has expired.')
    if not report.get('queues') or report.get('missing_queues'):
        add('queues_missing', 'critical', 'A required processing queue is absent from the health inventory.')
    if not report.get('compute') or report.get('missing_compute'):
        add('compute_missing', 'critical', 'Required processing capacity is absent from the health inventory.')
    age = report.get('controller_age_seconds')
    if age is None or age > 1200:
        add('coordinator_stale', 'critical', 'No completed coordinator pass within 20 minutes.')
    portal = report.get('portal', {})
    raw_age = report.get('raw_scan_age_seconds')
    if raw_age is None or raw_age > 1800:
        add('raw_scan_stale', 'critical', 'Raw inventory has not refreshed within 30 minutes.')
    if not portal.get('automatic_scan'):
        add('raw_scan_disabled', 'critical', 'Automatic Raw scanning is disabled.')
    for queue in report.get('queues', []):
        if queue.get('required') and (queue.get('state') != 'ENABLED' or queue.get('status') != 'VALID'):
            add('queue_unavailable', 'critical', f"{queue['name']}: {queue.get('state')}/{queue.get('status')}.")
        if queue.get('failed_last_30m', 0):
            add('worker_failures', 'warning', f"{queue['name']}: {queue['failed_last_30m']} jobs failed in the last 30 minutes.")
        for phase, age in queue.get('oldest_wait_seconds', {}).items():
            if age > 1800:
                add('job_start_delayed' if phase == 'STARTING' else 'job_admission_delayed', 'warning',
                    f"{queue['name']}: oldest {phase.lower()} job has waited {age // 60} minutes; check startup, dependencies and capacity.")
        waiting = queue['counts'].get('RUNNABLE', 0)
        active = queue['counts'].get('RUNNING', 0) + queue['counts'].get('STARTING', 0)
        if waiting and queue['oldest_runnable_seconds'] > 1800:
            add('capacity_backlog' if active else 'queue_not_starting',
                'warning' if active else 'critical',
                f"{queue['name']}: {waiting} runnable, {active} active; oldest queued {queue['oldest_runnable_seconds'] // 60} minutes.")
    for job in report.get('running_jobs', []):
        if job['progress_age_seconds'] > 2700:
            add('worker_progress_stale', 'warning', f"{job['name']}: no new log progress for over 45 minutes; inspect before retrying.")
    for env in report.get('compute', []):
        if env['status'] == 'INVALID':
            add('compute_invalid', 'critical', f"{env['name']}: {env['reason']}")
        if env.get('required') and env.get('state') != 'ENABLED':
            add('compute_disabled', 'critical', f"{env['name']}: configured capacity is disabled.")
    blocked = portal.get('processing_counts', {}).get('blocked', 0)
    if blocked:
        add('recordings_need_action', 'warning', f'{blocked} recordings are held; source/QA holds are not automatically overridden.')
    return findings


def handler(event, context):
    now = time.time()
    stamp = datetime.fromtimestamp(now, timezone.utc).isoformat()
    opts = Config(connect_timeout=5, read_timeout=20, max_pool_connections=16,
                  retries={'total_max_attempts': 2})
    s3 = boto3.client('s3', config=opts)
    batch = boto3.client('batch', config=opts)
    logs = boto3.client('logs', config=opts)
    report = {'schema': '6thsense-raw-health/1', 'checked_at': stamp,
              'check_interval_minutes': 30, 'check_errors': {}, 'queues': [],
              'running_jobs': [], 'compute': [], 'portal': {},
              'automatic_remediation': False}

    def attempt(name, fn):
        try:
            return fn()
        except Exception as exc:
            # Report error classes only: HTTP URLs, tokens and log bodies stay private.
            report['check_errors'][name] = type(exc).__name__
            return None

    def read(bucket, key):
        response = s3.get_object(Bucket=bucket, Key=key)
        if response['ContentLength'] > 2 * 1024**2:
            response['Body'].close()
            raise ValueError('Health input is too large')
        return json.load(response['Body']), response

    value = attempt('configuration', lambda: read(ARTIFACTS, 'raw-lifecycle/v1/config.json'))
    cfg = value[0] if value else {}
    report['controller_enabled'] = cfg.get('enabled', False)
    deadline = cfg.get('run_deadline_epoch')
    report['deadline_expired'] = cfg.get('completion_policy', 'deadline') != 'until_idle' and (not isinstance(deadline, (int, float)) or now >= deadline)
    status = attempt('coordinator_status', lambda: read(BUCKET, 'raw-lifecycle/v1/status.json'))
    if status:
        report['controller_age_seconds'] = max(0, now - status[1]['LastModified'].timestamp())
        report['controller_recordings'] = status[0].get('recordings')

    def portal_health():
        token = boto3.client('secretsmanager', config=opts).get_secret_value(
            SecretId=cfg['token_secret'])['SecretString']
        request = urllib.request.Request(cfg['api_url'] + '/api/ops/pipeline/health',
            headers={'Authorization': 'Bearer ' + token, 'Origin': 'https://6thsense.dev'})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read(65536))

    portal = attempt('portal_health', portal_health)
    if portal:
        report['portal'] = portal
        report['raw_scan_age_seconds'] = age_seconds(portal.get('last_raw_scan'), now)

    def website():
        with urllib.request.urlopen('https://6thsense.dev', timeout=20) as response:
            return response.status

    report['website_status'] = attempt('website', website)
    required_queues = {cfg.get('cpu_queue'), cfg.get('gpu_queue')} - {None}

    def all_queues():
        return [q for page in batch.get_paginator('describe_job_queues').paginate() for q in page['jobQueues']]

    queues = attempt('queues', all_queues) or []
    report['missing_queues'] = sorted(required_queues - {q['jobQueueArn'] for q in queues})
    queues = [q for q in queues if q['jobQueueArn'] in required_queues or (q['jobQueueName'].startswith('sixthsense-raw-lifecycle-v1-') and q['state'] == 'ENABLED')]
    required_compute = {e['computeEnvironment'] for q in queues if q['jobQueueArn'] in required_queues for e in q['computeEnvironmentOrder']}

    def queue_status(q):
        jobs = {}
        for status_name in (*ACTIVE, 'SUCCEEDED', 'FAILED'):
            jobs[status_name] = [j for page in batch.get_paginator('list_jobs').paginate(
                jobQueue=q['jobQueueArn'], jobStatus=status_name) for j in page.get('jobSummaryList', [])]
        queued = jobs['RUNNABLE']
        result = {'name': q['jobQueueName'], 'state': q['state'], 'status': q['status'], 'required': q['jobQueueArn'] in required_queues,
                  'counts': {k: len(v) for k, v in jobs.items()},
                  'oldest_runnable_seconds': int(max((now-j['createdAt']/1000 for j in queued), default=0)),
                  'oldest_wait_seconds': {phase: int(max((now-j['createdAt']/1000 for j in jobs[phase]), default=0))
                                          for phase in ('SUBMITTED', 'PENDING', 'STARTING')},
                  'succeeded_last_30m': sum(j.get('stoppedAt', 0)/1000 >= now-1800 for j in jobs['SUCCEEDED']),
                  'failed_last_30m': sum(j.get('stoppedAt', 0)/1000 >= now-1800 for j in jobs['FAILED'])}
        return result, jobs['RUNNING']

    running = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(queue_status, q): q['jobQueueName'] for q in queues}
        for future in concurrent.futures.as_completed(futures):
            result = attempt(futures[future], future.result)
            if result:
                report['queues'].append(result[0])
                running.extend(result[1])

    def progress(job):
        details = batch.describe_jobs(jobs=[job['jobId']])['jobs'][0]
        container = details.get('container', {})
        stream = container.get('logStreamName')
        last = details.get('startedAt', details.get('createdAt', int(now*1000)))
        if stream:
            group = container.get('logConfiguration', {}).get('options', {}).get('awslogs-group', '/aws/batch/sixthsense-clean-worker')
            events = logs.get_log_events(logGroupName=group, logStreamName=stream, startFromHead=False, limit=5)['events']
            if events:
                last = max(last, events[-1]['timestamp'])
        return {'id': job['jobId'], 'name': job['jobName'], 'progress_age_seconds': int(max(0, now-last/1000))}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(progress, j): j['jobId'] for j in running}
        for future in concurrent.futures.as_completed(futures):
            value = attempt('worker:' + futures[future], future.result)
            if value:
                report['running_jobs'].append(value)
    def all_compute():
        return [e for page in batch.get_paginator('describe_compute_environments').paginate() for e in page['computeEnvironments']]

    environments = attempt('compute', all_compute) or []
    report['missing_compute'] = sorted(required_compute - {e['computeEnvironmentArn'] for e in environments})
    report['compute'] = [{'name': e['computeEnvironmentName'], 'status': e['status'], 'state': e['state'],
        'required': e['computeEnvironmentArn'] in required_compute,
        'reason': e.get('statusReason', ''), 'desired_vcpus': e.get('computeResources', {}).get('desiredvCpus', 0),
        'max_vcpus': e.get('computeResources', {}).get('maxvCpus', 0)}
        for e in environments if e['computeEnvironmentArn'] in required_compute or e['computeEnvironmentName'].startswith('sixthsense-raw-lifecycle-v1-')]
    report['findings'] = evaluate(report)
    report['status'] = ('critical' if any(f['severity'] == 'critical' for f in report['findings'])
                        else 'attention' if report['findings'] else 'healthy')
    bot_secret = os.getenv('SLACK_BOT_SECRET_ARN')
    webhook_secret = os.getenv('SLACK_WEBHOOK_SECRET_ARN')
    slack_secret = bot_secret or webhook_secret
    if slack_secret:
        def notify_slack():
            if bot_secret and webhook_secret:
                raise ValueError('Configure only one Slack delivery method')
            credential = boto3.client('secretsmanager', config=opts).get_secret_value(SecretId=slack_secret)['SecretString']
            lines = [f"*Raw pipeline check: {report['status']}* — {stamp}"]
            for queue in report['queues']:
                counts = queue['counts']
                lines.append(f"{queue['name'].removeprefix('sixthsense-raw-lifecycle-v1-')}: {counts.get('RUNNING', 0)} running, {counts.get('RUNNABLE', 0)} queued; last 30m: {queue['succeeded_last_30m']} completed, {queue['failed_last_30m']} failed.")
            for label, key in [('Raw inventory', 'raw_scan_age_seconds'), ('Coordinator', 'controller_age_seconds')]:
                age = report.get(key)
                lines.append(f"{label}: {'unavailable' if age is None else str(int(age // 60)) + ' minutes since refresh'}.")
            lines.extend(f"• {f['detail']}" for f in report['findings'][:12])
            if not report['findings']:
                lines.append('No bottleneck detected by these checks.')
            return send_slack('\n'.join(lines), credential, bot=bool(bot_secret))

        report['slack'] = attempt('slack_delivery', notify_slack) or {'delivered': False}
        if not report['slack']['delivered']:
            report['findings'] = evaluate(report)
            report['status'] = 'critical'
    else:
        report['slack'] = {'delivered': False, 'configured': False}
    raw = json.dumps(report, sort_keys=True).encode()
    run_key = PREFIX + 'reports/' + stamp.replace(':', '-') + '.json'
    for key in (run_key, PREFIX + 'latest.json'):
        args = {'Bucket': BUCKET, 'Key': key, 'Body': raw, 'ContentType': 'application/json'}
        if key == run_key:
            args['IfNoneMatch'] = '*'
        s3.put_object(**args)
    boto3.client('cloudwatch', config=opts).put_metric_data(Namespace='SixthSense/RawPipeline', MetricData=[
        {'MetricName': 'HealthCheckSucceeded', 'Value': 1, 'Unit': 'Count'},
        {'MetricName': 'CriticalFindings', 'Value': sum(f['severity'] == 'critical' for f in report['findings']), 'Unit': 'Count'},
    ])
    print(json.dumps({'checked_at': stamp, 'status': report['status'], 'findings': report['findings'], 'report_key': run_key}))
    return {'status': report['status'], 'report_key': run_key, 'findings': report['findings']}
