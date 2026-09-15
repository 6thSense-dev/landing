"""A preview cannot satisfy the Raw -> Clean multimodal completion contract."""
import json
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.ops_artifacts import PROFILE, SCHEMA, artifact_status, validate_artifacts
from app.core.ops_clean import validate_manifest
from tests.test_ops_clean import manifest


def calibration_fixture():
    eye = {"K": [[800, 0, 960], [0, 800, 600], [0, 0, 1]], "dist": [0, 0, 0, 0]}
    return {"schema": "opencv-stereo", "device_id": "ABC123", "image_size": [1920, 1200],
            "distortion_model": "kannala_brandt", "eye_crop_x": {"cam0": [160, 2080], "cam1": [2080, 4000]},
            "cam0": {**eye, "position": "right"}, "cam1": {**eye, "position": "left"},
            "stereo": {"R": [[1,0,0],[0,1,0],[0,0,1]], "T": [.06,0,0], "baseline_m": .06}}


def multimodal_manifest():
    doc = manifest()
    doc["schema"] = SCHEMA
    rec = doc["recordings"][0]
    rec["sources"][0]["size_bytes"] = 100
    rec["media"] = dict(profile=PROFILE, clock="sensor_us", source_frame_count=3000,
        retained_frame_count=1800, imu_samples=18000, sensor_origin_us=2_000_000,
        source_seconds=100, retained_seconds=60, last_frame_duration_us=33333,
        last_frame_duration_basis="Camera cadence", imu_units={"acceleration":"m/s^2","angular_velocity":"deg/s"},
        layout={"width":4000,"height":1200,"left":[2080,0,1920,1200],"right":[160,0,1920,1200],"rotation_degrees":0,"provenance":"Camera layout declaration"},
        segments=[dict(segment_id=0,source_frame_start=0,source_frame_end=1800,sensor_start_us=2_000_000,sensor_end_us=62_000_000,clean_start_us=0,clean_end_us=60_000_000)])
    digest = hashlib.sha256(json.dumps(calibration_fixture()).encode()).hexdigest()
    rec["calibration_source"] = dict(bucket="6thsense-raw",key="calibrations/test.json",version_id="cal-v1",sha256=digest)
    rec["media"]["calibration"] = dict(device_id="ABC123",image_size=[1920,1200],eye_mapping={"left":"cam1","right":"cam0"},coordinate_frame="native_unrotated_eye_pixels",output_rotation_degrees=0,sha256=digest)
    doc["outputs"] = []
    for role, extension in [("left_video","mp4"),("right_video","mp4"),("left_frames","tar"),("right_frames","tar"),("frame_index","csv"),("imu","csv"),("timeline","json"),("calibration","json")]:
        out = dict(key=f"clean/factory-test/{role}.{extension}", recording=rec["recording"],role=role,bytes=100,version_id="output-v1",sha256="b"*64)
        if role in ("left_video","right_video","left_frames","right_frames","frame_index"): out["frame_count"] = 1800
        if role in ("left_frames","right_frames"): out["start_frame"] = 0
        if role == "imu": out["sample_count"] = 18000
        if role == "calibration": out["sha256"] = digest
        doc["outputs"].append(out)
    return doc


def test_new_contract_and_legacy_readability():
    assert validate_manifest(multimodal_manifest())
    assert artifact_status(multimodal_manifest()) == "complete"
    assert validate_manifest(manifest())
    assert artifact_status(manifest()) == "legacy_video_only"
    with pytest.raises(ValueError, match="New processing"):
        validate_artifacts(manifest())


@pytest.mark.parametrize("role", ["left_video","right_video","left_frames","right_frames","imu","frame_index","timeline","calibration"])
def test_every_required_modality_is_mandatory(role):
    doc = multimodal_manifest()
    doc["outputs"] = [o for o in doc["outputs"] if o["role"] != role]
    with pytest.raises(ValueError): validate_manifest(doc)


@pytest.mark.parametrize("fault", ["duplicate_key","foreign_recording","frame_count","shard_gap","clock","source_count","qc_cut","duration","samples","cropped_overlap","final_duration","unversioned"])
def test_mismatched_or_unverifiable_artifacts_are_refused(fault):
    doc = multimodal_manifest()
    media = doc["recordings"][0]["media"]
    if fault == "duplicate_key": doc["outputs"][1]["key"] = doc["outputs"][0]["key"]
    if fault == "foreign_recording": doc["outputs"][0]["recording"] = "wrong"
    if fault == "frame_count": doc["outputs"][0]["frame_count"] -= 1
    if fault == "shard_gap": doc["outputs"][2]["start_frame"] = 1
    if fault == "clock": media["clock"] = "host_receive_us"
    if fault == "source_count": media["source_frame_count"] = 1799
    if fault == "qc_cut": media["segments"][0]["sensor_start_us"] += 10
    if fault == "duration": media["retained_seconds"] = 120
    if fault == "samples": doc["outputs"][5]["sample_count"] = 0
    if fault == "cropped_overlap": media["layout"]["right"] = media["layout"]["left"]
    if fault == "final_duration": media.pop("last_frame_duration_basis")
    if fault == "unversioned": doc["outputs"][2]["version_id"] = "null"
    with pytest.raises(ValueError): validate_manifest(doc)


def test_fully_rejected_recording_does_not_require_invented_media():
    doc = manifest()
    doc.update(schema=SCHEMA, retained_seconds=0, rejected_seconds=100, outputs=[])
    doc["recordings"][0]["sources"][0]["size_bytes"] = 100
    doc["recordings"][0]["intervals"] = [{"start_s":0,"end_s":100,"disposition":"reject","reason":"Unrecoverable sensor data"}]
    validate_manifest(doc)


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [True, False])
async def test_worker_cannot_complete_with_video_only_evidence(legacy):
    from app.api.routes.ops_processing import result, ResultIn
    doc = manifest() if legacy else multimodal_manifest()
    job = SimpleNamespace(fingerprint="fp",lease_token="lease",lease_until=datetime.now(timezone.utc)+timedelta(minutes=5), state="running")
    run = SimpleNamespace(manifest_json=json.dumps(doc),run_id=doc["run_id"])
    class DB:
        committed = False
        async def get(self, model, key, **kwargs): return job if model.__name__ == "ProcessingJob" else run
        async def execute(self, stmt):
            if stmt.column_descriptions[0]['entity'].__name__ == 'OpsSetting':
                return SimpleNamespace(scalar_one_or_none=lambda:None)
            return SimpleNamespace(scalar_one_or_none=lambda:SimpleNamespace(
                recording=doc['recordings'][0]['recording'], deleted_at=None, wearer_id="person"))
        async def commit(self): self.committed = True
    db = DB()
    body = ResultIn(recording=doc["recordings"][0]["recording"],fingerprint="fp",lease_token="lease",outcome="completed",run_id=doc["run_id"])
    if legacy:
        with pytest.raises(HTTPException) as exc: await result(body, db=db)
        assert exc.value.status_code == 409 and not db.committed and job.state == "running"
    else:
        assert await result(body, db=db) == {"ok":True}
        assert db.committed and job.state == "awaiting_verification"


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_video_only_new_import_is_blocked_but_existing_ledger_is_preserved(monkeypatch, existing):
    from app.api.routes import ops_clean
    doc = manifest()
    historical = SimpleNamespace(run_id=doc["run_id"], manifest_json=json.dumps(doc), manifest_sha256="a"*64)
    monkeypatch.setattr(ops_clean, "committed_results", lambda:[(doc,"qc-results/factory-test/result.json","version","a"*64)])
    async def setting(*args): pass
    async def state(*args): return {"historical_preserved":True}
    monkeypatch.setattr(ops_clean, "_put_setting", setting)
    monkeypatch.setattr(ops_clean, "state", state)
    class Rows:
        def __init__(self, values): self.values = values
        def scalars(self): return self
        def all(self): return self.values
        def __iter__(self): return iter(self.values)
    class DB:
        committed = False
        calls = 0
        async def execute(self, stmt):
            self.calls += 1
            return Rows([historical] if self.calls == 2 and existing else [])
        async def get(self, model, key):
            return SimpleNamespace(wearer_id="person") if model.__name__ == "OpsCamera" else SimpleNamespace(id="person",is_active=True)
        async def commit(self): self.committed = True
        def add(self, row): raise AssertionError("Video-only evidence must not create a new ledger entry")
    db = DB()
    if existing:
        assert (await ops_clean.scan(db=db))["imported"] == 0
        assert db.committed and historical.manifest_sha256 == "a"*64
    else:
        with pytest.raises(HTTPException) as exc: await ops_clean.scan(db=db)
        assert exc.value.status_code == 409 and "New Clean imports" in exc.value.detail
        assert not db.committed


def test_uncalibrated_v2_history_is_readable_but_cannot_be_imported():
    doc = multimodal_manifest()
    doc["outputs"] = [o for o in doc["outputs"] if o["role"] != "calibration"]
    doc["recordings"][0].pop("calibration_source")
    doc["recordings"][0]["media"].pop("calibration")
    validate_manifest(doc)
    with pytest.raises(ValueError, match="calibration"):
        validate_artifacts(doc)


@pytest.mark.parametrize("fault", [None, "camera", "mapping", "digest", "singular_intrinsics"])
def test_committed_calibration_is_read_and_verified(fault):
    import io
    from app.core.ops_clean import _committed_result
    doc = multimodal_manifest()
    calibration = calibration_fixture()
    if fault == "camera": calibration["device_id"] = "FFFFFF"
    if fault == "singular_intrinsics": calibration["cam0"]["K"] = [[800,800,960],[800,800,600],[0,0,1]]
    raw = json.dumps(calibration).encode()
    digest = hashlib.sha256(raw).hexdigest()
    output = doc["outputs"][-1]
    output.update(sha256=digest, bytes=len(raw))
    doc["recordings"][0]["calibration_source"]["sha256"] = digest
    doc["recordings"][0]["media"]["calibration"]["sha256"] = digest
    if fault == "mapping": doc["recordings"][0]["media"]["calibration"]["eye_mapping"] = {"left":"cam0", "right":"cam1"}
    body = json.dumps(doc).encode()
    marker = {"manifest":{"key":"qc-results/factory-test/result.json","version_id":"v1","sha256":hashlib.sha256(body).hexdigest()}}
    class S3:
        def get_object(self, **kwargs):
            if kwargs["Key"].endswith("_SUCCESS.json"): data = json.dumps(marker).encode()
            elif kwargs["Key"].endswith("result.json"): data = body
            else: data = b"{}" if fault == "digest" else raw
            return {"Body":io.BytesIO(data),"ContentLength":len(data),"VersionId":kwargs.get("VersionId","v1")}
        def head_object(self, **kwargs):
            item = next(o for o in doc["outputs"] if o["key"] == kwargs["Key"])
            return {"ContentLength":item["bytes"],"Metadata":{"sha256":item["sha256"]}}
    if fault:
        with pytest.raises(ValueError): _committed_result(S3(),"qc-results/factory-test/_SUCCESS.json")
    else:
        assert _committed_result(S3(),"qc-results/factory-test/_SUCCESS.json")[0] == doc


@pytest.mark.parametrize('suffix', ['_s01', '_s11', '_s100'])
def test_legacy_cut_identity_keeps_camera_and_calibration(suffix):
    from app.core.ops_calibration import validate_calibration
    doc = multimodal_manifest(); rec = doc['recordings'][0]
    old = rec['recording']; rec['recording'] += suffix
    for source in rec['sources']: source['key'] = source['key'].replace(old, rec['recording'])
    for output in doc['outputs']: output['recording'] = rec['recording']
    assert validate_manifest(doc)
    validate_artifacts(doc)
    assert validate_calibration(calibration_fixture(), rec['recording'], rec['media']['layout'])['device_id'] == 'ABC123'


@pytest.mark.parametrize('fault', ['wrong_camera', 'wrong_source_segment', 'zero_segment', 'arbitrary_suffix', 'wrong_calibration'])
def test_legacy_cut_cannot_bypass_source_camera_checks(fault):
    doc = multimodal_manifest(); rec = doc['recordings'][0]
    old = rec['recording']; rec['recording'] += '_s11'
    if fault == 'wrong_camera': rec['recording'] = rec['recording'].replace('ABC123', 'FFFFFF')
    if fault == 'zero_segment': rec['recording'] = old + '_s00'
    if fault == 'arbitrary_suffix': rec['recording'] += '_ABC123'
    for source in rec['sources']: source['key'] = source['key'].replace(old, rec['recording'])
    for output in doc['outputs']: output['recording'] = rec['recording']
    if fault == 'wrong_source_segment': rec['sources'][0]['key'] = rec['sources'][0]['key'].replace('_s11/', '_s12/')
    if fault == 'wrong_calibration': rec['media']['calibration']['device_id'] = 'FFFFFF'
    with pytest.raises(ValueError): validate_manifest(doc)
