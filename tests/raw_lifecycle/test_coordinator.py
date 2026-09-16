import os
import sys
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
sys.path.insert(0, str(Path(__file__).parents[2] / "infra/raw_lifecycle"))

import coordinator as c  # noqa: E402


def raw_ref(version):
    return {
        "bucket": c.RAW,
        "key": "sessions/session/ego_20260916_010203_A1B2C3/video.mp4",
        "version_id": version,
        "bytes": 123,
        "etag": f'"{version}"',
    }


def test_nested_raw_key_belongs_to_nearest_recording_folder():
    outer = "ego_20260916_010203_A1B2C3"
    inner = "ego_20260916_040506_D4E5F6"
    key = f"sessions/session/{outer}/recovered/{inner}/video.mp4"

    assert c.find_recording(key) == inner


def test_historical_job_adoption_requires_current_source_versions(monkeypatch):
    state = {
        "recording": "ego_20260916_010203_A1B2C3",
        "snapshot": [raw_ref("current")],
        "jobs": {},
    }
    old = {
        "jobs": [{
            "kind": "conversion",
            "recording": state["recording"],
            "job_id": "historical-job",
            "plan_ref": {"version_id": "plan-v1", "sha256": "a" * 64},
        }],
    }
    monkeypatch.setattr(c, "read_pinned", lambda _ref: {
        "recording": state["recording"],
        "sources": [raw_ref("stale")],
    })

    with pytest.raises(ValueError, match="source versions differ"):
        c.adopt(state, old, {})

    assert state["jobs"] == {}


def test_uncertain_submission_is_never_blindly_retried(monkeypatch):
    class Paginator:
        def paginate(self, **_kwargs):
            return [{"jobSummaryList": []}]

    class Batch:
        def get_paginator(self, name):
            assert name == "list_jobs"
            return Paginator()

        def submit_job(self, **_kwargs):
            raise AssertionError("duplicate submission attempted")

    state = {
        "recording": "ego_20260916_010203_A1B2C3",
        "fingerprint": "f" * 64,
        "jobs": {"archive": {
            "name": "raw-life-archive-existing",
            "plan_ref": {"version_id": "plan-v1", "sha256": "a" * 64},
            "status": "SUBMITTING",
            "queue": "cpu",
        }},
    }
    monkeypatch.setattr(c, "batch", Batch())

    with pytest.raises(ValueError, match="manual reconciliation"):
        c.submit({}, state, "archive", {}, "cpu", "archive-def")


def test_pending_archive_cannot_invoke_retirement(monkeypatch):
    archive_job = {"job_id": "archive-job", "status": "RUNNING"}
    state = {
        "recording": "ego_20260916_010203_A1B2C3",
        "fingerprint": "f" * 64,
        "snapshot": [],
        "phase": "observed",
        "archive_plan": {"objects": []},
        "jobs": {"archive": archive_job},
    }
    cfg = {
        "archive_bucket": "archive",
        "cpu_queue": "cpu",
        "archive_definition": "archive-def",
        "retirement_enabled": True,
        "retirement_function": "retire-fn",
    }

    monkeypatch.setattr(c, "submit", lambda *_: archive_job)
    monkeypatch.setattr(c, "job_status", lambda job: job["status"])
    monkeypatch.setattr(c, "status", lambda _cfg, value, phase, reason: value.update(phase=phase, reason=reason))
    monkeypatch.setattr(c, "save", lambda *_: None)
    monkeypatch.setattr(c.boto3, "client", lambda service: (_ for _ in ()).throw(AssertionError(f"unexpected {service} client")))

    c.advance(cfg, state, {"imports": [{"run_id": "clean-existing"}]}, {}, {})

    assert state["phase"] == "imported"
    assert "archive_receipt" not in state


def retirement_state():
    planned = [raw_ref("v1"), {**raw_ref("v2"), "key": raw_ref("v2")["key"].replace("video.mp4", "other.mp4")}]
    return {
        "recording": "ego_20260916_010203_A1B2C3",
        "fingerprint": "f" * 64,
        "snapshot": planned,
        "archive_plan": {"objects": planned},
        "archive_receipt": {"bucket": "archive", "key": "receipt", "version_id": "rv1", "sha256": "a" * 64},
        "phase": "imported",
        "retirement_started": "2026-09-16T04:00:00+00:00",
        "jobs": {},
    }


def run_resume_handler(
    monkeypatch,
    state,
    groups,
    pinned,
    state_rows=(),
    completed=None,
    episode=None,
):
    calls = {"advanced": [], "holds": [], "saved": []}
    cfg = {"enabled": True, "run_deadline_epoch": 9_999_999_999, "settle_seconds": 0,
           "archive_bucket": "archive"}
    episode = episode or {
        "recording": state["recording"],
        "deleted": False,
        "imports": [{"run_id": "clean"}],
    }

    class Paginator:
        def paginate(self, **kwargs):
            assert kwargs["Bucket"] == c.PROCESSED
            return [{"Contents": [{"Key": key} for key in state_rows]}]

    class S3:
        def get_paginator(self, name):
            assert name == "list_objects_v2"
            return Paginator()

    def optional_json(bucket, key):
        if bucket == cfg["archive_bucket"]:
            assert key == f"retirement/{state['recording']}/{state['fingerprint']}.json"
            return completed
        if key.endswith("_CONTROL.json"):
            return {}
        assert key == c.PREFIX + "states/" + state["recording"] + ".json"
        return state

    def save(value):
        value["updated_at"] = "2026-09-16T04:30:00+00:00"
        calls["saved"].append(copy.deepcopy(value))

    monkeypatch.setattr(c, "read_json", lambda *_: (cfg, {}))
    monkeypatch.setattr(c, "optional_json", optional_json)
    monkeypatch.setattr(c, "api", lambda *_: {"episodes": [episode]})
    monkeypatch.setattr(c, "discover", lambda: groups)
    monkeypatch.setattr(c, "pin_objects", lambda objects: pinned)
    monkeypatch.setattr(c, "job_status", lambda job: job["status"])
    monkeypatch.setattr(c, "advance", lambda _cfg, value, *_: calls["advanced"].append(value.copy()))
    monkeypatch.setattr(c, "status", lambda _cfg, _state, _phase, reason: calls["holds"].append(reason))
    monkeypatch.setattr(c, "save", save)
    monkeypatch.setattr(c, "put_json", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(c, "s3", S3())

    c.handler({}, None)
    return calls


def intake_state(archive_status="SUCCEEDED"):
    ref = raw_ref("video-v1")
    return {
        "recording": "ego_20260916_010203_A1B2C3",
        "fingerprint": c.digest([c.source_identity(ref)]),
        "snapshot": [ref],
        "phase": "hold",
        "archive_plan": {"objects": [ref]},
        "jobs": {"archive": {"job_id": "archive-old", "status": archive_status}},
    }


def completed_metadata_snapshot(state):
    return [
        *state["snapshot"],
        {
            **raw_ref("metadata-v1"),
            "key": raw_ref("metadata-v1")["key"].replace("video.mp4", "metadata.json"),
        },
    ]


def intake_episode(state, imports=None):
    return {
        "recording": state["recording"],
        "deleted": False,
        "imports": [] if imports is None else imports,
    }


@pytest.mark.parametrize("archive_status", ["SUCCEEDED", "FAILED"])
def test_late_metadata_after_terminal_archive_starts_new_observation(monkeypatch, archive_status):
    state = intake_state(archive_status)
    snapshot = completed_metadata_snapshot(state)
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    groups = {state["recording"]: [{"LastModified": old}]}

    calls = run_resume_handler(
        monkeypatch, state, groups, snapshot, episode=intake_episode(state)
    )

    assert calls["holds"] == []
    assert calls["advanced"] == []
    fresh = calls["saved"][-1]
    assert fresh["phase"] == "observed"
    assert fresh["snapshot"] == snapshot
    assert fresh["fingerprint"] != state["fingerprint"]
    assert fresh["supersedes_fingerprint"] == state["fingerprint"]
    assert fresh["jobs"] == {}


def test_late_metadata_while_archive_running_stays_held(monkeypatch):
    state = intake_state("RUNNING")
    snapshot = completed_metadata_snapshot(state)
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    groups = {state["recording"]: [{"LastModified": old}]}

    calls = run_resume_handler(
        monkeypatch, state, groups, snapshot, episode=intake_episode(state)
    )

    assert calls["advanced"] == []
    assert calls["saved"] == []
    assert calls["holds"] == ["Updated upload waits for its earlier archive job to finish"]


def test_archive_only_supersession_rejects_replaced_existing_source(monkeypatch):
    state = intake_state("FAILED")
    replacement = raw_ref("video-v2")
    snapshot = completed_metadata_snapshot({**state, "snapshot": [replacement]})
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    groups = {state["recording"]: [{"LastModified": old}]}

    calls = run_resume_handler(
        monkeypatch, state, groups, snapshot, episode=intake_episode(state)
    )

    assert calls["advanced"] == []
    assert calls["saved"] == []
    assert calls["holds"] == ["New source versions arrived during processing; review before supersession"]


@pytest.mark.parametrize("activity", ["import", "conversion", "clean"])
def test_late_metadata_after_import_conversion_or_clean_stays_held(monkeypatch, activity):
    state = intake_state()
    imports = []
    if activity == "import":
        imports = [{"run_id": "clean-existing"}]
        state["jobs"] = {}
    else:
        state["jobs"][activity] = {"job_id": f"{activity}-old", "status": "SUCCEEDED"}
    snapshot = completed_metadata_snapshot(state)
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    groups = {state["recording"]: [{"LastModified": old}]}

    calls = run_resume_handler(
        monkeypatch, state, groups, snapshot, episode=intake_episode(state, imports)
    )

    assert calls["advanced"] == []
    assert calls["saved"] == []
    assert calls["holds"] == ["New source versions arrived during processing; review before supersession"]


def test_partial_retirement_resumes_with_original_state(monkeypatch):
    state = retirement_state()
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    groups = {state["recording"]: [{"LastModified": old}]}

    calls = run_resume_handler(monkeypatch, state, groups, [state["archive_plan"]["objects"][1]])

    assert calls["holds"] == []
    assert len(calls["advanced"]) == 1
    assert calls["advanced"][0]["fingerprint"] == state["fingerprint"]
    assert calls["advanced"][0]["snapshot"] == state["snapshot"]


def test_empty_raw_group_resumes_unfinished_retirement(monkeypatch):
    state = retirement_state()
    key = c.PREFIX + "states/" + state["recording"] + ".json"

    calls = run_resume_handler(monkeypatch, state, {}, [], state_rows=[key])

    assert calls["holds"] == []
    assert len(calls["advanced"]) == 1
    assert calls["advanced"][0]["retirement_started"] == state["retirement_started"]


@pytest.mark.parametrize("change", ["key", "version_id"])
def test_new_raw_identity_blocks_retirement_resume(monkeypatch, change):
    state = retirement_state()
    current = {**state["archive_plan"]["objects"][0]}
    current[change] = "sessions/session/ego_20260916_010203_A1B2C3/new.mp4" if change == "key" else "new-version"
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    groups = {state["recording"]: [{"LastModified": old}]}

    calls = run_resume_handler(monkeypatch, state, groups, [current])

    assert calls["advanced"] == []
    assert calls["holds"] == ["New source arrived during retirement; review before cleanup"]


def retirement_result(state):
    return {
        "schema": "6thsense-raw-retirement/1",
        "recording": state["recording"],
        "fingerprint": state["fingerprint"],
        "retired": True,
        "archive_receipt": state["archive_receipt"],
        "deleted_versions": [c.source_identity(ref) for ref in state["archive_plan"]["objects"]],
        "verified_at": "2026-09-16T04:20:00+00:00",
        "clean_runs": ["clean"],
    }


def test_completed_retirement_with_new_upload_starts_fresh_observation(monkeypatch):
    state = retirement_state()
    completed = retirement_result(state)
    current = {**raw_ref("new-version"), "key": raw_ref("new-version")["key"].replace("video.mp4", "new.mp4")}
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    groups = {state["recording"]: [{"LastModified": old}]}

    calls = run_resume_handler(monkeypatch, state, groups, [current], completed=completed)

    assert calls["holds"] == []
    assert calls["advanced"] == []
    assert calls["saved"][-2]["retired"] is True
    fresh = calls["saved"][-1]
    assert fresh["snapshot"] == [current]
    assert fresh["fingerprint"] != state["fingerprint"]
    assert "retirement_started" not in fresh


def test_retirement_result_must_cover_exact_archive_plan():
    state = retirement_state()
    result = retirement_result(state)
    result["deleted_versions"].pop()

    with pytest.raises(ValueError, match="Retirement audit conflicts"):
        c.validate_retirement_result(state, result)
