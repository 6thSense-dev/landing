"""Unit tests for the ingest rules a buyer reads first.

    cd scripts/catalog && python3 -m pytest tests -q     (or: make -C scripts/catalog test)

The end-to-end guard rail is `catalog-ingest validate`, which re-derives every
precomputed aggregate off the emitted bundle. These tests cover the things that
run BEFORE a bundle exists and that a passing bundle cannot prove: that a
threshold can actually fail, that an unbacked permission is refused, and that a
payload survives the float32 cast it is written into.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.imu import INLINE_MAX_READINGS, build_imu_preview  # noqa: E402
from ingest.records import MODALITIES  # noqa: E402
from ingest.validate import (  # noqa: E402
    COVERAGE_FAIL,
    CRC_FAIL,
    SKEW_FAIL_MS,
    SKEW_THRESHOLD_MS,
    _grade,
    _permission_evidence,
    _tiered,
    build_sync,
    drift_implied_ms,
)


# --------------------------------------------------------------------------- #
# imu.py — the f32 sidecar's `t` channel                                       #
# --------------------------------------------------------------------------- #

def _nonuniform_host_us_csv(path: Path, n: int) -> None:
    """A CSV shaped exactly like a real one: absolute epoch host_us, with a gap.

    The gap is what pushes `_time_base` off the uniform branch, which is what
    makes `dt_s` null, which is what puts a `t` column in the sidecar. Without
    it the buggy code path is never taken.
    """
    rows = ["host_us,ax,ay,az,gx,gy,gz"]
    t = 1_800_000_000_000_000  # 2027-01-15-ish, in microseconds since the epoch
    for i in range(n):
        t += 5000 if i != n // 2 else 40_000     # 200 Hz with one 40 ms stall
        rows.append(f"{t},{i * 0.001},0.5,9.81,0.01,0.02,0.03")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_sidecar_time_channel_is_seconds_from_clip_zero(tmp_path):
    """Regression: absolute host_us was written into f32 raw, collapsing the axis.

    float32 carries ~7 significant digits; epoch microseconds need 16. Sample 0,
    sample 1 and sample 2499 all decoded to the same value, so the chart's dt
    fell to 1e-9, its duration to ~0, and every tick, the strip and the hover
    readout went with it. The bundle validator could not see it: the file length
    was still n_readings * stride_bytes.
    """
    n = INLINE_MAX_READINGS + 500
    csv_path = tmp_path / "imu.csv"
    _nonuniform_host_us_csv(csv_path, n)

    result = build_imu_preview(
        csv_path, sidecar_path=tmp_path / "imu.f32", sidecar_url="imu/x.f32",
        clip_t0_us=1_800_000_000_000_000)
    preview = result.preview
    assert preview["encoding"] == "sidecar_f32le"
    assert preview["dt_s"] is None, "the fixture must be non-uniform for this to bite"
    side = preview["sidecar"]
    assert side["order"][0] == "t" and side["stride_bytes"] == 28

    raw = (tmp_path / "imu.f32").read_bytes()
    assert len(raw) == n * 28
    values = struct.unpack(f"<{n * 7}f", raw)
    times = values[0::7]

    assert times[0] != times[1] != times[-1]
    assert all(b > a for a, b in zip(times, times[1:])), "t must be strictly increasing"
    # 2500 samples at 200 Hz plus one 40 ms stall is ~12.5 s, not 1.8e15.
    assert 12.0 < times[-1] - times[0] < 13.0


def test_inline_and_sidecar_agree_on_the_time_axis(tmp_path):
    """Both branches must produce the same seconds-from-clip-zero axis."""
    n = 100
    csv_path = tmp_path / "imu.csv"
    _nonuniform_host_us_csv(csv_path, n)
    inline = build_imu_preview(csv_path, sidecar_path=tmp_path / "a.f32",
                               sidecar_url="imu/a.f32",
                               clip_t0_us=1_800_000_000_000_000).preview
    assert inline["encoding"] == "inline_f32"
    t = inline["channels"]["t"]
    assert t[0] == pytest.approx(inline["t0_s"], abs=1e-6)
    assert 0.4 < t[-1] - t[0] < 0.7


def test_the_sidecar_declares_its_own_length_correctly(tmp_path):
    """`bytes` and `stride_bytes` are what a client checks before parsing."""
    n = INLINE_MAX_READINGS + 1
    csv_path = tmp_path / "imu.csv"
    _nonuniform_host_us_csv(csv_path, n)
    side = build_imu_preview(csv_path, sidecar_path=tmp_path / "b.f32",
                             sidecar_url="imu/b.f32", clip_t0_us=None).preview["sidecar"]
    assert side["bytes"] == side["n_readings"] * side["stride_bytes"] == n * 28
    assert (tmp_path / "b.f32").stat().st_size == side["bytes"]


# --------------------------------------------------------------------------- #
# validate.py — the acceptance bounds can actually fail                        #
# --------------------------------------------------------------------------- #

def test_every_measured_check_can_reach_fail():
    """The defect: tiering against infinity made `fail` unreachable by construction."""
    assert _tiered(SKEW_THRESHOLD_MS - 1, SKEW_THRESHOLD_MS, SKEW_FAIL_MS,
                   higher_is_better=False) == "pass"
    assert _tiered(SKEW_THRESHOLD_MS + 1, SKEW_THRESHOLD_MS, SKEW_FAIL_MS,
                   higher_is_better=False) == "warn"
    assert _tiered(SKEW_FAIL_MS + 1, SKEW_THRESHOLD_MS, SKEW_FAIL_MS,
                   higher_is_better=False) == "fail"
    assert _tiered(0.5, 0.9999, CRC_FAIL, higher_is_better=True) == "fail"
    assert _tiered(0.1, 0.60, COVERAGE_FAIL, higher_is_better=True) == "fail"


def test_grade_b_tests_the_h1_skew_bound():
    """A clip 24% over the most common rejection cause is not "within tolerance"."""
    common = dict(dropped=0, dropout=0.0, crc=1.0, hands=["left"], coverage=0.5, cap_c=False)
    assert _grade({"pass"}, skew=20.0, **common) == "B"        # cov 0.5 < 0.60, so not A
    assert _grade({"pass"}, skew=40.0, **common) == "C"        # over H1: caveated, not B
    assert _grade({"pass"}, skew=None, **common) == "C"        # unmeasured is not a pass


def test_grade_a_needs_a_clean_check_table_as_well_as_clean_numbers():
    common = dict(dropped=0, dropout=0.0, crc=1.0, hands=["left"], coverage=0.9, cap_c=False)
    assert _grade({"pass"}, skew=10.0, **common) == "A"
    assert _grade({"pass", "warn"}, skew=10.0, **common) == "B"
    assert _grade({"pass", "not_run"}, skew=10.0, **common) == "B"
    assert _grade({"pass", "fail"}, skew=10.0, **common) == "C"


# --------------------------------------------------------------------------- #
# validate.py — rights must be backed by paperwork                             #
# --------------------------------------------------------------------------- #

DENIED = {k: "denied" for k in
          ("model_training", "commercial_use", "redistribution", "derived_model")}
BACKING = {
    "consent_on_file": True,
    "consent": {"subjects_consented": 1, "covers_model_training": True,
                "covers_redistribution": True, "document_ref": "consent/2026-01"},
}


def test_denied_needs_no_paperwork():
    result, measured, _ = _permission_evidence(dict(DENIED), {})
    assert result == "pass"
    assert measured == "no permissions granted"


def test_granted_without_consent_fails_the_clip():
    """`granted` on a null consent record is worse than `denied`: it is an assertion."""
    rights = {**DENIED, "model_training": "granted",
              "determined_utc": "2026-01-01T00:00:00Z", "license_url": "media/x/LICENSE.txt"}
    result, _, note = _permission_evidence(rights, {})
    assert result == "fail"
    assert "consent" in note


def test_granted_without_a_licence_document_fails_the_clip():
    rights = {**DENIED, "model_training": "granted",
              "determined_utc": "2026-01-01T00:00:00Z", "license_url": None}
    result, _, note = _permission_evidence(rights, dict(BACKING))
    assert result == "fail"
    assert "license_url" in note


def test_granted_without_a_dated_review_fails_the_clip():
    rights = {**DENIED, "model_training": "granted",
              "determined_utc": None, "license_url": "media/x/LICENSE.txt"}
    result, _, _ = _permission_evidence(rights, dict(BACKING))
    assert result == "fail"


def test_fully_backed_grant_passes():
    rights = {**DENIED, "model_training": "granted", "commercial_use": "granted",
              "determined_utc": "2026-01-01T00:00:00Z", "license_url": "media/x/LICENSE.txt"}
    result, _, _ = _permission_evidence(rights, dict(BACKING))
    assert result == "pass"


def test_on_request_warns_rather_than_failing():
    """`on_request` asserts terms exist to negotiate, not a permission. Weaker claim."""
    rights = {**DENIED, "commercial_use": "on_request",
              "determined_utc": None, "license_url": None}
    result, _, _ = _permission_evidence(rights, {})
    assert result == "warn"


# --------------------------------------------------------------------------- #
# validate.py — the alignment error is composed, not copied                    #
# --------------------------------------------------------------------------- #

META = {
    "synchronisation": {
        "common_clock": "CLOCK_REALTIME microseconds",
        "anchor_fit_residual_ms": {"left": 12.418, "right": 12.418},
        "cross_hand_relative_rate_ppm_hostclock": 1379.92,
        "validation_result": "not_validated",
    }
}


def test_headline_is_never_smaller_than_the_drift_it_implies():
    """The reported max used to be the fit residual, which its own record contradicted."""
    sync = build_sync(META, streams=["video", "tactile_left", "tactile_right"],
                      hands=["left", "right"], duration_s=11.57, cfr_divergence_ms=3.8)
    implied = drift_implied_ms(1379.92, 11.57)
    assert implied == pytest.approx(15.96, abs=0.01)
    assert sync["maximum_alignment_error_ms"] >= round(implied, 3)
    assert sync["clock_fit_residual_ms"] == 12.418
    assert sync["maximum_alignment_error_ms"] > sync["clock_fit_residual_ms"]


def test_container_divergence_counts_as_an_alignment_error():
    sync = build_sync({"synchronisation": {}}, streams=["video", "imu"], hands=[],
                      duration_s=9.6, cfr_divergence_ms=58.88)
    assert sync["maximum_alignment_error_ms"] == pytest.approx(58.88)
    video = next(s for s in sync["streams"] if s["stream_id"] == "video")
    assert video["maximum_alignment_error_ms"] == pytest.approx(58.88)


# The producer that ships a fit standard error alongside the residual. This is the shape
# the pipeline emits now; META above is the older two-field shape and is kept so the
# fallback stays covered.
META_SE = {
    "synchronisation": {
        "common_clock": "CLOCK_REALTIME microseconds",
        "anchor_fit_residual_ms": {"left": 32.343, "right": 32.100},
        "anchor_fit_se_worst_ms": {"left": 4.150, "right": 4.090},
        "anchor_fit_lag1_autocorr": {"left": -0.36, "right": -0.35},
        "validation_result": "not_validated",
    }
}


def test_alignment_is_the_fit_standard_error_not_the_anchor_scatter():
    """The headline must follow the SE. Quoting the residual overstated it ~8x here and
    pushed a sub-frame corpus past one video frame."""
    sync = build_sync(META_SE, streams=["video", "tactile_left", "tactile_right"],
                      hands=["left", "right"], duration_s=84.6, cfr_divergence_ms=0.001)
    assert sync["clock_fit_se_worst_ms"] == pytest.approx(4.150)
    # The jitter still ships, named for what it is, and is NOT the headline.
    assert sync["clock_fit_residual_ms"] == pytest.approx(32.343)
    assert sync["maximum_alignment_error_ms"] == pytest.approx(4.150)
    assert sync["maximum_alignment_error_ms"] < 33.3
    left = next(s for s in sync["streams"] if s["stream_id"] == "tactile_left")
    assert left["maximum_alignment_error_ms"] == pytest.approx(4.150)


def test_a_curving_clock_falls_back_to_the_residual():
    """Averaging arrival scatter is only valid when it IS scatter. Positive lag-1
    autocorrelation means the clock is not linear over the take, so the fit's standard
    error is not defensible and the conservative number has to be used instead."""
    meta = {"synchronisation": {**META_SE["synchronisation"],
                                "anchor_fit_lag1_autocorr": {"left": 0.41, "right": -0.35}}}
    sync = build_sync(meta, streams=["video", "tactile_left", "tactile_right"],
                      hands=["left", "right"], duration_s=84.6, cfr_divergence_ms=0.001)
    # left curves -> its residual is used; right is clean -> its SE is used.
    assert sync["maximum_alignment_error_ms"] == pytest.approx(32.343)
    assert any("POSITIVE lag-1" in n for n in sync["notes"])
    left = next(s for s in sync["streams"] if s["stream_id"] == "tactile_left")
    right = next(s for s in sync["streams"] if s["stream_id"] == "tactile_right")
    assert left["maximum_alignment_error_ms"] == pytest.approx(32.343)
    assert right["maximum_alignment_error_ms"] == pytest.approx(4.090)


def test_a_producer_without_an_se_still_gets_the_old_conservative_number():
    """A package built before the SE shipped must not silently gain a better headline."""
    sync = build_sync(META, streams=["video", "tactile_left", "tactile_right"],
                      hands=["left", "right"], duration_s=11.57, cfr_divergence_ms=3.8)
    assert sync["clock_fit_se_worst_ms"] == pytest.approx(12.418)
    assert sync["clock_fit_residual_ms"] == pytest.approx(12.418)


# Frames genuinely missing from the emission grid. The sequential-index figure charges
# them as clock error; the grid figure does not. Which one is used is gated on the take
# declaring a grid, because slot-rounding an ARRIVAL-stamped index masks real jitter.
META_GRID = {
    "synchronisation": {
        **META_SE["synchronisation"],
        "video_sensor_grid": {"grid_period_ms": 33.28, "grid_error_ms": 0.0,
                              "frames_lost_in_transport": 41},
    }
}


def test_lost_frames_are_not_charged_as_clock_error_when_a_grid_is_declared():
    sync = build_sync(META_GRID, streams=["video", "tactile_left", "tactile_right"],
                      hands=["left", "right"], duration_s=58.34,
                      cfr_divergence_ms=271.9, grid_divergence_ms=0.001,
                      frames_missing_on_grid=41)
    video = next(s for s in sync["streams"] if s["stream_id"] == "video")
    assert video["maximum_alignment_error_ms"] == pytest.approx(0.001)
    # the glove fit, not the video, is now the binding term
    assert sync["maximum_alignment_error_ms"] == pytest.approx(4.150)


def test_without_a_declared_grid_the_conservative_figure_is_kept():
    """An arrival-stamped package must not gain a better number just because the ingest
    learned how to snap timestamps to a grid."""
    sync = build_sync(META_SE, streams=["video", "tactile_left", "tactile_right"],
                      hands=["left", "right"], duration_s=58.34,
                      cfr_divergence_ms=271.9, grid_divergence_ms=0.001,
                      frames_missing_on_grid=41)
    video = next(s for s in sync["streams"] if s["stream_id"] == "video")
    assert video["maximum_alignment_error_ms"] == pytest.approx(271.9)
    assert sync["maximum_alignment_error_ms"] == pytest.approx(271.9)


def test_a_single_stream_clip_has_no_sync_record():
    assert build_sync(META, streams=["video"], hands=[], duration_s=1.0,
                      cfr_divergence_ms=1.0) is None


# --------------------------------------------------------------------------- #
# records.py — the modality enum has no escape hatch                           #
# --------------------------------------------------------------------------- #

def test_the_modality_enum_matches_the_media_slots():
    """Every listed modality must have somewhere in `media` to point."""
    assert set(MODALITIES) == {"video", "tactile", "imu", "segcap", "calibration"}
    for dead in ("audio", "hand_pose", "depth"):
        assert dead not in MODALITIES
