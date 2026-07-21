"""Composite agent readiness score from crawl universe + Cursor-style exploration."""

from __future__ import annotations

from typing import Any, Dict, Optional


def compute_agent_readiness(
    *,
    coverage: Dict[str, Any],
    universe: Dict[str, Any],
    exploration: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Readiness = how complete the catalog is + how much an aria-tree agent can use it.

    Layers:
    1. Catalog (crawl) — did we discover pages/actions/info?
    2. Static accessibility — graph-resolvable on-site targets
    3. Live aria match — actions visible in aria_snapshot on real browser
    4. Live activation — agent successfully clicked by role+name
    """
    totals = universe.get("totals") or {}
    on_site = int(totals.get("on_site_actions") or 0)
    all_actions = int(totals.get("actions") or 0)
    info_nodes = int(totals.get("info_nodes") or 0)
    pages = int(universe.get("page_count") or 0)
    internal_urls = int(universe.get("discovered_internal_url_count") or 0)

    static_accessibility = float(coverage.get("action_accessibility_percent") or 0)
    crawl_completeness = 100.0 if pages >= internal_urls else (
        round(100.0 * pages / max(1, internal_urls), 2) if internal_urls else 100.0
    )

    aria_match_rate = 0.0
    activation_rate = 0.0
    if exploration:
        aria_match_rate = float(exploration.get("aria_match_rate") or 0) * 100.0
        activation_rate = float(exploration.get("activation_rate") or 0) * 100.0

    # Weights favor what a Cursor-like agent actually experiences in the browser.
    if exploration:
        readiness = round(
            crawl_completeness * 0.15
            + static_accessibility * 0.25
            + aria_match_rate * 0.35
            + activation_rate * 0.25,
            1,
        )
    else:
        readiness = round(
            crawl_completeness * 0.2 + static_accessibility * 0.8,
            1,
        )

    return {
        "readiness_score": readiness,
        "crawl_completeness_percent": crawl_completeness,
        "static_accessibility_percent": static_accessibility,
        "aria_match_percent": round(aria_match_rate, 2),
        "activation_percent": round(activation_rate, 2),
        "catalog": {
            "pages": pages,
            "internal_urls_discovered": internal_urls,
            "total_actions": all_actions,
            "on_site_actions": on_site,
            "info_nodes": info_nodes,
        },
        "methodology": _methodology(bool(exploration)),
    }


def _methodology(has_exploration: bool) -> str:
    if has_exploration:
        return (
            "Universe built from full crawl (HTML + nav graph). "
            "Cursor-style pass uses Playwright aria_snapshot and getByRole clicks with screenshots. "
            "Vision is evidence only; action discovery is accessibility-tree first."
        )
    return (
        "Universe built from crawl only. Run agent exploration to score aria match and activation."
    )


def _clamp_score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _metric_float(metrics: Dict[str, Any], key: str, default: float) -> float:
    """Read a numeric metric without treating 0 as missing."""
    if key not in metrics or metrics[key] is None:
        return default
    return float(metrics[key])


def _static_pass_percent(static_audits: Optional[Dict[str, Any]]) -> float:
    if not static_audits:
        return 100.0
    ratio = static_audits.get("pass_ratio")
    if ratio is not None:
        return float(ratio) * 100.0
    passed = static_audits.get("passed")
    total = static_audits.get("total")
    if passed is not None and total:
        return 100.0 * float(passed) / float(total)
    checks = static_audits.get("checks") or []
    if checks:
        ok = sum(1 for check in checks if check.get("passed"))
        return 100.0 * ok / len(checks)
    return 100.0


def compute_overall_agent_score(
    *,
    agent_accessibility_score: float,
    agent_speed_score: float,
    static_audits: Optional[Dict[str, Any]] = None,
    exploration: Optional[Dict[str, Any]] = None,
    agent_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Headline score shown in the UI.

    - Crawl-only: accessibility + speed + static operability (llms.txt, labels, DOM).
    - After explore: crawl base plus live aria match, activation, efficiency, and gap penalty
      so recommended site fixes move the number when the agent performs better.
    """
    accessibility = float(agent_accessibility_score or 0)
    speed = float(agent_speed_score or 0)
    crawl_base = round(accessibility * 0.7 + speed * 0.3, 1)
    static_pct = _static_pass_percent(static_audits)

    if not exploration:
        static_delta = (static_pct - 80.0) * 0.08
        overall = _clamp_score(crawl_base + static_delta)
        return {
            "overall_score": overall,
            "crawl_base_score": crawl_base,
            "score_breakdown": {
                "crawl_accessibility": accessibility,
                "crawl_speed": speed,
                "static_operability": round(static_pct, 1),
                "explore_delta": 0.0,
                "includes_explore": False,
            },
            "score_methodology": _overall_methodology(False),
        }

    aria = float(exploration.get("aria_match_rate") or 0) * 100.0
    activation = float(exploration.get("activation_rate") or 0) * 100.0
    efficiency = (agent_report or {}).get("efficiency") or {}
    actions_lost = _metric_float(efficiency, "actions_lost_percent", 100.0)
    gap_count = int(_metric_float(efficiency, "gap_count", 0))
    high_gaps = int(_metric_float(efficiency, "high_gaps", 0))

    explore_delta = (
        (aria - 85.0) * 0.12
        + activation * 0.38
        + max(0.0, 40.0 - actions_lost) * 0.10
        - gap_count * 0.35
        - high_gaps * 1.25
    )
    static_delta = (static_pct - 80.0) * 0.06
    combined_delta = explore_delta + static_delta
    overall = _clamp_score(crawl_base + combined_delta)

    return {
        "overall_score": overall,
        "crawl_base_score": crawl_base,
        "score_breakdown": {
            "crawl_accessibility": accessibility,
            "crawl_speed": speed,
            "static_operability": round(static_pct, 1),
            "aria_match": round(aria, 1),
            "activation": round(activation, 1),
            "actions_lost_percent": round(actions_lost, 1),
            "gap_count": gap_count,
            "explore_delta": round(combined_delta, 1),
            "includes_explore": True,
        },
        "score_methodology": _overall_methodology(True),
    }


def refresh_audit_overall_score(
    audit: Dict[str, Any],
    *,
    static_audits: Optional[Dict[str, Any]] = None,
    exploration: Optional[Dict[str, Any]] = None,
    agent_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Recompute headline overall_score on audit dict (after explore or report rebuild)."""
    scored = compute_overall_agent_score(
        agent_accessibility_score=float(audit.get("agent_accessibility_score") or 0),
        agent_speed_score=float(audit.get("agent_speed_score") or 0),
        static_audits=static_audits
        or audit.get("static_audits")
        or (agent_report or {}).get("static_audits"),
        exploration=exploration,
        agent_report=agent_report or audit.get("agent_report"),
    )
    audit.update(scored)
    return audit


def _overall_methodology(has_exploration: bool) -> str:
    if has_exploration:
        return (
            "Overall = crawl accessibility/speed base + live agent bonus "
            "(aria match, activation, low actions-lost) − gap penalty + static operability."
        )
    return "Overall = crawl accessibility/speed + static operability (llms.txt, labels, DOM)."
