"""Validate native per-camera stereo calibration without claiming capture sync QA."""
import math
import re


def validate_calibration(data, recording, layout=None):
    """Return the explicit native-to-output mapping; never borrow another rig's solve.

    Calibration stays in native, unrotated per-eye pixel coordinates. Consumers
    must apply output_rotation_degrees when interpreting rotated output pixels.
    Structural checks do not certify reprojection accuracy or physical sync.
    """
    camera = recording.rsplit("_", 1)[-1].upper()
    if not re.fullmatch(r"ego_\d{8}_\d{6}_[A-Fa-f0-9]{6}", recording) or not isinstance(data, dict):
        raise ValueError("Invalid calibration/source camera")
    if data.get("schema") != "opencv-stereo" or data.get("device_id", "").upper() != camera:
        raise ValueError("Calibration must identify the recording's actual camera")
    binding = data.get("binding", {})
    if binding and binding.get("camera_device_id", "").upper() != camera:
        raise ValueError("Calibration module binding disagrees with the camera")
    size = data.get("image_size")
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or v <= 0 for v in size):
        raise ValueError("Calibration requires native per-eye resolution")
    if data.get("distortion_model") != "kannala_brandt":
        raise ValueError("Unsupported calibration distortion model")

    def vector(value, n):
        return isinstance(value, list) and len(value) == n and all(type(x) in (int, float) and math.isfinite(x) for x in value)

    def matrix(value):
        return isinstance(value, list) and len(value) == 3 and all(vector(row, 3) for row in value)

    mapping = {}
    for sensor in ("cam0", "cam1"):
        eye = data.get(sensor, {})
        k = eye.get("K")
        if not matrix(k) or k[0][0] <= 0 or k[1][1] <= 0 or k[0][1] != 0 or k[1][0] != 0 or k[2] != [0, 0, 1]:
            raise ValueError("Calibration has invalid camera intrinsics")
        if not 0 <= k[0][2] < size[0] or not 0 <= k[1][2] < size[1] or not vector(eye.get("dist"), 4):
            raise ValueError("Calibration intrinsics/distortion disagree with image size")
        side = eye.get("position")
        if side not in ("left", "right") or side in mapping:
            raise ValueError("Calibration must distinguish both physical eyes")
        crop = data.get("eye_crop_x", {}).get(sensor)
        if not isinstance(crop, list) or len(crop) != 2 or any(type(x) is not int for x in crop) or crop[0] < 0 or crop[1] - crop[0] != size[0]:
            raise ValueError("Calibration needs explicit native sensor crops")
        if layout is not None and layout.get(side) != [crop[0], 0, *size]:
            raise ValueError("Calibration does not match extraction eye order/crop/resolution")
        mapping[side] = sensor
    ranges = list(data["eye_crop_x"][s] for s in ("cam0", "cam1"))
    if max(ranges[0][0], ranges[1][0]) < min(ranges[0][1], ranges[1][1]):
        raise ValueError("Calibration sensor crops overlap")
    stereo = data.get("stereo", {})
    r, t, baseline = stereo.get("R"), stereo.get("T"), stereo.get("baseline_m")
    if not matrix(r) or not vector(t, 3) or type(baseline) not in (int, float) or not math.isfinite(baseline) or baseline <= 0:
        raise ValueError("Calibration requires finite stereo R/T and baseline in metres")
    if abs(math.sqrt(sum(x*x for x in t)) - baseline) > max(1e-6, baseline * .01):
        raise ValueError("Calibration baseline disagrees with stereo translation")
    det = sum(r[0][i] * (r[1][(i+1)%3]*r[2][(i+2)%3] - r[1][(i+2)%3]*r[2][(i+1)%3]) for i in range(3))
    if abs(det-1) > .01 or any(abs(sum(r[i][k]*r[j][k] for k in range(3))-(i == j)) > .01 for i in range(3) for j in range(3)):
        raise ValueError("Calibration stereo rotation is not a proper rotation")
    rotation = layout.get("rotation_degrees") if layout is not None else 0
    if type(rotation) is not int or rotation not in (0, 180):
        raise ValueError("Unsupported output rotation")
    if layout is not None and (layout.get("height") != size[1] or layout.get("width") != max(v[1] for v in ranges)):
        raise ValueError("Calibration native frame dimensions disagree with extraction")
    return dict(device_id=camera, image_size=size, eye_mapping=mapping,
                coordinate_frame="native_unrotated_eye_pixels", output_rotation_degrees=rotation)
