"""The two rules the ~30-clip corpus size broke, and the citation rule that guards it.

    cd scripts/catalog && python3 -m pytest tests -q     (or: make -C scripts/catalog test)

Neither of these can be proved by a bundle that validates. A manifest saying
`unit: "hours"` with bars of 0.0027 is schema-perfect and unreadable, and a comparison
series with an invented number validates exactly as well as a cited one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest.benchmark import (  # noqa: E402
    AUTO_HOURS_MIN_SECONDS,
    collection_wide_limitations,
    measured_scope,
    BenchmarkConfigError,
    build_benchmark,
    build_facets,
    build_totals,
    comparison_note,
    country_label,
    parse_comparisons,
    primary_series,
    resolve_unit,
    UnlabelledCountryError,
    validate_benchmark_config,
)

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "schema"


def _clips(n: int, seconds: float, *, task="Parts transfer", category="manipulation"):
    """n clips of `seconds` each, carrying only the fields the benchmark folds over."""
    return [
        {
            "id": f"clip-{i:02d}",
            "duration_s": seconds,
            "category": category,
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
            "_task": task,
        }
        for i in range(n)
    ]


def _bench(clips, **kw):
    return build_benchmark(
        clips, series_of=lambda c: "egotac", task_of=lambda c: c["_task"], **kw)


# --------------------------------------------------------------------------- #
# the unit is picked from the data                                             #
# --------------------------------------------------------------------------- #

def test_auto_picks_minutes_for_the_delivered_corpus():
    """30 clips x ~37 s is twenty minutes. `hours` there emits bars of 0.0027."""
    bench = _bench(_clips(30, 37.5))
    assert bench["unit"] == "minutes"
    only = bench["tasks"][0]["values"]["egotac"]
    assert only == pytest.approx(18.75, abs=0.01)
    # The specific defect: the same corpus on an hours axis.
    assert _bench(_clips(30, 37.5), unit="hours")["tasks"][0]["values"]["egotac"] \
        == pytest.approx(0.3125, abs=0.0001)


def test_auto_flips_to_hours_at_the_published_threshold():
    """Exactly at 2 h reads in hours; a second under it still reads in minutes."""
    assert resolve_unit("auto", AUTO_HOURS_MIN_SECONDS) == "hours"
    assert resolve_unit("auto", AUTO_HOURS_MIN_SECONDS - 1) == "minutes"
    assert _bench(_clips(120, 60.0))["unit"] == "hours"          # 2.0 h exactly
    assert _bench(_clips(119, 60.0))["unit"] == "minutes"        # 1.98 h


def test_an_explicit_unit_is_never_overridden():
    """`auto` is a default, not a policy: a producer who says hours gets hours."""
    assert _bench(_clips(30, 37.5), unit="hours")["unit"] == "hours"
    assert _bench(_clips(300, 60.0), unit="minutes")["unit"] == "minutes"


def test_the_emitted_unit_is_never_the_word_auto():
    for unit in ("auto", None):
        assert _bench(_clips(4, 40.0), unit=unit)["unit"] in ("hours", "minutes")


def test_a_bad_unit_is_refused_rather_than_silently_ignored():
    with pytest.raises(BenchmarkConfigError):
        resolve_unit("seconds", 0.0)


def test_clips_unit_counts_clips_not_seconds():
    bench = _bench(_clips(7, 40.0), unit="clips")
    assert bench["unit"] == "clips"
    assert bench["tasks"][0]["values"]["egotac"] == 7


def test_totals_publish_the_same_unit_the_chart_uses():
    """A '0.04 hours' stat tile next to a minutes axis is the bug this closes."""
    short = build_totals(_clips(30, 37.5), subjects=1, sessions=1)
    assert short["duration_unit"] == "minutes"
    assert short["hours"] == pytest.approx(0.3125, abs=1e-4)   # still stored in hours
    long = build_totals(_clips(300, 60.0), subjects=1, sessions=1)
    assert long["duration_unit"] == "hours"


# --------------------------------------------------------------------------- #
# comparison series must be sourced                                            #
# --------------------------------------------------------------------------- #

CITED = {"label": "Ego4D", "hours": 3670, "retrieved": "2026-08-23",
         "source_url": "https://ego4d-data.org/docs/start-here/"}


def test_shipped_config_has_no_comparison_series():
    """The default must stay empty: we hold no per-task breakdown for any of them."""
    cfg_path = Path(__file__).resolve().parent.parent / "fixtures" / "collection.toml"
    import tomllib
    with cfg_path.open("rb") as fh:
        cfg = tomllib.load(fh)
    assert parse_comparisons(cfg) == []


def test_a_comparison_without_a_source_url_is_refused():
    bad = {k: v for k, v in CITED.items() if k != "source_url"}
    with pytest.raises(BenchmarkConfigError, match="source_url"):
        parse_comparisons({"benchmark": {"comparison": [bad]}})


@pytest.mark.parametrize("missing", ["label", "hours", "retrieved"])
def test_every_other_required_key_is_also_enforced(missing):
    bad = {k: v for k, v in CITED.items() if k != missing}
    with pytest.raises(BenchmarkConfigError):
        parse_comparisons({"benchmark": {"comparison": [bad]}})


def test_a_source_url_must_be_a_url_and_retrieved_must_be_a_date():
    with pytest.raises(BenchmarkConfigError, match="http"):
        parse_comparisons({"benchmark": {"comparison": [{**CITED, "source_url": "Ego4D paper"}]}})
    with pytest.raises(BenchmarkConfigError, match="retrieved"):
        parse_comparisons({"benchmark": {"comparison": [{**CITED, "retrieved": "August 2026"}]}})


def test_a_cited_comparison_becomes_its_own_bar_and_its_own_series():
    comps = parse_comparisons({"benchmark": {"comparison": [CITED]}})
    bench = _bench(_clips(30, 37.5), comparisons=comps, note=comparison_note(comps))
    assert bench["unit"] == "hours", "3670 h on the axis must not be plotted in minutes"
    assert [s["id"] for s in bench["series"]] == ["egotac", "ego4d"]
    ego = next(t for t in bench["tasks"] if t["label"] == "Ego4D")
    assert ego["values"] == {"ego4d": 3670.0}
    # ...and our own bar is still ours alone: no invented Ego4D split across our tasks.
    ours = next(t for t in bench["tasks"] if t["label"] == "Parts transfer")
    assert set(ours["values"]) == {"egotac"}


def test_the_citation_lands_in_the_note_the_chart_renders():
    comps = parse_comparisons({"benchmark": {"comparison": [CITED]}})
    note = _bench(_clips(3, 40.0), comparisons=comps, note=comparison_note(comps))["note"]
    assert "ego4d-data.org" in note and "2026-08-23" in note and "3,670 h" in note


def test_clip_counts_cannot_be_stacked_against_published_hours():
    cfg = {"benchmark": {"unit": "clips", "comparison": [CITED]}}
    with pytest.raises(BenchmarkConfigError, match="clips"):
        validate_benchmark_config(cfg)


# --------------------------------------------------------------------------- #
# our own series is configuration, not code                                    #
# --------------------------------------------------------------------------- #

def test_our_series_defaults_to_the_collection_identity():
    sid, label, color = primary_series({"id": "6s-egotac-eval", "name": "EGO-TAC sample"})
    assert (sid, label, color) == ("6s_egotac_eval", "EGO-TAC sample", "#14120c")


def test_renaming_our_dataset_is_one_line_of_toml():
    sid, label, color = primary_series({
        "id": "6s-egotac-eval", "name": "EGO-TAC sample",
        "benchmark": {"series": {"id": "sixthsense", "label": "6thSense EGO-TAC",
                                 "color": "#592202"}}})
    assert (sid, label, color) == ("sixthsense", "6thSense EGO-TAC", "#592202")


def test_a_series_id_that_the_schema_would_reject_is_refused_at_config_time():
    with pytest.raises(BenchmarkConfigError):
        primary_series({"id": "---"})
    with pytest.raises(BenchmarkConfigError):
        primary_series({"id": "x", "benchmark": {"series": {"color": "red"}}})


# --------------------------------------------------------------------------- #
# the category roll-up: the same clips, folded coarser, by the producer         #
# --------------------------------------------------------------------------- #

def _mixed(per_category: dict[str, int], seconds: float = 40.0):
    """Clips spread over several categories, each with its own subcategory task."""
    out, i = [], 0
    for category, n in per_category.items():
        for k in range(n):
            clip = _clips(1, seconds, category=category)[0]
            clip["id"] = f"clip-{i:02d}"
            clip["_task"] = f"{category}/{k}"       # one distinct task per clip
            out.append(clip)
            i += 1
    return out


def _both(clips, **kw):
    return build_benchmark(clips, series_of=lambda c: "egotac",
                           task_of=lambda c: c["_task"],
                           category_of=lambda c: c["category"], **kw)


def test_categories_collapse_the_picket_fence_the_tasks_are():
    """29 near-identical one-clip task bars is the defect; ~8 category bars is the fix."""
    bench = _both(_mixed({"industrial_inspection": 4, "kitchen_food_preparation": 3,
                          "retail_handling": 2}))
    assert len(bench["tasks"]) == 9          # one clip each: nothing to read
    assert len(bench["categories"]) == 3
    assert [c["clips"] for c in bench["categories"]] == [4, 3, 2]


def test_a_category_bar_joins_to_the_facet_by_machine_value_not_by_label():
    """Clicking a bar sets the category filter, so the bar must carry the filter's key."""
    clips = _mixed({"industrial_inspection": 2, "commercial_garment_care": 1})
    bench = _both(clips)
    facet = {b["value"]: b for b in build_facets(clips)["category"]}
    for bar in bench["categories"]:
        assert bar["value"] in facet, "no facet bucket to filter to"
        assert bar["label"] == facet[bar["value"]]["label"], "chart and filter bar disagree"
        assert bar["clips"] == facet[bar["value"]]["clips"]
    assert {b["label"] for b in bench["categories"]} == {"Industrial inspection",
                                                         "Commercial garment care"}


def test_both_roll_ups_total_the_same_because_they_are_the_same_clips():
    """A category view that quietly totals something else is worse than no category view."""
    bench = _both(_mixed({"a_one": 5, "b_two": 4, "c_three": 3}))
    total = lambda bars: sum(v for b in bars for v in b["values"].values())  # noqa: E731
    # Each bar is rounded to 6 dp on the way out, so 12 fine bars carry a few more
    # rounding steps than 3 coarse ones. Anything past that is a different fold.
    assert total(bench["tasks"]) == pytest.approx(total(bench["categories"]), abs=1e-5)
    assert sum(b["clips"] for b in bench["categories"]) == 12


def test_a_category_bar_carries_the_same_unit_and_series_as_the_task_bars():
    bench = _both(_mixed({"a_one": 15, "b_two": 15}), unit="minutes")
    assert bench["unit"] == "minutes"
    ids = {s["id"] for s in bench["series"]}
    for bar in bench["categories"]:
        assert set(bar["values"]) <= ids
        assert bar["values"]["egotac"] == pytest.approx(15 * 40.0 / 60.0, abs=1e-6)


def test_the_clips_unit_counts_clips_in_the_category_roll_up_too():
    bench = _both(_mixed({"a_one": 5, "b_two": 2}), unit="clips")
    assert {b["value"]: b["values"]["egotac"] for b in bench["categories"]} == {
        "a_one": 5, "b_two": 2}


def test_a_clip_with_no_category_is_skipped_not_bucketed_under_a_placeholder():
    clips = _mixed({"a_one": 3})
    clips[0]["category"] = None
    bench = _both(clips)
    assert [b["clips"] for b in bench["categories"]] == [2]
    assert len(bench["tasks"]) == 3, "the task roll-up still sees all three"


def test_a_cited_comparison_gets_one_category_bar_of_its_own():
    """Switching the chart between task and category must not lose a cited corpus."""
    comps = parse_comparisons({"benchmark": {"comparison": [CITED]}})
    bench = _both(_mixed({"a_one": 3}), comparisons=comps, note=comparison_note(comps))
    ego = next(b for b in bench["categories"] if b["label"] == "Ego4D")
    assert ego["values"] == {"ego4d": 3670.0}
    assert ego["clips"] is None, "a whole-corpus total has no clip count of ours"
    assert ego["value"] == "ego4d", "the comparison's series id, joining to no facet"
    ours = next(b for b in bench["categories"] if b["value"] == "a_one")
    assert set(ours["values"]) == {"egotac"}


def test_the_category_roll_up_defaults_to_clip_category_with_no_wiring():
    """A producer that never heard of `category_of` still emits a usable roll-up."""
    bench = build_benchmark(_clips(6, 40.0), series_of=lambda c: "egotac",
                            task_of=lambda c: c["_task"])
    assert [(b["value"], b["clips"]) for b in bench["categories"]] == [("manipulation", 6)]


# --------------------------------------------------------------------------- #
# a country code with no display label is a build failure                      #
# --------------------------------------------------------------------------- #

def test_the_two_countries_we_ship_have_names():
    assert country_label("CN") == "China"
    assert country_label("HK") == "Hong Kong"


def test_an_unnameable_country_code_stops_the_build():
    """The old behaviour returned the code, which validated and read as an abbreviation."""
    with pytest.raises(UnlabelledCountryError, match="XX"):
        country_label("XX")
    clips = _clips(3, 40.0)
    for clip in clips:
        clip["country"] = "XX"
    with pytest.raises(UnlabelledCountryError):
        build_facets(clips)


def test_the_message_names_both_ways_to_fix_it():
    with pytest.raises(UnlabelledCountryError) as exc:
        country_label("ZZ")
    assert "_COUNTRY_NAMES" in str(exc.value) and "country_labels" in str(exc.value)


def test_a_vendor_override_is_honoured_and_an_empty_one_is_not():
    assert country_label("HK", {"HK": "Hong Kong SAR"}) == "Hong Kong SAR"
    assert country_label("HK", {"HK": "   "}) == "Hong Kong", "blank is not an override"
    with pytest.raises(UnlabelledCountryError):
        country_label("XX", {"YY": "Somewhere"})


def test_every_country_bucket_ships_a_label_that_is_not_the_code():
    clips = [*_clips(4, 40.0), *_clips(2, 40.0)]
    clips[4]["country"] = clips[5]["country"] = "HK"
    buckets = build_facets(clips)["country"]
    assert [(b["value"], b["label"], b["clips"]) for b in buckets] == [
        ("CN", "China", 4), ("HK", "Hong Kong", 2)]
    assert all(b["label"] != b["value"] for b in buckets)


# --------------------------------------------------------------------------- #
# whatever we emit still has to validate                                       #
# --------------------------------------------------------------------------- #

def test_every_emitted_shape_validates_against_the_benchmark_schema():
    schema = json.loads((SCHEMA_DIR / "catalog.schema.json").read_text("utf-8"))
    validator = Draft202012Validator({**schema["$defs"]["Benchmark"],
                                      "$defs": schema["$defs"]})
    comps = parse_comparisons({"benchmark": {"comparison": [CITED]}})
    for bench in (_bench(_clips(30, 37.5)),
                  _bench(_clips(300, 60.0)),
                  _bench(_clips(9, 40.0), unit="clips"),
                  _bench(_clips(30, 37.5), comparisons=comps, note=comparison_note(comps)),
                  _both(_mixed({"a_one": 4, "b_two": 3, "c_three": 2})),
                  _both(_mixed({"a_one": 4}), unit="clips"),
                  _both(_mixed({"a_one": 4}), comparisons=comps,
                        note=comparison_note(comps))):
        validator.validate(bench)


def test_the_schema_requires_the_category_roll_up():
    """The chart codes against it, so a producer may not quietly stop emitting it."""
    schema = json.loads((SCHEMA_DIR / "catalog.schema.json").read_text("utf-8"))
    bench_schema = schema["$defs"]["Benchmark"]
    assert "categories" in bench_schema["required"]
    item = bench_schema["properties"]["categories"]["items"]
    assert item["required"] == ["value", "label", "values", "clips"]
    assert item["additionalProperties"] is False


# --------------------------------------------------------------------------- #
# scope is measured, not declared
# --------------------------------------------------------------------------- #

def _doc(*checks):
    return {"qa": {"checks": [{"check_id": cid, "result": r, "scope": sc, "note": "n"}
                              for cid, r, sc in checks]}}


def test_a_check_that_varies_between_clips_is_not_collection_wide():
    """The predicate behind both `scope` and `collection_wide_limitations`.

    A static id list claimed `privacy_redaction_record` described the programme. Measured
    over a 30-clip corpus it warned on 10 -- so ten clips carried a privacy warning of
    their own, folded under a heading reading "applies to the whole collection, not to this
    clip", while the same 10-of-30 tally kept it out of the collection block too. It was
    stated correctly in neither place.
    """
    details = {
        "a": _doc(("everywhere", "warn", "collection"), ("sometimes", "warn", "collection")),
        "b": _doc(("everywhere", "warn", "collection"), ("sometimes", "pass", "collection")),
    }
    assert measured_scope(details) == {"everywhere"}
    assert [e["check_id"] for e in collection_wide_limitations(details)] == ["everywhere"]


def test_scope_and_the_collection_block_describe_the_same_set():
    """These are two renderings of one fact, so they must never disagree -- that
    disagreement is what let a check go unreported by both surfaces."""
    from ingest.catalog_ingest import _restamp_scope
    details = {
        "a": _doc(("uniform", "warn", "collection"), ("varies", "warn", "collection"),
                  ("plain", "pass", "clip")),
        "b": _doc(("uniform", "warn", "collection"), ("varies", "pass", "collection"),
                  ("plain", "pass", "clip")),
    }
    touched = _restamp_scope(details)
    assert touched == ["b"] or touched == ["a", "b"]
    folded = {c["check_id"] for d in details.values()
              for c in d["qa"]["checks"] if c["scope"] == "collection"}
    assert folded == {e["check_id"] for e in collection_wide_limitations(details)}
    # the varying one is back on the clip, in both records
    for d in details.values():
        assert next(c for c in d["qa"]["checks"]
                    if c["check_id"] == "varies")["scope"] == "clip"


def test_a_clip_the_check_does_not_apply_to_does_not_break_the_uniformity():
    """A drop can hold both products, and a tactile check on a camera-only clip abstains.

    Counting `not_applicable` as "did not miss" meant one camera-only clip in a thirty-clip
    drop knocked a genuinely programme-wide tactile warning off collection scope and
    reprinted it on twenty-nine tactile clip pages -- the exact noise this predicate exists
    to remove. `clips` on the collection entry then reports the clips it APPLIES to, not
    the size of the drop, because the statement covers no others.
    """
    details = {
        "a": _doc(("tactile_channel_coverage", "warn", "collection")),
        "b": _doc(("tactile_channel_coverage", "warn", "collection")),
        "camera_only": _doc(("tactile_channel_coverage", "not_applicable", "clip")),
    }
    assert measured_scope(details) == {"tactile_channel_coverage"}
    entry, = collection_wide_limitations(details)
    assert entry["check_id"] == "tactile_channel_coverage"
    assert entry["clips"] == 2, "3 would claim the camera-only clip is covered by it"


def test_one_applicable_clip_cannot_carry_a_collection_wide_claim():
    """Abstentions do not shrink the electorate to one. A check that applies to a single
    clip is a fact about that clip however loudly it misses."""
    details = {
        "a": _doc(("tactile_channel_coverage", "warn", "collection")),
        "b": _doc(("tactile_channel_coverage", "not_applicable", "clip")),
        "c": _doc(("tactile_channel_coverage", "not_applicable", "clip")),
    }
    assert measured_scope(details) == set()
    assert collection_wide_limitations(details) == []


def test_a_uniform_clip_check_is_never_promoted_to_collection():
    """Demotion only. Two clips that happen to agree do not make a check programme-scoped,
    and a two-clip corpus would otherwise promote almost everything it measures."""
    from ingest.catalog_ingest import _restamp_scope
    details = {"a": _doc(("coincidence", "warn", "clip")),
               "b": _doc(("coincidence", "warn", "clip"))}
    assert _restamp_scope(details) == []
    assert all(c["scope"] == "clip" for d in details.values() for c in d["qa"]["checks"])


def test_nothing_claims_by_design_without_a_rationale_a_buyer_can_read():
    """`by_design` says a gap is a considered position. That is only checkable if the
    reasoning ships. The one check that carried it was justified by "one operator, one rig
    and one day", which the drop contradicts on rig, day and jurisdiction -- and the
    collection record it pointed at is None whenever there is no split, so the rationale
    could not have shipped even if it had been true."""
    details = {
        "a": _doc(("split_assigned", "warn", "collection")),
        "b": _doc(("split_assigned", "warn", "collection")),
    }
    entries = collection_wide_limitations(details)
    assert [e["check_id"] for e in entries] == ["split_assigned"]
    assert entries[0]["kind"] == "not_yet_measured"
    assert all(e["kind"] != "by_design" for e in entries)
