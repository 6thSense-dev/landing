"""The shape of the DELIVERED corpus, and the gap corpus that still has to exist.

    cd scripts/catalog && python3 -m pytest tests -q     (or: make -C scripts/catalog test)

`plan()` decides everything about a take that is not measured off the bytes -- country,
capture rig, which hands were instrumented, which modality is missing -- so it can be
asserted without ffmpeg, numpy or twenty minutes of encoding.

Two corpora, and the difference between them is the point:

  * the DEFAULT is the product. Every clip is egocentric stereo video plus both tactile
    gloves plus IMU plus segcap, recorded in CN or HK. No mono clip, no video-only clip,
    no one-handed clip, no clip with an unknown country. A buyer scrolling the grid must
    not have to work out which cards are the real offer.
  * `--with-gaps` puts the holes back, because the UI paths they exercise -- a disabled
    tab, an em-dash for a genuinely unknown value, a one-hand channel census, a mono pane
    with no disparity -- are live code with no other fixture behind them. Delete the only
    input that reaches those branches and they rot until a real take finally has a hole.
    It ALSO carries the two camera-only takes, which are not holes at all: camera-only is
    the second product this rig sells, and it sits behind the flag only because this drop
    happens to contain none of it.

So both are tested here. If the gap corpus ever stops producing a gap, this file fails
before the UI does.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# fixtures/ is a script directory, not a package. Load it by path rather than adding a
# second sys.path entry that pytest would then also collect from.
_spec = importlib.util.spec_from_file_location(
    "generate_fixtures", ROOT / "fixtures" / "generate_fixtures.py")
gf = importlib.util.module_from_spec(_spec)
sys.modules["generate_fixtures"] = gf
_spec.loader.exec_module(gf)

CLIPS, SEED = 30, 7
#: The whole permitted country set. Two entries, and both are separate ISO 3166-1
#: alpha-2 codes: HK is its own code, not a subdivision of CN.
COUNTRIES = {"CN", "HK"}


def _corpus(with_gaps: bool, clips: int = CLIPS, seed: int = SEED) -> list[dict]:
    ccs = gf.country_sequence(clips, seed)
    return [gf.plan(i, seed, with_gaps, ccs) for i in range(clips)]


@pytest.fixture(scope="module")
def default() -> list[dict]:
    return _corpus(with_gaps=False)


@pytest.fixture(scope="module")
def gapped() -> list[dict]:
    return _corpus(with_gaps=True)


# --------------------------------------------------------------------------- #
# the delivered corpus                                                         #
# --------------------------------------------------------------------------- #

def test_the_default_corpus_is_thirty_takes(default):
    assert len(default) == CLIPS
    assert len({p["take_id"] for p in default}) == CLIPS, "take ids collide"


def test_every_clip_is_stereo(default):
    """Egocentric STEREO is the product. There is no mono clip in the drop."""
    assert [p["take_id"] for p in default if not p["stereo"]] == []


def test_every_clip_carries_both_tactile_hands(default):
    """This DROP is all camera-plus-tactile.

    Not a statement about the product line -- camera-only is the other product and it is
    an equal, see the camera-only tests below. It is a statement about what was handed to
    the ingest for this delivery: 30 takes, every one of them with both gloves. A
    one-handed clip is a fault in either product and is never what was sold.
    """
    assert [p["take_id"] for p in default if p["hands"] != ["left", "right"]] == []


def test_every_clip_carries_imu_and_segcap(default):
    """No disabled tab in the delivered corpus: `gap` is what removes a modality."""
    assert [p["take_id"] for p in default if p["gap"]] == []


def test_only_china_and_hong_kong(default):
    """Two countries, no third, and never a null."""
    assert {p["country"] for p in default} == COUNTRIES
    assert all(p["country"] for p in default)


def test_the_country_mix_is_apportioned_not_sampled(default):
    """60/40 by weight, so the mix holds at any --clips instead of in expectation."""
    counts = {cc: sum(1 for p in default if p["country"] == cc) for cc in COUNTRIES}
    assert counts == {"CN": 18, "HK": 12}


@pytest.mark.parametrize("clips", [1, 5, 7, 12, 30, 31])
def test_the_two_country_scope_holds_at_every_clip_count(clips):
    """--clips 5 is the fast loop while iterating; it must not widen the scope."""
    corpus = _corpus(with_gaps=False, clips=clips)
    assert {p["country"] for p in corpus} <= COUNTRIES
    assert all(p["stereo"] and p["hands"] == ["left", "right"] for p in corpus)


def test_every_country_the_fixture_emits_has_a_display_label():
    """The pool and the label table are two files; this is the join between them.

    `country_label` refuses an unnameable code at build time, which is the real gate.
    This one fails in a second rather than twenty minutes into an ffmpeg run.
    """
    from ingest.benchmark import country_label
    for code, _weight in gf.COUNTRY_WEIGHTS:
        assert country_label(code) not in ("", code)
    assert country_label("CN") == "China"
    assert country_label("HK") == "Hong Kong"


def test_every_country_in_the_pool_has_a_timezone():
    """`plan` indexes TZ by country; a missing entry is a KeyError mid-run."""
    assert {cc for cc, _ in gf.COUNTRY_WEIGHTS} <= set(gf.TZ)


# --------------------------------------------------------------------------- #
# the buyer-facing prose is grammatical                                        #
# --------------------------------------------------------------------------- #

def test_every_environment_gets_the_right_indefinite_article():
    """"in a indoor workshop" shipped on a third of the corpus's Metadata tabs.

    Eight of the environments start with "indoor", and the description template used
    a hardcoded "a". The article is computed now; this asserts it over the real pool
    rather than over an example, so a new vowel-initial environment cannot reintroduce
    it silently.
    """
    vowel = {t["env"] for t in gf.POOL if t["env"].lstrip()[:1].lower() in "aeiou"}
    assert vowel, "the pool no longer has a vowel-initial environment to guard"
    for take in gf.POOL:
        art = gf._article(take["env"])
        assert art == ("an" if take["env"] in vowel else "a"), take["env"]


def test_the_article_handles_sound_not_spelling():
    """The usual exceptions, so the helper is not a bare vowel-letter test."""
    assert gf._article("hour-long take") == "an"
    assert gf._article("one-piece housing") == "a"
    assert gf._article("unit under test") == "a"
    assert gf._article("") == "a"


# --------------------------------------------------------------------------- #
# the gap corpus still exists and still has gaps                               #
# --------------------------------------------------------------------------- #

def test_with_gaps_restores_every_named_gap(gapped):
    """Each of these is the only fixture behind a live UI or grader branch."""
    assert {p["gap"] for p in gapped if p["gap"]} == {
        "right_hand_only", "no_imu", "no_country", "no_segcap", "no_tactile", "mono",
        "camera_only_clean"}


def test_the_gap_corpus_exercises_the_mono_pane(gapped):
    mono = [p for p in gapped if not p["stereo"]]
    assert len(mono) == 1 and mono[0]["gap"] == "mono"


def test_the_gap_corpus_exercises_one_hand_and_no_hands(gapped):
    assert [p["hands"] for p in gapped if p["gap"] == "right_hand_only"] == [["right"]]
    assert [p["hands"] for p in gapped if p["gap"] == "no_tactile"] == [[]]


# --------------------------------------------------------------------------- #
# the second product: camera-only is not a gap                                 #
# --------------------------------------------------------------------------- #

def test_the_corpus_carries_both_camera_only_ends_of_the_quality_range(gapped):
    """One camera-only take that must grade DOWN, one that must reach A.

    The grader has to get both right and they fail in opposite directions. A camera-only
    take that cannot reach A means the grade rule is charging a product for questions
    about a different product -- that is the defect `not_applicable` was added to fix. A
    camera-only take with real defects that reaches A anyway means `not_applicable` has
    become a loophole, which is the defect the fix must not introduce.
    """
    cam = {p["gap"]: p for p in gapped if p["gap"] in gf.CAMERA_ONLY}
    assert set(cam) == {"no_tactile", "camera_only_clean"}
    assert all(p["hands"] == [] for p in cam.values())
    assert all(p["stereo"] for p in cam.values()), "both products are stereo; mono is a fault"
    assert cam["no_tactile"]["prof"] == "caveat"
    assert cam["camera_only_clean"]["prof"] == "clean"


def test_the_clean_camera_only_take_delivers_exactly_one_clocked_stream(gapped):
    """No gloves AND no IMU, so `sync_max_skew_ms` has nothing to be a skew between.

    That is the only shape in which the two sync checks are honestly inapplicable, and it
    is the only shape in which this fixture can reach grade A without asserting a
    common-mode physical event that the take's own metadata says nobody solved.
    """
    clean = next(p for p in gapped if p["gap"] == "camera_only_clean")
    assert clean["hands"] == [] and clean["imu"] is False
    # ... and the take that keeps its IMU keeps the alignment question with it.
    assert next(p for p in gapped if p["gap"] == "no_tactile")["imu"] is True


def test_a_camera_only_take_is_never_described_as_wearing_a_glove(gapped):
    """The prose a buyer reads on the Metadata tab.

    The template that fed both products the same sentence produced "the camera share one
    host clock" on a glove-less take, and sold time alignment as the value of a package
    with one stream to align.
    """
    for p in (x for x in gapped if x["gap"] in gf.CAMERA_ONLY):
        long = p["spec"]["long"]
        assert "tactile arrays are worn" not in long, p["take_id"]
        assert "gloves and the camera share" not in long, p["take_id"]
        assert "the camera share one host clock" not in long, p["take_id"]
        assert "camera-only product" in long, p["take_id"]
    # ... and the tactile takes still say what they always said.
    worn = next(x for x in gapped if x["hands"] == ["left", "right"])
    assert "tactile arrays are worn snug" in worn["spec"]["long"]


def test_only_a_take_that_wore_a_glove_claims_a_clap():
    """`validation_method` is rendered verbatim on the Calib & sync tab.

    It describes a BIMANUAL CLAP. A camera-only take has no hands to clap with, so quoting
    it there would publish a measurement that could not have happened. And a take with
    neither glove nor IMU has one clocked stream, so there is nothing to corroborate at all
    -- null, which is what makes the ingest read the check as `not_applicable` rather than
    as a validation somebody skipped.
    """
    both = ["left", "right"]
    assert "bimanual clap" in gf.validation_method(True, both, True)
    assert "bimanual clap" in gf.validation_method(True, both, False)
    # camera + IMU: a real pair, and a real common-mode event that does not involve a glove
    cam_imu = gf.validation_method(True, [], True)
    assert "clap" not in cam_imu and "IMU accelerometer" in cam_imu
    # not corroborated, but there WAS something to corroborate
    assert "rests on the shared host clock" in gf.validation_method(False, [], True)
    assert "rests on the shared host clock" in gf.validation_method(False, both, True)
    # one clocked stream: nothing to validate, so nothing is claimed and nothing is withheld
    assert gf.validation_method(True, [], False) is None
    assert gf.validation_method(False, [], False) is None


def test_the_gap_corpus_still_only_uses_the_two_countries(gapped):
    """`no_country` drops the value; it never substitutes a third country."""
    assert {p["country"] for p in gapped} == COUNTRIES


def test_the_gap_corpus_leaves_the_rest_of_the_corpus_alone(gapped, default):
    """A flag that changed 30 takes to prove 6 branches would prove nothing else."""
    changed = [d["take_id"] for d, g in zip(default, gapped)
               if (d["stereo"], d["hands"], d["country"]) != (g["stereo"], g["hands"], g["country"])]
    # mono, right_hand_only, and the two camera-only takes; no_country keeps its code
    assert len(changed) == 4
    assert all(d["take_id"] == g["take_id"] for d, g in zip(default, gapped))


def test_the_unassessed_privacy_field_is_a_gap_not_a_default(default, gapped):
    """`faces_redacted: null` means "nobody looked". The delivered corpus looked."""
    assert all(p["privacy"].get("faces_redacted") is not None for p in default)
    assert any(p["privacy"].get("faces_redacted") is None for p in gapped)
