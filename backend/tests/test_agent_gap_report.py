"""Tests for agent gap report analytics."""

from app.services.agent_gap_report import build_agent_gap_report


def test_build_agent_gap_report_curator_like():
    universe = {
        "source_url": "https://curator.to",
        "actions": [
            {
                "id": "home::a1",
                "page_id": "home",
                "label": "Features",
                "target_kind": "same_page_anchor",
                "on_site": True,
                "agent_priority": "high",
            },
            {
                "id": "home::a2",
                "page_id": "home",
                "label": "Join Waitlist",
                "target_kind": "unknown_js",
                "on_site": False,
                "selector": "button.cta-primary",
            },
            {
                "id": "home::a3",
                "page_id": "home",
                "label": "Request demo",
                "target_kind": "unknown_js",
                "on_site": False,
                "selector": "button.cta-primary",
            },
        ],
    }
    exploration = {
        "mode": "cursor_llm_agent",
        "llm_enabled": True,
        "total_steps": 10,
        "pages_visited": 2,
        "aria_matched_action_ids": [],
        "activated_action_ids": ["llm_link_Features"],
        "events": [
            {"action": "VIEW_PAGE", "metadata": {"path": "/"}},
            {"action": "CLICK", "element_name": "Features", "element_role": "link", "success": True},
        ],
    }
    audit = {
        "headline": "Your operations, one conversation away.",
        "recommendations": ["Fix JS-only CTAs."],
        "navigation_issues": [
            {
                "page_id": "home",
                "label": "Join Waitlist",
                "code": "unknown_js",
                "message": "Action likely depends on JavaScript",
            }
        ],
    }

    report = build_agent_gap_report(
        universe=universe,
        exploration=exploration,
        audit=audit,
        source_url="https://curator.to",
    )

    assert report["has_exploration"] is True
    assert report["efficiency"]["gap_count"] >= 1
    assert any(g["label"] == "Join Waitlist" for g in report["gaps"])
    assert any("Features" in f["text"] for f in report["findings"])
    assert report["fixes"]


def test_actions_lost_uses_catalog_when_no_on_site_actions():
    universe = {
        "actions": [
            {
                "id": "a1",
                "page_id": "home",
                "label": "Book demo",
                "target_kind": "external_exit",
                "on_site": False,
            },
            {
                "id": "a2",
                "page_id": "home",
                "label": "Broken",
                "target_kind": "dead_target",
                "on_site": False,
            },
        ],
    }
    exploration = {
        "total_steps": 5,
        "activated_action_ids": [],
        "aria_matched_action_ids": [],
        "events": [],
    }
    audit = {"agent_accessibility_score": 0.0}

    report = build_agent_gap_report(universe=universe, exploration=exploration, audit=audit)
    eff = report["efficiency"]

    assert eff["on_site_actions"] == 0
    assert eff["catalog_actions"] == 2
    assert eff["actions_lost_basis"] == "catalog"
    assert eff["actions_lost_percent"] == 100.0
