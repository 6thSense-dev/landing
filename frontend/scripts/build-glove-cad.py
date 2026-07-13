#!/usr/bin/env python3
"""Generate the Hand + Nerve glove turntable meshes for /products.

These replace the AI-generated product images (public/hand-studio.png,
public/nerve-concept.png) with an honest CAD turntable of the REAL product: a
black textile glove worn on a human hand, with the 3D-printed "6thSense" sensor
module on the back of the wrist (see public/hand.jpg for the reference unit).

Unlike the Skin turntable — which is the robotic dexterous hand (public/
dexterous-hand.glb) — the Hand and Nerve are worn on human fingers, so the base
geometry here is the MANO human-hand template mesh (778 verts, mean pose: a
naturally relaxed, slightly-spread open right hand). We soften the bare-hand
tendon/knuckle detail and inflate slightly along the normals so it reads as a
soft fabric glove rather than an anatomy model.

Outputs (written to frontend/public/):
  glove-hand.glb   glove + wrist module               (the Hand, 01)
  glove-nerve.glb  glove + wrist module + 15 sensors  (the Nerve, 02)

The nerve sensors are a SEPARATE mesh named "sensors" so the frontend
(GloveTurntable.jsx) can pull them out and drive an emissive/pulse material —
the "one glove, two states" story: the Hand glove upgraded to Nerve.

MANO source: the mean-template mesh only (no identity/pose blendshapes are
used), loaded straight from the .pkl with a chumpy/scipy-sparse-bypassing
Unpickler. Point --mano at your MANO_RIGHT.pkl (or set MANO_RIGHT env var).

Run (needs numpy + trimesh):
    python3 frontend/scripts/build-glove-cad.py
"""
from __future__ import annotations

import argparse
import os
import pickle
from pathlib import Path

import numpy as np
import trimesh

# Default location of the MANO model on this machine (the postprocess repo).
_DEFAULT_MANO = Path(
    os.environ.get(
        "MANO_RIGHT",
        "/Users/alexnoh/Desktop/6thSense/postprocess/data/mano_v1_2/models/MANO_RIGHT.pkl",
    )
)
_OUT_DIR = Path(__file__).resolve().parents[1] / "public"


# ---------------------------------------------------------------------------
# MANO loading (self-contained: no postprocess import needed)
# ---------------------------------------------------------------------------
class _StandIn:
    """Absorbs chumpy / scipy.sparse pickle state we don't need."""

    def __setstate__(self, state):
        if isinstance(state, dict):
            self.__dict__.update(state)


class _Unpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if module.startswith("chumpy") or module.startswith("scipy.sparse"):
            return _StandIn
        return super().find_class(module, name)


def load_mano(pkl: Path):
    """Return (v_template Nx3, faces Mx3, J 16x3) as float/int numpy arrays."""
    with open(pkl, "rb") as fh:
        raw = _Unpickler(fh, encoding="latin1").load()
    v = np.asarray(raw["v_template"], dtype=np.float64).reshape(-1, 3)
    f = np.asarray(raw["f"], dtype=np.int64).reshape(-1, 3)
    j = np.asarray(raw["J"], dtype=np.float64).reshape(-1, 3)
    return v, f, j


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------
# MANO right-hand template frame (see postprocess uv_unwrap.py):
#   wrist at +X, fingers extend toward -X, palm thickness along Y,
#   palmar normal ~ -Y (so the DORSAL / back-of-hand side is +Y),
#   Z is the across-fingers axis.
DORSAL = np.array([0.0, 1.0, 0.0])

# MANO joint order: 0 wrist; 1-3 index; 4-6 middle; 7-9 pinky; 10-12 ring;
# 13-15 thumb. The four finger MCPs (knuckles) we average for the palm centre.
MCP_JOINTS = [1, 4, 10, 7]

# Present the hand fingers-UP, back-of-hand toward the viewer, so it spins like
# a display piece around the vertical axis. Maps the MANO template frame to a
# three.js-friendly frame (+Y up, +Z toward camera, +X right):
#   fingertip dir (MANO -X) -> +Y (up)
#   dorsal      (MANO +Y) -> +Z (toward viewer)
#   MANO +Z              -> +X (right)
_R = np.array(
    [
        [0.0, 0.0, 1.0],
        [-1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
)


def soften_glove(mesh: trimesh.Trimesh, iters: int = 6, inflate: float = 0.0032):
    """Smooth away bare-hand tendon detail, then puff along normals (fabric)."""
    trimesh.smoothing.filter_taubin(mesh, iterations=iters)
    mesh.vertices += mesh.vertex_normals * inflate
    return mesh


def sphere_at(center, radius, count=1):
    s = trimesh.creation.icosphere(subdivisions=2, radius=radius)
    s.apply_translation(center)
    return s


def rounded_module(x_len, y_thick, z_wid, segments=3):
    """A rounded rectangular puck (the 3D-printed 6thSense wrist module).

    Axes match the MANO template frame: X = along the hand (wrist->fingers),
    Y = dorsal thickness (the THIN dimension, so the puck lies FLAT on the back
    of the hand), Z = across the hand.
    """
    box = trimesh.creation.box(extents=(x_len, y_thick, z_wid))
    # Subdivide so the corners have vertices to fillet, then Taubin-smooth to
    # bevel the hard edges — reads as a printed, filleted part, not a raw cube.
    for _ in range(segments):
        box = box.subdivide()
    trimesh.smoothing.filter_taubin(box, iterations=6)
    return box


def make_logo_decal(src_png: Path, out_png: Path, tint=(232, 232, 232)):
    """Turn the alpha logo into a light decal PNG (tinted RGB, cropped to the
    mark) that reads on the dark module. Returns the content aspect (w / h)."""
    from PIL import Image

    im = Image.open(src_png).convert("RGBA")
    a = np.array(im)
    alpha = a[..., 3]
    ys, xs = np.where(alpha > 20)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    crop = a[y0 : y1 + 1, x0 : x1 + 1]
    out = crop.copy()
    out[..., 0], out[..., 1], out[..., 2] = tint  # recolor to a light grey
    Image.fromarray(out, "RGBA").save(out_png)
    h, w = crop.shape[0], crop.shape[1]
    return w / h


def logo_quad(center_xyz, top_y, x_len, z_wid):
    """A flat quad just above the module top, UV-mapped so the (upright) decal
    PNG shows unmirrored on the DORSAL face.

    Frame: quad spans MANO X (hand length) and Z (across). After the _R
    reorient the viewer sees the dorsal face with world_x = MANO z (screen right)
    and world_y = -MANO x (screen up). UVs are chosen so U -> screen-right and
    V -> screen-up, and the winding gives a +Y (dorsal-outward) normal — so the
    PNG paints exactly as authored. Any tweak is a rotation of the PNG itself,
    not blind UV math.
    """
    cx, _, cz = center_xyz
    hx, hz = x_len / 2, z_wid / 2
    y = top_y + 0.0004
    # verts: 0=(x-,z-) 1=(x+,z-) 2=(x+,z+) 3=(x-,z+)
    verts = np.array(
        [
            [cx - hx, y, cz - hz],
            [cx + hx, y, cz - hz],
            [cx + hx, y, cz + hz],
            [cx - hx, y, cz + hz],
        ]
    )
    # winding -> +Y (dorsal-outward) normal
    faces = np.array([[0, 2, 1], [0, 3, 2]])
    # U along +MANO z (screen right); V=1 at -MANO x (screen up) -> upright.
    uv = np.array([[0, 1], [0, 0], [1, 0], [1, 1]], dtype=np.float64)
    mesh = trimesh.Trimesh(
        vertices=verts,
        faces=faces,
        visual=trimesh.visual.TextureVisuals(
            uv=uv, material=trimesh.visual.material.PBRMaterial()
        ),
        process=False,
    )
    return mesh


def dorsal_surface_y(verts, xz, radius):
    """Max Y (dorsal height) of glove verts within `radius` of point xz=(x,z)."""
    d = np.hypot(verts[:, 0] - xz[0], verts[:, 2] - xz[1])
    near = verts[d < radius]
    if len(near) == 0:
        near = verts[np.argsort(d)[:20]]
    return float(near[:, 1].max())


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------
def build(mano_pkl: Path, out_dir: Path):
    v, f, J = load_mano(mano_pkl)

    glove = trimesh.Trimesh(vertices=v.copy(), faces=f.copy(), process=False)
    glove = soften_glove(glove)

    # ---- wrist module: a flat puck lying on the back of the hand, over the
    # metacarpals toward the wrist (like the real unit in public/hand.jpg).
    palm_center = J[MCP_JOINTS].mean(axis=0)
    wrist = J[0]
    seat = 0.58 * wrist + 0.42 * palm_center
    x_len, y_thick, z_wid = 0.040, 0.011, 0.033  # THIN along Y -> lies flat
    module = rounded_module(x_len, y_thick, z_wid)
    surf_y = dorsal_surface_y(glove.vertices, (seat[0], seat[2]), radius=0.022)
    # Sit it low and part-embedded so it reads as attached, not floating.
    module.apply_translation([seat[0], surf_y + y_thick * 0.18, seat[2]])
    module.metadata["name"] = "module"
    module_top = float(module.vertices[:, 1].max())

    # ---- 6thSense logo decal on the module top (quad + processed texture).
    logo_aspect = make_logo_decal(
        Path(__file__).resolve().parents[1] / "public" / "logos" / "Logo_Alpha.png",
        out_dir / "glove-logo.png",
    )
    logo_zw = 0.026
    logo_xl = logo_zw / logo_aspect  # keep the mark's aspect ratio
    logo = logo_quad((seat[0], 0, seat[2]), module_top, logo_xl, logo_zw)
    logo.metadata["name"] = "logo"

    # ---- nerve sensors: a SMALL bump at each of the 15 finger joints. Sunk
    # deep into the glove so only a shallow cap protrudes (per feedback).
    sensor_meshes = []
    s_radius, s_sink = 0.0036, 0.0021  # ~1.5 mm cap proud of the surface
    for idx in range(1, 16):
        jx = J[idx]
        surf = dorsal_surface_y(glove.vertices, (jx[0], jx[2]), radius=0.009)
        sensor_meshes.append(
            sphere_at([jx[0], surf - s_sink, jx[2]], radius=s_radius)
        )
    sensors = trimesh.util.concatenate(sensor_meshes)
    sensors.metadata["name"] = "sensors"

    glove.metadata["name"] = "glove"

    # ---- reorient everything together (fingers up, back toward viewer)
    def reorient(m):
        m.vertices = m.vertices @ _R.T
        return m

    for m in (glove, module, logo, sensors):
        reorient(m)

    out_dir.mkdir(parents=True, exist_ok=True)

    # HAND: glove + module + logo
    hand_scene = trimesh.Scene()
    hand_scene.add_geometry(glove, geom_name="glove")
    hand_scene.add_geometry(module, geom_name="module")
    hand_scene.add_geometry(logo, geom_name="logo")
    hand_path = out_dir / "glove-hand.glb"
    hand_scene.export(hand_path)

    # NERVE: glove + module + logo + sensors
    nerve_scene = trimesh.Scene()
    nerve_scene.add_geometry(glove, geom_name="glove")
    nerve_scene.add_geometry(module, geom_name="module")
    nerve_scene.add_geometry(logo, geom_name="logo")
    nerve_scene.add_geometry(sensors, geom_name="sensors")
    nerve_path = out_dir / "glove-nerve.glb"
    nerve_scene.export(nerve_path)

    print(f"glove  : {len(glove.vertices)} v / {len(glove.faces)} f")
    print(f"module : {len(module.vertices)} v (+ logo decal)")
    print(f"sensors: 15 bumps, {len(sensors.vertices)} v")
    print(f"wrote  : {hand_path}")
    print(f"wrote  : {nerve_path}")
    return glove, module, logo, sensors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mano", type=Path, default=_DEFAULT_MANO)
    ap.add_argument("--out", type=Path, default=_OUT_DIR)
    ap.add_argument("--preview", action="store_true", help="write /tmp preview PNG")
    args = ap.parse_args()

    glove, module, logo, sensors = build(args.mano, args.out)

    if args.preview:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection

        # Emulate the three.js turntable: +Y up, warm key light, dark bg. Remap
        # data (x,y,z) -> plot (x, z, y) so matplotlib's vertical axis is +Y.
        remap = lambda P: P[:, [0, 2, 1]]
        keylight = np.array([0.5, 0.5, 1.0])
        keylight = keylight / np.linalg.norm(keylight)

        def shaded(ax, m, base_rgb, emissive=0.0, zorder=1):
            tri = remap(m.vertices)[m.faces]
            n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
            n /= (np.linalg.norm(n, axis=1, keepdims=True) + 1e-9)
            # warm key + cool ambient floor so the matte glove reads on black.
            lam = np.clip(n @ keylight, 0, 1)
            rim = np.clip(n @ np.array([-0.6, 0.2, -0.5]), 0, 1)
            shade = 0.42 + 0.7 * lam
            cols = np.clip(
                base_rgb[None, :] * shade[:, None]
                + np.array([0.94, 0.38, 0.16])[None, :] * (0.35 * rim[:, None])
                + emissive,
                0, 1,
            )
            pc = Poly3DCollection(tri, facecolors=cols, edgecolor="none", zorder=zorder)
            pc.set_zsort("max")
            ax.add_collection3d(pc)

        # Raised camera looking down at the back of the hand so the flat module,
        # logo decal and shallow sensor bumps sit clearly on top (draw order via
        # zorder; matplotlib painter-sort is unreliable for near-flush parts).
        fig = plt.figure(figsize=(12, 6), facecolor="#0a0a0a")
        parts = [
            (glove, np.array([0.30, 0.30, 0.31]), 0.0, 1),
            (module, np.array([0.13, 0.13, 0.14]), 0.0, 3),
            (logo, np.array([0.85, 0.85, 0.85]), 0.5, 5),
            (sensors, np.array([0.80, 0.80, 0.82]), 0.18, 4),
        ]
        for i, (title, az) in enumerate([("Nerve — back 3/4", 118), ("Module + logo (top-down)", 90)]):
            ax = fig.add_subplot(1, 2, i + 1, projection="3d")
            ax.set_facecolor("#0a0a0a")
            for m, col, emi, zo in parts:
                shaded(ax, m, col, emi, zorder=zo)
            if i == 0:
                allv = remap(np.vstack([glove.vertices, sensors.vertices]))
                c = allv.mean(0)
                r = np.abs(allv - c).max() * 0.92
                ax.view_init(elev=42, azim=az)
            else:  # zoom on the module/logo region
                allv = remap(module.vertices)
                c = allv.mean(0)
                r = 0.03
                ax.view_init(elev=78, azim=az)
            ax.set_xlim(c[0] - r, c[0] + r)
            ax.set_ylim(c[1] - r, c[1] + r)
            ax.set_zlim(c[2] - r, c[2] + r)
            ax.set_axis_off()
            ax.set_title(title, color="#f0612a")
            ax.set_box_aspect((1, 1, 1))
        plt.tight_layout()
        plt.savefig("/tmp/glove_preview.png", dpi=100, facecolor="#0a0a0a")
        print("preview -> /tmp/glove_preview.png")


if __name__ == "__main__":
    main()
