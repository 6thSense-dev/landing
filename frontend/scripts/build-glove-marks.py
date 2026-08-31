#!/usr/bin/env python3
"""
Build the MARKS MAP for the new glove mesh (public/models/glove-holo).

The Tripo mesh ships one 4096² basecolor. Two product features are baked into
it but read badly once you drop the colour — which the holographic and matte
looks both do:

  * the anti-slip pad: the field of dark triradiate "Y" grips on the palm and
    finger undersides (see the reference photo — white glove, black grips);
  * the fiducial on the back of the wrist, which Tripo hallucinated as a blobby
    non-grid glyph rather than a real, detectable AprilTag.

This writes ONE extra texture, glove-marks.png, sharing the basecolor's UVs:

    R  anti-slip grip mask   1 where the baked Y-pattern is
    G  AprilTag luminance    0 = black cell, 1 = white cell (0 outside the tag)
    B  AprilTag quad mask    1 inside the tag square
    A  glove-fabric mask     1 on white glove shell, 0 on cuff / strap / forearm

Tripo only painted grips on the palm block, but the real glove carries them down
every finger (reference photo). The viewer therefore SYNTHESISES the missing
grips as a procedural triradiate lattice projected along the palm normal, and A
is what keeps that lattice on the glove instead of running over the cuff, the
wrist strap and the bare forearm. R stays the source of truth wherever Tripo did
paint grips, so the palm keeps the real baked pattern and only the gaps are
filled.

The viewer composites those over whatever body colour a look uses, so the same
asset serves the textured, holographic and matte renders and the basecolor is
left untouched (turn the marks off and you are back to the mesh as delivered).

R is a morphological TOP-HAT, not a darkness threshold and not a blur
difference. The grips are small dark marks on a light substrate; the cuff, the
wrist strap and the forearm are large dark or mid regions. A plain threshold
keeps all of them, and blur-difference keeps a bright halo around every panel
edge (tried, rejected — the whole glove lit up with outlines). Grey opening with
a structuring element wider than a grip mark erases the grips but preserves the
panels, so subtracting it leaves exactly the grips.

Needs numpy, scipy, opencv-python, Pillow. Run from anywhere:
    python3 frontend/scripts/build-glove-marks.py [--preview]
"""

import argparse
import pathlib
import sys

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage

Image.MAX_IMAGE_PIXELS = None

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "glove-holo"
BASECOLOR = MODEL_DIR / "glove+3d+model.fbm" / "glove+3d+model_basecolor.jpg"
OUT = MODEL_DIR / "glove-marks.png"

# Output resolution. The grips are ~30px across in the 4096² atlas, so half
# resolution still resolves them; the mask is computed at full res and area-
# averaged down, which anti-aliases it rather than dropping detail.
OUT_SIZE = 2048

# AprilTag family + id stamped on the wrist. 36h11 is the usual choice for
# robot-hand pose tracking, which is what this marker is for.
TAG_ID = 0
TAG_CELL_PX = 64  # render resolution per cell before it is warped into place

# Grip-mask tuning, in 0-255 luminance units on the 4096² atlas.
# TOPHAT_SE must be wider than a grip mark (~20-35px) and narrower than any
# panel we want to keep out. 49 was picked by inspection; 71 starts letting the
# seam and cuff edges back in, 33 starts eating the fatter grips.
TOPHAT_SE = 49
TOPHAT_LO, TOPHAT_HI = 45.0, 120.0        # top-hat response that counts as a grip
BLUR_SIGMA = 26.0                          # substrate estimate, for the gate below
SUBSTRATE_LO, SUBSTRATE_HI = 62.0, 120.0  # ignore marks on an already-dark panel

# Glove-fabric gate (channel A). Measured off the atlas: white shell is bright
# and near-neutral (~235,233,228 -> chroma 7), bare forearm is bright but warm
# (~200,160,130 -> chroma 70), cuff and strap are simply dark. Both tests run on
# a BLURRED copy so the grips themselves do not punch holes in their own mask.
FABRIC_LUM_LO, FABRIC_LUM_HI = 118.0, 165.0
FABRIC_CHROMA_LO, FABRIC_CHROMA_HI = 46.0, 22.0  # inverted: less chroma = more fabric


def luminance(rgb: np.ndarray) -> np.ndarray:
    return rgb @ np.array([0.2126, 0.7152, 0.0722], np.float32)


def smoothstep(x: np.ndarray, a: float, b: float) -> np.ndarray:
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def find_tag_quad(lum: np.ndarray) -> tuple[float, float, float, float]:
    """Locate the baked fiducial and return its OUTER 10-cell square.

    The printed patch is a white quiet zone around a black-bordered data field.
    The black field is the reliable thing to find (one big dark blob ringed by
    white), so detect that and step out one cell on every side: a 36h11 tag is
    6 data cells + a 1-cell black border + a 1-cell white quiet zone = 10.
    """
    # Search window around the wrist module. Generous, but tight enough that the
    # white glove body elsewhere in the atlas cannot win the "biggest blob" vote.
    cx, cy, r = 2150, 1053, 240
    win = lum[cy - r : cy + r, cx - r : cx + r]

    lab, n = ndimage.label(win < 95)
    if n == 0:
        raise SystemExit("no dark blob near the expected fiducial location")
    best = None
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if len(ys) < 8000:
            continue
        d = np.hypot(ys.mean() - r, xs.mean() - r)
        if best is None or d < best[0]:
            best = (d, (xs.min(), ys.min(), xs.max(), ys.max()))
    if best is None:
        raise SystemExit("fiducial's black field not found — retune the window")

    ix0, iy0, ix1, iy1 = (float(v) for v in best[1])
    # The black field spans the border cell + 6 data cells + border cell = 8.
    cell_x = (ix1 - ix0) / 8.0
    cell_y = (iy1 - iy0) / 8.0
    return (
        cx - r + ix0 - cell_x,
        cy - r + iy0 - cell_y,
        cx - r + ix1 + cell_x,
        cy - r + iy1 + cell_y,
    )


def render_tag(px: int) -> np.ndarray:
    """A real, detectable tag36h11 as a 10x10-cell greyscale image."""
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36h11)
    core = cv2.aruco.generateImageMarker(d, TAG_ID, 8 * px, borderBits=1)
    tag = np.full((10 * px, 10 * px), 255, np.uint8)
    tag[px : 9 * px, px : 9 * px] = core

    # Round-trip it: a marker we cannot detect is a decoration, not a fiducial.
    det = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(tag)
    if ids is None or TAG_ID not in ids.flatten():
        raise SystemExit("generated tag did not round-trip through the detector")
    print(f"  tag36h11 id={TAG_ID} verified by the detector")
    return tag


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true", help="also write /tmp previews")
    args = ap.parse_args()

    if not BASECOLOR.exists():
        raise SystemExit(f"basecolor not found: {BASECOLOR}")

    rgb = np.asarray(Image.open(BASECOLOR).convert("RGB"), dtype=np.float32)
    h, w, _ = rgb.shape
    print(f"basecolor {w}x{h}")
    lum = luminance(rgb)

    # ---- R: anti-slip grip pad ------------------------------------------
    inv = 255.0 - lum
    tophat = inv - ndimage.grey_opening(inv, size=(TOPHAT_SE, TOPHAT_SE))
    grip = smoothstep(tophat, TOPHAT_LO, TOPHAT_HI)
    # A dark panel's own noise is not a printed grip.
    grip *= smoothstep(ndimage.gaussian_filter(lum, BLUR_SIGMA),
                       SUBSTRATE_LO, SUBSTRATE_HI)

    # ---- G/B: the fiducial ----------------------------------------------
    x0, y0, x1, y1 = find_tag_quad(lum)
    print(f"  fiducial quad {x0:.0f},{y0:.0f} -> {x1:.0f},{y1:.0f}")
    tag = render_tag(TAG_CELL_PX)
    tw, th = int(round(x1 - x0)), int(round(y1 - y0))
    tag_fit = cv2.resize(tag, (tw, th), interpolation=cv2.INTER_AREA)

    tag_lum = np.zeros((h, w), np.float32)
    tag_mask = np.zeros((h, w), np.float32)
    ix, iy = int(round(x0)), int(round(y0))
    tag_lum[iy : iy + th, ix : ix + tw] = tag_fit.astype(np.float32) / 255.0
    tag_mask[iy : iy + th, ix : ix + tw] = 1.0
    # Soften the quad edge by a texel or two so the decal does not alias.
    tag_mask = ndimage.gaussian_filter(tag_mask, 1.5)
    # The grip mask must not fight the decal for the same texels.
    grip *= 1.0 - np.clip(tag_mask * 1.6, 0.0, 1.0)

    # ---- A: where a synthesised grip is allowed to land -------------------
    blurred = ndimage.gaussian_filter(rgb, (BLUR_SIGMA, BLUR_SIGMA, 0))
    chroma = blurred.max(axis=2) - blurred.min(axis=2)
    fabric = smoothstep(luminance(blurred), FABRIC_LUM_LO, FABRIC_LUM_HI)
    fabric *= smoothstep(chroma, FABRIC_CHROMA_LO, FABRIC_CHROMA_HI)
    # Deliberately NOT punched out over the fiducial: alpha 0 there would let
    # any premultiplying step downstream wipe the tag out of G/B. The shader
    # excludes the quad from the synthesised grips instead, via (1 - B).

    out = np.stack([grip, tag_lum, tag_mask, fabric], axis=-1)
    out = np.clip(out, 0.0, 1.0)

    # Resize CHANNEL BY CHANNEL. Pillow >= 10 premultiplies when it resizes an
    # RGBA image, which silently zeroes RGB everywhere alpha is 0 — that quietly
    # deleted the fiducial from G/B the first time round. These are four
    # independent masks, not a colour with transparency, so they must not be
    # treated as one.
    bands = [
        Image.fromarray((out[..., i] * 255).astype(np.uint8), "L") for i in range(4)
    ]
    if OUT_SIZE != w:
        bands = [b.resize((OUT_SIZE, OUT_SIZE), Image.LANCZOS) for b in bands]
    img = Image.merge("RGBA", bands)
    img.save(OUT, optimize=True)

    # Round-trip guard: if the fiducial cannot survive the write, everything
    # downstream is drawing a blank square and no one notices.
    back = np.asarray(Image.open(OUT))
    if back[..., 2].max() < 250 or back[..., 1].max() < 250:
        raise SystemExit(
            f"fiducial did not survive the encode (G max {back[..., 1].max()}, "
            f"B max {back[..., 2].max()}; both should reach 255)"
        )
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB, {OUT_SIZE}²) — tag intact")

    if args.preview:
        Image.fromarray((grip * 255).astype(np.uint8)).resize((1400, 1400)).save(
            "/tmp/marks-grip.png"
        )
        Image.fromarray((fabric * 255).astype(np.uint8)).resize((1400, 1400)).save(
            "/tmp/marks-fabric.png"
        )
        pad = 60
        Image.fromarray(
            (out[iy - pad : iy + th + pad, ix - pad : ix + tw + pad] * 255).astype(
                np.uint8
            ),
            "RGB",
        ).save("/tmp/marks-tag.png")
        print("previews: /tmp/marks-grip.png /tmp/marks-fabric.png /tmp/marks-tag.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
