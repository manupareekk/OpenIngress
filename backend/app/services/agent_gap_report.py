"""Structured agent findings, gaps, fixes, and efficiency metrics for reports."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Optional, Set

from ..models import AGENT_ACCESSIBLE_TARGET_KINDS, NavigationTargetKind
from .gap_taxonomy import (
    AUTH_REQUIRED,
    CATALOG_NOT_ACTIVATED,
    CLIENT_ONLY,
    DEAD_TARGET,
    LLMS_TXT,
    NAME_UNMATCHABLE,
    OFF_SITE_EXIT,
    STATIC_AUDIT,
    UNLABELED_STATIC,
    audit_recommendation_to_fix,
    cap_site_fixes,
    catalog_accessible_name,
    classify_action_gap,
    compute_navigability_pcts,
    dedupe_gaps,
    explore_is_valid,
    explore_min_steps,
    group_gaps_by_section,
    map_legacy_gap_type,
    names_compatible_with_action,
    product_fix_eligible,
    recommendation_for_gap,
    site_fix_eligible,
)
from .explore_jobs import (
    ExploreJobTracker,
    build_explore_visit_urls,
    finalize_job_results,
    infer_explore_jobs,
    job_success_accessibility_note,
    merge_job_progress,
)

# Rough seconds per agent step when timing is not instrumented.
EST_LOAD_SEC = 4.5
EST_CLICK_SEC = 2.0
EST_FAILED_CLICK_SEC = 5.0

def build_agent_gap_report(
    *,
    universe: Dict[str, Any],
    exploration: Optional[Dict[str, Any]] = None,
    audit: Optional[Dict[str, Any]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    static_audits: Optional[Dict[str, Any]] = None,
    page_html_by_id: Optional[Dict[str, str]] = None,
    source_url: str = "",
) -> Dict[str, Any]:
    audit = audit or {}
    exploration = exploration or {}
    events = events or exploration.get("events") or []
    static_audits = static_audits or {}

    actions = universe.get("actions") or []
    on_site = [a for a in actions if a.get("on_site")]
    unique_on_site = _dedupe_actions(on_site)

    aria_matched: Set[str] = set(exploration.get("aria_matched_action_ids") or [])
    activated_raw: Set[str] = set(exploration.get("activated_action_ids") or [])
    activated_labels = _activated_labels(activated_raw)

    unique_catalog = _dedupe_actions(actions)
    html_by_page = page_html_by_id or {}
    pages_crawled = len(universe.get("pages") or [])
    total_steps = int(exploration.get("total_steps") or len(events) or 0)
    explore_valid = explore_is_valid(total_steps, pages_crawled)

    activation_log = exploration.get("activation_log") or []
    activated_ids = set(exploration.get("activated_action_ids") or [])
    action_rows = [
        _action_row(
            action,
            aria_matched,
            activated_labels,
            html_by_page,
            explore_valid,
            activation_log,
            events,
            activated_ids,
        )
        for action in unique_on_site
    ]
    catalog_action_rows = [
        _action_row(
            action,
            aria_matched,
            activated_labels,
            html_by_page,
            explore_valid,
            activation_log,
            events,
            activated_ids,
        )
        for action in unique_catalog
    ]
    gaps = _build_gaps(
        unique_catalog,
        catalog_action_rows,
        audit,
        static_audits,
        html_by_page,
        explore_valid=explore_valid,
        explore_steps=total_steps,
        pages_crawled=pages_crawled,
    )
    findings = _build_findings(events, exploration, audit, source_url)
    efficiency = _compute_efficiency(
        action_rows=action_rows,
        catalog_action_rows=catalog_action_rows,
        events=events,
        exploration=exploration,
        audit=audit,
        gaps=gaps,
        explore_valid=explore_valid,
    )
    fixes = _build_fixes(
        gaps,
        audit,
        static_audits,
        explore_steps=total_steps,
        explore_valid=explore_valid,
    )
    gap_sections = group_gaps_by_section(gaps)
    navigability = compute_navigability_pcts(catalog_action_rows, html_by_page, exploration)
    explore_jobs = infer_explore_jobs(universe, audit=audit)
    stored_progress = exploration.get("job_progress")
    if stored_progress:
        job_progress = merge_job_progress(explore_jobs, stored_progress)
    else:
        job_progress = _job_progress_from_events(explore_jobs, events)
    job_results = finalize_job_results(explore_jobs, job_progress, gaps, universe=universe) if explore_jobs else []

    return {
        "source_url": source_url or universe.get("source_url") or "",
        "headline": audit.get("headline") or "",
        "exploration_mode": exploration.get("mode"),
        "llm_enabled": exploration.get("llm_enabled"),
        "has_exploration": bool(exploration.get("total_steps")),
        "findings": findings,
        "gaps": gaps,
        "fixes": fixes,
        "actions": action_rows,
        "efficiency": efficiency,
        "summary": _build_summary(
            findings, gaps, fixes, efficiency, exploration, audit, job_results
        ),
        "explore_jobs": explore_jobs,
        "job_results": job_results,
        "gap_sections": gap_sections,
        "explore_valid": explore_valid,
        "explore_min_steps": explore_min_steps(pages_crawled),
        "static_navigable_pct": navigability.get("static_navigable_pct"),
        "hydrated_navigable_pct": navigability.get("hydrated_navigable_pct"),
        "static_audits": static_audits,
    }


def _job_progress_from_events(jobs: List[Dict[str, Any]], events: List[Dict[str, Any]]) -> Dict[str, Any]:
    from .explore_jobs import ExploreJobTracker

    tracker = ExploreJobTracker(jobs)
    for event in events:
        meta = event.get("metadata") or {}
        path = meta.get("path") or event.get("url") or ""
        if event.get("action") == "VIEW_PAGE":
            tracker.record_page_view(str(path))
        elif event.get("action") == "CLICK":
            meta = event.get("metadata") or {}
            tracker.record_click(
                str(event.get("element_name") or ""),
                str(meta.get("path") or event.get("url") or ""),
                success=event.get("success", True) is not False,
                navigated=meta.get("navigated"),
            )
    return tracker.progress_payload()


def _dedupe_efficiency_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Count each navigable target once (nav is repeated per crawled page)."""
    seen: Set[str] = set()
    unique: List[Dict[str, Any]] = []
    for row in rows:
        if not row.get("catalog_accessible"):
            continue
        key = f"{row.get('path') or ''}::{_norm_label(row.get('label') or '')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _dedupe_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Set[str] = set()
    rows: List[Dict[str, Any]] = []
    for action in actions:
        label = _norm_label(action.get("label") or action.get("name") or "")
        key = f"{action.get('page_id')}::{label}::{action.get('target_kind')}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(action)
    return rows


def _norm_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _exploration_matched_action(
    action: Dict[str, Any],
    events: List[Dict[str, Any]],
    aria_matched_ids: Set[str],
) -> bool:
    aid = str(action.get("id") or "")
    if aid in aria_matched_ids:
        return True
    for event in events:
        if event.get("action") != "CLICK" or event.get("success") is False:
            continue
        live_name = str(event.get("element_name") or "")
        if names_compatible_with_action(action, live_name):
            return True
    return False


def _exploration_activated_action(
    action: Dict[str, Any],
    events: List[Dict[str, Any]],
    activated_ids: Set[str],
    activated_labels: Set[str],
) -> bool:
    aid = str(action.get("id") or "")
    if aid in activated_ids:
        return True
    label = _norm_label(catalog_accessible_name(action))
    if label and label in activated_labels:
        return True
    return _exploration_matched_action(action, events, set())


def _activated_labels(activated_ids: Set[str]) -> Set[str]:
    labels: Set[str] = set()
    for item in activated_ids:
        text = str(item)
        if text.startswith("llm_link_"):
            labels.add(_norm_label(text[9:]))
        elif text.startswith("llm_button_"):
            labels.add(_norm_label(text[11:]))
        else:
            labels.add(_norm_label(text))
    return labels


def _activation_obscured_for_action(action_id: str, activation_log: List[Dict[str, Any]]) -> bool:
    if not action_id:
        return False
    for entry in activation_log or []:
        if str(entry.get("action_id") or "") != action_id:
            continue
        if str(entry.get("activation_result") or "") in {"obscured", "timeout"}:
            return True
    return False


def _action_row(
    action: Dict[str, Any],
    aria_matched: Set[str],
    activated_labels: Set[str],
    page_html_by_id: Dict[str, str],
    explore_valid: bool,
    exploration_activation_log: Optional[List[Dict[str, Any]]] = None,
    events: Optional[List[Dict[str, Any]]] = None,
    activated_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    from .gap_taxonomy import action_in_static_html

    aid = str(action.get("id") or "")
    label = catalog_accessible_name(action) or str(
        action.get("label") or action.get("name") or action.get("selector") or "Unlabeled"
    )
    kind = str(action.get("target_kind") or "")
    page_id = str(action.get("page_id") or "")
    page_html = page_html_by_id.get(page_id, "")
    catalog_ok = kind in AGENT_ACCESSIBLE_TARGET_KINDS
    event_list = events or []
    activated_id_set = activated_ids or set()
    matched = _exploration_matched_action(action, event_list, aria_matched)
    activated = _exploration_activated_action(
        action, event_list, activated_id_set, activated_labels
    )
    in_static = action_in_static_html(action, page_html)
    in_hydrated = matched or activated
    live_tree_miss = catalog_ok and in_static and not in_hydrated and not activated
    gap_type = classify_action_gap(
        action,
        {
            "label": label,
            "target_kind": kind,
            "catalog_accessible": catalog_ok,
            "aria_matched": matched,
            "agent_activated": activated,
        },
        in_static_html=in_static,
        in_hydrated_tree=in_hydrated,
        explore_valid=explore_valid,
    )
    also_client_only = gap_type == CLIENT_ONLY or (
        gap_type == CATALOG_NOT_ACTIVATED and in_hydrated and not in_static
    )
    activation_obscured = _activation_obscured_for_action(
        str(action.get("id") or ""),
        exploration_activation_log,
    )
    return {
        "id": aid,
        "page_id": page_id,
        "path": action.get("target_path") or action.get("path") or "",
        "label": label,
        "role": action.get("role") or "",
        "selector": action.get("selector") or "",
        "target_kind": kind,
        "catalog_accessible": catalog_ok,
        "aria_matched": matched,
        "agent_activated": activated,
        "in_static_html": in_static,
        "in_hydrated_tree": in_hydrated,
        "priority": action.get("agent_priority") or "medium",
        "gap": gap_type,
        "also_client_only": also_client_only,
        "name_unmatchable": gap_type == NAME_UNMATCHABLE,
        "activation_obscured": activation_obscured,
        "live_tree_miss": live_tree_miss,
    }


def _build_gaps(
    actions: List[Dict[str, Any]],
    action_rows: List[Dict[str, Any]],
    audit: Dict[str, Any],
    static_audits: Dict[str, Any],
    page_html_by_id: Dict[str, str],
    *,
    explore_valid: bool,
    explore_steps: int,
    pages_crawled: int = 1,
) -> List[Dict[str, Any]]:
    gaps: List[Dict[str, Any]] = []
    min_steps = explore_min_steps(pages_crawled)
    for row in action_rows:
        gap_type = row.get("gap")
        if not gap_type or gap_type == OFF_SITE_EXIT:
            continue
        if gap_type == CATALOG_NOT_ACTIVATED and not explore_valid:
            severity = "info"
            impact = (
                f"\"{row.get('label') or 'Control'}\" not activated — explore inconclusive "
                f"({explore_steps} steps; minimum {min_steps} required)."
            )
        else:
            severity = _severity(gap_type, row)
            impact = _impact_text(gap_type, row, explore_valid=explore_valid)
        gaps.append(
            {
                "id": row["id"],
                "severity": severity,
                "type": gap_type,
                "page_id": row.get("page_id"),
                "label": row.get("label"),
                "path": row.get("path"),
                "selector": row.get("selector"),
                "target_kind": row.get("target_kind"),
                "in_static_html": row.get("in_static_html"),
                "also_client_only": row.get("also_client_only"),
                "name_unmatchable": row.get("name_unmatchable"),
                "activation_obscured": row.get("activation_obscured"),
                "live_tree_miss": row.get("live_tree_miss"),
                "impact": impact,
            }
        )

    for page_id, audit_payload in (static_audits or {}).items():
        if not isinstance(audit_payload, dict):
            continue
        for check in audit_payload.get("checks") or []:
            if check.get("passed"):
                continue
            check_id = str(check.get("id") or "")
            gap_type = str(check.get("gap_type") or STATIC_AUDIT)
            if check_id == "llms-txt":
                gap_type = LLMS_TXT
            gaps.append(
                {
                    "id": f"static::{page_id}::{check_id}",
                    "severity": check.get("severity") or ("high" if gap_type == LLMS_TXT else "medium"),
                    "type": gap_type,
                    "page_id": page_id,
                    "label": check_id,
                    "selector": "",
                    "target_kind": gap_type,
                    "static_check": True,
                    "llms_meta": check.get("llms_meta"),
                    "impact": str(check.get("detail") or check.get("message") or check_id),
                }
            )

    nav_issues = (audit.get("navigation_issues") or [])[:20]
    for issue in nav_issues:
        gap_type = map_legacy_gap_type(str(issue.get("code") or "nav_issue"))
        gaps.append(
            {
                "id": f"nav::{issue.get('page_id')}::{issue.get('label')}",
                "severity": "high" if gap_type in {CLIENT_ONLY, UNLABELED_STATIC} else "medium",
                "type": gap_type,
                "page_id": issue.get("page_id"),
                "label": issue.get("label") or "",
                "selector": issue.get("selector") or "",
                "target_kind": issue.get("code") or "",
                "impact": str(issue.get("message") or ""),
            }
        )

    return dedupe_gaps(gaps)


def _severity(gap_type: str, row: Dict[str, Any]) -> str:
    if gap_type == DEAD_TARGET and (row.get("priority") or "") == "high":
        return "critical"
    if gap_type in {UNLABELED_STATIC, CLIENT_ONLY, NAME_UNMATCHABLE, LLMS_TXT, DEAD_TARGET, AUTH_REQUIRED}:
        return "high"
    if gap_type == CATALOG_NOT_ACTIVATED:
        return "medium"
    if gap_type == OFF_SITE_EXIT:
        return "low"
    if gap_type == STATIC_AUDIT:
        return "medium"
    return "low"


def _impact_text(gap_type: str, row: Dict[str, Any], *, explore_valid: bool = True) -> str:
    label = row.get("label") or "Control"
    if gap_type == CLIENT_ONLY:
        return (
            f"\"{label}\" missing in static HTML; present after hydration "
            f"({row.get('selector') or 'control'})."
        )
    if gap_type == UNLABELED_STATIC:
        return f"\"{label}\" has no accessible name in static HTML."
    if gap_type == NAME_UNMATCHABLE:
        return f"\"{label}\" computed name is too long for reliable getByRole matching."
    if gap_type == CATALOG_NOT_ACTIVATED:
        if row.get("live_tree_miss"):
            return (
                f"\"{label}\" is in crawl/static HTML but was not found in the live "
                f"accessibility tree during explore."
            )
        if explore_valid:
            return f"\"{label}\" has an accessible name but was not activated during explore."
        return f"\"{label}\" — explore inconclusive (insufficient step budget)."
    if gap_type == DEAD_TARGET:
        return f"\"{label}\" points nowhere agents can reach."
    if gap_type == OFF_SITE_EXIT:
        return f"\"{label}\" leaves the site — informational for on-site tasks."
    if gap_type == AUTH_REQUIRED:
        return f"\"{label}\" requires authentication."
    if gap_type == LLMS_TXT:
        return str(row.get("impact") or "llms.txt check failed.")
    return f"\"{label}\" blocks reliable agent navigation ({gap_type})."


def _build_findings(
    events: List[Dict[str, Any]],
    exploration: Dict[str, Any],
    audit: Dict[str, Any],
    source_url: str,
) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    if audit.get("headline"):
        findings.append({"kind": "product", "text": audit["headline"]})

    pages_visited = exploration.get("pages_visited") or 0
    if pages_visited:
        paths = sorted({(e.get("metadata") or {}).get("path") for e in events if (e.get("metadata") or {}).get("path")})
        findings.append(
            {
                "kind": "coverage",
                "text": f"Agent visited {pages_visited} page(s): {', '.join(paths) or '—'}.",
            }
        )

    successful_clicks = [
        e for e in events if e.get("action") == "CLICK" and e.get("success", True) is not False
    ]
    for event in successful_clicks[:12]:
        name = event.get("element_name") or ""
        role = event.get("element_role") or "control"
        if name:
            findings.append({"kind": "action", "text": f"Activated {role} \"{name}\"."})

    failed = [e for e in events if e.get("action") == "CLICK" and e.get("success") is False]
    for event in failed[:5]:
        name = event.get("element_name") or "control"
        err = (event.get("metadata") or {}).get("error") or "click failed"
        findings.append({"kind": "failure", "text": f"Failed to activate \"{name}\": {err}."})

    if audit.get("funnel_summary"):
        findings.append({"kind": "crawl", "text": audit["funnel_summary"]})

    if source_url and not any(f["kind"] == "product" for f in findings):
        findings.insert(0, {"kind": "product", "text": f"Audited {source_url}."})

    return findings


def _build_fixes(
    gaps: List[Dict[str, Any]],
    audit: Dict[str, Any],
    static_audits: Dict[str, Any],
    *,
    explore_steps: int = 0,
    explore_valid: bool = True,
) -> List[Dict[str, Any]]:
    fixes: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for gap in gaps:
        gap_type = str(gap.get("type") or "")
        label = gap.get("label") or ""
        in_static = bool(gap.get("in_static_html", True))
        also_csr = bool(gap.get("also_client_only"))
        name_long = bool(gap.get("name_unmatchable"))
        if site_fix_eligible(
            gap_type,
            in_static_html=in_static,
            also_client_only=also_csr,
            name_unmatchable=name_long,
            live_tree_miss=bool(gap.get("live_tree_miss")),
            explore_valid=explore_valid,
        ):
            change = recommendation_for_gap(
                gap,
                explore_steps=explore_steps,
                in_static_html=in_static,
                hydrated_name=label,
            )
            if change:
                key = f"site::{gap_type}::{label}"
                if key not in seen:
                    seen.add(key)
                    fixes.append(
                        {
                            "priority": gap.get("severity") or "medium",
                            "gap_type": gap_type,
                            "fix_scope": "site",
                            "label": label,
                            "selector": gap.get("selector") or "",
                            "page_id": gap.get("page_id"),
                            "change": change,
                        }
                    )

        if product_fix_eligible(gap_type, in_static_html=in_static, explore_valid=explore_valid):
            key = f"product::{gap_type}::{label}"
            if key not in seen:
                seen.add(key)
                fixes.append(
                    {
                        "priority": "low",
                        "gap_type": gap_type,
                        "fix_scope": "product",
                        "label": label,
                        "selector": gap.get("selector") or "",
                        "page_id": gap.get("page_id"),
                        "change": (
                            f"[product][{gap_type}] {label} — present in static HTML but not activated. "
                            "Improve explorer matching (title substring, exact nav regex) and step budget."
                        ),
                    }
                )

        if gap.get("activation_obscured") and gap_type == CATALOG_NOT_ACTIVATED:
            key = f"site::overlay::{label}"
            if key not in seen:
                seen.add(key)
                fixes.append(
                    {
                        "priority": "medium",
                        "gap_type": gap_type,
                        "fix_scope": "site",
                        "label": label,
                        "selector": gap.get("selector") or "",
                        "page_id": gap.get("page_id"),
                        "change": (
                            f"[medium][{gap_type}] {label} — activation failed (obscured/timeout). "
                            "Site fix: ensure link is visible above fold and not covered by modals/overlays."
                        ),
                    }
                )

    has_llms_gap = any(g.get("type") == LLMS_TXT for g in gaps)
    for rec in (audit.get("recommendations") or [])[:8]:
        text = str(rec).strip()
        if has_llms_gap and "llms.txt" in text.lower():
            continue
        mapped = audit_recommendation_to_fix(text)
        if not mapped:
            continue
        change = mapped.get("change") or ""
        if change in seen:
            continue
        seen.add(change)
        fixes.append({**mapped, "fix_scope": "site"})

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    fixes.sort(key=lambda item: priority_order.get(item["priority"], 9))
    site_fixes = [f for f in fixes if f.get("fix_scope") != "product"]
    product_fixes = [f for f in fixes if f.get("fix_scope") == "product"][:5]
    return cap_site_fixes(site_fixes) + product_fixes


def _compute_efficiency(
    *,
    action_rows: List[Dict[str, Any]],
    catalog_action_rows: Optional[List[Dict[str, Any]]] = None,
    events: List[Dict[str, Any]],
    exploration: Dict[str, Any],
    audit: Dict[str, Any],
    gaps: List[Dict[str, Any]],
    explore_valid: bool = True,
) -> Dict[str, Any]:
    catalog_rows = catalog_action_rows if catalog_action_rows is not None else action_rows
    on_site_total = len(action_rows)
    catalog_total = len(catalog_rows)

    if on_site_total > 0:
        scope_rows = _dedupe_efficiency_rows(action_rows)
        actions_lost_basis = "on_site"
        denominator = len(scope_rows)
    else:
        scope_rows = _dedupe_efficiency_rows(catalog_rows)
        actions_lost_basis = "catalog"
        denominator = len(scope_rows)

    catalog_blocked = sum(1 for row in scope_rows if not row.get("catalog_accessible"))
    not_activated = sum(
        1
        for row in scope_rows
        if not row.get("agent_activated")
        and not (not explore_valid and row.get("gap") == CATALOG_NOT_ACTIVATED)
    )
    not_matched = sum(1 for row in scope_rows if not row.get("aria_matched"))

    clicks = [e for e in events if e.get("action") == "CLICK"]
    failed_clicks = [e for e in clicks if e.get("success") is False]
    page_views = [e for e in events if e.get("action") == "VIEW_PAGE"]
    total_steps = int(exploration.get("total_steps") or len(events) or 0)

    # Minimal path ≈ unique pages + a few high-value clicks per page.
    pages_visited = int(exploration.get("pages_visited") or len(page_views) or 0)
    minimal_steps = max(pages_visited + min(3, len(clicks)), 1)
    redundant_steps = max(total_steps - minimal_steps, 0)

    measured_ms = sum(int(e.get("duration_ms") or 0) for e in events)
    if measured_ms > 0:
        total_time_sec = measured_ms / 1000.0
        wasted_time_sec = sum(int(e.get("duration_ms") or 0) for e in failed_clicks) / 1000.0
        wasted_time_sec += redundant_steps * EST_CLICK_SEC
    else:
        total_time_sec = pages_visited * EST_LOAD_SEC + len(clicks) * EST_CLICK_SEC
        wasted_time_sec = len(failed_clicks) * EST_FAILED_CLICK_SEC + redundant_steps * EST_CLICK_SEC
        wasted_time_sec += catalog_blocked * EST_FAILED_CLICK_SEC * 0.35

    if denominator > 0:
        catalog_lost_percent = round(100.0 * not_activated / denominator, 1)
        catalog_loss_percent = round(100.0 * catalog_blocked / denominator, 1)
        aria_gap_percent = round(100.0 * not_matched / denominator, 1)
    else:
        catalog_lost_percent = 0.0
        catalog_loss_percent = 0.0
        aria_gap_percent = 0.0

    if actions_lost_basis == "catalog":
        accessibility = float(audit.get("agent_accessibility_score") or 0)
        accessibility_miss = round(max(0.0, 100.0 - accessibility), 1)
        actions_lost_percent = max(catalog_lost_percent, accessibility_miss)
    else:
        actions_lost_percent = catalog_lost_percent
    step_waste_percent = round(100.0 * redundant_steps / max(total_steps, 1), 1) if total_steps else 0.0
    time_lost_percent = min(
        100.0,
        round(100.0 * wasted_time_sec / max(total_time_sec, 0.1), 1),
    )

    return {
        "on_site_actions": on_site_total,
        "on_site_unique_targets": denominator if actions_lost_basis == "on_site" else len(_dedupe_efficiency_rows(action_rows)),
        "catalog_actions": catalog_total,
        "actions_lost_basis": actions_lost_basis,
        "catalog_blocked_actions": catalog_blocked,
        "not_activated_actions": not_activated,
        "not_aria_matched_actions": not_matched,
        "actions_lost_percent": actions_lost_percent,
        "catalog_loss_percent": catalog_loss_percent,
        "aria_gap_percent": aria_gap_percent,
        "total_agent_steps": total_steps,
        "minimal_steps_estimate": minimal_steps,
        "redundant_steps": redundant_steps,
        "step_waste_percent": step_waste_percent,
        "failed_clicks": len(failed_clicks),
        "successful_clicks": len(clicks) - len(failed_clicks),
        "estimated_total_time_sec": round(total_time_sec, 1),
        "estimated_wasted_time_sec": round(wasted_time_sec, 1),
        "time_lost_percent": time_lost_percent,
        "critical_gaps": sum(1 for g in gaps if g.get("severity") == "critical"),
        "high_gaps": sum(1 for g in gaps if g.get("severity") == "high"),
        "gap_count": len(gaps),
        "crawler_quality": exploration.get("crawler_quality") or {},
    }


def _actions_lost_summary_line(efficiency: Dict[str, Any]) -> str:
    lost = float(efficiency.get("actions_lost_percent") or 0)
    if efficiency.get("actions_lost_basis") == "catalog":
        return f"{lost}% of catalog actions were missed or unreachable during agent explore."
    return f"{lost}% of on-site catalog actions were never activated."


def _build_summary(
    findings: List[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
    fixes: List[Dict[str, Any]],
    efficiency: Dict[str, Any],
    exploration: Dict[str, Any],
    audit: Optional[Dict[str, Any]] = None,
    job_results: Optional[List[Dict[str, Any]]] = None,
) -> str:
    if not exploration.get("total_steps"):
        return (
            "Crawl complete — run Cursor agent exploration to surface live findings, "
            "gaps, and wasted effort."
        )
    parts = [
        f"Agent took {efficiency.get('total_agent_steps', 0)} steps; "
        f"~{efficiency.get('step_waste_percent', 0)}% were likely redundant.",
        _actions_lost_summary_line(efficiency),
        f"Estimated ~{efficiency.get('time_lost_percent', 0)}% agent time lost to dead ends, retries, and extra steps.",
    ]
    if gaps:
        parts.append(f"{len(gaps)} gap(s) found — {len(fixes)} recommended site change(s).")
    note = job_success_accessibility_note(
        job_results or [],
        (audit or {}).get("agent_accessibility_score"),
    )
    if note:
        parts.append(note)
    return " ".join(parts)


def build_agent_report_markdown(report: Dict[str, Any]) -> str:
    eff = report.get("efficiency") or {}
    lines = [
        "# Agent audit report",
        "",
        report.get("summary") or "",
        "",
        "## Efficiency",
        f"- Actions lost: **{eff.get('actions_lost_percent', 0)}%** ({eff.get('not_activated_actions', 0)}/{eff.get('on_site_actions', 0)} on-site actions not activated)",
        f"- Catalog blocked: **{eff.get('catalog_loss_percent', 0)}%**",
        f"- Aria tree gap: **{eff.get('aria_gap_percent', 0)}%**",
        f"- Step waste: **{eff.get('step_waste_percent', 0)}%** ({eff.get('redundant_steps', 0)} redundant of {eff.get('total_agent_steps', 0)})",
        f"- Est. time lost: **{eff.get('time_lost_percent', 0)}%** (~{eff.get('estimated_wasted_time_sec', 0)}s of {eff.get('estimated_total_time_sec', 0)}s)",
        "",
        "## What the agent found",
    ]
    for item in report.get("findings") or []:
        lines.append(f"- {item.get('text')}")

    lines.extend(["", "## Gaps"])
    for gap in (report.get("gaps") or [])[:25]:
        lines.append(
            f"- **[{gap.get('severity')}]** {gap.get('label') or gap.get('type')} — {gap.get('impact')}"
        )

    lines.extend(["", "## Exact changes"])
    for idx, fix in enumerate(report.get("fixes") or [], 1):
        lines.append(f"{idx}. [{fix.get('priority')}] {fix.get('change')}")

    return "\n".join(lines) + "\n"
