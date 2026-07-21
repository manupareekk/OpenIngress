import json
import os

from app.config import Config
from app.models import RunStatus
from app.services.readiness_manager import ReadinessManager


def test_cancel_run_marks_running_run_terminal(tmp_path):
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run({"title": "cancel me"}, user_id="dev")
    run_id = state["run_id"]
    state_path = os.path.join(tmp_path, run_id, "state.json")

    with open(state_path, encoding="utf-8") as handle:
        running_state = json.load(handle)
    running_state["status"] = RunStatus.RUNNING.value
    running_state["job_phase"] = "crawl"
    running_state["progress"] = "Crawling page 1/50..."
    running_state["progress_pct"] = 10
    with open(state_path, "w", encoding="utf-8") as handle:
        json.dump(running_state, handle)

    cancelled = manager.cancel_run(run_id, user_id="dev")

    assert cancelled["cancel_requested"] is True
    assert cancelled["status"] == RunStatus.FAILED.value
    assert cancelled["job_phase"] is None
    assert cancelled["error"] == "Cancelled by user"
    assert cancelled["progress"] == "Cancelled"
    assert cancelled["progress_pct"] == 0


def test_get_run_persists_synced_overall_score(tmp_path):
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run(
        {"title": "score sync", "siteUrl": "https://example.com"},
        user_id="dev",
    )
    run_id = state["run_id"]
    run_dir = os.path.join(tmp_path, run_id)
    state["site_url"] = "https://example.com/"
    manager._write_json(str(run_dir), "state.json", state)

    audit = {
        "agent_accessibility_score": 75.0,
        "agent_speed_score": 80.0,
    }
    with open(os.path.join(run_dir, "audit.json"), "w", encoding="utf-8") as handle:
        json.dump(audit, handle)
    with open(os.path.join(run_dir, "snapshot_before.json"), "w", encoding="utf-8") as handle:
        json.dump({"static_audits": {"pass_ratio": 1.0}}, handle)

    result = manager.get_run(run_id)

    assert result["audit"]["overall_score"] is not None
    with open(os.path.join(run_dir, "state.json"), encoding="utf-8") as handle:
        persisted_state = json.load(handle)
    assert persisted_state["overall_score"] == result["audit"]["overall_score"]


def test_get_run_hydrates_commerce_inputs_from_draft(tmp_path):
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run(
        {
            "title": "commerce setup",
            "siteUrl": "https://shop.example.com",
            "commerce_inputs": {
                "monthly_sessions": 50000,
                "average_order_value": 85,
                "conversion_rate": 2.4,
                "agent_traffic_share": 5,
            },
        },
        user_id="dev",
    )
    run_id = state["run_id"]
    run_dir = os.path.join(tmp_path, run_id)
    state.pop("commerce_inputs", None)
    manager._write_json(str(run_dir), "state.json", state)

    result = manager.get_run(run_id)

    assert result["state"]["commerce_inputs"] == {
        "monthly_sessions": 50000,
        "average_order_value": 85,
        "conversion_rate": 2.4,
        "agent_traffic_share": 5,
    }
    with open(os.path.join(run_dir, "state.json"), encoding="utf-8") as handle:
        persisted_state = json.load(handle)
    assert persisted_state["commerce_inputs"]["monthly_sessions"] == 50000


def test_get_run_returns_report_payload_without_raw_snapshot(tmp_path):
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run(
        {"title": "report payload", "siteUrl": "https://example.com"},
        user_id="dev",
    )
    run_id = state["run_id"]
    run_dir = os.path.join(tmp_path, run_id)
    state["site_url"] = "https://example.com/"
    state["import_complete"] = True
    manager._write_json(str(run_dir), "state.json", state)

    manager._write_json(
        str(run_dir),
        "snapshot_before.json",
        {
            "source_url": "https://example.com/",
            "static_audits": {"checks": [{"id": "llms-txt", "status": "pass"}]},
            "pages": [
                {
                    "id": "home",
                    "path": "/",
                    "title": "Home",
                    "html": ('<a href="/products/classic-tee">Classic Tee</a>' + "RAW_HTML_SHOULD_NOT_BE_RETURNED" * 1000),
                }
            ],
            "navigation_graph": {
                "pages": [{"id": "home", "path": "/"}],
                "actions": [
                    {
                        "id": "home::product",
                        "page_id": "home",
                        "element_text": "Classic Tee",
                        "target_path": "/products/classic-tee",
                        "target_kind": "internal_link",
                        "attributes": {},
                    }
                ],
            },
        },
    )
    manager._write_json(
        str(run_dir),
        "audit.json",
        {
            "page_type": "ecommerce",
            "platform": "shopify",
            "overall_score": 72,
            "agent_accessibility_score": 68,
            "agent_speed_score": 83,
            "recommendations": ["Label important actions."],
        },
    )
    manager._write_json(
        str(run_dir),
        "agent_report.json",
        {
            "source_url": "https://example.com/",
            "has_exploration": True,
            "static_audits": {"checks": [{"id": "llms-txt", "status": "pass"}]},
            "efficiency": {"actions_lost_percent": 12, "step_waste_percent": 5},
            "findings": [{"text": "Checkout button was hard to target."}],
            "fixes": [{"label": "Add button label", "priority": "high", "change": "Add aria-label."}],
            "job_results": [{"id": "checkout", "job": "Checkout", "status": "failed"}],
            "gaps": [{"type": "button-labels", "label": "Checkout"}],
        },
    )
    manager._write_json(str(run_dir), "universe.json", {"actions": [{"id": "raw"}]})
    manager._write_json(str(run_dir), "exploration.json", {"events": [{"raw": True}]})
    manager._write_jsonl(
        str(run_dir),
        "events.jsonl",
        [
            {
                "session_id": "s1",
                "task_id": "checkout",
                "snapshot_phase": "before",
                "step": 1,
                "action": "VIEW_PAGE",
                "url": "https://example.com/",
                "metadata": {
                    "screenshots": {
                        "viewport": {
                            "url": "/api/ingress/runs/run_x/screenshots/home.png",
                            "label": "home.png",
                        }
                    },
                    "large_internal_blob": "DROP_ME",
                },
            }
        ],
    )

    result = manager.get_run(run_id)
    encoded = json.dumps(result)

    assert "snapshot_before" not in result
    assert "coverage_before" not in result
    assert "universe" not in result
    assert "exploration" not in result
    assert "RAW_HTML_SHOULD_NOT_BE_RETURNED" not in encoded
    assert "DROP_ME" not in encoded
    assert result["audit"]["overall_score"] is not None
    assert result["audit"]["agent_accessibility_score"] == 68
    assert result["agent_report"]["has_exploration"] is True
    assert result["agent_report"]["efficiency"]["actions_lost_percent"] == 12
    assert result["exports"]["checks"]
    assert "shopify_report" not in (result.get("exports") or {})
    assert "commerce_contract" not in (result.get("exports") or {})
    assert result["exports"]["skill_md"]
    assert result["events"][0]["metadata"]["screenshots"]["viewport"]["label"] == "home.png"


def test_score_sync_does_not_regress_terminal_state(tmp_path):
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run({"title": "terminal"}, user_id="dev")
    run_id = state["run_id"]
    run_dir = os.path.join(tmp_path, run_id)
    completed_state = dict(state)
    completed_state["status"] = RunStatus.COMPLETED.value
    completed_state["job_phase"] = None
    completed_state["progress"] = "Agent exploration complete"
    manager._write_json(str(run_dir), "state.json", completed_state)

    stale_result = {
        "state": {
            **state,
            "status": RunStatus.RUNNING.value,
            "job_phase": "explore",
            "progress": "Running agent exploration...",
        },
        "audit": {"agent_accessibility_score": 80, "agent_speed_score": 90},
    }

    manager._sync_overall_score(str(run_dir), stale_result)

    with open(os.path.join(run_dir, "state.json"), encoding="utf-8") as handle:
        persisted = json.load(handle)
    assert persisted["status"] == RunStatus.COMPLETED.value
    assert persisted["job_phase"] is None
    assert persisted["progress"] == "Agent exploration complete"
    assert persisted["overall_score"] is not None


def test_get_run_recovers_stale_running_explore_from_agent_report(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "QUEUED_RUN_STALE_SECONDS", 60)
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run({"title": "stale", "siteUrl": "https://example.com"}, user_id="dev")
    run_id = state["run_id"]
    run_dir = os.path.join(tmp_path, run_id)
    state.update(
        {
            "status": RunStatus.RUNNING.value,
            "job_phase": "explore",
            "progress": "Running agent exploration...",
            "progress_pct": 50,
            "updated_at": "2000-01-01T00:00:00Z",
            "site_url": "https://example.com/",
        }
    )
    manager._write_json(str(run_dir), "state.json", state)
    manager._write_json(
        str(run_dir),
        "audit.json",
        {"overall_score": 70, "agent_accessibility_score": 70, "agent_speed_score": 70},
    )
    manager._write_json(
        str(run_dir),
        "agent_report.json",
        {
            "source_url": "https://example.com/",
            "has_exploration": False,
            "efficiency": {"gap_count": 1},
            "fixes": [],
            "findings": [],
            "job_results": [],
        },
    )

    result = manager.get_run(run_id)

    assert result["state"]["status"] == RunStatus.COMPLETED.value
    assert result["state"]["job_phase"] is None
    assert result["state"]["progress"] == "Agent exploration incomplete"
    assert result["state"]["recovery_reason"] == "agent_report_present"


def test_get_run_recovers_interrupted_crawl_from_partial_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(Config, "QUEUED_RUN_STALE_SECONDS", 60)
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run({"title": "partial", "siteUrl": "https://gymshark.com"}, user_id="dev")
    run_id = state["run_id"]
    run_dir = os.path.join(tmp_path, run_id)
    state.update(
        {
            "status": RunStatus.RUNNING.value,
            "job_phase": "crawl",
            "progress": "Crawling page 12/50...",
            "progress_pct": 22,
            "updated_at": "2000-01-01T00:00:00Z",
            "site_url": "https://www.gymshark.com/",
        }
    )
    manager._write_json(str(run_dir), "state.json", state)
    manager._write_json(
        str(run_dir),
        "snapshot_before.json",
        {
            "phase": "before",
            "label": "Before fixes",
            "source_url": "https://www.gymshark.com/",
            "pages": [
                {
                    "id": "home",
                    "path": "/",
                    "title": "Gymshark",
                    "html": "<html><body><main><h1>Gymshark</h1><a href='/collections/mens'>Men</a><button>Add to cart</button></main></body></html>",
                    "is_start": True,
                    "is_conversion": False,
                    "metadata": {"final_url": "https://www.gymshark.com/", "import_mode": "rendered_browser"},
                }
            ],
            "navigation_graph": {
                "variant_id": "A",
                "start_page_id": "home",
                "pages": [{"id": "home", "path": "/", "title": "Gymshark"}],
                "actions": [],
                "issues": [],
                "quality": {"extractor": "rendered_browser"},
                "extractor": "rendered_browser",
            },
            "static_audits": {"checks": [], "passed": 0, "total": 0, "pass_ratio": 1.0},
        },
    )

    result = manager.get_run(run_id)

    assert result["state"]["status"] == RunStatus.DRAFT.value
    assert result["state"]["progress"] == "Crawl complete"
    assert result["state"]["recovery_reason"] == "crawl_artifacts_present"
    assert "error" not in result["state"]
    assert result["state"]["pages_crawled"] == 1
    assert result["audit"]["overall_score"] is not None
    assert os.path.isfile(os.path.join(run_dir, "audit.json"))


def test_get_run_recovers_failed_missing_artifacts_when_snapshot_exists(tmp_path):
    manager = ReadinessManager(base_dir=str(tmp_path))
    state = manager.create_run({"title": "failed partial", "siteUrl": "https://gymshark.com"}, user_id="dev")
    run_id = state["run_id"]
    run_dir = os.path.join(tmp_path, run_id)
    state.update(
        {
            "status": RunStatus.FAILED.value,
            "job_phase": None,
            "progress": "Job interrupted",
            "progress_pct": 0,
            "error": "Worker stopped before producing report artifacts",
            "recovery_reason": "missing_artifacts",
            "updated_at": "2000-01-01T00:00:00Z",
            "site_url": "https://www.gymshark.com/",
        }
    )
    manager._write_json(str(run_dir), "state.json", state)
    manager._write_json(
        str(run_dir),
        "snapshot_before.json",
        {
            "phase": "before",
            "label": "Before fixes",
            "source_url": "https://www.gymshark.com/",
            "pages": [
                {
                    "id": "home",
                    "path": "/",
                    "title": "Gymshark",
                    "html": "<html><body><main><h1>Gymshark</h1><a href='/collections/mens'>Men</a></main></body></html>",
                    "is_start": True,
                    "is_conversion": False,
                    "metadata": {"final_url": "https://www.gymshark.com/", "import_mode": "rendered_browser"},
                }
            ],
            "navigation_graph": {
                "variant_id": "A",
                "start_page_id": "home",
                "pages": [{"id": "home", "path": "/", "title": "Gymshark"}],
                "actions": [],
                "issues": [],
                "quality": {"extractor": "rendered_browser"},
                "extractor": "rendered_browser",
            },
            "static_audits": {"checks": [], "passed": 0, "total": 0, "pass_ratio": 1.0},
        },
    )

    result = manager.get_run(run_id)

    assert result["state"]["status"] == RunStatus.DRAFT.value
    assert result["state"]["recovery_reason"] == "crawl_artifacts_present"
    assert "error" not in result["state"]
    assert result["audit"]["overall_score"] is not None
