"""Measured conformance: the H1/H3 sync record, the H2/H4 QA record, and bundle checks.

WHY sync, QA and validation share a module: they are the same activity -- deciding
whether what we measured is acceptable, and against which published bound. The grade
rule reads `sync.maximum_alignment_error_ms`, the H1 auto-flag threshold (33 ms, one
camera frame at 30 fps) appears in both the sync check and the grade, and the bundle
validator re-derives the same facts from the emitted files. Adjacency means each
threshold constant is written once and read three ways.

WHY the bundle validator re-derives instead of trusting: the manifest ships precomputed
facet counts and totals so the UI need not iterate 1000 clips to draw a header. That is
only safe if something proves the precomputation right, so `validate_bundle` recomputes
every aggregate from `clips[]`, resolves every relative URL, and fails on a mismatch.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, NamedTuple
from collections.abc import Iterable

from jsonschema import Draft202012Validator

from .benchmark import (RIGHTS_KEYS, UnlabelledCountryError, build_facets, build_totals,
                        provenance_class, trim)

# ---------------------------------------------------------------- published bounds
# Every measured-quality check carries TWO bounds, and both are published in
# CONTRACT.md 4.2. The PREFERRED bound is the requirement's own number and is what the
# check reports as `threshold`; missing it is a `warn`, caps the grade and produces a
# named entry in known_limitations. The ACCEPTANCE bound is wider, and missing THAT is a
# `fail`: the clip is dispositioned `quarantined` and never reaches the catalog.
#
# Both must exist. A tier system whose fail bound is infinity cannot express "this one is
# not good enough", which makes the grade a marketing label rather than a QA verdict --
# and the acceptance bound has to be a real number, published next to the preferred one,
# or a buyer cannot tell what we would actually refuse to ship.
SKEW_THRESHOLD_MS = 33.0  # H1 preferred: one camera frame at 30 fps
SKEW_FAIL_MS = 66.0       # H1 acceptance: two camera frames. Beyond this a contact event
                          # cannot be attributed to a frame at all, so the clip is useless
                          # for the one thing time-aligned tactile is bought for.
DROPOUT_THRESHOLD = 0.01  # H2 preferred alert bound
DROPOUT_FAIL = 0.05       # H2 acceptance: 5% of frames gone is a broken capture, not a clip
CRC_A, CRC_B = 0.9999, 0.999
CRC_FAIL = 0.99           # below 1 frame in 100 verifying, loss is not quantifiable
COVERAGE_A, COVERAGE_B = 0.60, 0.40
COVERAGE_FAIL = 0.25      # under a quarter of the readout working, the glove is broken
                          # hardware and a spatial contact map cannot be reconstructed
RECTIFICATION_PREFERRED_PX, RECTIFICATION_FAIL_PX = 0.5, 2.0
_GRADES = ("A", "B", "C")
_ASSET_EXTENSIONS = frozenset((
    "json", "jsonl", "csv", "f32", "npz", "npy", "parquet", "mp4", "mkv", "mov", "webm",
    "jpg", "jpeg", "png", "webp", "md", "txt", "pdf", "sha256", "py", "zip", "tar", "gz", "zst"))
_SIGN_CONVENTION = ("offset_ns = t_reference - t_stream; positive means the stream is EARLY "
                    "relative to the reference clock.")


# ------------------------------------------------------------------- sync (H1, H3)

def drift_implied_ms(drift_ppm: float | None, duration_s: float | None) -> float | None:
    """Relative rate error carried over the whole take, in milliseconds.

    A stream running `drift_ppm` fast against the reference has slipped this far by the
    end of a `duration_s` take. It is a LOWER BOUND on that stream's worst-case
    misalignment and is derivable by anyone holding the record, which is precisely why
    the headline may never be smaller than it.
    """
    if drift_ppm is None or duration_s is None:
        return None
    return abs(float(drift_ppm)) * 1e-6 * float(duration_s) * 1000.0


def build_sync(meta: dict, *, streams: list[str], hands: list[str], duration_s: float | None,
               cfr_divergence_ms: float | None, grid_divergence_ms: float | None = None,
               frames_missing_on_grid: int | None = None) -> dict | None:
    """Measured per-clip synchronisation. There is deliberately no boolean `synced`.

    A boolean cannot be checked and is therefore worthless. What ships instead is the
    named reference clock, the sign convention that makes every offset interpretable,
    the measured worst-case skew, and how -- or whether -- it was validated.

    `maximum_alignment_error_ms` is COMPOSED, not copied. The producer's anchor-fit
    residual is only one of its three components, and on its own it is routinely smaller
    than a bound a buyer can derive from two other fields in the same document:

      (a) clock_fit_se_worst_ms  -- the standard error of the fitted clock line at the
          ends of the take. NOT clock_fit_residual_ms, which is the worst single anchor's
          arrival jitter about that line and is ~10x larger; see the note in _sync_record;
      (b) |estimated_drift_ppm| * 1e-6 * duration_s * 1000 -- relative rate error carried
          to the end of the take, which a fit residual does not contain;
      (c) the divergence between the constant-rate container timeline and the real
          per-frame arrival times, measured off frame_times.csv.

    Reporting (a) alone as the headline is the defect this composition exists to prevent,
    and `validate_bundle` re-derives the inequality and fails the build if it is violated.
    """
    if len(streams) < 2:
        return None
    src = meta.get("synchronisation") or {}
    resid = src.get("anchor_fit_residual_ms")
    resid = resid if isinstance(resid, dict) else {}
    # THE ALIGNMENT IS THE FIT, NOT ANY SINGLE ANCHOR.
    #
    # A per-anchor stamp is quantised by USB burst arrival: it says when the host was
    # handed the bytes, not when the device sampled. What places a sample on the host
    # clock is the least-squares LINE through 40-135 such anchors, and the uncertainty of
    # a line is its standard error -- worst-case at the ends of the take, which is the
    # figure taken here. The max residual is an order of magnitude larger and is a jitter
    # DIAGNOSTIC, not an alignment error; publishing it as the headline overstated this
    # corpus about tenfold and pushed the number past one video frame, which reads as "not
    # frame-synchronised" for data that is.
    #
    # Averaging that scatter is only legitimate if it IS scatter. `anchor_fit_lag1_autocorr`
    # is the evidence and it is checked below: quantisation noise is non-positive
    # (measured -0.32 to -0.39 on the tactile streams), whereas a curving clock would be
    # positive -- and then a straight line is the wrong model and its standard error means
    # nothing. If a producer ships a positive autocorrelation we fall back to the residual
    # rather than quote an SE we cannot defend.
    se = src.get("anchor_fit_se_worst_ms")
    se = se if isinstance(se, dict) else {}
    lag1 = src.get("anchor_fit_lag1_autocorr")
    lag1 = lag1 if isinstance(lag1, dict) else {}
    _curving = [h for h, v in lag1.items() if isinstance(v, (int, float)) and v > 0]

    def _align(hand):
        """Alignment uncertainty for one hand: the fit SE, or the residual if we cannot
        stand behind the SE (no SE shipped, or that hand's clock is not straight)."""
        v = se.get(hand)
        if isinstance(v, (int, float)) and hand not in _curving:
            return float(v)
        v = resid.get(hand)
        return float(v) if isinstance(v, (int, float)) else None

    _align_all = [v for v in (_align(h) for h in (resid.keys() | se.keys())) if v is not None]
    fit_worst = max(_align_all) if _align_all else None
    # Kept and published beside the alignment, as the jitter it was averaged out of.
    _resid_measured = [v for v in resid.values() if isinstance(v, (int, float))]
    resid_worst = max(_resid_measured) if _resid_measured else None
    xh_ppm = src.get("cross_hand_relative_rate_ppm_hostclock")

    # WHICH VIDEO NUMBER COUNTS: sequential-index divergence, or grid-relative?
    #
    # They differ only when frames are missing, and then by a lot -- 41 dropped frames out
    # of 1713 reads as ~250 ms of sequential divergence and ~0 ms against the grid. The
    # first is the honest number for a timeline built from ARRIVAL stamps in a constant-rate
    # container: there, a lost frame really does shift every later frame by a period, and a
    # consumer seeking by time lands wrong.
    #
    # It is the WRONG number once the producer ships true per-frame exposure times and a
    # container carrying real PTS. Then nothing is mistimed; frames are absent. Charging
    # absence as clock error is what kept five sound takes out of a drop.
    #
    # So the grid figure is used ONLY when the take declares a measured sensor grid, which
    # is the producer asserting its timestamps are exposure-derived and not arrival. A
    # package that declares nothing keeps the conservative number and cannot silently
    # improve. The frame loss does not vanish either way -- it is published as
    # `frames_missing_on_grid` and drives its own QA check.
    _grid = src.get("video_sensor_grid")
    _declares_grid = isinstance(_grid, dict) and _grid.get("grid_period_ms") is not None
    if _declares_grid and grid_divergence_ms is not None:
        video_divergence_ms = grid_divergence_ms
    else:
        video_divergence_ms = cfr_divergence_ms

    rows = []
    for sid in streams:
        hand = sid.removeprefix("tactile_")
        per = _align(hand) if sid.startswith("tactile_") else None
        # Every listed stream names its clock, INCLUDING the one that is not on the
        # reference. A row of four nulls under a header that talks about a shared clock
        # reads as a gap in the record; "free-running sample counter, NOT stamped on the
        # reference clock" reads as the measurement it is. See `imu_not_on_reference`.
        clock = (src.get("video_frame_clock") if sid == "video"
                 else src.get("tactile_clock") if sid.startswith("tactile")
                 else src.get("imu_clock") if sid == "imu" else None)
        # The cross-hand rate error is a RELATIVE figure between the two gloves. It is
        # carried on the right-hand row by convention (the left is the local reference),
        # and `offset_sign_convention` plus this comment are what make that readable.
        drift = xh_ppm if sid == "tactile_right" else None
        parts = [v for v in (per, drift_implied_ms(drift, duration_s)) if v is not None]
        if sid == "video":
            parts = [v for v in (video_divergence_ms,) if v is not None]
        rows.append({"stream_id": sid, "clock_id": trim(clock, 96),
                     "offset_ns": 0 if sid == "video" else None,
                     "interpolation_policy": "nearest" if sid.startswith("tactile") else "none",
                     "estimated_drift_ppm": drift,
                     "maximum_alignment_error_ms": round(max(parts), 3) if parts else None})

    per_stream = [r["maximum_alignment_error_ms"] for r in rows
                  if r["maximum_alignment_error_ms"] is not None]
    overall = [*per_stream, *( [fit_worst] if fit_worst is not None else [] )]
    worst = round(max(overall), 3) if overall else None

    notes = [n for n in (trim(src.get(k), 1000) for k in
                         ("alignment_caveat", "cfr_vfr_warning", "cross_hand_note",
                          # A delivered stream that is NOT on the reference clock has to
                          # say so here, in the same list a buyer reads for the ones that
                          # are. Silence about it is what let "on a single host clock"
                          # stand over a stream that is on no clock at all.
                          "imu_not_on_reference")) if n]
    notes.append(
        "maximum_alignment_error_ms is the maximum over three measured components, not any "
        "one of them: the clock-fit standard error at the ends of the take "
        "(clock_fit_se_worst_ms"
        + (f" = {fit_worst:.3f} ms" if fit_worst is not None else " = null")
        + "), each stream's relative rate error carried over the take "
        "(|estimated_drift_ppm| * 1e-6 * duration_s * 1000)"
        + (f", and the container timeline's divergence from the real per-frame times "
           f"({cfr_divergence_ms:.3f} ms)." if cfr_divergence_ms is not None
           else ", and the container-timeline divergence, which could not be measured because "
                "no per-frame timestamp index ships."))
    notes.append(
        "clock_fit_residual_ms"
        + (f" ({resid_worst:.3f} ms)" if resid_worst is not None else " (null)")
        + " is the worst SINGLE anchor's scatter about that line, not the alignment. It is "
        "USB burst-arrival quantisation and is published as the jitter the fit averaged "
        "out; the fit is what places a sample on the host clock. The lag-1 autocorrelation "
        "of those residuals is published with them as the evidence that averaging is valid "
        "-- it is non-positive for quantisation noise and would be positive for a clock "
        "that curves, in which case a straight line is the wrong model.")
    if _curving:
        notes.append(
            "Alignment for " + ", ".join(sorted(_curving)) + " falls back to the max anchor "
            "residual rather than the fit standard error: that stream's residuals have "
            "POSITIVE lag-1 autocorrelation, which is the signature of a clock that is not "
            "linear over the take, and a linear fit's standard error is not meaningful there.")
    if not src:
        notes.append("No synchronisation record shipped with this take: alignment rests on a "
                     "shared host clock and has not been measured.")
    both = len(hands) == 2
    return {"reference_clock_id": trim(src.get("common_clock"), 200)
                or "undeclared: the take shipped no synchronisation record",
            "offset_sign_convention": _SIGN_CONVENTION, "streams": rows,
            "maximum_alignment_error_ms": worst,
            # Two different quantities, published side by side and each named for what it
            # is. Collapsing them into one field is the defect this pair exists to prevent.
            "clock_fit_se_worst_ms": fit_worst,
            "clock_fit_residual_ms": resid_worst,
            "validation_method": trim(src.get("validation_method"), 1000),
            "validation_result": src.get("validation_result") or "not_validated",
            "cross_hand_offset_ms": src.get("cross_hand_offset_ms") if both else None,
            "samples_per_video_frame": src.get("tactile_samples_per_video_frame"),
            "join_recipe": trim(src.get("join_recipe"), 2000), "notes": notes,
            "cross_hand_drift_ppm": xh_ppm if both else None}


def probe_disagreements(probe: Any, meta: dict) -> list[str]:
    """Where ffprobe and the sidecar differ. ffprobe wins; the difference is reported."""
    mv = (meta.get("modalities") or {}).get("video") or {}
    out = []
    for name, got, claim in (("resolution", probe.resolution, mv.get("resolution")),
                             ("fps", probe.fps, mv.get("fps")),
                             ("frames", probe.frames, mv.get("frames")),
                             ("duration_s", probe.duration_s, meta.get("duration_s"))):
        if claim is None or got is None:
            continue
        near = (isinstance(got, float) and isinstance(claim, (int, float))
                and abs(got - claim) <= abs(claim) * 1e-6)
        if not near and got != claim:
            out.append(f"{name}: ffprobe measured {got!r}, metadata.json claims {claim!r} "
                       f"-- using the measurement")
    return out


# --------------------------------------------------------------------- QA (H2, H4)

#: Checks whose answer is a property of the PROGRAMME, not of a take. They come out the
#: same on every clip by construction -- nobody has annotated any clip, no clip has a clap
#: decoded, the rig has one cam-IMU solve or none. Tagging them lets the clip page show
#: what makes THAT clip different and the collection page state these once. The check
#: still ships in full on every clip; this only affects where a reader is shown it.
#:
#: `split_assigned` is the odd one out and is tagged separately: publishing no split is a
#: DECISION with a rationale in collection.toml (one operator, one rig, one day puts the
#: same domain on both sides), not a gap. Rendering a considered position in the same
#: amber as an unmeasured one is what makes the page read worse than the corpus is.
_PROGRAMME_SCOPE = {
    "annotation_present", "calibration_cam_imu_present", "calibration_readout_time_ms",
    "imu_noise_characterised", "privacy_redaction_record", "sync_independent_validation",
    "split_assigned",
}
_BY_DESIGN = {"split_assigned"}


def _check(cid: str, category: str, result: str, measured: Any, threshold: Any,
           units: str | None = None, note: str | None = None) -> dict:
    """One acceptance check. H4 requires the measurement AND the bound it was tested against."""
    return {"check_id": cid, "category": category, "result": result,
            "measured_value": measured, "threshold": threshold, "units": units,
            "scope": "collection" if cid in _PROGRAMME_SCOPE else "clip",
            "kind": "by_design" if cid in _BY_DESIGN else "measured",
            "note": trim(note, 500)}


def _tiered(value: float | None, good: float, accept: float, *, higher_is_better: bool) -> str:
    """pass / warn / fail against a preferred and an acceptance bound."""
    if value is None:
        return "not_run"
    if higher_is_better:
        return "pass" if value >= good else ("warn" if value >= accept else "fail")
    return "pass" if value <= good else ("warn" if value <= accept else "fail")


def _permission_evidence(rights: dict, privacy: dict) -> tuple[str, Any, str | None]:
    """H5 x H6: is every permission we assert actually backed by paperwork?

    `granted` is an assertion a buyer's counsel will ask us to stand behind, so it fails
    the clip outright unless the consent record covers it, a licence document exists and a
    human signed the rights review off. `on_request` asserts only that terms exist to
    negotiate, which is a weaker claim and warns rather than fails -- but it is still a
    claim, so an unreviewed one is not silent. `denied` needs nothing.

    Returns (result, measured_value, note).
    """
    consent = privacy.get("consent") if isinstance(privacy.get("consent"), dict) else {}
    covers = {"model_training": consent.get("covers_model_training"),
              "commercial_use": consent.get("covers_model_training"),
              "redistribution": consent.get("covers_redistribution"),
              "derived_model": consent.get("covers_redistribution")}
    granted = [k for k in RIGHTS_KEYS if rights.get(k) == "granted"]
    on_request = [k for k in RIGHTS_KEYS if rights.get(k) == "on_request"]
    if not granted and not on_request:
        return ("pass", "no permissions granted",
                "Nothing is granted, so nothing needs backing. Any move off 'denied' re-runs "
                "this check against the consent record, the licence document and the review "
                "timestamp.")

    missing: list[str] = []
    if not rights.get("determined_utc"):
        missing.append("rights.determined_utc is null (no human review on record)")
    if not rights.get("license_url"):
        missing.append("rights.license_url is null (no licence document ships)")
    if privacy.get("consent_on_file") is not True:
        missing.append(f"privacy.consent_on_file is {privacy.get('consent_on_file')!r}")
    if not consent:
        missing.append("privacy.consent is null (no consent record at all)")
    missing += [f"consent does not cover {k}" for k in granted if covers.get(k) is not True]

    if not missing:
        return ("pass", f"{len(granted) + len(on_request)} permission(s) backed", None)
    asserted = ", ".join(granted + on_request)
    note = f"{asserted}: " + "; ".join(missing)
    # A `granted` permission without its paperwork is worse than `denied`, so it blocks
    # acceptance. `on_request` alone warns.
    return ("fail" if granted else "warn", "; ".join(missing)[:200], note)


def build_qa(ci: Any, *, sync: dict | None, calibration: dict | None,
             rights: dict, privacy: dict) -> tuple[dict, list[str]]:
    """The H2/H4 record: every check with its measurement and threshold, then the grade."""
    warn: list[str] = []
    hands, stamps = ci.tactile.hands, ci.frame_timestamps
    delivered = ci.probe.frames if ci.probe else None
    # The producer's own counter, and it counts what the WRITER lost. On this rig the loss
    # happens upstream of the writer -- the device's own metadata says `lost_before_writer:
    # true` with the write queue never above 7% -- so this reads 0 on takes that are
    # genuinely missing 2-8% of their frames. It is not wrong, it is answering a narrower
    # question than a buyer thinks it is.
    #
    # `frames_missing_on_grid` is measured HERE, off the delivered timestamp index, by
    # counting slots on the emission cadence that no frame occupies. It needs nothing from
    # the producer and cannot be under-reported by a counter that never saw the loss. When
    # the two disagree the larger one is the number that matters, so it is the one graded.
    _writer_dropped = ((ci.metadata or {}).get("quality") or {}).get("video_frames_dropped")
    # Only trust the grid count when the take declares its timestamps are exposure-derived.
    # On an ARRIVAL-stamped index the snap-to-nearest-slot step misfires: measured on
    # synthetic arrival jitter of +/-8 ms, slot rounding invented 3 missing frames out of
    # 1000 that were all present. Ungated, that phantom loss would be graded as real.
    _sync_meta = (ci.metadata or {}).get("synchronisation") or {}
    _grid_decl = _sync_meta.get("video_sensor_grid")
    _grid_missing = (ci.frames_missing_on_grid
                     if isinstance(_grid_decl, dict) and _grid_decl.get("grid_period_ms")
                     else None)
    dropped = max([v for v in (_writer_dropped, _grid_missing) if isinstance(v, int)],
                  default=None)
    parity = None if (delivered is None or stamps is None) else (delivered == stamps)
    crc, usable = ci.tactile.crc_pass_rate, ci.tactile.usable_channels
    sites = (ci.tactile.preview or {}).get("readout_sites")
    live = [usable[h] for h in hands if usable.get(h) is not None]
    coverage = (min(live) / sites) if (live and sites) else None
    dropout = (dropped / delivered) if (dropped is not None and delivered) else None
    skew = (sync or {}).get("maximum_alignment_error_ms")
    cam = ((calibration or {}).get("camera") or {})
    model = cam.get("model")
    imu_cal = ((calibration or {}).get("imu") or {})
    pii = privacy.get("pii_review")
    reviewed = bool(rights.get("determined_utc"))
    repro = ci.tactile.census_reproducible or {}
    perm_result, perm_measured, perm_note = _permission_evidence(rights, privacy)
    rect = cam.get("rectification_residual_px")
    validation = (sync or {}).get("validation_result")

    # H7 completeness. Every one of these is a documented rejection cause for a wide-FoV
    # egocentric rig, and none of them was checked before, which is how a clip with a
    # fully null IMU characterisation and no cam-IMU solve reached the top grade.
    noise_keys = ("accel_noise_density", "accel_random_walk",
                  "gyro_noise_density", "gyro_random_walk")
    noise_present = [k for k in noise_keys if imu_cal.get(k) is not None]
    imu_declared = imu_cal.get("status") in ("operational", "unverified", "failed")

    checks = [
        _check("sync_max_skew_ms", "sync", _tiered(skew, SKEW_THRESHOLD_MS, SKEW_FAIL_MS,
               higher_is_better=False), skew, SKEW_THRESHOLD_MS, "ms",
               f"Acceptance bound {SKEW_FAIL_MS:.0f} ms (two camera frames); above it the clip "
               f"is quarantined." if skew is not None else
               "No measured inter-stream skew ships with this take."),
        _check("sync_independent_validation", "sync",
               "pass" if validation == "pass" else
               ("fail" if validation == "fail" else "not_run" if sync is None else "warn"),
               validation, "pass", None,
               None if validation == "pass" else
               "The alignment IS measured -- see sync.maximum_alignment_error_ms -- but nothing "
               "physical corroborates it. A shared host clock gives every stream the same ruler, "
               "so there is no drift between them; what it cannot show is a constant offset, "
               "because a timestamp records when the host received the data, not when the event "
               "happened, and the video and tactile paths have different delays. Only a "
               "common-mode physical event -- a clap, visible in video and sharp on both gloves "
               "-- can measure that. Not measured here, so not claimed."),
        _check("video_frame_dropout", "media", _tiered(dropout, 0.0, DROPOUT_FAIL,
               higher_is_better=False), dropout, DROPOUT_THRESHOLD, "fraction",
               f"H2 alerts above {DROPOUT_THRESHOLD:.0%}; acceptance bound {DROPOUT_FAIL:.0%}."),
        _check("video_frame_timestamp_parity", "integrity",
               "not_run" if parity is None else ("pass" if parity else "fail"), parity, True, None,
               "H2: delivered frame count must equal the per-frame timestamp row count."),
        _check("tactile_crc_pass_rate", "tactile",
               "not_run" if not hands else _tiered(crc, CRC_A, CRC_FAIL, higher_is_better=True),
               crc, CRC_A, "fraction",
               "VENDOR-REPORTED: this counts the `crc_ok` flag column the capture daemon "
               "wrote. The on-wire bytes are not in the delivered array, so the ingest cannot "
               f"recompute it. Acceptance bound {CRC_FAIL}."),
        _check("tactile_census_reproducible", "tactile",
               "not_run" if not repro.get("hands_compared") else
               ("pass" if repro.get("agree") else
                "fail" if _census_flattered(repro) else "warn"),
               _census_measured(repro), "shipped masks == masks re-derived from counts", None,
               "The published census uses the producer's shipped taxel masks; it is "
               "independently re-derived here from `counts` with the stated rules and "
               "compared. A published `stable` count HIGHER than the re-derived one is a "
               "flattered coverage figure and fails."),
        _check("tactile_channel_coverage", "coverage",
               "not_run" if not hands else _tiered(coverage, COVERAGE_A, COVERAGE_FAIL,
                                                   higher_is_better=True),
               coverage, COVERAGE_A, "fraction",
               "Live AND stable channels on the worst hand, over readout sites. Acceptance "
               f"bound {COVERAGE_FAIL:.0%}; below it the glove is broken hardware."),
        _check("package_checksums", "integrity",
               "not_run" if ci.checksums_verified is None else
               ("pass" if ci.checksums_verified else "fail"), ci.checksums_verified, True),
        _check("camera_calibration_model", "calibration",
               "pass" if model in ("kannala_brandt", "fisheye624", "opencv_fisheye")
               else ("fail" if model else "warn"), model or "none", "a fisheye model", None,
               "A wide-FoV rig described by pinhole_radtan is a rejection, not a caveat."),
        _check("calibration_rectification_residual_px", "calibration",
               "not_run" if (rect is None or cam.get("stereo") is None) else
               _tiered(rect, RECTIFICATION_PREFERRED_PX, RECTIFICATION_FAIL_PX,
                       higher_is_better=False),
               rect, RECTIFICATION_PREFERRED_PX, "px",
               "Median |dy| measured on a delivered frame rectified with the calibration a "
               "consumer is told to apply. Not applicable to a monocular rig."),
        _check("calibration_cam_imu_present", "calibration",
               "not_run" if calibration is None else
               ("pass" if (calibration.get("cam_imu") or {}).get("time_offset_s") is not None
                and (calibration.get("cam_imu") or {}).get("R") is not None else "warn"),
               (calibration or {}).get("cam_imu") is not None, True, None,
               "H7: camera-IMU extrinsics AND time offset. Neither is derivable from the "
               "other calibrations, and VIO cannot start without both."),
        _check("calibration_readout_time_ms", "calibration",
               "not_run" if calibration is None or cam.get("shutter") == "global" else
               ("pass" if cam.get("readout_time_ms") is not None else "warn"),
               cam.get("readout_time_ms"), "present on a rolling shutter", "ms",
               "H7: without it, rolling-shutter motion on a head-mounted camera cannot be "
               "compensated."),
        _check("imu_noise_characterised", "calibration",
               "not_run" if not ci.imu_preview and not imu_declared else
               ("pass" if len(noise_present) == len(noise_keys) and imu_cal.get("rate_hz")
                else "warn"),
               f"{len(noise_present)}/4 noise parameters", "4/4 plus rate_hz", None,
               "This does NOT mean the IMU is faulty or absent -- where an imu stream ships it "
               "is delivering valid data, and the delivered rate is published beside this. What "
               "is missing is the NOISE model: accelerometer and gyroscope noise density and "
               "random walk, from an Allan deviation over a long stationary recording. A VIO "
               "pipeline needs those numbers to weight the IMU against vision, which is why a "
               "working but uncharacterised IMU still misses this bound."),
        _check("rights_reviewed", "rights", "pass" if reviewed else "warn", reviewed, True, None,
               None if reviewed else "No human rights review is on record; all four fail closed."),
        _check("privacy_consent_covers_granted_rights", "privacy", perm_result, perm_measured,
               "consent, licence and a dated review must back every permission we assert",
               None, perm_note),
        _check("privacy_redaction_record", "privacy",
               "fail" if (privacy.get("faces_redacted") is True
                          and privacy.get("redaction") is None) else
               ("pass" if privacy.get("redaction") else "warn"),
               bool(privacy.get("redaction")), True, None,
               "H6 requires the redaction RECORD -- policy version, targets, method, reviewer, "
               "date -- not just the outcome. `faces_redacted: true` with a null redaction "
               "record asserts an outcome the schema itself defines as never having happened."),
        _check("privacy_retention_policy", "privacy",
               "pass" if privacy.get("retention") else "warn",
               bool(privacy.get("retention")), True, None,
               "H6 requires a stated retention and deletion policy, and an address a subject "
               "can use to exercise it."),
        _check("privacy_pii_review", "privacy",
               "pass" if pii in ("passed", "not_required") else
               ("fail" if pii == "failed" else "warn"), pii, "passed"),
        _check("annotation_present", "annotation", "pass" if ci.segments else "warn",
               len(ci.segments), 1, "count"),
        _check("split_assigned", "annotation", "pass" if ci.split else "warn",
               ci.split, "train|val|test", None,
               "H10: without a published split every buyer invents their own and no two "
               "evaluations of this data are comparable."),
    ]

    results = {c["result"] for c in checks}
    grade = _grade(results, dropped=dropped, dropout=dropout, crc=crc, hands=hands,
                   coverage=coverage, skew=skew,
                   cap_c=ci.metadata is None or (ci.probe and ci.layout.frame_times is None))
    override = ci.cfg.get("grade_override")
    if override in _GRADES:
        if _GRADES.index(override) >= _GRADES.index(grade):
            grade = override
        else:
            warn.append(f"grade_override={override!r} would RAISE the computed grade {grade!r}; "
                        f"a human may only lower it, so the computed grade stands")
    disposition = "quarantined" if "fail" in results else "accepted"
    if disposition != "accepted":
        warn.append("QA disposition is not 'accepted': "
                    + ", ".join(c["check_id"] for c in checks if c["result"] == "fail"))
    return {
        "grade": grade, "disposition": disposition, "video_frames_dropped": dropped,
        # Both, so the gap between them is visible rather than silently resolved above.
        "video_frames_dropped_by_writer": _writer_dropped,
        "video_frames_missing_on_grid": _grid_missing,
        "video_frames_delivered": delivered, "video_timestamps": stamps,
        "frame_count_matches_timestamps": parity, "tactile_crc_pass_rate": crc,
        "tactile_crc_pass_rate_by_hand": ci.tactile.crc_by_hand,
        "tactile_frames_lost": ci.tactile.frames_lost, "usable_channels": usable,
        "tactile_coverage": None if coverage is None else round(coverage, 6),
        # Promoted out of checks[] and into the summary (see _QA_SUMMARY) because it is
        # the fact that says what `sync_max_alignment_error_ms` is worth, and it was
        # legible only by opening the Calib & sync tab and reading its tail. True means
        # a common-mode physical event corroborated the alignment; False means nothing
        # did and it rests on the shared host clock; null means no sync record shipped.
        "sync_validated": None if not sync else (validation == "pass"),
        "checksums_verified": ci.checksums_verified, "checks": checks,
        # Counted here, next to the checks themselves, so the card can say
        # "accepted, 3 warns". Every published clip is `accepted` -- a disposition
        # on its own therefore carries no information, and showing only that is
        # exactly how a warning stops reaching the buyer.
        "checks_warn": sum(1 for c in checks if c["result"] == "warn"),
        "checks_fail": sum(1 for c in checks if c["result"] == "fail"),
        "notes": None,
    }, warn


def _census_measured(repro: dict) -> str | None:
    """Both numbers, in one string, so a disagreement is legible without a second lookup."""
    bad = repro.get("disagreements") or {}
    if not repro.get("hands_compared"):
        return None
    if not bad:
        return "shipped masks reproduced exactly on " + ", ".join(repro["hands_compared"])
    return "; ".join(
        f"{hand}: shipped stable={d['published']['stable']} vs re-derived "
        f"{d['rederived']['stable']}" for hand, d in sorted(bad.items()))[:200]


def _census_flattered(repro: dict) -> bool:
    """True when the SHIPPED census claims more working channels than we could reproduce."""
    return any(d["published"]["stable"] > d["rederived"]["stable"]
               for d in (repro.get("disagreements") or {}).values())


def _grade(results: set[str], *, dropped: int | None, dropout: float | None, crc: float | None,
           hands: list[str], coverage: float | None, skew: float | None, cap_c: bool) -> str:
    """The published, deterministic grade rule from CONTRACT.md section 4.2.

    A human may override this downward, never upward. `cap_c` carries the two documented
    structural gaps -- no metadata document, or no per-frame timestamp index -- which
    make the delivery unverifiable regardless of how the numbers look.

    B tests the H1 skew bound as well as the H2 ones. It used not to, which meant a clip
    24% over the single most common rejection cause on a new rig could be labelled "within
    tolerance". A clip that misses the H1 bound is grade C: accepted, with the exceedance
    named in known_limitations, which is what grade C is for.
    """
    crc_ok_a = (crc is not None and crc >= CRC_A) if hands else True
    crc_ok_b = (crc is not None and crc >= CRC_B) if hands else True
    cov_a = (coverage is not None and coverage >= COVERAGE_A) if hands else True
    cov_b = (coverage is not None and coverage >= COVERAGE_B) if hands else True
    skew_ok = skew is not None and skew <= SKEW_THRESHOLD_MS
    if cap_c or "fail" in results:
        return "C"
    if (not results & {"warn", "not_run"} and dropped == 0 and crc_ok_a and cov_a and skew_ok):
        return "A"
    if ((dropout is not None and dropout <= DROPOUT_THRESHOLD) and crc_ok_b and cov_b
            and skew_ok):
        return "B"
    return "C"


# ------------------------------------------------------------------ bundle validation

class Row(NamedTuple):
    """One validation result line, rendered as a table row and folded into the exit code."""

    check: str
    status: str  # PASS | FAIL | WARN
    detail: str = ""


def _load_schema(schema_dir: Path, name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((schema_dir / name).read_text(encoding="utf-8")))


def _errors(v: Draft202012Validator, doc: Any, label: str, limit: int = 6) -> list[str]:
    return [f"{label}: {'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message[:160]}"
            for e in sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path))[:limit]]


def _walk_urls(node: Any, out: list[str]) -> None:
    """Collect every value that is a bundle-relative asset URL.

    Discrimination is by file extension, not by key name: `path` inside a PackageEntry
    describes the archive rather than the bundle, and a version string like
    `6s-catalog/1.0` is shaped exactly like a relative path. A closed extension set is
    the only rule that separates all three without a per-key allowlist that rots.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key != "path":  # PackageEntry.path is archive-relative, not a bundle URL
                _walk_urls(value, out)
    elif isinstance(node, list):
        for item in node:
            _walk_urls(item, out)
    elif (isinstance(node, str) and "/" in node and " " not in node and "{" not in node
          and not node.startswith(("http", "/"))
          and node.rsplit(".", 1)[-1].lower() in _ASSET_EXTENSIONS):
        out.append(node)


def validate_bundle(out_dir: Path, schema_dir: Path, *, media_mode: str = "reference") -> list[Row]:
    """Schema-validate the emitted bundle and re-derive every precomputed aggregate."""
    rows: list[Row] = []
    manifest_path = out_dir / "catalog.json"
    if not manifest_path.is_file():
        return [Row("catalog.json exists", "FAIL", str(manifest_path))]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    cat_v = _load_schema(schema_dir, "catalog.schema.json")
    clip_v = _load_schema(schema_dir, "clip.schema.json")
    errs = _errors(cat_v, manifest, "catalog.json")
    rows.append(Row("catalog.json matches catalog.schema.json", "FAIL" if errs else "PASS",
                    "; ".join(errs)))

    clips = manifest.get("clips", [])
    paths = ((manifest.get("collection") or {}).get("paths") or {})
    details, missing_details, clip_errs = {}, [], []
    for summary in clips:
        cid, slug = summary["id"], summary["slug"]
        rel = summary.get("detail", (paths.get("detail") or "").replace("{id}", cid).replace("{slug}", slug))
        if not rel:
            missing_details.append(cid)
            continue
        target = out_dir / rel
        if not target.is_file():
            missing_details.append(f"{cid} -> {rel}")
            continue
        doc = json.loads(target.read_text(encoding="utf-8"))
        details[cid] = doc
        clip_errs += _errors(clip_v, doc, rel)
    rows.append(Row("clip records match clip.schema.json", "FAIL" if clip_errs else "PASS",
                    "; ".join(clip_errs[:8])))
    rows.append(Row("every clip resolves to a detail record", "FAIL" if missing_details else "PASS",
                    ", ".join(missing_details[:6])))

    parity = [f"{cid}.{k}" for cid, doc in details.items() for k in
              ("title", "duration_s", "category", "capture", "bytes", "country")
              if doc.get(k) != next((s for s in clips if s["id"] == cid), {}).get(k)]
    rows.append(Row("summary is a strict subset of its detail record",
                    "FAIL" if parity else "PASS", ", ".join(parity[:8])))

    urls: list[str] = []
    _walk_urls(manifest, urls)
    for doc in details.values():
        _walk_urls({k: v for k, v in doc.items() if k != "metadata"}, urls)
    absent = sorted({u for u in set(urls) if not (out_dir / u).exists()})
    bundle_absent = [u for u in absent if not u.startswith("media/")]
    take_absent = [u for u in absent if u.startswith("media/")]
    rows.append(Row("bundle-owned assets exist", "FAIL" if bundle_absent else "PASS",
                    f"{len(bundle_absent)} missing: " + ", ".join(bundle_absent[:5])))
    status = "PASS" if not take_absent else ("WARN" if media_mode == "reference" else "FAIL")
    rows.append(Row("referenced take media exists", status,
                    f"{len(take_absent)} not materialised (media-mode={media_mode})"
                    if take_absent else ""))

    got = manifest.get("facets") or {}
    # A country label may legitimately be vendor-supplied (`country_labels` in the
    # collection config) and the bundle does not carry that mapping, so a recount cannot
    # re-derive it and would fail every bundle that used the override. Feed the
    # manifest's own labels back in: THIS row is about the counts agreeing, and
    # `_country_label_row` below is what judges whether the labels are usable at all.
    overrides = {b["value"]: b["label"] for b in (got.get("country") or [])
                 if isinstance(b, dict) and b.get("value") and b.get("label")}
    try:
        recomputed = build_facets(clips, country_overrides=overrides)
    except UnlabelledCountryError as exc:
        rows.append(Row("facet counts equal a recount over clips[]", "FAIL", str(exc)))
    else:
        drift = [f"{name}" for name in set(recomputed) | set(got)
                 if recomputed.get(name) != got.get(name)]
        rows.append(Row("facet counts equal a recount over clips[]", "FAIL" if drift else "PASS",
                        ", ".join(drift)))
    rows.append(_country_label_row(manifest))

    totals = (manifest.get("collection") or {}).get("totals") or {}
    fresh = build_totals(clips, subjects=totals.get("subjects"),
                         sessions=totals.get("sessions"), details=details)
    bad = [k for k, v in fresh.items() if _ne(totals.get(k), v)]
    rows.append(Row("collection totals equal the sum over clips[]", "FAIL" if bad else "PASS",
                    ", ".join(f"{k}: {totals.get(k)!r} != {fresh[k]!r}" for k in bad[:4])))

    rows.append(_copy_vs_sync_row(manifest))
    rows.append(_clip_copy_vs_sync_row(details))
    rows.append(_grid_size_copy_row(manifest))
    rows.append(_provenance_copy_row(manifest))

    got_class = (manifest.get("collection") or {}).get("provenance_class")
    want_class = provenance_class(clips, details)
    rows.append(Row("provenance_class folds over the per-take declaration",
                    "PASS" if got_class == want_class else "FAIL",
                    "" if got_class == want_class else f"{got_class!r} != {want_class!r}"))

    return rows + _sidecar_rows(details, out_dir) + _sync_rows(details) + _split_rows(manifest,
                                                                                      details)


#: A country facet bucket whose `label` is just its own alpha-2 code back again.
#: `{"value": "HK", "label": "HK"}` satisfies every constraint the schema can express --
#: the label is a non-empty string of the right length -- and still puts a machine code
#: in front of a buyer next to `China`.
_BARE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def _country_label_row(manifest: dict) -> Row:
    """Every country bucket must carry a human name, not the code back again.

    The producer already refuses to emit one (`benchmark.country_label` raises), so this
    is the second lock: it catches a hand-edited catalog.json, a bundle built by an older
    ingest, and any future path that reaches `facets` without going through
    `build_facets`. `validate` is the gate a bundle passes before it is uploaded, so the
    check has to exist on this side of it too.
    """
    buckets = ((manifest.get("facets") or {}).get("country")) or []
    bad = []
    for bucket in buckets:
        # The schema row above already rejects a malformed bucket, but validate_bundle
        # runs every check on every bundle rather than stopping at the first failure --
        # so this one has to survive a document that did not pass the schema.
        if not isinstance(bucket, dict):
            bad.append(f"{bucket!r}: not an object")
            continue
        value = str(bucket.get("value") or "")
        label = str(bucket.get("label") or "").strip()
        if not label:
            bad.append(f"{value or '?'}: no label")
        elif label == value and _BARE_CODE_RE.fullmatch(value):
            bad.append(f"{value}: label is the bare code")
    return Row("every country facet bucket carries a display label",
               "FAIL" if bad else "PASS",
               "; ".join(bad[:6]) + (". Add the name to _COUNTRY_NAMES in "
                                     "ingest/benchmark.py or to country_labels in the "
                                     "collection config." if bad else ""))


#: Prose that claims frame-level synchronisation. Deliberately narrow: it matches the
#: shape of the claim ("to about one video frame", "within one frame", "sub-frame"), not
#: any sentence that happens to mention frames.
_FRAME_CLAIM_RE = re.compile(
    r"(?:within|to|of)\s+(?:about\s+|roughly\s+|approximately\s+|~\s*)?"
    r"(?:one|1|a\s+single)\s+(?:video\s+)?frame"
    r"|sub-?frame\s+(?:accura|precis|alignment|sync)",
    re.IGNORECASE,
)


def _copy_vs_sync_row(manifest: dict) -> Row:
    """The headline may not claim a synchronisation the measurements contradict.

    This is the H4 failure mode with the copy deck instead of the disposition field: the
    per-clip records said 34-57 ms honestly, one at a time, at the bottom of a tab, while
    the paragraph a buyer reads first said "about one video frame". Both were shipped, and
    the one they read first was false for two thirds of the corpus.

    The rule is narrow on purpose. It fires only when the collection copy makes a
    frame-level precision claim AND the measured aggregate says at least one clip misses
    it. Stating the measured number is always allowed; claiming a bound the data does not
    support is not, and the message carries the real figures so the fix is one edit.
    """
    collection = manifest.get("collection") or {}
    totals = collection.get("totals") or {}
    over = totals.get("sync_clips_over_one_frame")
    measured = totals.get("sync_clips_measured") or 0
    copy = _collection_copy(collection)
    hit = _FRAME_CLAIM_RE.search(copy)
    if not hit or not over:
        return Row("collection copy does not overstate measured sync", "PASS", "")
    worst = totals.get("sync_max_alignment_error_ms")
    return Row(
        "collection copy does not overstate measured sync", "FAIL",
        f"collection copy claims {hit.group(0)!r} but {over}/{measured} clips exceed one "
        f"frame (measured max {worst} ms). Quote the measured figure or drop the claim.")


#: Every buyer-visible string the collection publishes about itself. `standfirst` is on
#: this list from the day it existed: a promoted line that is exempt from the copy rules
#: is where the next false claim lands, because it is the only line most readers see.
_COPY_KEYS = ("standfirst", "description", "notice")


def _collection_copy(collection: dict) -> str:
    return " ".join(str(collection.get(k) or "") for k in _COPY_KEYS)


#: The readout-GRID size. Every clip's known_limitations says, verbatim, "quote the
#: usable-channel count, never the 484-site grid size" -- and the header quoted
#: "two 22x22 tactile gloves" anyway, in the largest body type on the page, directly
#: contradicting the QA record shipped underneath it. Measured worst-hand coverage is a
#: median of 0.60, so the grid size overstates the working sensor by about 1.7x.
_GRID_SIZE_RE = re.compile(r"\b(?:22\s*[x\u00d7]\s*22|484)\b", re.IGNORECASE)

#: Prose that asserts the media was RECORDED. Narrow on purpose: it matches verbs of
#: capture, not the words "camera" or "workspace".
_RECORDED_CLAIM_RE = re.compile(
    r"\b(?:captured|recorded|filmed|shot|collected)\s+(?:in|at|on|across|throughout)\b",
    re.IGNORECASE,
)


def _grid_size_copy_row(manifest: dict) -> Row:
    """The collection copy may not quote the grid size the clips forbid quoting.

    A 22x22 glove has 484 readout sites and, in this corpus, a median of 290 that are
    live AND stable on the worst hand. Both numbers are true; only one of them is the
    sensor a buyer is paying for, and the clip records already say which. The rule is a
    lock on the one place the QA record cannot reach -- the marketing paragraph.
    """
    collection = manifest.get("collection") or {}
    hit = _GRID_SIZE_RE.search(_collection_copy(collection))
    if not hit:
        return Row("collection copy quotes the channel census, not the grid size", "PASS", "")
    return Row(
        "collection copy quotes the channel census, not the grid size", "FAIL",
        f"collection copy quotes {hit.group(0)!r}, the readout-grid size that every clip's "
        f"known_limitations forbids quoting. Quote the published live-and-stable channel "
        f"census instead, or say 'channel census' and let the data supply the figure.")


def _provenance_copy_row(manifest: dict) -> Row:
    """A synthetic corpus may not say it was captured anywhere.

    `provenance_class` is folded from each take's own declaration, and the header
    renders a banner from it saying the streams "are not recordings of a real
    workspace". The sentence immediately above that banner said the takes were
    "captured in mainland China and Hong Kong". One of the two is wrong on every read,
    and the geography is the one with no referent -- a country on a generated clip is a
    declared attribute, not an observation. Say "modelled on"; when the real takes land
    and provenance_class becomes `recorded`, "captured in" is correct again and this
    rule stops firing.
    """
    collection = manifest.get("collection") or {}
    klass = collection.get("provenance_class")
    if klass not in ("synthetic", "mixed"):
        return Row("collection copy matches provenance_class", "PASS", "")
    hit = _RECORDED_CLAIM_RE.search(_collection_copy(collection))
    if not hit:
        return Row("collection copy matches provenance_class", "PASS", "")
    return Row(
        "collection copy matches provenance_class", "FAIL",
        f"provenance_class is {klass!r} and the header renders a banner saying these are "
        f"not recordings, but the copy says {hit.group(0)!r}. Use 'modelled on' until the "
        f"corpus is recorded.")


def _clip_copy_vs_sync_row(details: dict[str, dict]) -> Row:
    """The same rule, one level down: a clip's own prose against its own measurement.

    Fixing only the collection headline moves the false sentence rather than removing
    it -- the per-clip `description` sits in the Metadata tab a scroll below the
    measured figure, and the two contradicting each other on adjacent tabs is worse
    than either alone. Compared against THIS clip's frame period, not a constant.
    """
    bad: list[str] = []
    for cid, doc in sorted(details.items()):
        copy = " ".join(str(doc.get(k) or "") for k in ("description", "description_short"))
        hit = _FRAME_CLAIM_RE.search(copy)
        if not hit:
            continue
        sync = doc.get("sync")
        worst = sync.get("maximum_alignment_error_ms") if isinstance(sync, dict) else None
        if not isinstance(worst, (int, float)):
            continue
        fps = doc.get("fps")
        try:
            frame_ms = 1000.0 / float(fps)
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if float(worst) > frame_ms:
            bad.append(f"{cid}: claims {hit.group(0)!r} but measures "
                       f"{float(worst):.2f} ms against a {frame_ms:.2f} ms frame")
    return Row("clip copy does not overstate measured sync", "FAIL" if bad else "PASS",
               "; ".join(bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else ""))


def _ne(a: Any, b: Any) -> bool:
    """Compare, tolerating float rounding in `hours`."""
    if isinstance(a, float) or isinstance(b, float):
        return a is None or b is None or abs(float(a) - float(b)) > 1e-6
    return a != b


def _sidecar_rows(details: dict[str, dict], out_dir: Path) -> list[Row]:
    """A sidecar whose length is not n_readings * stride_bytes is a corrupt download."""
    bad = []
    for cid, doc in details.items():
        peak = (doc.get("tactile_preview") or {}).get("peak_series")
        for side in (b.get("sidecar") for b in (doc.get("imu_preview"), peak) if b):
            if not side:
                continue
            path, want = out_dir / side["url"], side["n_readings"] * side["stride_bytes"]
            if not path.is_file():
                bad.append(f"{cid}: {side['url']} missing")
            elif path.stat().st_size != want:
                bad.append(f"{cid}: {side['url']} is {path.stat().st_size} B, want {want} B")
    return [Row("f32 sidecars are n_readings * stride_bytes", "FAIL" if bad else "PASS",
                ", ".join(bad[:4]))]


def _sync_rows(details: dict[str, dict]) -> list[Row]:
    """H1 arithmetic: the headline may not be smaller than a bound derivable from the record.

    A buyer WILL do this subtraction -- it is two fields and a multiplication -- and a
    headline that loses it is a fit residual wearing an alignment error's name. So the
    build does it first and refuses to ship a bundle that fails it.
    """
    bad: list[str] = []
    for cid, doc in sorted(details.items()):
        sync = doc.get("sync")
        if not isinstance(sync, dict):
            continue
        top = sync.get("maximum_alignment_error_ms")
        bounds: list[tuple[str, float]] = []
        for row in sync.get("streams") or []:
            if isinstance(row.get("maximum_alignment_error_ms"), (int, float)):
                bounds.append((f"streams[{row.get('stream_id')}]",
                               float(row["maximum_alignment_error_ms"])))
            implied = drift_implied_ms(row.get("estimated_drift_ppm"), doc.get("duration_s"))
            if implied is not None:
                bounds.append((f"{row.get('stream_id')} drift over duration_s", implied))
        # The bound is the fit STANDARD ERROR, not the max anchor residual. The residual is
        # deliberately NOT a bound here: it is the per-anchor arrival jitter the fit
        # averages out, it is legitimately an order of magnitude larger than the alignment,
        # and requiring the headline to exceed it is what forced this corpus to publish a
        # 34 ms figure for data aligned to about 3. It still ships, beside the SE and
        # labelled as jitter, and `sync.notes` says which is which.
        if isinstance(sync.get("clock_fit_se_worst_ms"), (int, float)):
            bounds.append(("clock_fit_se_worst_ms", float(sync["clock_fit_se_worst_ms"])))
        # Both sides are published to millisecond thousandths, so the comparison is made
        # at that precision: a 4e-4 ms rounding artefact is not an H1 violation.
        for label, value in bounds:
            if top is None or round(float(top), 3) < round(value, 3):
                bad.append(f"{cid}: maximum_alignment_error_ms={top!r} < {label}={value:.3f} ms")
    return [Row("max alignment error >= every bound derivable from the record",
                "FAIL" if bad else "PASS", "; ".join(bad[:4]))]


def _split_rows(manifest: dict, details: dict[str, dict]) -> list[Row]:
    """H10: the published normalisation constants must be train-scoped, and re-derivable.

    A constant fitted over the whole collection leaks test statistics into training. The
    scope is a claim like any other, so it is recomputed here from the clips the manifest
    itself assigns to train, and a mismatch fails the build.
    """
    splits = ((manifest.get("collection") or {}).get("splits")) or None
    if not splits:
        return [Row("split normalisation constants are train-scoped", "WARN",
                    "no split published: every buyer will invent their own")]
    norm = splits.get("normalization")
    if not norm:
        return [Row("split normalisation constants are train-scoped", "WARN",
                    "no normalisation constants published")]
    train = [c for c in manifest.get("clips", []) if c.get("split") == "train"]
    fresh = normalization_from(train, details)
    bad = [f"{k}: {norm.get(k)!r} != {v!r}" for k, v in fresh.items() if _ne(norm.get(k), v)]
    if norm.get("scope") != "train":
        bad.append(f"scope is {norm.get('scope')!r}, not 'train'")
    return [Row("split normalisation constants are train-scoped",
                "FAIL" if bad else "PASS", "; ".join(bad[:4]))]


def normalization_from(clips: list[dict], details: dict[str, dict]) -> dict:
    """Recompute the published constants from a set of clips. One definition, two callers."""
    pedestals, scales = [], []
    for clip in clips:
        tp = (details.get(clip["id"]) or {}).get("tactile_preview") or {}
        if tp.get("pedestal_counts") is not None:
            pedestals.append(float(tp["pedestal_counts"]))
        if tp.get("ceiling_counts") is not None:
            scales.append(float(tp["ceiling_counts"]))
    return {
        "computed_from_clips": len(clips),
        "tactile_pedestal_counts": (round(sum(pedestals) / len(pedestals), 4)
                                    if pedestals else None),
        "tactile_scale_counts": max(scales) if scales else None,
    }


def render_table(rows: Iterable[Row]) -> str:
    """Fixed-width table; the status column is what a CI job greps for."""
    rows = list(rows)
    width = max((len(r.check) for r in rows), default=10)
    lines = [f"  {'CHECK'.ljust(width)}  STATUS  DETAIL", f"  {'-' * width}  ------  ------"]
    for r in rows:
        lines.append(f"  {r.check.ljust(width)}  {r.status:<6}  {r.detail[:96]}")
    return "\n".join(lines)


def render_report(manifest: dict, takes: list[dict], rows: Iterable[Row], *,
                  media_mode: str) -> str:
    """INGEST_REPORT.md -- the human half of the QA output.

    Deliberately free of a run timestamp: it carries the manifest's `generated_utc`
    instead, so a no-op rebuild produces byte-identical output and `_write_if_changed`
    really does write nothing.
    """
    col, clips = manifest.get("collection") or {}, {c["id"]: c for c in manifest.get("clips", [])}
    held = [t for t in takes if t.get("quarantined")]
    failed = [t for t in takes if not t["ok"] and not t.get("quarantined")]
    warned = sum(len(t["warnings"]) for t in takes)
    out = [f"# Ingest report — {col.get('name', '?')} v{col.get('version', '?')}", "",
           f"- manifest generated: `{manifest.get('generated_utc')}`",
           f"- media mode: `{media_mode}`",
           f"- takes seen: **{len(takes)}**, in catalog: **{len(clips)}**, "
           f"quarantined by QA: **{len(held)}**, failed: **{len(failed)}**, "
           f"warnings: **{warned}**",
           "", "## Bundle validation", "", "| check | status | detail |", "|---|---|---|"]
    out += [f"| {r.check} | **{r.status}** | {r.detail[:120] or '—'} |" for r in rows]
    out += ["", "## Clips", "", "| clip | grade | duration | modalities | hands | warns |",
            "|---|---|---|---|---|---|"]
    for t in sorted(takes, key=lambda x: x["clip_id"]):
        if (c := clips.get(t["clip_id"])) is not None:
            out.append(f"| `{c['id']}` | {c['qa']['grade']} | {c['duration_s']:.1f}s | "
                       f"{', '.join(c['modalities']) or '—'} | {', '.join(c['hands']) or '—'} | "
                       f"{len(t['warnings'])} |")
    if held:
        out += ["", "## Quarantined by QA (absent from the catalog)", "",
                "The acceptance rule refused these. That is the rule working, not the ingest "
                "breaking, so they do not set the exit code — but nothing here reaches a buyer.",
                ""]
        out += [f"- `{t['take_dir']}` — {t['quarantined']}" for t in held]
    if failed:
        out += ["", "## Failed takes (absent from the catalog)", ""]
        out += [f"- `{t['take_dir']}` — {t['error']}" for t in failed]
    for key, head, gloss in (
            ("notes", "ffprobe vs metadata.json",
             "The measurement is used; the claim is recorded here."),
            ("warnings", "Warnings",
             "Every one renders as an em-dash or a fail-closed value in front of a buyer.")):
        if items := [(t["clip_id"], x) for t in takes for x in t[key]]:
            out += ["", f"## {head}", "", gloss, ""] + [f"- `{c}` — {x}" for c, x in items]
    return "\n".join(out) + "\n"
