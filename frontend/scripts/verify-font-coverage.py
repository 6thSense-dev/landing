#!/usr/bin/env python3
"""
Assert that every shipped Newsreader face still renders every codepoint the
original variable fonts did.

`scripts/instance-fonts.py` pins the wght/opsz axes to shrink the payload. That
is supposed to be glyph-neutral - it resolves variation data, it does not subset.
This script is the standing proof of that, checked against the coverage manifest
recorded from the pre-instancing originals (src/newsreader-coverage.json).

A missing glyph in somebody's name is far worse than any number of saved bytes,
so this exits non-zero on ANY shortfall and names the offending codepoints.

IMPORTANT - why this checks per FILE, not per union:
    An earlier version unioned the codepoints of every file matching a subset
    and compared that to the manifest. It could not fail. Deleting the whole
    600-weight latin-ext file still passed (the 400 file covered the range), and
    subsetting the 400 latin file down to nine characters still passed (the 600
    file covered it). Coverage is only meaningful per face: each individual
    @font-face the browser might pick has to be complete on its own.

The face list is read from src/fonts.css, so a face that is renamed, dropped, or
repointed at a stale file is caught too.

    python3 scripts/verify-font-coverage.py

Requires: fonttools, brotli
"""

import json
import os
import re
import sys

from fontTools.ttLib import TTFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "public", "fonts")
CSS = os.path.join(ROOT, "src", "fonts.css")
MANIFEST = os.path.join(ROOT, "src", "newsreader-coverage.json")

FACE_RE = re.compile(r"@font-face \{[^}]*\}", re.S)

# How many Newsreader @font-face rules we expect to find. Guards against the
# whole family silently disappearing from fonts.css, which would otherwise
# "pass" by having nothing to check.
EXPECTED_FACES = 6


def codepoints(path):
    s = set()
    for t in TTFont(path)["cmap"].tables:
        s |= set(t.cmap.keys())
    return s


def fmt(cs, limit=20):
    o = sorted(cs)
    s = ", ".join(f"U+{c:04X}" for c in o[:limit])
    return s + (f" ... (+{len(o) - limit} more)" if len(o) > limit else "")


def expand(ranges):
    out = set()
    for lo, hi in ranges:
        out |= set(range(lo, hi + 1))
    return out


def main():
    man = json.load(open(MANIFEST))
    expected = {k: expand(v["ranges"]) for k, v in man["faces"].items()}
    css = open(CSS).read()

    faces = []
    for block in FACE_RE.findall(css):
        if "'Newsreader'" not in block:
            continue
        style = re.search(r"font-style:\s*(\w+)", block).group(1)
        weight = re.search(r"font-weight:\s*(\d+)", block).group(1)
        src = re.search(r"url\('/fonts/([^']+)'\)", block).group(1)
        urange = re.search(r"unicode-range:\s*([^;]+);", block)
        # latin-ext is the subset whose range starts at U+0100
        subset = "latin-ext" if urange and "U+0100-02BA" in urange.group(1) else "latin"
        faces.append((style, weight, subset, src))

    ok = True
    if len(faces) != EXPECTED_FACES:
        print(
            f"FAIL - expected {EXPECTED_FACES} Newsreader @font-face rules, found {len(faces)}"
        )
        ok = False

    print(f"{'face':<28}{'expected':>9}{'in file':>9}{'ok':>6}  file")
    print("-" * 96)
    for style, weight, subset, src in sorted(faces):
        key = f"{style}|{subset}"
        want = expected.get(key)
        path = os.path.join(FONTS, src)
        label = f"{style} {weight} {subset}"
        if want is None:
            print(
                f"{label:<28}{'?':>9}{'-':>9}{'FAIL':>6}  no manifest entry for {key}"
            )
            ok = False
            continue
        if not os.path.exists(path):
            print(f"{label:<28}{len(want):>9}{'-':>9}{'FAIL':>6}  MISSING FILE {src}")
            ok = False
            continue
        got = codepoints(path)
        # Each face must be complete on its own.
        good = want <= got
        ok &= good
        print(
            f"{label:<28}{len(want):>9}{len(got):>9}{('ok' if good else 'FAIL'):>6}  {src}"
        )
        if not good:
            print(f"    LOST {len(want - got)}: {fmt(want - got)}")

    print("-" * 96)
    if ok:
        print(
            "PASS - every Newsreader face independently covers the original codepoint set."
        )
        return 0
    print("FAIL - coverage regressed. Do not ship.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
