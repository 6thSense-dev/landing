"""The rules that stop a caveat being lost between the record and the buyer.

    cd scripts/catalog && python3 -m pytest tests -q     (or: make -C scripts/catalog test)

Every rule here exists because the same failure happened once: the honest number
was in the data, one clip at a time, at the bottom of a tab, and the sentence a
buyer read first said something else. A bundle that validates against both
schemas proves none of this — the contradiction is between two fields that are
each individually well-formed.

  * `sync_aggregate`     the measured worst case, at the collection level (H1)
  * `_copy_vs_sync_row`  copy may not claim a precision the measurements refuse
  * `provenance_class`   generated media declares itself, and unknown is not clean
  * `corpus_shape_note`  one to two clips per task is stated, not implied
  * `_provenance_guard`  a synthetic bundle cannot be uploaded by accident
  * `_country_label_row` a filter bucket never shows a machine code as its own name
  * `_grid_size_copy_row` the header quotes the channel census, not the 484-site grid
  * `_provenance_copy_row` a synthetic corpus never says it was captured anywhere
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.benchmark import (  # noqa: E402
    build_totals,
    corpus_shape_note,
    provenance_class,
    sync_aggregate,
)
from ingest.validate import (  # noqa: E402
    _clip_copy_vs_sync_row,
    _copy_vs_sync_row,
    _country_label_row,
    _grid_size_copy_row,
    _provenance_copy_row,
)
from upload_bundle import _provenance_guard  # noqa: E402


def _clip(cid: str, *, fps=30.0, seconds=40.0):
    return {
        "id": cid,
        "fps": fps,
        "duration_s": seconds,
        "category": "manipulation",
        "subcategory": None,
        "recorded_month": "2026-08",
        "country": "CN",
        "bytes": 1000,
        # The delivered shape: stereo, both gloves, every modality.
        "capture": "stereo_egocentric",
        "hands": ["left", "right"],
        "modalities": ["video", "tactile", "imu", "segcap", "calibration"],
        "split": "train",
        "rights": {k: "denied" for k in
                   ("model_training", "commercial_use", "redistribution", "derived_model")},
        "qa": {"grade": "B", "tactile_coverage": 0.6},
    }


def _detail(error_ms, *, media_class="recorded"):
    return {
        "sync": {"maximum_alignment_error_ms": error_ms},
        "provenance": {"media_class": media_class},
    }


# --------------------------------------------------------------------------- #
# H1 at the collection level                                                   #
# --------------------------------------------------------------------------- #

def test_the_aggregate_is_the_maximum_not_the_typical():
    """One bad take must move the headline. That is the entire point of H1."""
    clips = [_clip(f"c{i}") for i in range(5)]
    details = {f"c{i}": _detail(v) for i, v in enumerate([9.7, 12.0, 14.0, 15.0, 56.74])}
    agg = sync_aggregate(clips, details)
    assert agg["sync_max_alignment_error_ms"] == 56.74
    # ...and it is not the mean (21.5) or the median (14.0) wearing its name.
    assert agg["sync_max_alignment_error_ms"] != pytest.approx(21.5, abs=1.0)


def test_clips_over_one_frame_uses_each_clips_own_frame_period():
    """34 ms is over one frame at 30 fps and inside one at 60 fps interlaced-half.

    Hardcoding 33 ms would call the second clip a miss when its own frame period
    is 16.7 ms, and the first a pass at 24 fps when its period is 41.7 ms.
    """
    clips = [_clip("slow", fps=24.0), _clip("fast", fps=60.0)]
    details = {"slow": _detail(34.0), "fast": _detail(34.0)}
    agg = sync_aggregate(clips, details)
    # 34 < 41.67 (24 fps) so `slow` passes; 34 > 16.67 (60 fps) so `fast` does not.
    assert agg["sync_clips_over_one_frame"] == 1


def test_p95_sits_next_to_the_max_not_instead_of_it():
    clips = [_clip(f"c{i}") for i in range(20)]
    details = {f"c{i}": _detail(10.0) for i in range(19)}
    details["c19"] = _detail(100.0)
    agg = sync_aggregate(clips, details)
    assert agg["sync_max_alignment_error_ms"] == 100.0
    assert agg["sync_p95_alignment_error_ms"] < 100.0  # the outlier is visible as one
    assert agg["sync_clips_measured"] == 20


def test_unmeasured_reads_as_unmeasured_and_never_as_zero():
    """A null here is worse news than a large number and must not look like good news."""
    clips = [_clip("c0"), _clip("c1")]
    agg = sync_aggregate(clips, {"c0": {"sync": {"maximum_alignment_error_ms": None}}})
    assert agg == {
        "sync_clips_measured": 0,
        "sync_max_alignment_error_ms": None,
        "sync_p95_alignment_error_ms": None,
        "sync_clips_over_one_frame": None,
        # A count, not a null: nothing was validated, and "0 of 2" is a fact the
        # header can state. Nulling it would read as "not applicable".
        "sync_clips_independently_validated": 0,
    }


def test_independent_validation_is_counted_over_every_clip_not_the_measured_subset():
    """The figure that says what the error is WORTH.

    A clip can publish a tiny alignment error and have nothing physical corroborating
    it, and a clip that measured no error at all is also a clip nothing corroborated.
    So the denominator is the corpus, not the measured subset -- otherwise a corpus
    that measured one clip and validated it would report 1/1.
    """
    clips = [_clip(f"c{i}") for i in range(4)]
    details = {
        "c0": {"sync": {"maximum_alignment_error_ms": 10.0, "validation_result": "pass"}},
        "c1": {"sync": {"maximum_alignment_error_ms": 10.0, "validation_result": "not_validated"}},
        # measured nothing AND validated nothing: it still counts against the total.
        "c2": {"sync": {"maximum_alignment_error_ms": None, "validation_result": "not_validated"}},
        # no sync record at all.
        "c3": {},
    }
    agg = sync_aggregate(clips, details)
    assert agg["sync_clips_independently_validated"] == 1
    assert agg["sync_clips_measured"] == 2


def test_totals_carry_the_aggregate_so_the_header_need_not_open_29_records():
    clips = [_clip("c0"), _clip("c1")]
    totals = build_totals(
        clips, subjects=1, sessions=1,
        details={"c0": _detail(20.0), "c1": _detail(56.74)},
    )
    assert totals["sync_max_alignment_error_ms"] == 56.74
    assert totals["sync_clips_over_one_frame"] == 1
    assert totals["sync_clips_measured"] == 2


# --------------------------------------------------------------------------- #
# the copy may not outrun the measurement                                      #
# --------------------------------------------------------------------------- #

def _manifest(copy: str, *, over=20, measured=29, worst=56.74):
    return {
        "collection": {
            "description": copy,
            "notice": None,
            "totals": {
                "sync_clips_over_one_frame": over,
                "sync_clips_measured": measured,
                "sync_max_alignment_error_ms": worst,
            },
        }
    }


@pytest.mark.parametrize("copy", [
    "so a contact event can be located to about one video frame",
    "aligned to within one frame",
    "sub-frame accuracy across both streams",
    "streams are aligned to a single frame",
])
def test_a_frame_level_claim_fails_the_build_when_the_data_refuses_it(copy):
    row = _copy_vs_sync_row(_manifest(copy))
    assert row.status == "FAIL"
    assert "56.74" in row.detail and "20/29" in row.detail


def test_stating_the_measured_figure_is_always_allowed():
    """The rule forbids the CLAIM, never the number. Quoting 56.74 ms must pass."""
    row = _copy_vs_sync_row(_manifest(
        "The measured worst-case alignment error is 56.74 ms; 20 of 29 clips exceed "
        "one 30 fps video frame."))
    assert row.status == "PASS"


def test_the_claim_is_fine_when_the_data_supports_it():
    row = _copy_vs_sync_row(_manifest("aligned to within one video frame", over=0))
    assert row.status == "PASS"


def test_the_rule_does_not_fire_on_any_mention_of_frames():
    for copy in ("30 frames per second", "per-frame timestamps ship in frame_times.csv"):
        assert _copy_vs_sync_row(_manifest(copy)).status == "PASS", copy


# --------------------------------------------------------------------------- #
# generated media declares itself                                              #
# --------------------------------------------------------------------------- #

def test_provenance_folds_over_the_per_take_declaration():
    clips = [_clip("a"), _clip("b")]
    real = {"a": _detail(10.0), "b": _detail(10.0)}
    fake = {k: _detail(10.0, media_class="synthetic") for k in ("a", "b")}
    mixed = {"a": _detail(10.0), "b": _detail(10.0, media_class="synthetic")}
    assert provenance_class(clips, real) == "recorded"
    assert provenance_class(clips, fake) == "synthetic"
    assert provenance_class(clips, mixed) == "mixed"


def test_an_undeclared_take_counts_as_synthetic_not_as_recorded():
    """"We could not tell" and "it is real" are different answers, and only one of
    them is safe to publish on a page a buyer is reading."""
    clips = [_clip("a")]
    assert provenance_class(clips, {"a": {"provenance": {}}}) == "synthetic"
    assert provenance_class(clips, {}) == "synthetic"


def test_upload_refuses_a_synthetic_bundle_without_the_flag(tmp_path):
    manifest = tmp_path / "catalog.json"
    manifest.write_text(json.dumps({"collection": {"provenance_class": "synthetic"}}))
    assert _provenance_guard(manifest, allow_synthetic=False) == 2
    assert _provenance_guard(manifest, allow_synthetic=True) is None


def test_upload_allows_a_recorded_bundle_and_refuses_one_that_cannot_say(tmp_path):
    good = tmp_path / "catalog.json"
    good.write_text(json.dumps({"collection": {"provenance_class": "recorded"}}))
    assert _provenance_guard(good, allow_synthetic=False) is None

    silent = tmp_path / "old.json"
    silent.write_text(json.dumps({"collection": {}}))
    assert _provenance_guard(silent, allow_synthetic=False) == 2


# --------------------------------------------------------------------------- #
# the shape of the corpus is stated, not implied                               #
# --------------------------------------------------------------------------- #

def test_one_clip_per_task_says_so_in_the_note():
    clips = [_clip(f"c{i}") for i in range(29)]
    tasks = [f"task-{i}" for i in range(24)]
    note = corpus_shape_note(clips, lambda c: tasks[int(c["id"][1:]) % 24])
    assert "24 tasks across 29 clips" in note
    assert "one to two takes per task" in note
    # Render-agnostic: the consumer draws a list at this ratio, not bars.
    assert "bars" not in note


def test_a_real_distribution_gets_the_plain_ratio():
    clips = [_clip(f"c{i}") for i in range(60)]
    note = corpus_shape_note(clips, lambda c: "one-task")
    assert "60.0 takes per task" in note
    assert "not a distribution" not in note


# The manifest publishes TWO folds of the same clips and the chart picks one, so a
# note that quotes only the task ratio gets printed under a chart it does not
# describe. These pin the second clause.

def test_the_note_states_the_category_ratio_too():
    clips = [_clip(f"c{i}") for i in range(30)]
    tasks = [f"task-{i}" for i in range(25)]
    cats = [f"cat-{i}" for i in range(10)]
    note = corpus_shape_note(
        clips,
        lambda c: tasks[int(c["id"][1:]) % 25],
        lambda c: cats[int(c["id"][1:]) % 10],
    )
    assert "25 tasks across 30 clips" in note
    assert "one to two takes per task" in note
    assert "10 categories at 3.0 takes each" in note
    # Still render-agnostic: one fold draws bars, the other draws a table.
    assert "bars" not in note


def test_a_category_fold_that_does_not_aggregate_is_not_mentioned():
    """One category per task is not a second view, and the UI will not offer it."""
    clips = [_clip(f"c{i}") for i in range(30)]
    tasks = [f"task-{i}" for i in range(25)]
    note = corpus_shape_note(
        clips,
        lambda c: tasks[int(c["id"][1:]) % 25],
        lambda c: tasks[int(c["id"][1:]) % 25],
    )
    assert "categories" not in note


def test_no_category_fold_reads_exactly_as_before():
    clips = [_clip(f"c{i}") for i in range(29)]
    tasks = [f"task-{i}" for i in range(24)]
    task_of = lambda c: tasks[int(c["id"][1:]) % 24]  # noqa: E731
    assert corpus_shape_note(clips, task_of) == corpus_shape_note(clips, task_of, lambda c: None)


# --------------------------------------------------------------------------- #
# a filter bucket never shows a machine code where every sibling shows a name    #
# --------------------------------------------------------------------------- #

def _facets(*buckets):
    return {"facets": {"country": list(buckets)}}


def test_a_named_country_bucket_passes():
    row = _country_label_row(_facets({"value": "CN", "label": "China", "clips": 18},
                                     {"value": "HK", "label": "Hong Kong", "clips": 12}))
    assert row.status == "PASS"


def test_a_bucket_whose_label_is_its_own_code_fails_the_build():
    """`{value: 'HK', label: 'HK'}` is schema-valid and still wrong in front of a buyer."""
    row = _country_label_row(_facets({"value": "CN", "label": "China", "clips": 18},
                                     {"value": "HK", "label": "HK", "clips": 12}))
    assert row.status == "FAIL"
    assert "HK" in row.detail and "bare code" in row.detail


@pytest.mark.parametrize("label", [None, "", "   "])
def test_a_bucket_with_no_label_at_all_fails(label):
    row = _country_label_row(_facets({"value": "CN", "label": label, "clips": 18}))
    assert row.status == "FAIL"
    assert "no label" in row.detail


def test_the_detail_says_where_to_fix_it():
    row = _country_label_row(_facets({"value": "HK", "label": "HK", "clips": 1}))
    assert "_COUNTRY_NAMES" in row.detail and "country_labels" in row.detail


def test_the_rule_only_fires_on_a_label_that_really_is_the_code():
    """A label that legitimately equals its value elsewhere must not be swept up."""
    row = _country_label_row(_facets({"value": "USA", "label": "USA", "clips": 1}))
    assert row.status == "PASS", "only a two-letter uppercase code is a country code"


def test_a_vendor_supplied_label_survives_the_recount():
    """`country_labels` in the collection config is not carried in the bundle, so the
    facet recount reads the manifest's own labels back rather than re-deriving them --
    otherwise every bundle that used the override failed the count cross-check."""
    from ingest.benchmark import build_facets
    clips = [_clip("a"), _clip("b")]
    got = build_facets(clips, country_overrides={"CN": "China (mainland)"})
    assert got["country"][0]["label"] == "China (mainland)"
    overrides = {b["value"]: b["label"] for b in got["country"]}
    assert build_facets(clips, country_overrides=overrides) == got
    assert _country_label_row({"facets": got}).status == "PASS"


def test_a_malformed_bucket_is_reported_rather_than_crashing_the_validator():
    """validate_bundle runs every check on every bundle, including one that already
    failed the schema row, so this check has to survive a non-object bucket."""
    row = _country_label_row({"facets": {"country": ["CN", {"value": "HK",
                                                            "label": "Hong Kong"}]}})
    assert row.status == "FAIL"
    assert "not an object" in row.detail


def test_a_collection_with_no_country_facet_is_not_a_failure():
    """Every clip missing a country hides the control; it does not fail the build."""
    assert _country_label_row({"facets": {}}).status == "PASS"
    assert _country_label_row({}).status == "PASS"


# --------------------------------------------------------------------------- #
# the same rule one level down: a clip's own prose vs its own measurement       #
# --------------------------------------------------------------------------- #

def test_a_clips_own_description_is_held_to_its_own_frame_period():
    """Fixing only the headline moves the false sentence into the Metadata tab,
    one scroll below the measured figure that contradicts it."""
    details = {
        "c0": {"fps": 30.0, "sync": {"maximum_alignment_error_ms": 35.897},
               "description": "a contact event can be located to about one video frame"},
    }
    row = _clip_copy_vs_sync_row(details)
    assert row.status == "FAIL"
    assert "35.90" in row.detail and "33.33" in row.detail


def test_a_clip_that_actually_meets_the_bound_may_say_so():
    details = {
        "c0": {"fps": 30.0, "sync": {"maximum_alignment_error_ms": 9.7},
               "description": "aligned to within one video frame"},
    }
    assert _clip_copy_vs_sync_row(details).status == "PASS"


def test_a_clip_making_no_claim_passes_however_bad_the_measurement():
    details = {
        "c0": {"fps": 30.0, "sync": {"maximum_alignment_error_ms": 500.0},
               "description": "the measured worst case is published per clip"},
    }
    assert _clip_copy_vs_sync_row(details).status == "PASS"


# --------------------------------------------------------------------------- #
# the header may not contradict the QA record shipped underneath it            #
# --------------------------------------------------------------------------- #

def _collection(**fields):
    base = {"description": "", "standfirst": None, "notice": None,
            "provenance_class": "recorded",
            "totals": {"sync_clips_over_one_frame": 0, "sync_clips_measured": 30,
                       "sync_max_alignment_error_ms": 56.74}}
    base.update(fields)
    return {"collection": base}


@pytest.mark.parametrize("field", ["description", "standfirst", "notice"])
def test_the_grid_size_is_refused_wherever_the_collection_says_it(field):
    """Every clip says "quote the usable-channel count, never the 484-site grid size".

    The header said "two 22x22 tactile gloves" anyway, in the largest body type on the
    page. The rule covers all three buyer-visible collection strings, because moving the
    sentence into `standfirst` is exactly how the claim came back.
    """
    row = _grid_size_copy_row(_collection(**{field: "two 22x22 tactile gloves"}))
    assert row.status == "FAIL"
    assert "22x22" in row.detail


@pytest.mark.parametrize("copy", ["484 readout sites per hand", "the 22 x 22 grid",
                                  "a 22\u00d722 pad"])
def test_the_grid_size_is_refused_however_it_is_spelled(copy):
    assert _grid_size_copy_row(_collection(description=copy)).status == "FAIL"


def test_quoting_the_census_instead_of_the_grid_passes():
    """The rule forbids the GRID SIZE, never a channel figure."""
    row = _grid_size_copy_row(_collection(
        description="two tactile gloves whose live-and-stable channel census is published "
                    "per clip, at a median of 290 working sites on the worst hand"))
    assert row.status == "PASS"


def test_a_synthetic_corpus_may_not_say_it_was_captured_anywhere():
    """`captured in` sat one line above a banner saying these are not recordings."""
    row = _provenance_copy_row(_collection(
        provenance_class="synthetic",
        description="Thirty takes, captured in mainland China and Hong Kong."))
    assert row.status == "FAIL"
    assert "captured in" in row.detail


def test_the_standfirst_is_held_to_the_provenance_rule_too():
    row = _provenance_copy_row(_collection(
        provenance_class="mixed", standfirst="Recorded across five sites."))
    assert row.status == "FAIL"


def test_modelled_on_is_how_a_synthetic_corpus_states_its_geography():
    row = _provenance_copy_row(_collection(
        provenance_class="synthetic",
        description="Thirty takes, modelled on light industrial work in mainland China "
                    "and Hong Kong. The rig is a camera; the workspace is not real."))
    assert row.status == "PASS"


def test_a_recorded_corpus_may_say_captured_in():
    """The rule is about the PAIRING, and it stops firing when the corpus is real."""
    row = _provenance_copy_row(_collection(
        provenance_class="recorded",
        description="Thirty takes, captured in mainland China and Hong Kong."))
    assert row.status == "PASS"


def test_the_standfirst_cannot_smuggle_a_frame_level_claim_past_the_sync_rule():
    """The promoted line is the one most readers see, so it is scanned like the rest."""
    manifest = _collection(standfirst="Every stream aligned to within one video frame.")
    manifest["collection"]["totals"]["sync_clips_over_one_frame"] = 20
    row = _copy_vs_sync_row(manifest)
    assert row.status == "FAIL"
    assert "20/30" in row.detail
