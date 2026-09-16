"""Provision isolated Raw lifecycle resources; starts disabled until explicitly enabled.
Run with AWS_PROFILE=ronak-catalog-sso. No secret values are printed.
"""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import tarfile
import time
import zipfile
from datetime import datetime, timezone
import boto3
from botocore.exceptions import ClientError

ACCOUNT='194680606079'; REGION='us-west-2'; NAME='sixthsense-raw-lifecycle-v1'
ARCHIVE='6thsense-archive-'+ACCOUNT; ARTIFACTS='6thsense-deploy-artifacts'
ROOT=Path(__file__).resolve().parent
RUNTIME_SOURCE=Path('/data/projects/6thsense/pipeline-takeover-20260916/clean-runtime')
EVIDENCE=Path('/data/projects/6thsense/pipeline-takeover-20260916')
s=boto3.Session(region_name=REGION)
assert s.client('sts').get_caller_identity()['Account']==ACCOUNT,'Wrong AWS account'
iam=s.client('iam'); s3=s.client('s3'); batch=s.client('batch'); ec2=s.client('ec2'); lam=s.client('lambda'); events=s.client('events')


def policy(statements):return {'Version':'2012-10-17','Statement':statements}
def allow(actions,resources):return {'Effect':'Allow','Action':actions,'Resource':resources}
def role(name,service,statements):
 trust=policy([{'Effect':'Allow','Principal':{'Service':service},'Action':'sts:AssumeRole'}])
 try: arn=iam.create_role(RoleName=name,AssumeRolePolicyDocument=json.dumps(trust),Tags=[{'Key':'purpose','Value':NAME}])['Role']['Arn']
 except iam.exceptions.EntityAlreadyExistsException: arn=iam.get_role(RoleName=name)['Role']['Arn']
 iam.put_role_policy(RoleName=name,PolicyName='LifecycleScope',PolicyDocument=json.dumps(policy(statements)))
 return arn

def upload(key,body):
 h=hashlib.sha256(body).hexdigest()
 try: r=s3.put_object(Bucket=ARTIFACTS,Key=key,Body=body,Metadata={'sha256':h},IfNoneMatch='*');v=r['VersionId']
 except ClientError as e:
  if e.response['Error']['Code'] not in ('412','PreconditionFailed'):raise
  r=s3.head_object(Bucket=ARTIFACTS,Key=key);assert r['Metadata']['sha256']==h;v=r['VersionId']
 return {'bucket':ARTIFACTS,'key':key,'version_id':v,'sha256':h,'bytes':len(body)}

def runtime():
 files={str(p.relative_to(RUNTIME_SOURCE)):p.read_bytes() for p in RUNTIME_SOURCE.rglob('*.py')}
 # Existing runtime is immutable. New jobs use a new content-addressed copy.
 stage=files['stage_worker.py'].decode().replace("TASK='raw-h265-all-20260915'", "TASK=os.environ.get('PIPELINE_TASK','raw-h265-all-20260915')")
 # Treat a permission denial as failure, never as evidence that output is absent.
 stage=stage.replace("('404','NoSuchKey','NotFound','403','AccessDenied')", "('404','NoSuchKey','NotFound')")
 files['stage_worker.py']=stage.encode()
 worker=files['worker.py'].decode()
 anchor=" assert report['recording']==spec['recording']==rec and spec['kind']=='stereo_video' and spec['source_complete_flag'] is True"
 assert anchor in worker,'Pinned Clean runtime changed'
 binding="\n identity=lambda a:(a['bucket'],a['key'],a['version_id'],a['bytes'])\n assert len(report['sources'])==len(spec['sources']) and {identity(a) for a in report['sources']}=={identity(a) for a in spec['sources']},'Conversion receipt source versions differ from plan'"
 files['worker.py']=worker.replace(anchor,anchor+binding).encode()
 files['archive_worker.py']=(ROOT/'archive_worker.py').read_bytes()
 stream=io.BytesIO()
 with tarfile.open(fileobj=stream,mode='w:gz') as t:
  for name,body in sorted(files.items()):
   ti=tarfile.TarInfo(name);ti.size=len(body);ti.mtime=0;t.addfile(ti,io.BytesIO(body))
 data=stream.getvalue();h=hashlib.sha256(data).hexdigest()
 return upload('clean-plans/raw-lifecycle-v1/runtime-'+h+'.tar.gz',data)

def bootstrap(ref,filename):
 return "import boto3,hashlib,tarfile,io,os\nfrom pathlib import Path\nr="+repr(ref)+"\ndata=boto3.client('s3').get_object(Bucket=r['bucket'],Key=r['key'],VersionId=r['version_id'])['Body'].read()\nassert hashlib.sha256(data).hexdigest()==r['sha256']\np=Path('/tmp/lifecycle-runtime');p.mkdir()\nwith tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as t:t.extractall(p,filter='data')\nos.execvp('python',['python','-u',str(p/"+repr(filename)+")])"

def archive_bucket():
 try: s3.create_bucket(Bucket=ARCHIVE,CreateBucketConfiguration={'LocationConstraint':REGION})
 except ClientError as e:
  if e.response['Error']['Code']!='BucketAlreadyOwnedByYou':raise
 s3.put_bucket_versioning(Bucket=ARCHIVE,VersioningConfiguration={'Status':'Enabled'})
 s3.put_public_access_block(Bucket=ARCHIVE,PublicAccessBlockConfiguration={k:True for k in ['BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets']})
 s3.put_bucket_ownership_controls(Bucket=ARCHIVE,OwnershipControls={'Rules':[{'ObjectOwnership':'BucketOwnerEnforced'}]})
 s3.put_bucket_encryption(Bucket=ARCHIVE,ServerSideEncryptionConfiguration={'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]})
 s3.put_bucket_tagging(Bucket=ARCHIVE,Tagging={'TagSet':[{'Key':'purpose','Value':'original-recording-retention'}]})
 # Never expire originals/current or noncurrent versions. Only abandoned upload parts.
 s3.put_bucket_lifecycle_configuration(Bucket=ARCHIVE,LifecycleConfiguration={'Rules':[{'ID':'abort-incomplete-multipart','Status':'Enabled','Filter':{'Prefix':''},'AbortIncompleteMultipartUpload':{'DaysAfterInitiation':7}}]})
 s3.put_bucket_policy(Bucket=ARCHIVE,Policy=json.dumps(policy([{'Sid':'DenyInsecureTransport','Effect':'Deny','Principal':'*','Action':'s3:*','Resource':[f'arn:aws:s3:::{ARCHIVE}',f'arn:aws:s3:::{ARCHIVE}/*'],'Condition':{'Bool':{'aws:SecureTransport':'false'}}}])))

def compute(lane,old,maxcpu):
 name=NAME+'-'+lane
 oldenv=batch.describe_compute_environments(computeEnvironments=[old])['computeEnvironments'][0]
 oldcr=oldenv['computeResources']; oldlt=oldcr['launchTemplate']['launchTemplateId']
 ltname=name+'-scratch'
 try: lt=ec2.describe_launch_templates(LaunchTemplateNames=[ltname])['LaunchTemplates'][0]['LaunchTemplateId']
 except ClientError as e:
  if e.response['Error']['Code']!='InvalidLaunchTemplateName.NotFoundException':raise
  data=ec2.describe_launch_template_versions(LaunchTemplateId=oldlt,Versions=['1'])['LaunchTemplateVersions'][0]['LaunchTemplateData']
  lt=ec2.create_launch_template(LaunchTemplateName=ltname,LaunchTemplateData=data,TagSpecifications=[{'ResourceType':'launch-template','Tags':[{'Key':'purpose','Value':NAME}]}])['LaunchTemplate']['LaunchTemplateId']
 current=batch.describe_compute_environments(computeEnvironments=[name])['computeEnvironments']
 if current: ce=current[0]['computeEnvironmentArn']
 else:
  cr={k:oldcr[k] for k in ['type','allocationStrategy','instanceTypes','subnets','securityGroupIds','instanceRole','ec2Configuration']}
  cr['ec2Configuration']=[{k:v for k,v in item.items() if k in ('imageType','imageIdOverride','imageKubernetesVersion')} for item in cr['ec2Configuration']]
  cr.update(minvCpus=0,maxvCpus=maxcpu,desiredvCpus=0,launchTemplate={'launchTemplateId':lt,'version':'1'},tags={'purpose':NAME})
  ce=batch.create_compute_environment(computeEnvironmentName=name,type='MANAGED',state='ENABLED',computeResources=cr,serviceRole=oldenv['serviceRole'],tags={'purpose':NAME})['computeEnvironmentArn']
 for _ in range(24):
  info=batch.describe_compute_environments(computeEnvironments=[ce])['computeEnvironments'][0]
  if info['status']=='VALID':break
  if info['status']=='INVALID':raise RuntimeError(info['statusReason'])
  time.sleep(5)
 else:raise RuntimeError('Compute environment readiness timed out')
 queues=batch.describe_job_queues(jobQueues=[name])['jobQueues']
 if queues:return queues[0]['jobQueueArn']
 return batch.create_job_queue(jobQueueName=name,state='ENABLED',priority=1,computeEnvironmentOrder=[{'order':1,'computeEnvironment':ce}],tags={'purpose':NAME})['jobQueueArn']

def function(name,handler,arn,code,timeout=840):
 args={'FunctionName':name,'Runtime':'python3.12','Role':arn,'Handler':handler,'Timeout':timeout,'MemorySize':1024,'Environment':{'Variables':{'CONFIG_KEY':'raw-lifecycle/v1/config.json'}}}
 try:
  lam.get_function(FunctionName=name)
  lam.update_function_code(FunctionName=name,ZipFile=code)
  lam.get_waiter('function_updated_v2').wait(FunctionName=name)
  lam.update_function_configuration(**args)
 except lam.exceptions.ResourceNotFoundException:
  for attempt in range(12):
   try:lam.create_function(**args,Code={'ZipFile':code},Tags={'purpose':NAME});break
   except lam.exceptions.InvalidParameterValueException:
    if attempt==11:raise
    time.sleep(5)
 lam.get_waiter('function_active_v2').wait(FunctionName=name)
 lam.put_function_concurrency(FunctionName=name,ReservedConcurrentExecutions=1)
 return lam.get_function(FunctionName=name)['Configuration']['FunctionArn']

def prepare():
 try:
  previous=json.loads(s3.get_object(Bucket=ARTIFACTS,Key='raw-lifecycle/v1/config.json')['Body'].read())
  if previous.get('enabled'):raise RuntimeError('Pause the live coordinator before changing definitions or spending window')
 except ClientError as exc:
  if exc.response['Error']['Code'] not in ('404','NoSuchKey','NotFound'):raise
 archive_bucket(); ref=runtime()
 logs=allow(['logs:CreateLogGroup','logs:CreateLogStream','logs:PutLogEvents'],f'arn:aws:logs:{REGION}:{ACCOUNT}:*')
 rawread=[allow(['s3:ListBucket','s3:ListBucketVersions','s3:ListBucketMultipartUploads'],'arn:aws:s3:::6thsense-raw'),allow(['s3:GetObject','s3:GetObjectVersion'],'arn:aws:s3:::6thsense-raw/sessions/*')]
 artifactread=[allow(['s3:GetObject','s3:GetObjectVersion'],f'arn:aws:s3:::{ARTIFACTS}/clean-plans/*')]
 archread=[allow(['s3:ListBucket','s3:GetBucketVersioning'],f'arn:aws:s3:::{ARCHIVE}'),allow(['s3:GetObject','s3:GetObjectVersion'],f'arn:aws:s3:::{ARCHIVE}/*')]
 cleanread=[allow(['s3:ListBucket'],'arn:aws:s3:::6thsense-processed'),allow(['s3:GetObject','s3:GetObjectVersion'],'arn:aws:s3:::6thsense-processed/*')]
 archive_role=role(NAME+'-archive','ecs-tasks.amazonaws.com',rawread+artifactread+archread+[allow(['s3:PutObject','s3:AbortMultipartUpload','s3:ListMultipartUploadParts'],f'arn:aws:s3:::{ARCHIVE}/*')])
 worker_role=role(NAME+'-worker','ecs-tasks.amazonaws.com',rawread+artifactread+cleanread+archread+[allow(['s3:PutObject','s3:AbortMultipartUpload','s3:ListMultipartUploadParts'],['arn:aws:s3:::6thsense-processed/clean/raw-lifecycle-v1/*','arn:aws:s3:::6thsense-processed/clean/raw-clean-auto-*','arn:aws:s3:::6thsense-processed/qc-results/raw-clean-auto-*'])])
 cpu=compute('cpu','raw-clean-finalize-20260915',64)
 gpu=compute('gpu','raw-h265-all-20260915',8)
 definitions={}
 for lane,old,filename,vcpus,memory,jobrole in [('archive','raw-clean-finalize-20260915:3','archive_worker.py',2,4096,archive_role),('clean','raw-clean-finalize-20260915:3','worker.py',32,56000,worker_role),('conversion','raw-h265-all-20260915-convert:2','stage_worker.py',4,12000,worker_role)]:
  original=batch.describe_job_definitions(jobDefinitions=[old])['jobDefinitions'][0]
  cp=copy.deepcopy(original['containerProperties']);cp['jobRoleArn']=jobrole
  cp['command']=['python','-u','-c',bootstrap(ref,filename)]
  cp['environment']=[e for e in cp['environment'] if e['name']!='PIPELINE_TASK']+[{'name':'PIPELINE_TASK','value':'raw-lifecycle-v1'}]
  cp['resourceRequirements']=[{'type':'VCPU','value':str(vcpus)},{'type':'MEMORY','value':str(memory)}]+([{'type':'GPU','value':'1'}] if lane=='conversion' else [])
  definitions[lane]=batch.register_job_definition(jobDefinitionName=NAME+'-'+lane,type='container',containerProperties=cp,timeout={'attemptDurationSeconds':21600},retryStrategy={'attempts':1},tags={'purpose':NAME},propagateTags=True)['jobDefinitionArn']
 secretname=NAME+'-portal-token';sm=s.client('secretsmanager')
 try: secretarn=sm.describe_secret(SecretId=secretname)['ARN']
 except sm.exceptions.ResourceNotFoundException:secretarn=sm.create_secret(Name=secretname,SecretString=secrets.token_urlsafe(48),Tags=[{'Key':'purpose','Value':NAME}])['ARN']
 tokenread=allow(['secretsmanager:GetSecretValue'],secretarn)
 batchread=allow(['batch:DescribeJobs','batch:ListJobs'],'*')
 retire_role=role(NAME+'-retirement','lambda.amazonaws.com',rawread+archread+cleanread+[logs,tokenread,batchread,allow(['s3:GetObject'],f'arn:aws:s3:::{ARTIFACTS}/raw-lifecycle/v1/config.json'),allow(['s3:DeleteObjectVersion'],'arn:aws:s3:::6thsense-raw/sessions/*')])
 coord_role=role(NAME+'-coordinator','lambda.amazonaws.com',rawread+archread+cleanread+artifactread+[logs,tokenread,batchread,
   allow(['s3:PutObject'],[f'arn:aws:s3:::{ARTIFACTS}/clean-plans/raw-lifecycle-v1/*','arn:aws:s3:::6thsense-processed/raw-lifecycle/v1/*','arn:aws:s3:::6thsense-processed/clean/*/metadata.json','arn:aws:s3:::6thsense-processed/clean/*/metadata-provenance.json',f'arn:aws:s3:::{ARCHIVE}/retirement/*']),
   allow(['s3:GetObject'],f'arn:aws:s3:::{ARTIFACTS}/raw-lifecycle/v1/config.json'),
   allow(['batch:SubmitJob'],[cpu,gpu,*definitions.values()]),
   allow(['lambda:InvokeFunction'],f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:{NAME}-retirement')])
 code=io.BytesIO()
 with zipfile.ZipFile(code,'w',zipfile.ZIP_DEFLATED) as z:
  for f in ['coordinator.py','retirement.py','watchdog.py']:z.write(ROOT/f,f)
  for f in ['ops_calibration.py','ops_regions.py']:z.write(ROOT.parents[1]/'backend/app/core'/f,f)
 retirefn=function(NAME+'-retirement','retirement.handler',retire_role,code.getvalue())
 coordfn=function(NAME+'-coordinator','coordinator.handler',coord_role,code.getvalue())
 stop_role=role(NAME+'-watchdog','lambda.amazonaws.com',[logs,batchread,allow(['batch:TerminateJob','batch:CancelJob'],'*'),allow(['batch:UpdateJobQueue'],[cpu,gpu]),allow(['s3:GetObject','s3:PutObject'],f'arn:aws:s3:::{ARTIFACTS}/raw-lifecycle/v1/config.json')])
 stopfn=function(NAME+'-watchdog','watchdog.handler',stop_role,code.getvalue(),300)
 deadline=time.time()+8*3600
 cfg={'enabled':False,'retirement_enabled':False,'archive_bucket':ARCHIVE,'api_url':'https://api.6thsense.dev',
      'token_secret':secretarn,'cpu_queue':cpu,'gpu_queue':gpu,'archive_definition':definitions['archive'],'clean_definition':definitions['clean'],
      'conversion_definition':definitions['conversion'],'clean_runtime':ref,'retirement_function':retirefn,'coordinator_function':coordfn,
      'watchdog_function':stopfn,'retirement_role':retire_role,'settle_seconds':600,'run_deadline_epoch':deadline,
      'compute_budget_usd':100,'created_at':datetime.now(timezone.utc).isoformat()}
 s3.put_object(Bucket=ARTIFACTS,Key='raw-lifecycle/v1/config.json',Body=json.dumps(cfg).encode(),ContentType='application/json')
 EVIDENCE.joinpath('lifecycle-config.json').write_text(json.dumps(cfg,indent=2))
 print(json.dumps({'prepared':True,'enabled':False,'archive_bucket':ARCHIVE,'config':str(EVIDENCE/'lifecycle-config.json')}))

def enable(retire):
 cfg=json.loads(s3.get_object(Bucket=ARTIFACTS,Key='raw-lifecycle/v1/config.json')['Body'].read())
 assert time.time()<cfg['run_deadline_epoch']
 for queue in (cfg['cpu_queue'],cfg['gpu_queue']):
  batch.update_job_queue(jobQueue=queue,state='ENABLED')
  for _ in range(24):
   info=batch.describe_job_queues(jobQueues=[queue])['jobQueues'][0]
   if info['state']=='ENABLED' and info['status']=='VALID':break
   time.sleep(5)
  else:raise RuntimeError('Queue enable timed out')
 if retire:
  pol=json.loads(s3.get_bucket_policy(Bucket='6thsense-raw')['Policy'])
  for st in pol['Statement']:
   if st.get('Sid')=='DenyObjectDeletionExceptAdmin':
    allowed=st['Condition']['ArnNotEquals']['aws:PrincipalArn']
    allowed=allowed if isinstance(allowed,list) else [allowed]
    if cfg['retirement_role'] not in allowed:allowed.append(cfg['retirement_role'])
    st['Condition']['ArnNotEquals']['aws:PrincipalArn']=allowed
  EVIDENCE.joinpath('raw-policy-with-retirement.json').write_text(json.dumps(pol,indent=2))
  s3.put_bucket_policy(Bucket='6thsense-raw',Policy=json.dumps(pol))
 cfg['enabled']=True;cfg['retirement_enabled']=retire
 s3.put_object(Bucket=ARTIFACTS,Key='raw-lifecycle/v1/config.json',Body=json.dumps(cfg).encode(),ContentType='application/json')
 for name,schedule,fn in [(NAME+'-tick','rate(2 minutes)',cfg['coordinator_function']),
      (NAME+'-budget-stop','rate(5 minutes)',cfg['watchdog_function'])]:
  rule=events.put_rule(Name=name,ScheduleExpression=schedule,State='ENABLED',Description='Owned Raw lifecycle automation')['RuleArn']
  try:lam.add_permission(FunctionName=fn,StatementId=name,Action='lambda:InvokeFunction',Principal='events.amazonaws.com',SourceArn=rule)
  except lam.exceptions.ResourceConflictException:pass
  events.put_targets(Rule=name,Targets=[{'Id':'invoke','Arn':fn,'RetryPolicy':{'MaximumRetryAttempts':12 if name.endswith('budget-stop') else 0,'MaximumEventAgeInSeconds':3600 if name.endswith('budget-stop') else 120}}])
 print(json.dumps({'enabled':True,'retirement_enabled':retire,'next_tick':'within 2 minutes','budget_stop_utc':datetime.fromtimestamp(cfg['run_deadline_epoch'],timezone.utc).isoformat()}))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','enable']);p.add_argument('--retire',action='store_true');a=p.parse_args()
 prepare() if a.stage=='prepare' else enable(a.retire)
