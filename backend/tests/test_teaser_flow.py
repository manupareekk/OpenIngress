"""Teaser (free site check) flow tests."""

import json
import os

import pytest

from app.services.readiness_manager import ReadinessManager


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.supabase_client.upsert_run_metadata",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.supabase_client.mark_teaser_used",
        lambda *args, **kwargs: None,
    )
    return ReadinessManager(base_dir=str(tmp_path))


USER = "00000000-0000-4000-8000-000000000099"


def test_create_repeat_teaser_allowed(manager):
    """Homepage demo flow may start a new teaser run after a prior one."""
    first = manager.create_run(
        {"run_mode": "teaser", "siteUrl": "https://example.com"},
        user_id=USER,
    )
    second = manager.create_run(
        {"run_mode": "teaser", "siteUrl": "https://other.example"},
        user_id=USER,
    )
    assert first["run_mode"] == "teaser"
    assert second["run_mode"] == "teaser"
    assert first["run_id"] != second["run_id"]


def test_get_teaser_check_returns_limited_fields(manager):
    state = manager.create_run(
        {"run_mode": "teaser", "siteUrl": "https://example.com"},
        user_id=None,
    )
    run_id = state["run_id"]
    run_dir = os.path.join(manager.base_dir, run_id)
    audit = {
        "overall_score": 81.0,
        "agent_accessibility_score": 75.5,
        "agent_speed_score": 91.0,
    }
    with open(os.path.join(run_dir, "audit.json"), "w", encoding="utf-8") as handle:
        json.dump(audit, handle)
    with open(os.path.join(run_dir, "state.json"), encoding="utf-8") as handle:
        st = json.load(handle)
    st["status"] = "completed"
    st["teaser_complete"] = True
    st["site_url"] = "https://example.com"
    with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as handle:
        json.dump(st, handle)

    check = manager.get_teaser_check(run_id)
    assert check["overall_score"] is not None
    assert check["overall_score"] >= 70
    assert check["agent_accessibility_score"] == 75.5
    assert "agent_speed_score" not in check
    assert check["host"] == "example.com"
    assert check.get("max_pages") == 100
    assert check.get("pages_crawled") == 0


def test_get_run_blocked_for_locked_teaser(manager):
    state = manager.create_run(
        {"run_mode": "teaser", "siteUrl": "https://example.com"},
        user_id=None,
    )
    run_id = state["run_id"]
    run_dir = os.path.join(manager.base_dir, run_id)
    with open(os.path.join(run_dir, "state.json"), encoding="utf-8") as handle:
        st = json.load(handle)
    st["teaser_complete"] = True
    with open(os.path.join(run_dir, "state.json"), "w", encoding="utf-8") as handle:
        json.dump(st, handle)

    with pytest.raises(PermissionError, match="Full report is not available"):
        manager.get_run(run_id)
