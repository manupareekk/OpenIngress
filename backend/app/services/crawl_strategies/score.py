"""Strategy-specific scoring helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def score_strategy(strategy: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    page_types = {str(row.get("page_type") or "") for row in strategy.get("page_segments") or []}
    action_roles = {str(row.get("action_role") or "") for row in strategy.get("action_segments") or []}
    steps: List[Dict[str, Any]] = []
    total_weight = 0
    earned = 0

    for step in config.get("funnel_steps") or []:
        weight = int(step.get("weight") or 0)
        total_weight += weight
        page_hit = any(item in page_types for item in step.get("page_types") or [])
        action_hit = any(item in action_roles for item in step.get("action_roles") or [])
        if page_hit and (action_hit or not step.get("action_roles")):
            status = "pass"
            earned += weight
        elif page_hit or action_hit:
            status = "partial"
            earned += round(weight * 0.55)
        else:
            status = "not_detected"
        steps.append(
            {
                "id": step.get("id"),
                "label": step.get("label"),
                "status": status,
                "weight": weight,
            }
        )

    risks = strategy.get("risks") or []
    risk_penalty = min(18, len(risks) * 4)
    score = max(0, min(100, round((earned / max(total_weight, 1)) * 100 - risk_penalty)))
    return {
        "readiness_score": score,
        "funnel_steps": steps,
        "risk_penalty": risk_penalty,
    }
