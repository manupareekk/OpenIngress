"""Helpers for merged Codex + Playwright audit payloads."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

from ..config import Config

_BUSINESS_ACTION_TITLES = {
    "orient": "Reach the homepage",
    "portfolio": "Open portfolio work",
    "product": "Reach a product or feature page",
    "find_product": "Find a product page",
    "add_to_cart": "Start a purchase from a product page",
    "pricing": "View pricing or plans",
    "checkout": "Reach cart or checkout",
    "book_demo": "Book a demo",
    "convert": "Start signup or join the waitlist",
    "blog": "Read a blog or article",
    "about": "Reach the company or about page",
    "contact": "Find a contact or sales path",
}

_STRONG_PATH_SEGMENTS = {
    "pricing",
    "plans",
    "product",
    "products",
    "feature",
    "features",
    "solution",
    "solutions",
    "shop",
    "store",
    "cart",
    "checkout",
    "demo",
    "request-demo",
    "book-demo",
    "signup",
    "sign-up",
    "waitlist",
    "register",
    "contact",
    "hire",
    "sales",
}

_BUSINESS_RELEVANT_JOB_IDS = {
    "portfolio",
    "product",
    "find_product",
    "add_to_cart",
    "pricing",
    "checkout",
    "book_demo",
    "convert",
    "contact",
}

_PAGE_TYPE_SUPPORT = {
    "ecommerce": {"find_product", "add_to_cart", "checkout", "pricing"},
    "marketing": {"product", "pricing", "book_demo", "convert", "contact"},
    "saas": {"product", "pricing", "book_demo", "convert", "contact"},
    "general": {"product", "pricing", "book_demo", "convert", "contact"},
    "portfolio": {"portfolio", "contact"},
    "agency": {"portfolio", "book_demo", "contact"},
    "blog": {"blog", "contact"},
}

_GENERIC_FUNNEL_STEPS = [
    {
        "id": "discover",
        "label": "Discover",
        "weight": 15,
        "job_ids": {"orient", "product", "find_product", "blog"},
        "summary": "Homepage, product, feature, docs, or content discovery.",
    },
    {
        "id": "evaluate",
        "label": "Evaluate",
        "weight": 20,
        "job_ids": {"product", "find_product", "pricing", "blog", "about"},
        "summary": "Product detail, pricing, comparison, trust, or support evaluation.",
    },
    {
        "id": "convert",
        "label": "Convert",
        "weight": 30,
        "job_ids": {"convert", "book_demo", "add_to_cart", "pricing", "contact"},
        "summary": "Signup, demo, waitlist, purchase, contact sales, or primary CTA.",
    },
    {
        "id": "handoff",
        "label": "Handoff",
        "weight": 25,
        "job_ids": {"checkout", "book_demo", "convert", "contact"},
        "summary": "Checkout, scheduler, auth, form submission, or external-app handoff.",
    },
    {
        "id": "recover",
        "label": "Recover",
        "weight": 10,
        "job_ids": {"contact", "about"},
        "summary": "Contact, support, fallback route, retry, or visible recovery path.",
    },
]


_FUNNEL_STATUS_MULTIPLIERS = {
    "success": 0.0,
    "pass": 0.0,
    "partial": 0.45,
    "detected": 0.45,
    "warn": 0.45,
    "blocked": 1.0,
    "failed": 1.0,
    "fail": 1.0,
    "not_detected": 1.0,
    "not_tested": 0.6,
}

_SUMMARY_CACHE: Dict[str, Dict[str, str]] = {}

_ACTION_SUMMARY_SYSTEM_PROMPT = """You write short, product-facing audit explanations for agent-readiness reports.

Return strict JSON with exactly these string fields:
- headline
- action_summary
- score_pressure
- next_focus

Writing rules:
- Be concrete and business-readable.
- Explain what the agent actually completed first.
- Explain why the score stayed low or high using the supplied metrics.
- Mention the dominant blocker or gap explicitly.
- Never invent actions, blockers, or metrics.
- Never say "blocked" unless the evidence shows the agent could not do anything useful.
- Keep each field to one or two sentences.

Example 1 input pattern:
- score 45, verdict Not ready
- validated actions: Reach the homepage (success), Reach a product page (partial)
- agent reach 0%, structural speed 100%, missed actions 100%, extra navigation 0%
- blocker: llms.txt missing

Example 1 output:
{
  "headline": "Agents completed orientation and partially followed the product path, but the site is still not ready for dependable agent use.",
  "action_summary": "The browser run reached the homepage and followed the Learn more path into the example domain flow, but it did not complete a stronger business action.",
  "score_pressure": "The score stayed low because agent reach was 0% and missed actions were 100%, which outweighed the otherwise lightweight page structure and efficient click path. A missing llms.txt also remained a high-confidence readiness gap.",
  "next_focus": "Raise the score by exposing measurable on-site actions and publishing llms.txt so agents have both reachable actions and machine-readable guidance."
}

Example 2 input pattern:
- score 81, verdict Mostly agent ready
- validated actions: Reach pricing (success), Start signup (success)
- agent reach 78%, structural speed 84%, missed actions 12%, extra navigation 8%
- blocker: duplicate navigation labels

Example 2 output:
{
  "headline": "Agents completed the primary pricing and signup flows, so the site is mostly ready for autonomous use.",
  "action_summary": "The browser run validated the key commercial paths with only minor friction during navigation.",
  "score_pressure": "The score did not go higher because some actions were still missed and duplicate navigation labels add targeting ambiguity for agents.",
  "next_focus": "Clean up the duplicated navigation labels and close the remaining missed-action gaps to move this from mostly ready to reliably ready."
}

Example 3 input pattern:
- score 29, verdict Not ready
- validated actions: none
- agent reach 5%, structural speed 62%, missed actions 90%, extra navigation 41%
- blocker: checkout button hidden behind JS-only control

Example 3 output:
{
  "headline": "The browser run did not validate a dependable action path, so the site is not ready for autonomous agent use.",
  "action_summary": "Agents explored the page but could not complete a meaningful business action in the audited flow.",
  "score_pressure": "The score stayed low because reach was minimal, most actions were missed, and the agent wasted many steps fighting the interface. The checkout control was also hidden behind a JS-only interaction pattern.",
  "next_focus": "Expose the checkout action as a real reachable control first, then reduce the missed-action and extra-navigation penalties."
}
"""

_IMPROVEMENT_FORECAST_SYSTEM_PROMPT = """You write concise forecast copy for agent-readiness reports.

Return strict JSON with exactly these fields:
- headline: string
- summary: string
- items: array of exactly 3 objects

Each item object must contain exactly:
- title: string
- detail: string

Rules:
- Use the supplied deterministic numbers; do not invent new ones.
- Frame each item as a practical improvement lever, not a vague recommendation.
- Mention the expected score lift and traversal-time reduction naturally in the detail.
- Keep each field short and concrete.
- If a predicted time reduction is 0, say it mainly improves score/reliability rather than speed.

Example input:
{
  "current_score": 45,
  "projected_score": 70,
  "projected_score_lift_percent": 25,
  "projected_time_saved_percent": 8,
  "items": [
    {
      "component": "agent_reach",
      "target_label": "Raise agent reach to 60%",
      "score_lift_percent": 12,
      "time_saved_percent": 3,
      "reason": "The crawl currently measures 0% reachable on-site actions."
    },
    {
      "component": "semantic_clarity",
      "target_label": "Publish llms.txt and tighten semantic guidance",
      "score_lift_percent": 7,
      "time_saved_percent": 0,
      "reason": "The report found a missing llms.txt gap and limited semantic guidance."
    },
    {
      "component": "task_validation",
      "target_label": "Validate one more key business task",
      "score_lift_percent": 6,
      "time_saved_percent": 5,
      "reason": "The agent only completed orientation and partial product exploration."
    }
  ]
}

Example output:
{
  "headline": "If you improve these 3 things, your score could rise by about 25% and agents could spend about 8% less time traversing.",
  "summary": "The fastest lift comes from giving agents clearer on-site reach, stronger guidance, and one more fully validated business path.",
  "items": [
    {
      "title": "Raise agent reach on measurable actions",
      "detail": "Move reach toward 60% and the score could improve by about 12%, while agents may spend about 3% less time searching for a usable path."
    },
    {
      "title": "Publish llms.txt and tighten guidance",
      "detail": "This could add about 7% to the score by improving clarity and machine-readable structure, with reliability gains more than speed gains."
    },
    {
      "title": "Validate one more key business task",
      "detail": "Completing a stronger end-to-end path could lift the score by about 6% and reduce traversal time by about 5%."
    }
  ]
}
"""


def combine_audit_states(codex_state: Dict[str, Any], playwright_state: Dict[str, Any] | None = None) -> Dict[str, Any]:
    combined = dict(codex_state or {})
    pw = playwright_state or {}
    codex_status = str(codex_state.get("status") or "")
    pw_status = str(pw.get("status") or "")

    if codex_status == "failed":
        combined["status"] = "failed"
        combined["error"] = codex_state.get("error") or "Codex audit failed"
    elif pw_status == "failed":
        combined["status"] = "failed"
        combined["error"] = pw.get("error") or "Playwright audit failed"
    elif codex_status == "completed" and pw_status == "completed":
        combined["status"] = "completed"
        combined.pop("error", None)
    elif codex_status == "queued" or pw_status == "queued":
        combined["status"] = "queued"
    elif codex_status in {"running", "completed"} or pw_status in {"running", "draft"}:
        combined["status"] = "running"

    codex_pct = int(codex_state.get("progress_pct") or 0)
    pw_pct = int(pw.get("progress_pct") or 0)
    if pw_status:
        combined["progress_pct"] = 100 if combined["status"] == "completed" else min(99, (codex_pct + pw_pct) // 2)
    if combined.get("status") == "completed":
        combined["progress_pct"] = 100

    if combined.get("status") != "completed":
        if codex_status == "completed" and pw_status in {"running", "queued", "draft"}:
            combined["progress"] = "Generating report..."
        elif pw_status in {"running", "queued", "draft"} and pw.get("progress"):
            combined["progress"] = f"{codex_state.get('progress') or 'Running Codex scan'} | {pw.get('progress')}"
        elif codex_state.get("progress"):
            combined["progress"] = codex_state.get("progress")

    return combined


def build_combined_audit_report(
    codex_result: Dict[str, Any] | None,
    playwright_payload: Dict[str, Any] | None,
) -> Dict[str, Any]:
    codex = codex_result or {}
    playwright = playwright_payload or {}
    audit = playwright.get("audit") or {}
    agent_report = playwright.get("agent_report") or {}
    has_playwright = bool(playwright)
    codex_inconclusive = _is_inconclusive_codex_result(codex)
    fixes: List[Dict[str, Any]] = []
    seen = set()

    if not (codex_inconclusive and has_playwright):
        for fix in codex.get("recommended_fixes") or []:
            title = str(fix.get("title") or "").strip().lower()
            if title and title not in seen:
                seen.add(title)
                fixes.append(
                    {
                        "source": "codex",
                        "priority": fix.get("priority"),
                        "title": fix.get("title"),
                        "detail": fix.get("detail"),
                    }
                )
    for fix in agent_report.get("fixes") or []:
        title = str(fix.get("title") or "").strip().lower()
        if title and title not in seen:
            seen.add(title)
            fixes.append(
                {
                    "source": "playwright",
                    "priority": fix.get("priority"),
                    "title": fix.get("title"),
                    "detail": fix.get("detail"),
                }
            )

    summary = []
    business_summary = (playwright.get("exports") or {}).get("business_summary") or []
    playwright_exports = playwright.get("exports") or {}

    if codex_inconclusive and has_playwright:
        summary.append(
            "Codex static inspection was inconclusive, so this combined summary uses the rendered-browser audit as primary evidence."
        )
    elif codex.get("executive_summary"):
        summary.append(str(codex.get("executive_summary")))

    for item in business_summary[:3]:
        text = str(item or "").strip()
        if text:
            summary.append(text)

    assessment = _build_assessment(
        codex=codex,
        audit=audit,
        agent_report=agent_report,
        has_playwright=has_playwright,
        codex_inconclusive=codex_inconclusive,
    )
    action_evidence = _build_action_evidence(audit=audit, agent_report=agent_report)
    access = _build_access_summary(
        codex=codex,
        audit=audit,
        agent_report=agent_report,
        codex_inconclusive=codex_inconclusive,
        has_playwright=has_playwright,
        action_evidence=action_evidence,
    )
    metrics = _build_metrics(audit=audit, agent_report=agent_report, codex=codex, assessment=assessment)
    insights = _build_user_insights(
        codex=codex,
        audit=audit,
        agent_report=agent_report,
        access=access,
        action_evidence=action_evidence,
    )
    score_explanation = _build_score_explanation(
        codex=codex,
        audit=audit,
        agent_report=agent_report,
        assessment=assessment,
        action_evidence=action_evidence,
        insights=insights,
    )
    improvement_forecast = _build_improvement_forecast(
        codex=codex,
        audit=audit,
        agent_report=agent_report,
        assessment=assessment,
        action_evidence=action_evidence,
        insights=insights,
    )
    business_dashboard = _build_business_dashboard(
        audit=audit,
        agent_report=agent_report,
        action_evidence=action_evidence,
        insights=insights,
    )
    report_summary = _unique(
        summary
        + [score_explanation.get("headline"), score_explanation.get("score_pressure"), score_explanation.get("next_focus")]
    )[:4]
    if codex_inconclusive and has_playwright:
        report_summary = [
            item for item in report_summary if "insufficient evidence" not in str(item or "").lower()
        ]

    report = {
        "source_url": codex.get("url") or (playwright.get("state") or {}).get("site_url"),
        "score": assessment.get("score"),
        "verdict": assessment.get("verdict"),
        "confidence": assessment.get("confidence"),
        "assessment": assessment,
        "action_evidence": action_evidence,
        "score_explanation": score_explanation,
        "improvement_forecast": improvement_forecast,
        "access": access,
        "metrics": metrics,
        "insights": insights,
        "business_dashboard": business_dashboard,
        "scores": {
            "codex": None if codex_inconclusive and has_playwright else codex.get("score"),
            "playwright": audit.get("overall_score") or audit.get("readiness_score"),
        },
        "verdicts": {
            "codex": codex.get("verdict"),
            "playwright": (playwright.get("exports") or {}).get("verdict"),
        },
        "summary": report_summary,
        "fixes": fixes[:12],
        "has_codex": bool(codex),
        "has_playwright": has_playwright,
    }
    report["artifact"] = _build_combined_artifact(
        report=report,
        codex=codex,
        playwright=playwright,
        playwright_exports=playwright_exports,
    )
    return report


def _build_assessment(
    *,
    codex: Dict[str, Any],
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    has_playwright: bool,
    codex_inconclusive: bool,
) -> Dict[str, Any]:
    rendered_score = _number(audit.get("overall_score") or audit.get("readiness_score"))
    codex_score = _number(codex.get("score"))
    efficiency = agent_report.get("efficiency") or {}
    coverage = audit.get("coverage") or {}
    action_coverage = _number(coverage.get("action_accessibility_percent"))
    action_loss = _number(efficiency.get("actions_lost_percent"))
    if action_coverage is None and action_loss is not None:
        action_coverage = max(0, 100 - action_loss)
    step_waste = _number(efficiency.get("step_waste_percent"))
    time_loss = _number(efficiency.get("time_lost_percent"))
    path_efficiency = None
    if step_waste is not None or time_loss is not None:
        path_efficiency = max(0, 100 - max(step_waste or 0, time_loss or 0))

    components = _score_components(
        rendered_score=rendered_score,
        action_coverage=action_coverage,
        path_efficiency=path_efficiency,
        codex_score=None if codex_inconclusive else codex_score,
        codex_inconclusive=codex_inconclusive,
    )
    score = _weighted_score(components)
    if rendered_score is not None and codex_score is not None and not codex_inconclusive:
        basis = "Weighted from rendered task performance, action coverage, path efficiency, and Codex semantic inspection."
    elif rendered_score is not None:
        basis = "Weighted from rendered task performance, action coverage, and path efficiency; Codex was used as context."
    elif codex_score is not None:
        basis = "Codex semantic inspection only; no rendered-browser task audit was available."
    else:
        basis = "No completed audit evidence was available."

    gap_count = int(efficiency.get("gap_count") or 0)
    if score is None:
        verdict = "Inconclusive"
    elif score >= 90 and (action_loss is None or action_loss <= 5) and gap_count <= 1:
        verdict = "Agent ready"
    elif score >= 75:
        verdict = "Mostly agent ready"
    elif score >= 50:
        verdict = "Fragile"
    else:
        verdict = "Not ready"

    if has_playwright and codex and not codex_inconclusive:
        confidence = "high"
    elif has_playwright or codex:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "score": score,
        "verdict": verdict,
        "confidence": confidence,
        "basis": basis,
        "components": components,
    }


def _build_access_summary(
    *,
    codex: Dict[str, Any],
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    codex_inconclusive: bool,
    has_playwright: bool,
    action_evidence: Dict[str, Any],
) -> Dict[str, Any]:
    coverage = audit.get("coverage") or {}
    efficiency = agent_report.get("efficiency") or {}
    reached = []
    missed = []
    reasons = []

    accessible = coverage.get("accessible_actions")
    total = coverage.get("total_actions")
    if accessible is not None and total is not None:
        reached.append(f"Reached {accessible}/{total} captured on-site actions in the rendered product.")
    elif efficiency.get("on_site_actions") is not None:
        loss = _number(efficiency.get("actions_lost_percent")) or 0
        reached.append(f"Reached rendered product actions with {loss:g}% measured action loss.")

    for item in action_evidence.get("validated_actions") or []:
        detail = str(item.get("result") or item.get("supporting_detail") or "").strip()
        if detail:
            reached.append(f"{item.get('title')}: {detail}")
        blocker = str(item.get("blocker") or "").strip()
        if blocker and blocker != "—":
            missed.append(f"{item.get('title')}: {blocker}")

    for item in action_evidence.get("business_actions") or []:
        if item.get("status") in {"success", "partial"}:
            continue
        title = str(item.get("title") or "").strip()
        basis = str(item.get("basis_inline") or "").strip()
        if title and basis:
            reasons.append(f"{title}: {basis}")

    for item in codex.get("what_agents_can_do") or []:
        if not codex_inconclusive:
            reached.append(str(item))

    for gap in agent_report.get("gaps") or []:
        text = str(gap.get("impact") or gap.get("label") or gap.get("type") or "").strip()
        if text:
            missed.append(text)
    for fix in agent_report.get("fixes") or []:
        text = str(fix.get("change") or fix.get("detail") or fix.get("title") or "").strip()
        if text and text.lower() not in {"speed posture looks reasonable for agent browsing; keep optimizing blocked actions and payload size."}:
            missed.append(text)

    for blocker in codex.get("blockers") or []:
        text = str(blocker.get("detail") or blocker.get("title") or "").strip()
        if text:
            if codex_inconclusive and has_playwright:
                reasons.append(f"Static limitation: {text}")
            else:
                missed.append(text)

    action_loss = _number(efficiency.get("actions_lost_percent"))
    if action_loss is not None:
        reasons.append(f"Measured action loss: {action_loss:g}%.")
    for item in ((codex.get("evidence") or {}).get("limitations") or [])[:2]:
        reasons.append(_contextualize_codex_limitation(str(item), has_playwright=has_playwright))

    return {
        "reached": _unique(reached)[:6],
        "missed": _unique(missed)[:6],
        "reasons": _unique(reasons)[:6],
    }


def _build_metrics(
    *,
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    codex: Dict[str, Any],
    assessment: Dict[str, Any],
) -> List[Dict[str, Any]]:
    coverage = audit.get("coverage") or {}
    efficiency = agent_report.get("efficiency") or {}
    action_coverage = coverage.get("action_accessibility_percent")
    if action_coverage is None and efficiency.get("actions_lost_percent") is not None:
        action_coverage = max(0, 100 - float(efficiency.get("actions_lost_percent") or 0))
    metrics = [
        {"label": "Agent readiness", "value": _metric_score(assessment.get("score"))},
        {"label": "Action coverage", "value": _metric_percent(action_coverage)},
        {"label": "Action loss", "value": _metric_percent(efficiency.get("actions_lost_percent"))},
        {"label": "Gaps found", "value": str(efficiency.get("gap_count") if efficiency.get("gap_count") is not None else len(agent_report.get("gaps") or []))},
    ]
    if codex.get("verdict"):
        metrics.append({"label": "Semantic scan", "value": str(codex.get("verdict")).replace("-", " ")})
    return metrics


def _build_business_dashboard(
    *,
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    action_evidence: Dict[str, Any],
    insights: Dict[str, Any],
) -> Dict[str, Any]:
    funnel = _build_business_funnel(
        audit=audit,
        agent_report=agent_report,
        action_evidence=action_evidence,
    )
    revenue_at_risk = _estimate_revenue_at_risk(funnel=funnel, agent_report=agent_report)
    confidence = _business_dashboard_confidence(funnel=funnel, action_evidence=action_evidence)
    health_kpis = _business_health_kpis(
        revenue_at_risk=revenue_at_risk,
        audit=audit,
        agent_report=agent_report,
        funnel=funnel,
    )
    blockers = _business_dashboard_blockers(funnel=funnel, insights=insights)
    opportunity_forecast = _business_opportunity_forecast(funnel=funnel, blockers=blockers, revenue_at_risk=revenue_at_risk)
    risk_label = _risk_label(revenue_at_risk)
    return {
        "revenue_at_risk_percent": revenue_at_risk,
        "risk_label": risk_label,
        "confidence": confidence,
        "headline": f"{revenue_at_risk:g}% estimated agent path loss",
        "summary": _business_dashboard_summary(risk_label=risk_label, funnel=funnel, blockers=blockers),
        "funnel": funnel,
        "health_kpis": health_kpis,
        "opportunity_forecast": opportunity_forecast,
        "top_business_blockers": blockers,
    }


def _build_business_funnel(
    *,
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    action_evidence: Dict[str, Any],
) -> List[Dict[str, Any]]:
    validated_by_id = _rows_by_id(action_evidence.get("validated_actions") or [])
    business_by_id = _rows_by_id(action_evidence.get("business_actions") or [])
    possible_by_id = _rows_by_id(action_evidence.get("possible_journeys") or [])
    job_results = _rows_by_id(agent_report.get("job_results") or [])
    top_actions = audit.get("top_actions") or []

    return [
        _generic_funnel_row(
            step=step,
            validated_by_id=validated_by_id,
            business_by_id=business_by_id,
            possible_by_id=possible_by_id,
            job_results=job_results,
            top_actions=top_actions,
        )
        for step in _GENERIC_FUNNEL_STEPS
    ]


def _generic_funnel_row(
    *,
    step: Dict[str, Any],
    validated_by_id: Dict[str, Dict[str, Any]],
    business_by_id: Dict[str, Dict[str, Any]],
    possible_by_id: Dict[str, Dict[str, Any]],
    job_results: Dict[str, Dict[str, Any]],
    top_actions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    job_ids = set(step.get("job_ids") or set())
    matched_validated = [row for job_id, row in validated_by_id.items() if job_id in job_ids]
    matched_business = [row for job_id, row in business_by_id.items() if job_id in job_ids]
    matched_possible = [row for job_id, row in possible_by_id.items() if job_id in job_ids]
    matched_results = [row for job_id, row in job_results.items() if job_id in job_ids]
    failed = [row for row in matched_results if _normalize_funnel_status(row.get("status")) in {"blocked", "failed"}]

    if matched_validated:
        best = _best_status([_normalize_funnel_status(row.get("status")) for row in matched_validated])
        evidence = _first_text(matched_validated, "supporting_detail", "result", "goal") or f"{step['label']} path was validated by the browser run."
        blocker = _first_text(matched_validated, "blocker")
    elif failed:
        best = "blocked"
        evidence = _first_text(failed, "result", "goal") or f"{step['label']} path was attempted but blocked."
        blocker = _first_text(failed, "blocker") or "The agent could not complete this business step."
    elif matched_business:
        best = "partial"
        evidence = _first_text(matched_business, "basis_inline", "result", "goal") or f"{step['label']} signal was detected but not validated end to end."
        blocker = _first_text(matched_business, "blocker") or "Detected path was not fully validated by the browser run."
    elif matched_possible:
        best = "not_tested"
        evidence = _first_text(matched_possible, "basis_inline", "goal") or f"{step['label']} was inferred from weak crawl signals."
        blocker = "Lower-confidence path; validate this step with a rendered agent run."
    elif _top_action_matches_step(top_actions, job_ids):
        best = "partial"
        evidence = f"{step['label']} has CTA evidence, but no completed agent journey was validated."
        blocker = "CTA was detected but not proven as a completed business path."
    else:
        best = "not_detected"
        evidence = str(step.get("summary") or "No clear evidence captured for this funnel step.")
        blocker = "No clear agent-readable path was captured for this step."

    weight = int(step.get("weight") or 0)
    return {
        "id": step.get("id"),
        "label": step.get("label"),
        "status": best,
        "weight": weight,
        "loss_contribution_percent": _loss_contribution(weight, best),
        "evidence": evidence,
        "blocker": blocker if best != "success" else "",
    }


def _estimate_revenue_at_risk(*, funnel: List[Dict[str, Any]], agent_report: Dict[str, Any]) -> float:
    base = sum(float(row.get("loss_contribution_percent") or 0) for row in funnel)
    step_waste = _number((agent_report.get("efficiency") or {}).get("step_waste_percent")) or 0
    friction_penalty = min(10.0, step_waste * 0.2)
    confidence_penalty = 5.0 if any(
        row.get("id") in {"convert", "handoff"} and row.get("status") in {"partial", "not_tested"}
        for row in funnel
    ) else 0.0
    return round(max(0.0, min(100.0, base + friction_penalty + confidence_penalty)), 1)


def _business_health_kpis(
    *,
    revenue_at_risk: float,
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    funnel: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    coverage = audit.get("coverage") or {}
    efficiency = agent_report.get("efficiency") or {}
    action_health = _number(coverage.get("action_accessibility_percent"))
    if action_health is None and efficiency.get("actions_lost_percent") is not None:
        action_health = max(0.0, 100.0 - float(efficiency.get("actions_lost_percent") or 0))
    conversion_steps = [row for row in funnel if row.get("id") in {"convert", "handoff", "add_to_cart", "cart", "checkout_handoff"}]
    conversion_loss = sum(float(row.get("loss_contribution_percent") or 0) for row in conversion_steps)
    conversion_weight = sum(float(row.get("weight") or 0) for row in conversion_steps) or 1.0
    conversion_health = max(0.0, 100.0 - ((conversion_loss / conversion_weight) * 100.0))
    friction = _number(efficiency.get("step_waste_percent")) or 0
    blocked = sum(1 for row in funnel if row.get("status") in {"blocked", "failed", "not_detected"})
    fastest = max(funnel, key=lambda row: float(row.get("loss_contribution_percent") or 0), default={})
    return [
        {
            "label": "Revenue at risk",
            "value": _metric_percent(revenue_at_risk),
            "status": _risk_label(revenue_at_risk).lower(),
            "note": "Estimated from blocked and degraded agentic funnel steps.",
        },
        {
            "label": "Conversion path health",
            "value": _metric_percent(round(conversion_health, 1)),
            "status": _health_label(conversion_health),
            "note": "Health of conversion and handoff stages.",
        },
        {
            "label": "Website action health",
            "value": _metric_percent(round(action_health, 1) if action_health is not None else None),
            "status": _health_label(action_health),
            "note": "Share of captured actions agents can reach.",
        },
        {
            "label": "Agent friction",
            "value": _metric_percent(round(friction, 1)),
            "status": _inverse_health_label(friction),
            "note": "Extra navigation or wasted steps measured during the run.",
        },
        {
            "label": "Blocked conversion steps",
            "value": str(blocked),
            "status": "good" if blocked == 0 else ("moderate" if blocked <= 1 else "high"),
            "note": "Funnel steps with blocked or missing evidence.",
        },
        {
            "label": "Fastest recovery opportunity",
            "value": str(fastest.get("label") or "—"),
            "status": "neutral",
            "note": "Largest contribution to estimated revenue at risk.",
        },
    ]


def _risk_label(percent: Any) -> str:
    value = _number(percent) or 0
    if value >= 70:
        return "Critical"
    if value >= 40:
        return "High"
    if value >= 15:
        return "Moderate"
    return "Low"


def _business_dashboard_confidence(
    *,
    funnel: List[Dict[str, Any]],
    action_evidence: Dict[str, Any],
) -> str:
    if action_evidence.get("validated_actions"):
        return "high"
    if action_evidence.get("business_actions"):
        return "medium"
    return "low"


def _business_dashboard_summary(*, risk_label: str, funnel: List[Dict[str, Any]], blockers: List[Dict[str, Any]]) -> str:
    top_step = max(funnel, key=lambda row: float(row.get("loss_contribution_percent") or 0), default={})
    top_label = str(top_step.get("label") or "the primary funnel").lower()
    if blockers:
        return f"{risk_label} risk is concentrated around {top_label}; the top blocker is {blockers[0].get('title')}."
    return f"{risk_label} risk is concentrated around {top_label}; validate and unblock that path first."


def _business_dashboard_blockers(*, funnel: List[Dict[str, Any]], insights: Dict[str, Any]) -> List[Dict[str, Any]]:
    blockers: List[Dict[str, Any]] = []
    for row in sorted(funnel, key=lambda item: float(item.get("loss_contribution_percent") or 0), reverse=True):
        if row.get("status") == "success":
            continue
        blockers.append(
            {
                "title": f"{row.get('label')} path is {str(row.get('status') or '').replace('_', ' ')}",
                "severity": "high" if float(row.get("loss_contribution_percent") or 0) >= 15 else "medium",
                "business_impact": f"This stage contributes {row.get('loss_contribution_percent')} percentage points to estimated agentic revenue at risk.",
                "developer_fix": f"Make the {str(row.get('label') or 'buyer')} step reachable, labelled, and recoverable for agents.",
                "evidence": row.get("evidence") or "",
            }
        )
        if len(blockers) >= 4:
            return blockers
    for item in insights.get("blockers") or []:
        blockers.append(
            {
                "title": item.get("title") or "Business blocker",
                "severity": item.get("severity") or "medium",
                "business_impact": item.get("why_it_matters") or item.get("user_intent") or "This can reduce agent conversion reliability.",
                "developer_fix": item.get("next_step") or "Expose a durable, labelled, agent-readable path.",
                "evidence": item.get("what_happened") or "",
            }
        )
        if len(blockers) >= 4:
            break
    return blockers[:4]


def _business_opportunity_forecast(
    *,
    funnel: List[Dict[str, Any]],
    blockers: List[Dict[str, Any]],
    revenue_at_risk: float,
) -> List[Dict[str, Any]]:
    rows = []
    for row in sorted(funnel, key=lambda item: float(item.get("loss_contribution_percent") or 0), reverse=True)[:3]:
        contribution = float(row.get("loss_contribution_percent") or 0)
        if contribution <= 0:
            continue
        rows.append(
            {
                "title": f"Recover {row.get('label')} leakage",
                "detail": f"Fixing this stage could reduce estimated risk by up to {contribution:g} percentage points.",
                "recovery_percent": round(contribution, 1),
            }
        )
    if not rows and blockers:
        rows.append(
            {
                "title": blockers[0].get("title"),
                "detail": "Fix the top blocker first to create measurable funnel recovery.",
                "recovery_percent": 0,
            }
        )
    if not rows:
        rows.append(
            {
                "title": "Keep validating high-value paths",
                "detail": f"Current estimated risk is {revenue_at_risk:g}%; retest after product or content changes.",
                "recovery_percent": 0,
            }
        )
    return rows[:3]


def _rows_by_id(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    result = {}
    for row in rows:
        row_id = str(row.get("id") or "").strip()
        if row_id and row_id not in result:
            result[row_id] = row
    return result


def _normalize_funnel_status(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    if text in {"success", "pass"}:
        return "success"
    if text in {"partial", "detected", "warn"}:
        return "partial"
    if text in {"blocked", "failed", "fail"}:
        return "blocked"
    if text == "not_detected":
        return "not_detected"
    if text == "not_tested":
        return "not_tested"
    return text or "not_tested"


def _best_status(statuses: List[str]) -> str:
    order = {"success": 0, "partial": 1, "not_tested": 2, "blocked": 3, "failed": 3, "not_detected": 4}
    return sorted(statuses or ["not_tested"], key=lambda status: order.get(status, 5))[0]


def _loss_contribution(weight: int, status: str) -> float:
    value = float(weight or 0) * float(_FUNNEL_STATUS_MULTIPLIERS.get(status, 0.6))
    return round(value, 1)


def _first_text(rows: List[Dict[str, Any]], *keys: str) -> str:
    for row in rows:
        for key in keys:
            value = str(row.get(key) or "").strip()
            if value and value != "—":
                return value
    return ""


def _top_action_matches_step(top_actions: List[Dict[str, Any]], job_ids: set[str]) -> bool:
    labels = " ".join(str(action.get("label") or "").lower() for action in top_actions)
    targets = " ".join(str(action.get("target_path") or "").lower() for action in top_actions)
    haystack = f"{labels} {targets}"
    tokens_by_job = {
        "product": ("product", "feature", "solution"),
        "find_product": ("product", "shop", "collection"),
        "pricing": ("pricing", "plans"),
        "convert": ("signup", "sign up", "trial", "waitlist"),
        "book_demo": ("demo", "book", "sales"),
        "add_to_cart": ("cart", "buy", "bag"),
        "checkout": ("checkout", "cart"),
        "contact": ("contact", "support", "sales"),
        "blog": ("blog", "article", "docs"),
    }
    tokens = [token for job_id in job_ids for token in tokens_by_job.get(job_id, ())]
    return any(token in haystack for token in tokens)


def _health_label(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "neutral"
    if number >= 80:
        return "good"
    if number >= 60:
        return "moderate"
    return "high"


def _inverse_health_label(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "neutral"
    if number <= 10:
        return "good"
    if number <= 25:
        return "moderate"
    return "high"


def _build_user_insights(
    *,
    codex: Dict[str, Any],
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    access: Dict[str, Any],
    action_evidence: Dict[str, Any],
) -> Dict[str, Any]:
    gaps = agent_report.get("gaps") or []
    efficiency = agent_report.get("efficiency") or {}
    coverage = audit.get("coverage") or {}
    blockers = []
    wins = []
    notes = []

    dead_targets = [gap for gap in gaps if str(gap.get("type") or "") == "dead_target"]
    if dead_targets:
        labels = [str(gap.get("label") or "").strip() for gap in dead_targets if str(gap.get("label") or "").strip()]
        page = str(dead_targets[0].get("page_id") or "site").strip()
        target_count = len(labels) or len(dead_targets)
        blockers.append(
            {
                "severity": "high",
                "title": f"{target_count} links point to routes agents cannot reach",
                "user_intent": f"Open content from {page}",
                "what_happened": _sample_sentence(labels, fallback="Several links resolve to missing or unreachable pages."),
                "why_it_matters": "Agents can identify the link, click it, and still fail the delegated task because the destination is broken.",
                "next_step": "Fix the hrefs/routes or remove unpublished links from the rendered page.",
            }
        )

    llms_gaps = [gap for gap in gaps if str(gap.get("type") or "") in {"llms_txt", "llms-txt"}]
    if llms_gaps:
        blockers.append(
            {
                "severity": "medium",
                "title": "Agent guidance file was not available",
                "user_intent": "Understand site structure before acting",
                "what_happened": "The audit could not confirm a working llms.txt at the domain root.",
                "why_it_matters": "This does not block ordinary clicks, but it removes a useful map for agents and enterprise crawlers.",
                "next_step": "Publish llms.txt at the apex/www domain and verify it returns 200 over HTTPS.",
            }
        )

    for blocker in codex.get("blockers") or []:
        title = str(blocker.get("title") or "").strip()
        detail = str(blocker.get("detail") or "").strip()
        if not title or len(blockers) >= 4:
            continue
        blockers.append(
            {
                "severity": str(blocker.get("severity") or "medium"),
                "title": title,
                "user_intent": "Read and operate the page reliably",
                "what_happened": detail,
                "why_it_matters": "Semantic or visibility ambiguity can make an otherwise visible interface harder for agents to target.",
                "next_step": _next_step_for_codex_blocker(title),
            }
        )

    accessible = coverage.get("accessible_actions")
    total = coverage.get("total_actions")
    if accessible is not None and total is not None:
        wins.append(
            {
                "title": "Rendered actions were discoverable",
                "value": f"{accessible}/{total}",
                "detail": "Captured actions were present in the rendered audit and could be evaluated for agent use.",
            }
        )

    successful = int(efficiency.get("successful_clicks") or 0)
    failed = int(efficiency.get("failed_clicks") or 0)
    if successful or failed:
        wins.append(
            {
                "title": "Agent click path was measurable",
                "value": f"{successful} success / {failed} failed",
                "detail": "The browser agent attempted real interactions, so the report is based on execution rather than screenshots alone.",
            }
        )

    for item in (action_evidence.get("validated_actions") or [])[:3]:
        detail = str(item.get("supporting_detail") or item.get("result") or "").strip()
        if not detail:
            detail = str(item.get("goal") or "").strip()
        wins.append({"title": item.get("title") or "Validated path", "value": "", "detail": detail})

    step_waste = _number(efficiency.get("step_waste_percent"))
    if step_waste is not None:
        notes.append(
            {
                "title": "Path efficiency",
                "detail": f"The agent spent {step_waste:g}% extra steps/time versus the shortest observed path.",
            }
        )

    return {
        "blockers": blockers[:4],
        "wins": wins[:4],
        "notes": notes[:3],
    }


def _build_score_explanation(
    *,
    codex: Dict[str, Any],
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    assessment: Dict[str, Any],
    action_evidence: Dict[str, Any],
    insights: Dict[str, Any],
) -> Dict[str, str]:
    context = {
        "score": assessment.get("score"),
        "verdict": assessment.get("verdict"),
        "confidence": assessment.get("confidence"),
        "agent_reach_percent": audit.get("agent_accessibility_score")
        or ((audit.get("coverage") or {}).get("action_accessibility_percent")),
        "structural_speed_percent": audit.get("agent_speed_score"),
        "missed_actions_percent": (agent_report.get("efficiency") or {}).get("actions_lost_percent"),
        "extra_navigation_percent": (agent_report.get("efficiency") or {}).get("step_waste_percent"),
        "validated_actions": [
            {
                "title": item.get("title"),
                "status": item.get("status"),
                "result": item.get("result"),
                "goal": item.get("goal"),
            }
            for item in (action_evidence.get("validated_actions") or [])[:4]
        ],
        "business_actions": [
            {
                "title": item.get("title"),
                "confidence": item.get("confidence"),
                "status": item.get("status"),
                "basis_inline": item.get("basis_inline"),
            }
            for item in (action_evidence.get("business_actions") or [])[:4]
        ],
        "possible_journeys": [
            {
                "title": item.get("title"),
                "confidence": item.get("confidence"),
            }
            for item in (action_evidence.get("possible_journeys") or [])[:4]
        ],
        "top_blocker": (insights.get("blockers") or [{}])[0],
        "codex_summary": str(codex.get("executive_summary") or "").strip(),
    }
    cache_key = hashlib.sha1(json.dumps(context, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    if cache_key in _SUMMARY_CACHE:
        return _SUMMARY_CACHE[cache_key]

    summary = _generate_score_explanation_with_llm(context) if Config.llm_available() else None
    if not summary:
        summary = _fallback_score_explanation(context)
    if len(_SUMMARY_CACHE) > 128:
        _SUMMARY_CACHE.clear()
    _SUMMARY_CACHE[cache_key] = summary
    return summary


def _generate_score_explanation_with_llm(context: Dict[str, Any]) -> Dict[str, str] | None:
    try:
        from ..utils.llm_client import LLMClient

        client = LLMClient()
        result = client.chat_json(
            [
                {"role": "system", "content": _ACTION_SUMMARY_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context, indent=2, sort_keys=True)},
            ],
            temperature=0.15,
            max_tokens=500,
        )
    except Exception:
        return None

    summary = {
        "headline": str(result.get("headline") or "").strip(),
        "action_summary": str(result.get("action_summary") or "").strip(),
        "score_pressure": str(result.get("score_pressure") or "").strip(),
        "next_focus": str(result.get("next_focus") or "").strip(),
    }
    if not all(summary.values()):
        return None
    return summary


def _fallback_score_explanation(context: Dict[str, Any]) -> Dict[str, str]:
    validated_actions = context.get("validated_actions") or []
    top_blocker = context.get("top_blocker") or {}
    score = context.get("score")
    verdict = str(context.get("verdict") or "Inconclusive").strip()
    agent_reach = _number(context.get("agent_reach_percent"))
    structural_speed = _number(context.get("structural_speed_percent"))
    missed_actions = _number(context.get("missed_actions_percent"))
    extra_navigation = _number(context.get("extra_navigation_percent"))

    if validated_actions:
        action_parts = []
        for item in validated_actions[:3]:
            title = str(item.get("title") or "").strip()
            status = str(item.get("status") or "").strip()
            if title and status:
                action_parts.append(f"{title} ({status})")
        action_summary = "Validated actions: " + ", ".join(action_parts) + "."
    else:
        action_summary = "The browser run did not validate a dependable business action path yet."

    if validated_actions and any(str(item.get("status") or "") == "partial" for item in validated_actions):
        headline = "Agents completed some useful steps, but the audited flow is still not dependable enough for autonomous use."
    elif validated_actions:
        headline = f"Agents completed {len(validated_actions)} validated action path(s), but the site still needs more reliable coverage before it is fully agent-ready."
    else:
        headline = "The browser run did not validate a dependable action path, so the site is not yet ready for autonomous agent use."

    pressure_bits = []
    if agent_reach is not None:
        pressure_bits.append(f"agent reach was {agent_reach:g}%")
    if missed_actions is not None:
        pressure_bits.append(f"missed actions were {missed_actions:g}%")
    if extra_navigation is not None and extra_navigation > 0:
        pressure_bits.append(f"extra navigation was {extra_navigation:g}%")
    if structural_speed is not None:
        pressure_bits.append(f"structural speed stayed at {structural_speed:g}%")
    blocker_title = str(top_blocker.get("title") or "").strip()
    blocker_detail = str(top_blocker.get("why_it_matters") or top_blocker.get("what_happened") or "").strip()
    if pressure_bits:
        score_pressure = f"The score landed at {score if score is not None else '—'}/100 because " + ", while ".join(
            [", ".join(pressure_bits[:2]), ", ".join(pressure_bits[2:])]
        ).strip(", while ")
        score_pressure += "."
    else:
        score_pressure = "The score reflects the balance between validated actions, reach, friction, and semantic clarity."
    if blocker_title:
        score_pressure += f" The strongest blocker was {blocker_title.lower()}."
    if blocker_detail:
        score_pressure += f" {blocker_detail}"

    next_focus_parts = []
    if agent_reach is not None and agent_reach < 50:
        next_focus_parts.append("expose clearer on-site actions that the crawl can measure")
    if missed_actions is not None and missed_actions >= 50:
        next_focus_parts.append("reduce the missed-action penalty")
    if blocker_title:
        next_focus_parts.append(f"fix {blocker_title.lower()}")
    if not next_focus_parts:
        next_focus_parts.append("tighten the highest-friction action path")
    next_focus = "Next focus: " + ", then ".join(_unique(next_focus_parts)[:3]) + "."

    return {
        "headline": headline,
        "action_summary": action_summary,
        "score_pressure": score_pressure,
        "next_focus": next_focus,
    }


def _build_improvement_forecast(
    *,
    codex: Dict[str, Any],
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    assessment: Dict[str, Any],
    action_evidence: Dict[str, Any],
    insights: Dict[str, Any],
) -> Dict[str, Any]:
    current_score = int(assessment.get("score") or 0)
    components = {str(item.get("label") or ""): item for item in (assessment.get("components") or [])}
    efficiency = agent_report.get("efficiency") or {}
    validated_actions = action_evidence.get("validated_actions") or []
    blockers = insights.get("blockers") or []
    fixes = agent_report.get("fixes") or []

    candidate_specs = [
        _component_improvement_candidate(
            label="Action coverage",
            title="Raise agent reach on measurable on-site actions",
            target_score=_target_component_score(components.get("Action coverage"), baseline=60, boost=40),
            reason=_agent_reach_reason(audit, action_evidence),
            time_saved_percent=_estimate_time_saved_from_reach(audit, efficiency),
            current_score=current_score,
            components=components,
        ),
        _component_improvement_candidate(
            label="Path efficiency",
            title="Reduce extra navigation and dead-end steps",
            target_score=_target_component_score(components.get("Path efficiency"), baseline=85, boost=20),
            reason=_path_efficiency_reason(efficiency),
            time_saved_percent=_estimate_path_time_saved(efficiency),
            current_score=current_score,
            components=components,
        ),
        _component_improvement_candidate(
            label="Semantic clarity",
            title="Strengthen semantic guidance and machine-readable structure",
            target_score=_target_component_score(components.get("Semantic clarity"), baseline=92, boost=10),
            reason=_semantic_clarity_reason(codex, blockers, fixes),
            time_saved_percent=_estimate_semantic_time_saved(blockers, efficiency),
            current_score=current_score,
            components=components,
        ),
        _component_improvement_candidate(
            label="Rendered task performance",
            title="Validate one more key business task end to end",
            target_score=_target_component_score(components.get("Rendered task performance"), baseline=70, boost=25),
            reason=_rendered_task_reason(validated_actions, action_evidence),
            time_saved_percent=_estimate_validation_time_saved(efficiency, validated_actions),
            current_score=current_score,
            components=components,
        ),
    ]
    candidates = [item for item in candidate_specs if item]
    top_items = sorted(candidates, key=lambda item: (item["score_lift_percent"], item["time_saved_percent"]), reverse=True)[:3]
    projected_score = _simulate_projected_score(current_score, components, top_items)
    projected_score_lift = max(0, projected_score - current_score)
    projected_time_saved = min(95, sum(int(item.get("time_saved_percent") or 0) for item in top_items))

    context = {
        "current_score": current_score,
        "projected_score": projected_score,
        "projected_score_lift_percent": projected_score_lift,
        "projected_time_saved_percent": projected_time_saved,
        "items": [
            {
                "component": item["component_key"],
                "target_label": item["target_label"],
                "score_lift_percent": item["score_lift_percent"],
                "time_saved_percent": item["time_saved_percent"],
                "reason": item["reason"],
            }
            for item in top_items
        ],
    }
    summary = _generate_improvement_forecast_with_llm(context) if Config.llm_available() else None
    if not summary:
        summary = _fallback_improvement_forecast(context)
    summary["projected_score"] = projected_score
    summary["projected_score_lift_percent"] = projected_score_lift
    summary["projected_time_saved_percent"] = projected_time_saved
    summary["raw_items"] = top_items
    return summary


def _component_improvement_candidate(
    *,
    label: str,
    title: str,
    target_score: int | None,
    reason: str,
    time_saved_percent: int,
    current_score: int,
    components: Dict[str, Dict[str, Any]],
) -> Dict[str, Any] | None:
    component = components.get(label) or {}
    current_component_score = component.get("score")
    weight = int(component.get("weight") or 0)
    if current_component_score is None or not weight or target_score is None:
        return None
    target_score = max(int(current_component_score), min(100, int(target_score)))
    if target_score <= int(current_component_score):
        return None
    projected = _simulate_score_with_component(components, label, target_score)
    score_lift = max(0, projected - current_score)
    if score_lift <= 0:
        return None
    return {
        "component_key": label.lower().replace(" ", "_"),
        "title": title,
        "target_label": f"{title} to about {target_score}%",
        "score_lift_percent": score_lift,
        "time_saved_percent": max(0, int(time_saved_percent)),
        "reason": reason,
        "target_score": target_score,
    }


def _target_component_score(component: Dict[str, Any] | None, *, baseline: int, boost: int) -> int | None:
    if not component or component.get("score") is None:
        return None
    current = int(component.get("score") or 0)
    return min(100, max(baseline, current + boost))


def _simulate_score_with_component(
    components: Dict[str, Dict[str, Any]],
    component_label: str,
    target_score: int,
) -> int:
    total = 0.0
    for label, item in components.items():
        score = item.get("score")
        if score is None:
            continue
        use_score = target_score if label == component_label else int(score)
        total += float(use_score) * (float(item.get("weight") or 0) / 100)
    return round(total)


def _simulate_projected_score(
    current_score: int,
    components: Dict[str, Dict[str, Any]],
    improvements: List[Dict[str, Any]],
) -> int:
    if not improvements:
        return current_score
    target_map = {item["component_key"]: item["target_score"] for item in improvements}
    total = 0.0
    for label, item in components.items():
        score = item.get("score")
        if score is None:
            continue
        key = label.lower().replace(" ", "_")
        use_score = target_map.get(key, int(score))
        total += float(use_score) * (float(item.get("weight") or 0) / 100)
    return round(total)


def _agent_reach_reason(audit: Dict[str, Any], action_evidence: Dict[str, Any]) -> str:
    coverage = audit.get("coverage") or {}
    top_title = str(((action_evidence.get("business_actions") or [{}])[0]).get("title") or "").strip()
    total = int(coverage.get("total_actions") or 0)
    reachable = int(coverage.get("accessible_actions") or 0)
    base = f"The crawl only measured {reachable}/{total or 1} reachable captured action(s)."
    if top_title:
        return f"{base} The strongest unvalidated business action is {top_title.lower()}."
    return base


def _path_efficiency_reason(efficiency: Dict[str, Any]) -> str:
    step_waste = _number(efficiency.get("step_waste_percent")) or 0
    time_lost = _number(efficiency.get("time_lost_percent")) or 0
    return f"The run currently loses about {max(step_waste, time_lost):g}% of its path efficiency to retries, detours, or dead ends."


def _semantic_clarity_reason(codex: Dict[str, Any], blockers: List[Dict[str, Any]], fixes: List[Dict[str, Any]]) -> str:
    blocker_title = str((blockers[0] if blockers else {}).get("title") or "").strip()
    if blocker_title:
        return f"The strongest clarity gap right now is {blocker_title.lower()}."
    fix_title = str((fixes[0] if fixes else {}).get("title") or "").strip()
    if fix_title:
        return f"The report already recommends {fix_title.lower()} to improve semantic guidance."
    return str(codex.get("executive_summary") or "Semantic guidance can be clearer for agents.").strip()


def _rendered_task_reason(validated_actions: List[Dict[str, Any]], action_evidence: Dict[str, Any]) -> str:
    partials = [item for item in validated_actions if str(item.get("status") or "") == "partial"]
    if partials:
        return f"The agent only partially completed {partials[0].get('title', 'a key task').lower()}."
    possible = action_evidence.get("possible_journeys") or []
    if possible:
        return f"The report still has inferred-but-unvalidated journeys such as {possible[0].get('title', 'a business action').lower()}."
    return "The agent still needs one more fully validated business action path."


def _estimate_time_saved_from_reach(audit: Dict[str, Any], efficiency: Dict[str, Any]) -> int:
    time_lost = int(round(_number(efficiency.get("time_lost_percent")) or 0))
    external = int(((audit.get("coverage") or {}).get("external_actions")) or 0)
    if time_lost:
        return min(20, max(3, round(time_lost * 0.35)))
    return 3 if external else 0


def _estimate_path_time_saved(efficiency: Dict[str, Any]) -> int:
    step_waste = int(round(_number(efficiency.get("step_waste_percent")) or 0))
    time_lost = int(round(_number(efficiency.get("time_lost_percent")) or 0))
    return min(40, max(step_waste, time_lost))


def _estimate_semantic_time_saved(blockers: List[Dict[str, Any]], efficiency: Dict[str, Any]) -> int:
    if any("guidance" in str(item.get("title") or "").lower() or "semantic" in str(item.get("title") or "").lower() for item in blockers):
        return max(0, min(12, round((_number(efficiency.get("time_lost_percent")) or 0) * 0.2)))
    return 0


def _estimate_validation_time_saved(efficiency: Dict[str, Any], validated_actions: List[Dict[str, Any]]) -> int:
    if not validated_actions:
        return max(5, int(round((_number(efficiency.get("time_lost_percent")) or 0) * 0.25)))
    if any(str(item.get("status") or "") == "partial" for item in validated_actions):
        return max(4, int(round((_number(efficiency.get("time_lost_percent")) or 0) * 0.25)))
    return 0


def _generate_improvement_forecast_with_llm(context: Dict[str, Any]) -> Dict[str, Any] | None:
    try:
        from ..utils.llm_client import LLMClient

        client = LLMClient()
        result = client.chat_json(
            [
                {"role": "system", "content": _IMPROVEMENT_FORECAST_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context, indent=2, sort_keys=True)},
            ],
            temperature=0.15,
            max_tokens=650,
        )
    except Exception:
        return None

    items = result.get("items")
    if not isinstance(items, list) or len(items) != 3:
        return None
    normalized_items = []
    for item in items[:3]:
        title = str((item or {}).get("title") or "").strip()
        detail = str((item or {}).get("detail") or "").strip()
        if not title or not detail:
            return None
        normalized_items.append({"title": title, "detail": detail})
    headline = str(result.get("headline") or "").strip()
    summary = str(result.get("summary") or "").strip()
    if not headline or not summary:
        return None
    return {"headline": headline, "summary": summary, "items": normalized_items}


def _fallback_improvement_forecast(context: Dict[str, Any]) -> Dict[str, Any]:
    score_lift = int(context.get("projected_score_lift_percent") or 0)
    time_saved = int(context.get("projected_time_saved_percent") or 0)
    items = []
    for raw in (context.get("items") or [])[:3]:
        title = str(raw.get("target_label") or "Improve this area").strip()
        delta = int(raw.get("score_lift_percent") or 0)
        time_delta = int(raw.get("time_saved_percent") or 0)
        reason = str(raw.get("reason") or "").strip()
        if time_delta > 0:
            detail = f"Could lift the score by about {delta}% and cut traversal time by about {time_delta}%. {reason}"
        else:
            detail = f"Could lift the score by about {delta}%, mainly through clarity and reliability rather than speed. {reason}"
        items.append({"title": title, "detail": detail})
    while len(items) < 3:
        items.append({"title": "Tighten the next highest-friction path", "detail": "This should improve reliability and create more measurable agent evidence."})
    return {
        "headline": f"If you improve these 3 things, your score could rise by about {score_lift}% and agents could spend about {time_saved}% less time traversing.",
        "summary": "These are the fastest independent levers based on the current score components, validated actions, and blockers.",
        "items": items[:3],
    }


def _build_action_evidence(*, audit: Dict[str, Any], agent_report: Dict[str, Any]) -> Dict[str, Any]:
    explore_jobs = {
        str(job.get("id") or "").strip(): job
        for job in (agent_report.get("explore_jobs") or [])
        if str(job.get("id") or "").strip()
    }
    top_actions = [action for action in (audit.get("top_actions") or []) if isinstance(action, dict)]
    page_type = str(audit.get("page_type") or "").strip().lower()
    validated_actions: List[Dict[str, Any]] = []
    business_actions: List[Dict[str, Any]] = []
    possible_journeys: List[Dict[str, Any]] = []
    for row in agent_report.get("job_results") or []:
        status = str(row.get("status") or "").strip().lower()
        if status not in {"success", "partial"}:
            continue
        job_id = str(row.get("id") or "").strip()
        job = explore_jobs.get(job_id) or {}
        title = _action_title(job_id, job, row)
        supporting_detail = _supporting_detail(job=job, row=row)
        validated_actions.append(
            {
                "id": job_id or title.lower().replace(" ", "_"),
                "title": title,
                "goal": str(row.get("goal") or job.get("goal") or "").strip(),
                "status": status,
                "result": str(row.get("result") or "").strip(),
                "blocker": str(row.get("blocker") or "").strip(),
                "supporting_detail": supporting_detail,
            }
        )

    for job_id, job in explore_jobs.items():
        if job_id == "orient":
            continue
        attempted_row = _job_result_for_id(agent_report.get("job_results") or [], job_id)
        if attempted_row and str(attempted_row.get("status") or "").lower() in {"success", "partial"}:
            continue
        inferred = _build_inferred_action(
            job_id=job_id,
            job=job,
            top_actions=top_actions,
            page_type=page_type,
            attempted_row=attempted_row,
        )
        if not inferred:
            continue
        high_confidence = bool(inferred.pop("high_confidence"))
        is_primary_business_action = job_id in _BUSINESS_RELEVANT_JOB_IDS
        target = business_actions if high_confidence and is_primary_business_action else possible_journeys
        target.append(inferred)

    # Fall back to top action evidence when there are no inferred business actions at all.
    if not business_actions and not possible_journeys and not explore_jobs and top_actions:
        fallback = _fallback_business_action(top_actions[0], page_type=page_type)
        if fallback:
            business_actions.append(fallback)

    return {
        "validated_actions": validated_actions[:6],
        "business_actions": business_actions[:6],
        "possible_journeys": possible_journeys[:8],
    }


def _build_inferred_action(
    *,
    job_id: str,
    job: Dict[str, Any],
    top_actions: List[Dict[str, Any]],
    page_type: str,
    attempted_row: Dict[str, Any] | None,
) -> Dict[str, Any] | None:
    title = _action_title(job_id, job, attempted_row)
    goal = str(job.get("goal") or "").strip()
    prefixes = [str(path).strip() for path in (job.get("path_prefixes") or []) if str(path).strip() and str(path).strip() != "/"]
    nav_keywords = [str(token).strip().lower() for token in (job.get("nav_keywords") or []) if str(token).strip()]
    top_labels = [str(action.get("label") or "").strip() for action in top_actions if str(action.get("label") or "").strip()]
    matched_labels = []
    for label in top_labels:
        lower = label.lower()
        if any(keyword in lower or lower in keyword for keyword in nav_keywords):
            matched_labels.append(label)
    cta_label = str(job.get("cta_label") or "").strip()
    if cta_label:
        matched_labels.append(cta_label)
    matched_labels = _unique(matched_labels)[:3]

    strong_paths = [path for path in prefixes if _has_strong_path_signal(path)]
    page_type_support = job_id in _PAGE_TYPE_SUPPORT.get(page_type, set())
    score = 0
    if strong_paths:
        score += 2
    if len(matched_labels) >= 2:
        score += 2
    elif matched_labels:
        score += 1
    if page_type_support:
        score += 1
    if cta_label:
        score += 1

    high_confidence = bool(strong_paths or len(matched_labels) >= 2 or (page_type_support and matched_labels)) and score >= 3
    confidence = "high" if high_confidence else ("medium" if score >= 2 else "low")
    basis_inline = _basis_inline(
        prefixes=strong_paths or prefixes,
        matched_labels=matched_labels,
        page_type=page_type if page_type_support else "",
    )
    if not basis_inline:
        return None

    inferred = {
        "id": job_id,
        "title": title,
        "goal": goal,
        "confidence": confidence,
        "basis_inline": basis_inline,
        "high_confidence": high_confidence,
    }
    if attempted_row and str(attempted_row.get("status") or "").lower() in {"success", "partial"}:
        inferred["status"] = str(attempted_row.get("status") or "").lower()
        inferred["result"] = str(attempted_row.get("result") or "").strip()
        blocker = str(attempted_row.get("blocker") or "").strip()
        if blocker and blocker != "—":
            inferred["blocker"] = blocker
    return inferred


def _fallback_business_action(top_action: Dict[str, Any], *, page_type: str) -> Dict[str, Any] | None:
    label = str(top_action.get("label") or "").strip()
    if not label:
        return None
    target_path = str(top_action.get("target_path") or "").strip()
    parts = []
    if target_path:
        parts.append(target_path)
    if page_type:
        parts.append(f"{page_type.replace('_', ' ')} page type")
    basis = "Inferred from " + " and ".join(parts) + f' around the CTA "{label}".'
    return {
        "id": "top_action",
        "title": f'Investigate the CTA "{label}"',
        "goal": "Review the strongest action found in the rendered crawl and confirm whether it is a primary business action.",
        "confidence": "medium",
        "basis_inline": basis,
    }


def _job_result_for_id(rows: List[Dict[str, Any]], job_id: str) -> Dict[str, Any] | None:
    for row in rows:
        if str(row.get("id") or "").strip() == job_id:
            return row
    return None


def _action_title(job_id: str, job: Dict[str, Any], row: Dict[str, Any] | None = None) -> str:
    if job_id in _BUSINESS_ACTION_TITLES:
        return _BUSINESS_ACTION_TITLES[job_id]
    raw = str((job or {}).get("job") or (row or {}).get("job") or "").strip()
    return raw or "Agent action"


def _supporting_detail(*, job: Dict[str, Any], row: Dict[str, Any]) -> str:
    result = str(row.get("result") or "").strip()
    if result and result != "partial activation":
        return result
    prefixes = [str(path).strip() for path in (job.get("path_prefixes") or []) if str(path).strip() and str(path).strip() != "/"]
    cta_label = str(job.get("cta_label") or "").strip()
    parts = []
    if prefixes:
        parts.append("Path evidence: " + ", ".join(prefixes[:3]))
    if cta_label:
        parts.append(f'CTA evidence: "{cta_label}"')
    return " | ".join(parts)


def _has_strong_path_signal(path: str) -> bool:
    lowered = str(path or "").strip("/").lower()
    if not lowered:
        return False
    return any(segment in lowered.split("/") for segment in _STRONG_PATH_SEGMENTS)


def _basis_inline(*, prefixes: List[str], matched_labels: List[str], page_type: str) -> str:
    parts = []
    if prefixes:
        parts.append(", ".join(prefixes[:3]))
    if matched_labels:
        quoted = ", ".join(f'"{label}"' for label in matched_labels[:3])
        parts.append(f"CTA labels {quoted}")
    if page_type:
        parts.append(f"{page_type.replace('_', ' ')} page type")
    if not parts:
        return ""
    return "Inferred from " + " and ".join(parts) + "."


def _sample_sentence(items: List[str], *, fallback: str) -> str:
    clean = [item for item in items if item]
    if not clean:
        return fallback
    if len(clean) == 1:
        return f"“{clean[0]}” points to a route agents cannot reach."
    sample = ", ".join(f"“{item}”" for item in clean[:3])
    more = f", and {len(clean) - 3} more" if len(clean) > 3 else ""
    return f"{sample}{more} point to routes agents cannot reach."


def _next_step_for_codex_blocker(title: str) -> str:
    lowered = title.lower()
    if "animation" in lowered or "hidden" in lowered or "visibility" in lowered:
        return "Keep primary content perceivable before animations complete, and respect reduced motion."
    if "duplicate" in lowered or "navigation" in lowered:
        return "Expose one primary navigation per viewport in the accessibility tree, or label each nav clearly."
    if "heading" in lowered or "glyph" in lowered:
        return "Use one meaningful h1 and mark decorative glyphs aria-hidden."
    return "Tighten roles, labels, and visible state so agents can target the control deterministically."


def _score_components(
    *,
    rendered_score: float | None,
    action_coverage: float | None,
    path_efficiency: float | None,
    codex_score: float | None,
    codex_inconclusive: bool,
) -> List[Dict[str, Any]]:
    raw = [
        {
            "label": "Rendered task performance",
            "score": rendered_score,
            "weight": 35,
            "detail": "What the browser agent could execute after the product rendered.",
        },
        {
            "label": "Action coverage",
            "score": action_coverage,
            "weight": 30,
            "detail": "How many discovered actions were addressable and reachable.",
        },
        {
            "label": "Path efficiency",
            "score": path_efficiency,
            "weight": 20,
            "detail": "Penalty for failed clicks, repeated steps, and wasted time.",
        },
        {
            "label": "Semantic clarity",
            "score": codex_score,
            "weight": 15,
            "detail": "Codex review of static semantics, labels, headings, and agent-readable structure.",
            "note": "context only" if codex_inconclusive else "",
        },
    ]
    available_weight = sum(item["weight"] for item in raw if item["score"] is not None)
    components = []
    for item in raw:
        score = item["score"]
        normalized_weight = 0 if score is None or not available_weight else round((item["weight"] / available_weight) * 100)
        components.append(
            {
                "label": item["label"],
                "score": None if score is None else round(score),
                "weight": normalized_weight,
                "detail": item["detail"],
                "note": item.get("note") or "",
            }
        )
    return components


def _weighted_score(components: List[Dict[str, Any]]) -> int | None:
    available = [item for item in components if item.get("score") is not None and item.get("weight")]
    if not available:
        return None
    return round(sum(float(item["score"]) * (float(item["weight"]) / 100) for item in available))


def _contextualize_codex_limitation(text: str, *, has_playwright: bool) -> str:
    value = str(text or "").strip()
    if not has_playwright:
        return value
    lowered = value.lower()
    if "no rendered-browser" in lowered or "no headless browser" in lowered or "post-hydration" in lowered:
        return (
            "Codex static pass did not launch its own browser; the paired rendered-browser audit supplied "
            "computed visibility, runtime accessibility, and task-execution evidence."
        )
    if "only the submitted page" in lowered or "linked pages" in lowered:
        return "Codex static pass inspected the submitted page; the paired crawl explored linked product paths."
    return f"Codex static pass limitation: {value}"


def _is_inconclusive_codex_result(codex: Dict[str, Any]) -> bool:
    return (
        bool(codex)
        and str(codex.get("verdict") or "").lower() == "inconclusive"
        and str(codex.get("confidence") or "").lower() == "low"
        and float(codex.get("score") or 0) == 0
    )


def _build_combined_artifact(
    *,
    report: Dict[str, Any],
    codex: Dict[str, Any],
    playwright: Dict[str, Any],
    playwright_exports: Dict[str, Any],
) -> Dict[str, Any]:
    source_url = str(report.get("source_url") or "").strip()
    title = "Combined agent readiness artifact"
    evidence = []
    if report.get("has_playwright"):
        evidence.append("Rendered-browser audit: executed the page, inspected reachable actions, and measured task readiness.")
    if report.get("has_codex"):
        evidence.append("Codex audit: independently inspected the submitted surface and produced semantic findings.")

    report_md = _build_artifact_report_md(
        title=title,
        source_url=source_url,
        report=report,
        codex=codex,
        playwright_exports=playwright_exports,
        evidence=evidence,
    )
    skill_md = _build_artifact_skill_md(
        source_url=source_url,
        report=report,
        codex=codex,
        playwright_exports=playwright_exports,
    )

    return {
        "title": title,
        "evidence": evidence,
        "report_md": report_md,
        "skill_md": skill_md,
        "llms_txt": playwright_exports.get("llms_txt") or "",
    }


def _build_artifact_report_md(
    *,
    title: str,
    source_url: str,
    report: Dict[str, Any],
    codex: Dict[str, Any],
    playwright_exports: Dict[str, Any],
    evidence: List[str],
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Source: {source_url or 'unknown'}",
        "",
        "## Agent readiness score",
        "",
        f"- Score: {_score_text(report.get('score'))}",
        f"- Verdict: {report.get('verdict') or 'Inconclusive'}",
        f"- Confidence: {report.get('confidence') or 'low'}",
        f"- Basis: {(report.get('assessment') or {}).get('basis') or 'Combined audit evidence.'}",
        "",
    ]
    dashboard = report.get("business_dashboard") or {}
    if dashboard:
        lines.extend(
            [
                "## Business funnel dashboard",
                "",
                f"- Estimated agentic revenue at risk: {_metric_percent(dashboard.get('revenue_at_risk_percent'))}",
                f"- Risk: {dashboard.get('risk_label') or 'Unknown'}",
                f"- Confidence: {dashboard.get('confidence') or 'low'}",
                f"- Summary: {dashboard.get('summary') or 'No business summary was generated.'}",
                "",
                "### Funnel health",
                "",
            ]
        )
        for step in dashboard.get("funnel") or []:
            lines.append(
                f"- **{step.get('label')}**: {str(step.get('status') or '').replace('_', ' ')}; "
                f"{_metric_percent(step.get('loss_contribution_percent'))} risk contribution. "
                f"{step.get('evidence') or ''} Blocker: {step.get('blocker') or '-'}"
            )
        blockers = dashboard.get("top_business_blockers") or []
        lines.extend(["", "### Top business blockers", ""])
        if blockers:
            for index, blocker in enumerate(blockers, 1):
                lines.append(
                    f"{index}. {blocker.get('title')}: {blocker.get('business_impact')} "
                    f"Fix: {blocker.get('developer_fix')}"
                )
        else:
            lines.append("No high-impact business blockers were detected.")

    lines.extend([
        "",
        "## Score logic",
        "",
    ])
    for component in (report.get("assessment") or {}).get("components") or []:
        score = _score_text(component.get("score"), fallback="not used")
        note = f" ({component.get('note')})" if component.get("note") else ""
        lines.append(f"- {component.get('label')}: {score}, {component.get('weight')}% weight{note}. {component.get('detail')}")

    lines.extend([
        "",
        "## Executive summary",
        "",
    ])
    for item in report.get("summary") or []:
        lines.append(f"- {item}")
    if not report.get("summary"):
        lines.append("- No summary was generated.")

    lines.extend(["", "## Evidence used", ""])
    for item in evidence:
        lines.append(f"- {item}")

    access = report.get("access") or {}
    lines.extend(["", "## What agents could access", ""])
    for item in access.get("reached") or ["No reached actions were recorded."]:
        lines.append(f"- {item}")
    lines.extend(["", "## What agents could not access", ""])
    for item in access.get("missed") or ["No blocked actions were recorded."]:
        lines.append(f"- {item}")
    lines.extend(["", "## Why", ""])
    for item in access.get("reasons") or ["No additional limitations were recorded."]:
        lines.append(f"- {item}")

    lines.extend(["", "## Recommended fixes", ""])
    fixes = report.get("fixes") or []
    if fixes:
        for fix in fixes:
            source = str(fix.get("source") or "audit").title()
            priority = str(fix.get("priority") or "medium").title()
            lines.append(f"- [{source} / {priority}] {fix.get('title')}: {fix.get('detail')}")
    else:
        lines.append("- No blocking fixes were found in the combined artifact.")

    codex_blockers = codex.get("blockers") or []
    if codex_blockers:
        lines.extend(["", "## Codex semantic notes", ""])
        for blocker in codex_blockers[:5]:
            lines.append(f"- {blocker.get('title')}: {blocker.get('detail')}")

    base_report = str(playwright_exports.get("report_md") or "").strip()
    if base_report:
        lines.extend(["", "## Rendered-browser report", "", base_report])

    return "\n".join(lines).strip() + "\n"


def _build_artifact_skill_md(
    *,
    source_url: str,
    report: Dict[str, Any],
    codex: Dict[str, Any],
    playwright_exports: Dict[str, Any],
) -> str:
    base_skill = str(playwright_exports.get("skill_md") or "").strip()
    lines = []
    if base_skill:
        lines.append(base_skill)
        lines.extend(["", "---", ""])
    lines.extend(
        [
            "# Combined OpenIngress remediation context",
            "",
            f"Source: {source_url or 'unknown'}",
            "",
            f"Combined score: {_score_text(report.get('score'))} ({report.get('verdict') or 'Inconclusive'})",
            f"Score basis: {(report.get('assessment') or {}).get('basis') or 'Combined audit evidence.'}",
            "",
            "Use the combined evidence before changing code:",
            "- Fix actions agents could not reach in the rendered product.",
            "- Fix static or semantic risks that make actions disappear for non-visual agents.",
            "",
            "## Combined fixes",
            "",
        ]
    )
    fixes = report.get("fixes") or []
    if fixes:
        for fix in fixes:
            source = str(fix.get("source") or "audit")
            priority = str(fix.get("priority") or "medium")
            lines.append(f"- `{priority}` `{source}`: {fix.get('title')} — {fix.get('detail')}")
    else:
        lines.append("- No blocking combined fixes were found. Preserve current working semantics when making unrelated changes.")

    codex_summary = str(codex.get("executive_summary") or "").strip()
    if codex_summary:
        lines.extend(["", "## Codex semantic note", "", codex_summary])

    lines.extend(
        [
            "",
            "## Guardrails",
            "",
            "- Do not optimize only for visual layout; preserve role, name, state, and keyboard reachability.",
            "- Prefer native links/buttons over clickable divs.",
            "- Re-run the combined OpenIngress audit after changes and compare both rendered-browser and Codex evidence.",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _score_text(score: Any, fallback: Any = None) -> str:
    if score is None:
        return str(fallback or "inconclusive")
    return f"{score}/100"


def _number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _metric_percent(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    return f"{number:g}%"


def _metric_score(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    return f"{number:g}/100"


def _unique(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out
