import os
import sys
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
