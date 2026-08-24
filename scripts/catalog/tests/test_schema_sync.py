"""The two schemas must not drift apart. CONTRACT.md §8 promises this runs; it now does.

`clip.schema.json` duplicates the shared `$defs` rather than `$ref`-ing across files, so a
buyer's engineer can validate either document with no registry wiring. The price is a drift
risk, and the contract closes it with an assertion — which is only worth anything if the
assertion executes. The version printed in CONTRACT.md before this file existed raised
`KeyError: 'type'` on `LicenseUrl`, so it had never been run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"
SHARED = ["AssetUrl", "ExternalUrl", "LicenseUrl", "ClipId", "Slug", "CountryCode",
          "YearMonth", "Capture", "Modality", "Hand", "Resolution", "Grade", "Permission",
          "Split"]
# `title` and `description` may differ: each file describes the def in its own context.
FACETS = ("type", "enum", "pattern", "anyOf", "const", "minLength", "maxLength",
          "minItems", "maxItems", "items", "minimum", "maximum")


def _defs(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))["$defs"]


@pytest.fixture(scope="module")
def catalog_defs() -> dict:
    return _defs("catalog.schema.json")


@pytest.fixture(scope="module")
def clip_defs() -> dict:
    return _defs("clip.schema.json")


@pytest.mark.parametrize("name", SHARED)
def test_shared_defs_are_identical_where_it_matters(name, catalog_defs, clip_defs):
    assert name in catalog_defs and name in clip_defs
    for facet in FACETS:
        assert catalog_defs[name].get(facet) == clip_defs[name].get(facet), (name, facet)


@pytest.mark.parametrize("name", ["catalog.schema.json", "clip.schema.json"])
def test_each_schema_is_itself_valid_draft_2020_12(name):
    Draft202012Validator.check_schema(json.loads((SCHEMA_DIR / name).read_text("utf-8")))


def test_every_modality_has_a_media_slot(clip_defs):
    """A modality with nowhere in `media` to point cannot be listed on a card."""
    media = json.loads((SCHEMA_DIR / "clip.schema.json").read_text("utf-8"))
    slots = set(media["$defs"]["Media"]["required"])
    for modality in clip_defs["Modality"]["enum"]:
        assert modality in slots, (
            f"`{modality}` is a listed modality with no pointer in `media`: it would filter, "
            f"light a chip and add its full duration to facets.modality[].hours while "
            f"resolving to no file and no quality metadata."
        )
