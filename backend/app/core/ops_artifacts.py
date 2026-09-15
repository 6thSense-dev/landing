"""Required multimodal outputs for new Clean results; legacy ledgers stay readable."""
import math
import re

SCHEMA = "6thsense-clean-qc/2"
PROFILE = "stereo-imu-frames/1"
REQUIREMENT = {"schema": SCHEMA, "profile": PROFILE,
               "required_roles": ["left_video", "right_video", "left_frames", "right_frames", "imu", "frame_index", "timeline", "calibration"]}
ROLE_EXTENSIONS = {"left_video": ".mp4", "right_video": ".mp4", "left_frames": ".tar",
                   "right_frames": ".tar", "imu": ".csv", "frame_index": ".csv",
                   "timeline": ".json", "calibration": ".json", "joined_preview": ".mp4"}


def _count(value):
    return type(value) is int and value > 0


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_artifacts(doc, *, require_calibration=True):
    """Validate inventory and timeline claims; S3 verifies every pinned output next.

    The trusted worker must fully decode videos and check actual frame/IMU coverage.
    This validator cannot infer the contents of a CSV or TAR from its S3 metadata.
    """
    if doc.get("schema") != SCHEMA:
        raise ValueError("New processing requires left/right video, full frames, IMU and their timeline (QC v2)")
    recordings = {r["recording"]: r for r in doc["recordings"]}
    if not any(i["disposition"] == "keep" for r in recordings.values() for i in r["intervals"]) and doc.get("outputs"):
        raise ValueError("Fully rejected results cannot publish retained media")
    for output in doc.get("outputs", []):
        role = output.get("role")
        if role not in ROLE_EXTENSIONS or not output["key"].endswith(ROLE_EXTENSIONS[role]):
            raise ValueError("Unknown artifact role or format")
        if role != "joined_preview" and output.get("recording") not in recordings:
            raise ValueError("Artifact must identify its source recording")
    for name, rec in recordings.items():
        if any(not _count(s.get("size_bytes")) for s in rec.get("sources", [])):
            raise ValueError("Source byte sizes are required for exact Raw receipt reconciliation")
        keep = [i for i in rec["intervals"] if i["disposition"] == "keep"]
        outputs = [o for o in doc.get("outputs", []) if o.get("recording") == name and o.get("role") != "joined_preview"]
        if not keep:
            if outputs:
                raise ValueError("Fully rejected footage cannot have retained artifacts")
            continue
        media = rec.get("media", {})
        if media.get("profile") != PROFILE or media.get("clock") != "sensor_us":
            raise ValueError("Required stereo/IMU/frame profile or measured sensor clock is missing")
        total, count, samples = (media.get(k) for k in ("source_frame_count", "retained_frame_count", "imu_samples"))
        if not all(_count(v) for v in (total, count, samples)) or count > total:
            raise ValueError("Invalid source, retained-frame or IMU counts")
        if media.get("imu_units") != {"acceleration": "m/s^2", "angular_velocity": "deg/s"}:
            raise ValueError("IMU units must be explicit")
        layout = media.get("layout", {})
        if not layout.get("provenance") or type(layout.get("rotation_degrees")) is not int or layout["rotation_degrees"] not in (0, 180):
            raise ValueError("Declared eye order/orientation provenance is required")
        w, h = layout.get("width"), layout.get("height")
        if not _count(w) or not _count(h):
            raise ValueError("Invalid declared source dimensions")
        crops = []
        for eye in ("left", "right"):
            crop = layout.get(eye)
            if not isinstance(crop, list) or len(crop) != 4 or any(type(v) is not int for v in crop):
                raise ValueError("An explicit crop for each eye is required")
            x, y, ew, eh = crop
            if min(x, y) < 0 or min(ew, eh) <= 0 or ew % 2 or eh % 2 or x+ew > w or y+eh > h:
                raise ValueError("Invalid eye crop")
            crops.append(crop)
        a, b = crops
        if a[2:] != b[2:] or (max(a[0], b[0]) < min(a[0]+a[2], b[0]+b[2]) and max(a[1], b[1]) < min(a[1]+a[3], b[1]+b[3])):
            raise ValueError("Eye crops overlap or have different dimensions")
        calibrations = [o for o in outputs if o.get("role") == "calibration"]
        if require_calibration or calibrations or media.get("calibration") or rec.get("calibration_source"):
            if len(calibrations) != 1:
                raise ValueError("Exactly one calibration artifact is required per retained recording")
            calibration, source = media.get("calibration", {}), rec.get("calibration_source", {})
            digest = calibration.get("sha256", "")
            if not re.fullmatch(r"[a-f0-9]{64}", digest) or digest != calibrations[0].get("sha256") or digest != source.get("sha256"):
                raise ValueError("Calibration source, artifact and timeline hashes must agree")
            if source.get("version_id") in (None, "", "null") or source.get("bucket") not in ("6thsense-raw", "6thsense-deploy-artifacts") or not source.get("key"):
                raise ValueError("Version-pinned calibration source is required")
            if calibration.get("device_id") != name.rsplit("_", 1)[-1].upper() or calibration.get("image_size") != a[2:]:
                raise ValueError("Calibration camera/resolution disagrees with this recording")
            if calibration.get("coordinate_frame") != "native_unrotated_eye_pixels" or calibration.get("output_rotation_degrees") != layout["rotation_degrees"] or set(calibration.get("eye_mapping", {})) != {"left", "right"} or set(calibration["eye_mapping"].values()) != {"cam0", "cam1"}:
                raise ValueError("Explicit calibration pixel coordinates and eye mapping are required")
        origin = media.get("sensor_origin_us")
        segments = media.get("segments", [])
        if type(origin) is not int or origin < 0 or len(segments) != len(keep):
            raise ValueError("Every retained interval needs its measured frame/IMU mapping")
        clean_end = n = previous_source = 0
        for segment_id, (seg, interval) in enumerate(zip(segments, keep)):
            fields = [seg.get(k) for k in ("segment_id", "source_frame_start", "source_frame_end", "sensor_start_us", "sensor_end_us", "clean_start_us", "clean_end_us")]
            if any(type(v) is not int or v < 0 for v in fields):
                raise ValueError("Invalid segment time/frame mapping")
            sid, first, last, start, end, cs, ce = fields
            if sid != segment_id or first < previous_source or not first < last <= total or start >= end or cs != clean_end or ce-cs != end-start:
                raise ValueError("Overlapping/inconsistent retained segments")
            if abs((start-origin)/1e6-interval["start_s"]) > .000002 or abs((end-origin)/1e6-interval["end_s"]) > .000002:
                raise ValueError("Artifacts must use exactly the accepted QC intervals")
            n += last-first
            previous_source, clean_end = last, ce
        seconds = sum(i["end_s"]-i["start_s"] for i in keep)
        if n != count or abs(clean_end/1e6-seconds) > .000002:
            raise ValueError("Frame/timeline counts disagree with retained time")
        if not _number(media.get("retained_seconds")) or abs(media["retained_seconds"]-seconds) > .000002 or not _number(media.get("source_seconds")) or abs(media["source_seconds"]-rec["source_seconds"]) > .000002:
            raise ValueError("Media duration disagrees with the QC ledger")
        if not _count(media.get("last_frame_duration_us")) or media["last_frame_duration_us"] > 100_000 or not media.get("last_frame_duration_basis"):
            raise ValueError("Final frame duration provenance is required")
        by_role = {role: [o for o in outputs if o.get("role") == role] for role in REQUIREMENT["required_roles"]}
        for role in ("left_video", "right_video", "frame_index", "imu", "timeline"):
            if len(by_role[role]) != 1:
                raise ValueError(f"Exactly one {role} artifact is required per retained recording")
        for role in ("left_video", "right_video", "frame_index"):
            if type(by_role[role][0].get("frame_count")) is not int or by_role[role][0]["frame_count"] != count:
                raise ValueError("Video and frame-index counts must match")
        if type(by_role["imu"][0].get("sample_count")) is not int or by_role["imu"][0]["sample_count"] != samples:
            raise ValueError("IMU sample count mismatch")
        for role in ("left_frames", "right_frames"):
            cursor = 0
            for shard in sorted(by_role[role], key=lambda o: o.get("start_frame", -1)):
                if type(shard.get("start_frame")) is not int or shard["start_frame"] != cursor or not _count(shard.get("frame_count")):
                    raise ValueError("Frame shards must cover every retained frame without gaps or duplicates")
                cursor += shard["frame_count"]
            if cursor != count:
                raise ValueError("Both full frame sequences are required")


def artifact_status(doc):
    if doc.get("schema") != SCHEMA:
        return "legacy_video_only"
    try:
        validate_artifacts(doc)
    except (ValueError, TypeError, KeyError):
        return "incomplete"
    return "complete"
