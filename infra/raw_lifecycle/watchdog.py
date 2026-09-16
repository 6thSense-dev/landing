"""Enforce the initial compute window: stop only this pipeline's new work."""
import json,time
import coordinator as c

def handler(event,context):
 cfg,_=c.read_json(c.ARTIFACTS,'raw-lifecycle/v1/config.json')
 if time.time()<cfg['run_deadline_epoch']-60:return {'stopped':False}
 cfg['enabled']=False
 cfg['retirement_enabled']=False
 c.s3.put_object(Bucket=c.ARTIFACTS,Key='raw-lifecycle/v1/config.json',Body=c.encoded(cfg),ContentType='application/json')
 stopped=[]
 for queue in (cfg['cpu_queue'],cfg['gpu_queue']):
  c.batch.update_job_queue(jobQueue=queue,state='DISABLED')
  for status in ('SUBMITTED','PENDING','RUNNABLE','STARTING','RUNNING'):
   for page in c.batch.get_paginator('list_jobs').paginate(jobQueue=queue,jobStatus=status):
    for job in page.get('jobSummaryList',[]):
     if not job['jobName'].startswith('raw-life-'):continue
     c.batch.terminate_job(jobId=job['jobId'],reason='Initial authorized compute window ended; archived originals preserved')
     stopped.append(job['jobId'])
 return {'stopped':True,'jobs':stopped}
