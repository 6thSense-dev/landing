"""Incremental ingest must invalidate QA emitted before not_applicable existed."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ingest import catalog_ingest as ci
from ingest.probe import TakeLayout, VideoProbe, digest_files


def test_previous_qa_cache_rebuilds_then_current_cache_is_reused(tmp_path):
    take = tmp_path / "take"
    take.mkdir()
    video = take / "stereo.mp4"
    video.write_bytes(b"synthetic container; probe is injected")
    stamps = take / "frame_times.csv"
    stamps.write_text("frame,host_us\n0,1000000\n1,1033333\n")
    metadata = take / "metadata.json"
    metadata.write_text('{"quality":{"video_frames_dropped":0}}')
    layout = TakeLayout(take, "camera", video={"stereo_sbs": video},
                        frame_times=stamps, metadata_path=metadata,
                        files=[video, stamps, metadata])
    plan = ci.Plan(layout, {}, json.loads(metadata.read_text()), "camera", "camera")
    out = tmp_path / "catalog"
    (out / "clips").mkdir(parents=True)
    detail = out / "clips/camera.json"
    legacy = {"hands": [], "qa": {"grade": "B", "checks": [
        {"check_id": "tactile_crc_pass_rate", "result": "not_run"}]}}
    detail.write_text(json.dumps(legacy))
    ctx = ci.BuildCtx(out, "reference", False, False, False, False, {}, "collection")
    # Reproduce the prior release's real hash, not a fabricated mismatching key.
    with patch.object(ci, "PIPELINE_VERSION", "6s-catalog-ingest/1.1.0"):
        legacy_hash = ci._input_hash(digest_files(layout, {}), ctx)
    cached = {"input_hash": legacy_hash, "summary": {"id": "camera", "qa": {"grade": "B"}}}
    probe = VideoProbe(video, video.stat().st_size, 2/30, 1920, 600, 30, "h264", 2, True)
    # Only external media probing is substituted. Hashing, cache branching,
    # clip assembly, QA and writing the replacement detail are real.
    with patch.object(ci, "probe_video", return_value=probe) as probe_video:
        result = ci._ingest(plan, ctx, {}, cached)
    assert result.ok, result.error
    assert result.changed, "prior semantic cache was reused"
    probe_video.assert_called_once_with(video)
    assert result.input_hash != legacy_hash
    checks = {c["check_id"]: c["result"] for c in result.detail["qa"]["checks"]}
    assert checks["tactile_crc_pass_rate"] == "not_applicable"
    assert result.detail["provenance"]["pipeline_version"] == ci.PIPELINE_VERSION
    assert json.loads(detail.read_text()) == result.detail

    refreshed = {"input_hash": result.input_hash, "summary": result.summary}
    content = detail.read_bytes()
    with patch.object(ci, "probe_video", side_effect=AssertionError("unchanged cache re-probed")):
        again = ci._ingest(plan, ctx, {}, refreshed)
    assert again.ok and not again.changed
    assert again.detail == result.detail
    assert detail.read_bytes() == content
