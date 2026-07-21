"""Tests for OpenIngress gap taxonomy."""

from app.services.gap_taxonomy import (
    match_names_for_action,
    CATALOG_NOT_ACTIVATED,
    CLIENT_ONLY,
    NAME_UNMATCHABLE,
    OFF_SITE_EXIT,
    UNLABELED_STATIC,
    action_in_static_html,
    allows_accessible_name_fix,
    audit_recommendation_to_fix,
    classify_action_gap,
    dedupe_gaps,
    explore_is_valid,
    explore_min_steps,
    recommendation_for_gap,
    site_fix_eligible,
)
from app.services.catalog_activation import pick_catalog_actions_for_page


def test_explore_min_steps():
    assert explore_min_steps(1) == 15
    assert explore_min_steps(10) == 20
    assert explore_is_valid(14, 10) is False
    assert explore_is_valid(20, 10) is True


def test_activated_actions_have_no_gap():
    action = {"target_kind": "internal_page", "label": "WORK"}
    row = {
        "label": "WORK",
        "target_kind": "internal_page",
        "catalog_accessible": True,
        "aria_matched": False,
        "agent_activated": True,
    }
    assert (
        classify_action_gap(
            action,
            row,
            in_static_html=True,
            in_hydrated_tree=True,
            explore_valid=True,
        )
        is None
    )


def test_back_link_name_aliases():
    action = {
        "label": "← back",
        "selector": 'a[aria-label="Back to writing"]',
        "role": "link",
    }
    names = match_names_for_action(action)
    assert "back to writing" in [n.lower() for n in names]


def test_classify_client_only_when_hydrated_only():
    action = {"target_kind": "same_page_anchor", "label": "HOME"}
    row = {
        "label": "HOME",
        "target_kind": "same_page_anchor",
        "catalog_accessible": True,
        "aria_matched": True,
        "agent_activated": False,
    }
    gap = classify_action_gap(
        action,
        row,
        in_static_html=False,
        in_hydrated_tree=True,
        explore_valid=True,
    )
    assert gap == CLIENT_ONLY


def test_no_generic_name_fix_for_catalog_not_activated():
    assert allows_accessible_name_fix(CATALOG_NOT_ACTIVATED) is False
    assert site_fix_eligible(CATALOG_NOT_ACTIVATED, in_static_html=True) is False
    assert site_fix_eligible(CATALOG_NOT_ACTIVATED, in_static_html=False) is True
    assert site_fix_eligible(CATALOG_NOT_ACTIVATED, in_static_html=True, also_client_only=True) is True
    assert site_fix_eligible(CATALOG_NOT_ACTIVATED, in_static_html=True, name_unmatchable=True) is True


def test_action_in_static_html_uses_selector_not_body_noise():
    html = '<html><body>home is where the heart is<p></body>'
    assert action_in_static_html({"label": "home"}, html) is False
    html_nav = '<nav><a href="/work">Work</a></nav>'
    assert action_in_static_html(
        {"label": "Work", "selector": 'a[href="/work"]', "target_path": "/work"},
        html_nav,
    )


def test_dedupe_gaps_drops_duplicate_nav_issue():
    gaps = [
        {"id": "a1", "page_id": "home", "label": "Join", "type": CLIENT_ONLY, "severity": "high"},
        {
            "id": "nav::home::Join",
            "page_id": "home",
            "label": "Join",
            "type": CLIENT_ONLY,
            "severity": "medium",
        },
    ]
    out = dedupe_gaps(gaps)
    assert len(out) == 1


def test_audit_recommendation_filters_generic_aria():
    assert audit_recommendation_to_fix("Make this control discoverable via role + accessible name") is None
    assert audit_recommendation_to_fix("Add /llms.txt at domain root with site summary")["gap_type"] == "llms_txt"


def test_writing_slug_pick_from_catalog():
    actions = [
        {
            "id": "w1",
            "label": "My Post Title",
            "target_kind": "same_page_anchor",
            "target_path": "/writing/my-post",
            "role": "link",
        }
    ]
    picks = pick_catalog_actions_for_page("/writing", actions, activated_ids=set(), budget_met=set())
    assert picks and picks[0]["id"] == "w1"


def test_name_unmatchable_long_label():
    long_label = "Jan 1, 2025 " + ("Article title " * 10) + "5 min read excerpt"
    action = {"target_kind": "same_page_anchor", "label": long_label}
    row = {
        "label": long_label,
        "target_kind": "same_page_anchor",
        "catalog_accessible": True,
        "aria_matched": False,
        "agent_activated": False,
    }
    gap = classify_action_gap(
        action,
        row,
        in_static_html=True,
        in_hydrated_tree=False,
        explore_valid=True,
    )
    assert gap == NAME_UNMATCHABLE
    text = recommendation_for_gap({"type": NAME_UNMATCHABLE, "label": long_label, "page_id": "writing"})
    assert "aria-label" in (text or "")


def test_off_site_informational():
    action = {"target_kind": "external_exit", "label": "Twitter"}
    row = {"label": "Twitter", "target_kind": "external_exit", "catalog_accessible": False}
    assert (
        classify_action_gap(
            action,
            row,
            in_static_html=True,
            in_hydrated_tree=False,
            explore_valid=True,
        )
        == OFF_SITE_EXIT
    )
    assert recommendation_for_gap({"type": OFF_SITE_EXIT, "label": "Twitter"}) is None


def test_unlabeled_static_allows_name_fix():
    assert allows_accessible_name_fix(UNLABELED_STATIC) is True
    text = recommendation_for_gap({"type": UNLABELED_STATIC, "label": "", "page_id": "home"})
    assert "aria-label" in (text or "").lower() or "accessible name" in (text or "").lower()
