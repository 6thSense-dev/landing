"""Synthetic end-to-end QA records distinguish absent gloves from missing evidence."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ingest.validate import build_qa


def qa_for(*, hands=(), crc=None, dropped=0):
    ci = NS(
        tactile=NS(hands=list(hands), crc_pass_rate=crc, usable_channels={},
                   preview=None, census_reproducible={}, crc_by_hand={}, frames_lost=None),
        frame_timestamps=100, probe=NS(frames=100),
        metadata={"quality": {"video_frames_dropped": dropped}},
        frames_missing_on_grid=None, imu_preview={"present": True},
        checksums_verified=True, segments=[{}], split="train", cfg={},
        layout=NS(frame_times=Path("synthetic-timestamps.csv")),
    )
    calibration = {
        "camera": {"model": "opencv_fisheye", "stereo": {},
                   "rectification_residual_px": 0.1, "shutter": "rolling", "readout_time_ms": 2},
        "cam_imu": {"time_offset_s": 0, "R": [1, 0, 0]},
        "imu": {"status": "operational", "rate_hz": 200,
                **{k: 0.001 for k in ("accel_noise_density", "accel_random_walk",
                                     "gyro_noise_density", "gyro_random_walk")}},
    }
    rights = {k: "denied" for k in
              ("model_training", "commercial_use", "redistribution", "derived_model")}
    rights["determined_utc"] = "2026-01-01T00:00:00Z"
    privacy = {"pii_review": "passed", "redaction": {"synthetic": True},
               "retention": {"synthetic": True}}
    qa, _ = build_qa(ci, sync={"maximum_alignment_error_ms": 1, "validation_result": "pass"},
                     calibration=calibration, rights=rights, privacy=privacy,
                     streams=["video", "imu"])
    return qa


def test_absent_gloves_publish_inapplicable_and_allow_grade_a():
    qa = qa_for()
    checks = {c["check_id"]: c["result"] for c in qa["checks"]}
    for key in ("tactile_crc_pass_rate", "tactile_channel_coverage", "tactile_census_reproducible"):
        assert checks[key] == "not_applicable"
    assert qa["grade"] == "A"


def test_claimed_glove_with_missing_measurement_remains_unmeasured():
    qa = qa_for(hands=["left"])
    checks = {c["check_id"]: c["result"] for c in qa["checks"]}
    assert checks["tactile_crc_pass_rate"] == "not_run"
    assert qa["grade"] != "A"


def test_absent_gloves_do_not_excuse_actual_video_loss():
    assert qa_for(dropped=1)["grade"] != "A"


def test_schema_accepts_explicit_inapplicable_but_rejects_unknown_result():
    schema = json.loads((ROOT / "schema/clip.schema.json").read_text())
    def enum_for_result(node):
        if isinstance(node, dict):
            if "result" in node.get("properties", {}):
                yield node["properties"]["result"]
            for value in node.values():
                yield from enum_for_result(value)
        elif isinstance(node, list):
            for value in node:
                yield from enum_for_result(value)
    result_schemas = list(enum_for_result(schema))
    assert result_schemas
    for result_schema in result_schemas:
        validator = Draft202012Validator(result_schema)
        assert validator.is_valid("not_applicable")
        assert not validator.is_valid("unknown_result")
