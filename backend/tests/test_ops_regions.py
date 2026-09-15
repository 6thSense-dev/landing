import pytest
from app.core.ops_regions import clean_region
from tests.test_ops_routes import app, _sid, _client


def doc(*sessions):
    return {"recordings": [{"sources": [{"key": f"sessions/{session}/ABC123/episode/video.mp4"}]} for session in sessions]}


@pytest.mark.parametrize("country", ["korea", "china", "vietnam", "india"])
def test_legacy_source_sessions_preserve_geography_after_raw_deletion(country):
    result = clean_region(doc(f"2026-09-03_{country}-datafarm", f"{country}-contributors"))
    assert result["key"] == country
    assert result["status"] == "classified"


def test_broker_tagged_sources_and_explicit_manifest_region():
    tagged = {"recordings": [{"sources": [{"key": "t/tenant/camera/video.mp4", "tags": {"region": "vietnam", "country": "VN"}}]}]}
    assert clean_region(tagged)["key"] == "vietnam"
    tagged["recordings"][0]["sources"][0].pop("tags")
    tagged["country"] = "CN"
    assert clean_region(tagged)["key"] == "china"


@pytest.mark.parametrize("sessions", [("korea-work", "china-work"), ("korea-work", "unknown"), ("mykorealabel",), ("unknown",)])
def test_ambiguous_or_missing_region_is_never_guessed(sessions):
    assert clean_region(doc(*sessions))["key"] == "unassigned"


def test_conflicting_tags_and_key_need_review():
    source = doc("korea-work")
    source["country"] = "US"
    assert clean_region(source)["key"] == "unassigned"
    source["country"] = "CN"
    assert clean_region(source)["status"] == "conflicting"


def test_empty_and_test_footage_stay_out_of_country_totals():
    assert clean_region({"recordings": [{"sources": []}]})["key"] == "unassigned"
    assert clean_region(doc("2026-09-03_flowtest"))["key"] == "test"


@pytest.mark.asyncio
async def test_clean_api_uses_preserved_sources_without_reassigning_or_repricing(app, db_session):
    import json
    from app.models import CleanRun, Wearer
    from tests.test_ops_clean import manifest
    sid = await _sid(db_session, "ops")
    person = Wearer(name="Contributor", location="China", rate_krw_hour=22000)
    db_session.add(person)
    await db_session.flush()
    source = manifest()
    source["recordings"][0]["sources"][0]["key"] = source["recordings"][0]["sources"][0]["key"].replace("sessions/site/", "sessions/2026-09-03_korea-datafarm/")
    original = json.dumps(source)
    run = CleanRun(run_id="factory-test", device_id="ABC123", wearer_id=person.id,
                   manifest_key="qc-results/factory-test/result.json", manifest_version="v1",
                   manifest_sha256="a" * 64, manifest_json=original,
                   retained_seconds=60, rejected_seconds=40, rate_krw_hour=11000, paid=True, amount_krw=183)
    db_session.add(run)
    await db_session.commit()
    async with _client(app) as client:
        response = await client.get("/api/ops/clean/state", cookies={"sid": sid})
    assert response.status_code == 200
    row = response.json()["runs"][0]
    assert row["region"] == {"key": "korea", "label": "Korea", "status": "classified"}
    assert row["paid"] and row["amount_krw"] == 183 and row["rate_krw_hour"] == 11000
    await db_session.refresh(run)
    assert run.manifest_json == original and run.wearer_id == person.id
