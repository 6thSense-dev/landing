"""Deploy only the read-only 30-minute monitor, without touching processing."""
import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path

import boto3

ACCOUNT = '194680606079'
REGION = 'us-west-2'
NAME = 'sixthsense-raw-lifecycle-v1-health'
SLACK_KEYS = ('SLACK_BOT_SECRET_ARN', 'SLACK_WEBHOOK_SECRET_ARN')


def notification_environment(requested, existing):
    """Preserve the current destination unless a replacement is explicitly supplied."""
    slack = {k: requested[k] for k in SLACK_KEYS if requested.get(k)}
    if not slack:
        slack = {k: existing[k] for k in SLACK_KEYS if existing.get(k)}
    if len(slack) > 1:
        raise ValueError('Configure only one Slack delivery method')
    for arn in slack.values():
        if not arn.startswith(f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:'):
            raise ValueError('Slack secret must belong to the monitor account and region')
    return {**{k: v for k, v in existing.items() if k not in SLACK_KEYS}, **slack}


def deploy():
    session = boto3.Session(region_name=REGION)
    assert session.client('sts').get_caller_identity()['Account'] == ACCOUNT, 'Wrong AWS account'
    iam, lam, events, s3, cw = [session.client(service) for service in ('iam', 'lambda', 'events', 's3', 'cloudwatch')]
    try:
        existing = lam.get_function_configuration(FunctionName=NAME).get('Environment', {}).get('Variables', {})
    except lam.exceptions.ResourceNotFoundException:
        existing = {}
    environment = notification_environment(os.environ, existing)
    slack_secret = next((environment[k] for k in SLACK_KEYS if environment.get(k)), None)
    logs = session.client('logs')
    try:
        logs.create_log_group(logGroupName='/aws/lambda/' + NAME)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    logs.put_retention_policy(logGroupName='/aws/lambda/' + NAME, retentionInDays=30)
    cfg = json.load(s3.get_object(Bucket='6thsense-deploy-artifacts', Key='raw-lifecycle/v1/config.json')['Body'])
    secret_arn = session.client('secretsmanager').describe_secret(SecretId=cfg['token_secret'])['ARN']
    trust = {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Principal': {'Service': 'lambda.amazonaws.com'}, 'Action': 'sts:AssumeRole'}]}
    try:
        role = iam.create_role(RoleName=NAME, AssumeRolePolicyDocument=json.dumps(trust))['Role']['Arn']
    except iam.exceptions.EntityAlreadyExistsException:
        role = iam.get_role(RoleName=NAME)['Role']['Arn']
    statements = [
        {'Effect': 'Allow', 'Action': ['batch:DescribeJobs', 'batch:ListJobs', 'batch:DescribeJobQueues', 'batch:DescribeComputeEnvironments'], 'Resource': '*'},
        {'Effect': 'Allow', 'Action': 's3:GetObject', 'Resource': [
            'arn:aws:s3:::6thsense-deploy-artifacts/raw-lifecycle/v1/config.json',
            'arn:aws:s3:::6thsense-processed/raw-lifecycle/v1/status.json']},
        {'Effect': 'Allow', 'Action': 's3:PutObject', 'Resource': 'arn:aws:s3:::6thsense-processed/raw-lifecycle/v1/health/*'},
        {'Effect': 'Allow', 'Action': 'secretsmanager:GetSecretValue', 'Resource': secret_arn},
        {'Effect': 'Allow', 'Action': 'logs:GetLogEvents', 'Resource': f'arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/batch/sixthsense-clean-worker:log-stream:*'},
        {'Effect': 'Allow', 'Action': ['logs:CreateLogStream', 'logs:PutLogEvents'], 'Resource': f'arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/{NAME}:*'},
        {'Effect': 'Allow', 'Action': 'cloudwatch:PutMetricData', 'Resource': '*', 'Condition': {'StringEquals': {'cloudwatch:namespace': 'SixthSense/RawPipeline'}}},
    ]
    if slack_secret:
        statements.append({'Effect': 'Allow', 'Action': 'secretsmanager:GetSecretValue', 'Resource': slack_secret})
    iam.put_role_policy(RoleName=NAME, PolicyName='ReadOnlyPipelineChecks', PolicyDocument=json.dumps({'Version': '2012-10-17', 'Statement': statements}))
    source = Path(__file__).with_name('health_monitor.py').read_bytes()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('health_monitor.py', source)
    args = dict(FunctionName=NAME, Runtime='python3.12', Role=role, Handler='health_monitor.handler', Timeout=240, MemorySize=256)
    args['Environment'] = {'Variables': environment}
    try:
        lam.get_function(FunctionName=NAME)
    except lam.exceptions.ResourceNotFoundException:
        for attempt in range(12):
            try:
                lam.create_function(**args, Code={'ZipFile': stream.getvalue()}, Tags={'purpose': 'raw-pipeline-health'})
                break
            except lam.exceptions.InvalidParameterValueException:
                if attempt == 11:
                    raise
                time.sleep(5)
        lam.get_waiter('function_active_v2').wait(FunctionName=NAME)
    else:
        lam.update_function_code(FunctionName=NAME, ZipFile=stream.getvalue())
        lam.get_waiter('function_updated_v2').wait(FunctionName=NAME)
        lam.update_function_configuration(**args)
        lam.get_waiter('function_updated_v2').wait(FunctionName=NAME)
    lam.put_function_concurrency(FunctionName=NAME, ReservedConcurrentExecutions=1)
    arn = lam.get_function_configuration(FunctionName=NAME)['FunctionArn']
    rule = events.put_rule(Name=NAME, ScheduleExpression='rate(30 minutes)', State='ENABLED', Description='Check Raw pipeline progress, capacity, errors and dashboard freshness every 30 minutes')['RuleArn']
    try:
        lam.add_permission(FunctionName=NAME, StatementId='half-hour-health', Action='lambda:InvokeFunction', Principal='events.amazonaws.com', SourceArn=rule, SourceAccount=ACCOUNT)
    except lam.exceptions.ResourceConflictException:
        policy = json.loads(lam.get_policy(FunctionName=NAME)['Policy'])
        statement = next(s for s in policy['Statement'] if s['Sid'] == 'half-hour-health')
        assert statement['Condition']['ArnLike']['AWS:SourceArn'] == rule
    result = events.put_targets(Rule=NAME, Targets=[{'Id': 'health', 'Arn': arn}])
    assert result['FailedEntryCount'] == 0
    # Visible CloudWatch alarms; external notifications require a chosen destination.
    for metric, comparison, threshold, missing, periods in [
            ('HealthCheckSucceeded', 'LessThanThreshold', 1, 'breaching', 2),
            ('CriticalFindings', 'GreaterThanThreshold', 0, 'notBreaching', 1)]:
        cw.put_metric_alarm(AlarmName=NAME + '-' + metric, Namespace='SixthSense/RawPipeline', MetricName=metric,
            Statistic='Maximum', Period=1800, EvaluationPeriods=periods, DatapointsToAlarm=periods,
            Threshold=threshold, ComparisonOperator=comparison, TreatMissingData=missing,
            AlarmDescription='Raw processing monitor: inspect latest report in 6thsense-processed/raw-lifecycle/v1/health/latest.json')
    proof = {'function': arn, 'rule': rule, 'schedule': 'rate(30 minutes)', 'source_sha256': hashlib.sha256(source).hexdigest(),
             'reports': 's3://6thsense-processed/raw-lifecycle/v1/health/', 'external_notifications_configured': bool(slack_secret),
             'processing_configuration_changed': False}
    s3.put_object(Bucket='6thsense-deploy-artifacts', Key='raw-lifecycle/v1/audit/raw-backlog-20260919/health-deployment.json', Body=json.dumps(proof).encode(), ContentType='application/json')
    print(json.dumps(proof))


if __name__ == '__main__':
    deploy()
