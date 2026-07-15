#!/usr/bin/env python3
"""Assemble the Eye2 camera enclosure CAD into one turntable mesh for /products.

The Eye2 is the 6thSense egocentric capture camera. Its printed enclosure ships
as two STL parts, exported from the same CAD assembly (so they already share one
coordinate frame — no manual alignment needed):

  Eye2 Main Frame.stl   the front housing that holds the camera        (main-frame)
  Eye2 Back Case.stl    the rear cover / cable side                    (back-case)

We load both, keep them as SEPARATE named meshes in one GLB scene, and let the
frontend (Eye2Turntable.jsx) center the combined bounds and spin it. Kept as two
meshes (not merged) so a future frontend can style the front/back differently,
the same way GloveTurntable pulls out the "sensors" mesh.

Honest imagery (DESIGN.md): this is the REAL product CAD, not an AI render.

Outputs (written to frontend/public/):
  eye2.glb   assembled enclosure (pre-meshopt; run gltf-transform after — see
             the npx command printed at the end)

Run (needs numpy + trimesh; Pillow only for --preview):
    python3 frontend/scripts/build-eye2-cad.py
    python3 frontend/scripts/build-eye2-cad.py --preview   # writes /tmp PNG
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import trimesh

# Staged CAD lives outside the repo (raw STLs are also copied into public/ for
# the download affordance by the caller; this script only reads them).
_DEFAULT_CAD = Path("/Users/ronak/Documents/00-6thsense/assets/cad")
_OUT_DIR = Path(__file__).resolve().parents[1] / "public"

PARTS = [
    ("Eye2 Main Frame.stl", "main-frame"),
    ("Eye2 Back Case.stl", "back-case"),
]


def load_part(path: Path) -> trimesh.Trimesh:
    """Load one STL as a single Trimesh, merging duplicate verts (STL is a raw
    triangle soup — welding gives smooth shared normals in the viewer)."""
    m = trimesh.load(path, process=True)
    if isinstance(m, trimesh.Scene):
        m = trimesh.util.concatenate(tuple(m.geometry.values()))
    m.merge_vertices()
    m.fix_normals()
    return m


def build(cad_dir: Path, out_dir: Path):
    scene = trimesh.Scene()
    parts = []
    for fname, name in PARTS:
        m = load_part(cad_dir / fname)
        m.metadata["name"] = name
        scene.add_geometry(m, geom_name=name)
        parts.append((name, m))

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "eye2.glb"
    scene.export(out_path)

    total_f = sum(len(m.faces) for _, m in parts)
    combined = trimesh.util.concatenate([m for _, m in parts])
    for name, m in parts:
        print(f"{name:12s}: {len(m.vertices):6d} v / {len(m.faces):6d} f")
    print(f"combined    : {len(combined.vertices)} v / {total_f} f")
    print(
        f"bounds      : min {np.round(combined.bounds[0], 2)}  "
        f"max {np.round(combined.bounds[1], 2)}"
    )
    print(f"wrote       : {out_path}")
    print()
    print("Now meshopt-compress it (run from frontend/):")
    print("  npx --yes @gltf-transform/cli weld public/eye2.glb public/eye2.glb")
    print("  npx --yes @gltf-transform/cli meshopt public/eye2.glb public/eye2.glb")
    return parts, combined


def preview(parts):
    """Quick matplotlib render at two angles so we can eyeball orientation and
    confirm the two parts assemble (mirrors build-glove-cad.py --preview)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection

    # three.js turntable is +Y up; matplotlib vertical is its 3rd axis, so remap
    # data (x,y,z) -> plot (x, z, y).
    remap = lambda P: P[:, [0, 2, 1]]
    key = np.array([0.5, 0.6, 1.0])
    key = key / np.linalg.norm(key)

    def shaded(ax, m, base, zorder=1):
        tri = remap(m.vertices)[m.faces]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-9
        lam = np.clip(n @ key, 0, 1)
        rim = np.clip(n @ np.array([-0.6, 0.2, -0.5]), 0, 1)
        shade = 0.35 + 0.7 * lam
        cols = np.clip(
            base[None, :] * shade[:, None]
            + np.array([0.94, 0.38, 0.16])[None, :] * (0.3 * rim[:, None]),
            0,
            1,
        )
        pc = Poly3DCollection(tri, facecolors=cols, edgecolor="none", zorder=zorder)
        pc.set_zsort("max")
        ax.add_collection3d(pc)

    fig = plt.figure(figsize=(12, 6), facecolor="#0a0a0a")
    palette = {
        "main-frame": np.array([0.20, 0.20, 0.22]),
        "back-case": np.array([0.12, 0.12, 0.13]),
    }
    allv = remap(np.vstack([m.vertices for _, m in parts]))
    c = allv.mean(0)
    r = np.abs(allv - c).max() * 0.95
    for i, (title, elev, az) in enumerate(
        [("Eye2 — 3/4 front", 20, 45), ("Eye2 — side", 8, 100)]
    ):
        ax = fig.add_subplot(1, 2, i + 1, projection="3d")
        ax.set_facecolor("#0a0a0a")
        for zo, (name, m) in enumerate(parts):
            shaded(ax, m, palette.get(name, np.array([0.2, 0.2, 0.2])), zorder=zo + 1)
        ax.set_xlim(c[0] - r, c[0] + r)
        ax.set_ylim(c[1] - r, c[1] + r)
        ax.set_zlim(c[2] - r, c[2] + r)
        ax.view_init(elev=elev, azim=az)
        ax.set_axis_off()
        ax.set_title(title, color="#f0612a")
        ax.set_box_aspect((1, 1, 1))
    plt.tight_layout()
    plt.savefig("/tmp/eye2_preview.png", dpi=100, facecolor="#0a0a0a")
    print("preview -> /tmp/eye2_preview.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cad", type=Path, default=_DEFAULT_CAD)
    ap.add_argument("--out", type=Path, default=_OUT_DIR)
    ap.add_argument("--preview", action="store_true", help="write /tmp preview PNG")
    args = ap.parse_args()

    parts, _ = build(args.cad, args.out)
    if args.preview:
        preview(parts)


if __name__ == "__main__":
    main()
