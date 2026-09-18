import copy
import hashlib
import io
import json
from types import SimpleNamespace
import pytest
from botocore.exceptions import ClientError
from app.core.ops_raw_preview import decoded_playback, BUCKET


class Store:
    def __init__(self): self.docs={}; self.heads={}; self.signed=[]
    def get_object(self, **args):
        key=args['Key']
        if key not in self.docs: raise ClientError({'Error':{'Code':'NoSuchKey'}},'GetObject')
        body=json.dumps(self.docs[key],sort_keys=True).encode()
        return {'ContentLength':len(body),'Body':io.BytesIO(body)}
    def head_object(self, **args): return self.heads[args['Key']]
    def generate_presigned_url(self, operation, **args):
        self.signed.append(args);return 'https://private-preview.invalid/video'


def setup():
    rec='ego_20260917_192001_166283';source={'bucket':'6thsense-raw','key':'sessions/india/'+rec+'/capture.egoc','version_id':'raw1','bytes':123,'etag':'e'}
    preview={'bucket':BUCKET,'key':f'clean/task/staging/{rec}/preview.mp4','version_id':'preview1','bytes':456,'sha256':'a'*64}
    report={'schema':'6thsense-raw-conversion-result/1','status':'converted_staging','recording':rec,'task':'task','sources':[source],'outputs':[preview],'decoded_frame_count':100,'verification':{'preview':{'codec':'h264','frames':100,'all_frames_decoded':True,'all_timestamps_checked':True}}}
    body=json.dumps(report,sort_keys=True).encode();ref={'bucket':BUCKET,'key':f'clean/task/staging/{rec}/conversion.json','version_id':'receipt1','bytes':len(body),'sha256':hashlib.sha256(body).hexdigest()}
    state={'recording':rec,'conversion_receipt':ref,'review_preview':preview,'conversion_plan':{'task':'task'}}
    s=Store();s.docs={'raw-lifecycle/v1/states/'+rec+'.json':state,ref['key']:report};s.heads={source['key']:{'VersionId':'raw1','ContentLength':123,'ETag':'"e"'},preview['key']:{'ContentLength':456,'Metadata':{'sha256':'a'*64}}}
    cfg=SimpleNamespace(bucket='6thsense-raw',presign_ttl=900)
    return rec,source,preview,report,state,s,cfg


def test_verified_full_review_is_version_pinned_and_read_only():
    rec,source,preview,report,state,s,cfg=setup();before=copy.deepcopy(s.docs)
    files=decoded_playback(rec,[source],s,cfg,processed_s3=s)
    assert len(files)==1 and files[0]['review_only'] is True
    assert s.signed[0]['Params']=={'Bucket':BUCKET,'Key':preview['key'],'VersionId':'preview1'}
    assert s.signed[0]['ExpiresIn']==900 and s.docs==before


@pytest.mark.parametrize('problem',['new_version','size','etag','operator_rejection','scene_disposition','retired','other_recording','no_preview','no_state'])
def test_stale_or_protected_preview_never_plays(problem):
    rec,source,preview,report,state,s,cfg=setup()
    if problem=='new_version':s.heads[source['key']]['VersionId']='replacement'
    elif problem=='size':s.heads[source['key']]['ContentLength']=999
    elif problem=='etag':s.heads[source['key']]['ETag']='changed'
    elif problem in ('operator_rejection','scene_disposition','retired'):state[problem]=True
    elif problem=='other_recording':state['recording']='foreign'
    elif problem=='no_preview':state.pop('review_preview')
    else:s.docs.clear()
    assert decoded_playback(rec,[source],s,cfg,processed_s3=s)==[] and not s.signed


@pytest.mark.parametrize('problem',['preview_bytes','preview_hash','receipt_hash','canary','partial','foreign_bucket','foreign_key'])
def test_unverified_receipt_cannot_be_signed(problem):
    rec,source,preview,report,state,s,cfg=setup()
    if problem=='preview_bytes':s.heads[preview['key']]['ContentLength']=1
    elif problem=='preview_hash':s.heads[preview['key']]['Metadata']['sha256']='b'*64
    elif problem=='receipt_hash':state['conversion_receipt']['sha256']='b'*64
    else:
        if problem=='canary':report['status']='converted_canary'
        elif problem=='partial':report['verification']['preview']['frames']=50
        elif problem=='foreign_bucket':preview['bucket']='other-bucket'
        else:preview['key']='clean/another/preview.mp4'
        body=json.dumps(report,sort_keys=True).encode();state['conversion_receipt'].update(bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
    with pytest.raises(ValueError):decoded_playback(rec,[source],s,cfg,processed_s3=s)
    assert not s.signed


def test_access_denied_is_not_a_missing_preview():
    rec,source,preview,report,state,s,cfg=setup()
    def denied(**args):raise ClientError({'Error':{'Code':'AccessDenied'}},'GetObject')
    s.get_object=denied
    with pytest.raises(ClientError):decoded_playback(rec,[source],s,cfg,processed_s3=s)
