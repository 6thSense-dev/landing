#!/usr/bin/env python3
"""
Turn the variable Newsreader woff2 files into static per-weight instances.

WHY
---
Google serves Newsreader for the `ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400`
request as a VARIABLE font. The latin subset alone is 129KB, but only 7% of that
is glyph outlines - 52% is `gvar` (the variation deltas for wght 200..800 x
opsz 6..72) and another 38% is GPOS/GDEF. The site renders Newsreader at exactly
one size (17px) and two weights, so almost all of that payload is unused.

Pinning the axes drops `gvar` entirely: 132,000B -> 21,580B for latin @400.

WHAT THIS DOES *NOT* DO
-----------------------
It does not subset. No codepoint is removed. Instancing only resolves the
variation tables at fixed axis values; `cmap` is untouched. The script asserts
set-equality of codepoints before/after and refuses to write on any loss.
`scripts/verify-font-coverage.py` re-proves this independently.

TRADEOFF (reversible)
---------------------
Pinning `opsz` to 18 gives up automatic optical sizing. That is the right call
while Newsreader is body-only at 17px (opsz 18 is the font's own default, so
current rendering is unchanged). If Newsreader is ever used for large display
copy, either raise OPSZ here or set KEEP_OPSZ_AXIS = True to keep the axis at a
cost of roughly +36KB per instance.

PIPELINE
--------
    python3 scripts/fetch-fonts.py      # downloads variable woff2 + writes fonts.css
    python3 scripts/instance-fonts.py   # replaces Newsreader with static instances

Idempotent: re-running after instancing is a no-op.
Requires: fonttools, brotli  (pip install fonttools brotli)
"""

import hashlib
import io
import os
import re

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "public", "fonts")
CSS = os.path.join(ROOT, "src", "fonts.css")

# Chrome's `font-optical-sizing: auto` resolves opsz to the used font-size in
# CSS px, so 17px body copy renders at opsz 17 - NOT the font's 18 default.
# Measured against the variable original at 17px (700px-wide specimen, dpr 3):
#   opsz 12.75 -> 369.2px wide (59103 differing subpixels vs variable)
#   opsz 17    -> 336.8px wide (11949 differing subpixels)  <- matches
#   opsz 18    -> 329.2px wide (49458 differing subpixels, ~2.3% narrower)
# The variable original measures 336.797px, so 17 is a 0.016px metric match and
# the residual diff is antialiasing only. Pinning at 18 would visibly tighten
# the line. Keep OPSZ in sync with the size Newsreader is actually set at.
OPSZ = 17
KEEP_OPSZ_AXIS = False

# Variable sources to replace, and the (style, subset) label used for naming.
SOURCES = [
    ("newsreader-400-norm-latin-b76914.woff2", "norm", "latin"),
    ("newsreader-400-norm-latin-ext-d8c865.woff2", "norm", "latin-ext"),
    ("newsreader-400-ital-latin-905125.woff2", "ital", "latin"),
    ("newsreader-400-ital-latin-ext-c74ec7.woff2", "ital", "latin-ext"),
]

FACE_RE = re.compile(r"@font-face \{[^}]*\}", re.S)


def codepoints(font):
    s = set()
    for t in font["cmap"].tables:
        s |= set(t.cmap.keys())
    return s


def make_instance(src_path, weight):
    """Return (woff2_bytes, codepoint_set) for one pinned instance."""
    font = TTFont(src_path)
    before = codepoints(font)
    axes = {a.axisTag for a in font["fvar"].axes}

    limits = {}
    if "wght" in axes:
        limits["wght"] = weight
    if "opsz" in axes and not KEEP_OPSZ_AXIS:
        limits["opsz"] = OPSZ

    inst = instancer.instantiateVariableFont(
        font, limits, inplace=True, updateFontNames=False
    )
    after = codepoints(inst)
    lost = before - after
    if lost:
        raise SystemExit(
            f"ABORT: {os.path.basename(src_path)} @{weight} lost codepoints: "
            + ", ".join(f"U+{c:04X}" for c in sorted(lost))
        )

    inst.flavor = "woff2"
    buf = io.BytesIO()
    inst.save(buf)
    return buf.getvalue(), after


def main():
    css = open(CSS).read()
    total_before = total_after = 0
    made = 0

    for src_name, style_tag, subset in SOURCES:
        src = os.path.join(FONTS, src_name)
        if not os.path.exists(src):
            print(f"skip {src_name} (absent - already instanced?)")
            continue
        if "fvar" not in TTFont(src):
            print(f"skip {src_name} (already static)")
            continue

        # Which @font-face blocks actually reference this file? Their
        # font-weight values are the instances we need to emit. Keyed off the
        # src url because latin / latin-ext blocks are otherwise identical.
        faces = [b for b in FACE_RE.findall(css) if src_name in b]
        if not faces:
            raise SystemExit(f"ABORT: no @font-face references {src_name}")
        weights = sorted(
            {int(re.search(r"font-weight:\s*(\d+)", b).group(1)) for b in faces}
        )

        orig_size = os.path.getsize(src)
        total_before += orig_size
        for w in weights:
            data, cps = make_instance(src, w)
            h = hashlib.md5(data).hexdigest()[:6]
            out_name = f"newsreader-{w}-{style_tag}-{subset}-{h}.woff2"
            with open(os.path.join(FONTS, out_name), "wb") as f:
                f.write(data)
            total_after += len(data)
            made += 1
            print(
                f"  {src_name} ({orig_size}B) -> {out_name} "
                f"({len(data)}B, {len(cps)} codepoints)"
            )

            # Repoint only the block(s) with this exact weight AND this src.
            def repoint(block, _w=w, _out=out_name, _src=src_name):
                if _src not in block:
                    return block
                if int(re.search(r"font-weight:\s*(\d+)", block).group(1)) != _w:
                    return block
                return block.replace(f"/fonts/{_src}", f"/fonts/{_out}")

            css = FACE_RE.sub(lambda m: repoint(m.group(0)), css)

        if src_name in css:
            raise SystemExit(f"ABORT: {src_name} still referenced after rewrite")
        os.remove(src)

    if not made:
        print("Nothing to do.")
        return

    open(CSS, "w").write(css)
    print(
        f"Rewrote {CSS}: {made} static instances, "
        f"{total_before}B -> {total_after}B on disk"
    )


if __name__ == "__main__":
    main()
