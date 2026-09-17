"""Sieve preserves recovery disclosures and cannot promote unknowns to facts."""
import copy
import json
from types import SimpleNamespace

import pytest
from app.core import ops_sieve as sieve
from app.core.ops_reconstructed_metadata import UNKNOWN_FIELDS
from tests.test_ops_sieve import fixture


def recovered_fixture(change=None):
    storage,row=fixture()
    doc,rec=row['doc'],row['rec']
    base=f"clean/{row['run_id']}/{row['recording']}/"
    auth={'bucket':'6thsense-deploy-artifacts','key':'clean-plans/source-metadata-recovery/test/auth.json',
          'version_id':'auth-v1','sha256':'a'*64,'bytes':100}
    metadata=dict.fromkeys(UNKNOWN_FIELDS)
    metadata.update(schema='6thsense-reconstructed-source-metadata/1',metadata_origin='reconstructed',
        recording_id=rec['recording'],device_id=rec['recording'].split('_')[-1],
        capture_completeness='unknown',frame_count_scope='available_source_frames',
        inspection_scope='all_available_sources',frame_count=rec['media']['source_frame_count'],
        available_video_duration_us=1000000,
        recovery_authorization=auth,source_media=copy.deepcopy(rec['sources']),
        calibration_provenance={'source':rec['calibration_source'],'mode':'recovered_camera_calibration'})
    if change:change(metadata)
    meta=storage.add(base+'metadata.json',sieve.encoded(metadata))
    reconstructed=dict(meta,key='clean/recovery/staging/'+rec['recording']+'/metadata.json')
    recovery={'authorization':auth,'metadata':reconstructed,'scope':'available_source_only','capture_completeness':'unknown'}
    rec.setdefault('source_provenance',{})['metadata_recovery']=recovery
    rec['media']['capture_completeness']='unknown'
    provenance={'schema':'6thsense-clean-source-metadata/2','run_id':doc['run_id'],
        'recording':rec['recording'],'source_media':[{k:s[k] for k in ('bucket','key','version_id')} for s in rec['sources']],
        'copy_mode':'reconstructed_from_verified_sources','metadata':meta,'source_metadata':[],
        'reconstruction':recovery}
    storage.add(base+'metadata-provenance.json',sieve.encoded(provenance))
    manifest=storage.add(f"qc-results/{doc['run_id']}/result.json",sieve.encoded(doc))
    storage.add(f"qc-results/{doc['run_id']}/_SUCCESS.json",sieve.encoded({'manifest':manifest}))
    row.update(manifest_version=manifest['version_id'],manifest_sha256=manifest['sha256'])
    return storage,row,metadata,provenance


def test_sieve_copies_disclosed_reconstructed_metadata_without_raw_reads():
    storage,row,metadata,_=recovered_fixture()
    result=sieve.copy_recording(storage,row)
    assert result['status']=='inherited' and len(storage.copies)==5
    copied=[(bucket,key) for _,bucket,key,_ in storage.copies if key.endswith('/metadata.json')]
    actual=json.loads(storage.objects[copied[0]][0])
    assert actual==metadata and actual['complete'] is None
    assert actual['capture_completeness']=='unknown'
    assert all(bucket!='6thsense-raw' for bucket,_,_ in storage.reads)


@pytest.mark.parametrize('field',UNKNOWN_FIELDS)
def test_recovery_cannot_invent_original_capture_claims(field):
    storage,row,_,_=recovered_fixture(lambda m:m.update({field:True}))
    with pytest.raises(ValueError,match='Reconstructed metadata'):
        sieve.copy_recording(storage,row)
    assert storage.copies==[]


@pytest.mark.parametrize('field,value',[
    ('inspection_scope','canary'),('frame_count',1),('frame_count',True),
    ('capture_completeness','complete'),('recording_id','another-take'),
    ('device_id','FFFFFF'),('frame_count_scope','captured_frames'),
])
def test_scope_camera_and_frame_counts_must_match_committed_clean(field,value):
    storage,row,_,_=recovered_fixture(lambda m:m.update({field:value}))
    with pytest.raises(ValueError,match='Reconstructed metadata'):
        sieve.copy_recording(storage,row)
    assert storage.copies==[]


@pytest.mark.parametrize('field,value',[('sha256','e'*64),('version_id','wrong-version'),('size_bytes',1)])
def test_reconstruction_sources_must_match_committed_clean(field,value):
    storage,row,_,_=recovered_fixture(lambda m:m['source_media'][0].update({field:value}))
    with pytest.raises(ValueError,match='Reconstructed metadata source'):
        sieve.copy_recording(storage,row)
    assert storage.copies==[]


def test_generated_metadata_cannot_be_relabelled_as_an_original():
    storage,row,_,provenance=recovered_fixture()
    provenance.update(schema='6thsense-clean-source-metadata/1',copy_mode='byte_exact_from_versioned_source',
                      source_metadata=[dict(provenance['metadata'],bucket='6thsense-raw')])
    key=f"clean/{row['run_id']}/{row['recording']}/metadata-provenance.json"
    storage.add(key,sieve.encoded(provenance))
    with pytest.raises(ValueError,match='Original metadata digest'):
        sieve.copy_recording(storage,row)
    assert storage.copies==[]


def import_fixture(monkeypatch):
    from app.api.routes import ops_pipeline as route
    storage,row,metadata,provenance=recovered_fixture()
    rec=row['rec'];base=f"clean/{row['run_id']}/{row['recording']}/"
    key=f"sessions/korea-site/ABC123/{rec['recording']}/video.mp4"
    source=storage.add(key,b'original video',bucket='6thsense-raw')
    rec['sources']=[dict(source,size_bytes=source['bytes'])]
    applicability={'basis':'Recorded module binding and matching camera geometry'}
    auth={'schema':'6thsense-source-metadata-recovery/1','recording':rec['recording'],
          'device_id':'ABC123','scope':'available_source_only','capture_completeness':'unknown',
          'basis':'Explicit recovery authorization','sources':[source],
          'calibration':rec['calibration_source'],'calibration_applicability':applicability}
    auth_ref=storage.add('clean-plans/source-metadata-recovery/test/auth.json',sieve.encoded(auth),bucket='6thsense-deploy-artifacts')
    timeline={'sensor_clock':'unwrapped_camera_sensor_us','imu_samples':100,'imu_units':{},
        'unreadable_sensor_frames':0,'imu_conflicting_measurements':0,'sensor_discontinuities':0,
        'maximum_imu_gap_us':3334,'duration_us':1000000,'video_clock':'source_presentation_us',
        'chunk_join':'available chunks','recovered_chunk_display_clock':'nominal if recovered'}
    metadata.update(source_media=[source],recovery_authorization=auth_ref,
        sensor_observations={k:v for k,v in timeline.items() if k not in ('duration_us','video_clock','chunk_join','recovered_chunk_display_clock')},
        duration_basis={k:timeline[k] for k in ('video_clock','chunk_join','recovered_chunk_display_clock')},
        image_size=[rec['media']['layout']['width'],rec['media']['layout']['height']])
    metadata['calibration_provenance']['applicability']=applicability
    body=sieve.encoded(metadata)
    reconstructed=storage.add(f"clean/recovery/staging/{rec['recording']}/metadata.json",body)
    final_ref=storage.add(base+'metadata.json',body)
    recovery={'authorization':auth_ref,'metadata':reconstructed,'scope':'available_source_only','capture_completeness':'unknown'}
    rec['source_provenance']['metadata_recovery']=recovery
    report={'schema':'6thsense-raw-conversion-result/1','recording':rec['recording'],
        'status':'converted_staging','source_complete_flag':None,'metadata_frame_count':None,
        'frames_absent_against_capture_metadata':None,'sources':[source],
        'metadata_recovery_ref':auth_ref,'reconstructed_metadata':reconstructed,'outputs':[reconstructed],
        'calibration_source':rec['calibration_source'],'decoded_frame_count':metadata['frame_count'],
        'sensor_decoder':'native_luma/1','timeline':timeline}
    receipt=storage.add(f"clean/recovery/staging/{rec['recording']}/conversion.json",sieve.encoded(report))
    rec['source_provenance']['conversion_receipt']=receipt
    provenance.update(source_media=[{k:source[k] for k in ('bucket','key','version_id')}],
                      metadata=final_ref,reconstruction=recovery)
    storage.add(base+'metadata-provenance.json',sieve.encoded(provenance))
    manifest=storage.add(f"qc-results/{row['run_id']}/result.json",sieve.encoded(row['doc']))
    storage.add(f"qc-results/{row['run_id']}/_SUCCESS.json",sieve.encoded({'manifest':manifest}))
    row.update(manifest_version=manifest['version_id'],manifest_sha256=manifest['sha256'])
    take={'session':'korea-site','prefixes':[key.rsplit('/',1)[0]+'/'],
          'media':[{'key':key,'bytes':source['bytes']}]}
    original=storage.lookup
    def lookup(Bucket,Key,VersionId=None):
        if Bucket not in ('6thsense-raw','6thsense-deploy-artifacts'):
            return original(Bucket,Key,VersionId)
        value=storage.objects[Bucket,Key]
        assert VersionId in (None,value[1]['version_id'])
        return value
    storage.lookup=lookup
    monkeypatch.setattr(route,'walk_bucket',lambda prefix:{rec['recording']:take})
    monkeypatch.setattr(route,'get_settings',lambda:SimpleNamespace(bucket='6thsense-raw'))
    monkeypatch.setattr(route,'_client',lambda settings:storage)
    episode=SimpleNamespace(recording=rec['recording'],session='korea-site')
    return route,storage,row,episode,take,report


def test_real_import_source_validation_accepts_authorized_unknown_completion(monkeypatch):
    route,storage,row,episode,_,_=import_fixture(monkeypatch)
    metadata,proof,_,_=route._metadata_evidence(storage,row['doc'])
    assert metadata['complete'] is None and proof['source_metadata']==[]
    route._validate_new_source(row['doc'],episode)
    assert not storage.copies


@pytest.mark.parametrize('fault',['original_arrived','unauthorized_hash','report_complete','canary','observations','stale_source'])
def test_real_import_refuses_recovery_evidence_drift(monkeypatch,fault):
    route,storage,row,episode,take,report=import_fixture(monkeypatch)
    if fault=='original_arrived':take['meta_key']='new original metadata.json'
    elif fault=='stale_source':storage.add(row['rec']['sources'][0]['key'],b'replaced video',bucket='6thsense-raw')
    elif fault=='unauthorized_hash':
        ref=row['rec']['source_provenance']['metadata_recovery']['authorization']
        body,_,meta=storage.objects[ref['bucket'],ref['key']]
        auth=json.loads(body);auth['sources'][0]['sha256']='f'*64
        storage.objects[ref['bucket'],ref['key']]=(sieve.encoded(auth),ref,meta)
    else:
        if fault=='report_complete':report['source_complete_flag']=True
        elif fault=='canary':report['status']='converted_canary'
        else:report['timeline']['imu_conflicting_measurements']=20
        ref=storage.add(f"clean/recovery/staging/{row['recording']}/conversion.json",sieve.encoded(report))
        row['rec']['source_provenance']['conversion_receipt']=ref
    with pytest.raises((ValueError,AssertionError)):
        route._validate_new_source(row['doc'],episode)
