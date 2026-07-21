"""Build safe Playwright probe plans from strategy intelligence."""

from __future__ import annotations

from typing import Any, Dict, List


def build_probe_plan(strategy: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    page_segments = strategy.get("page_segments") or []
    action_segments = strategy.get("action_segments") or []
    by_page_type = _first_by(page_segments, "page_type")
    by_action_role = _first_by(action_segments, "action_role")
    probes: List[Dict[str, Any]] = []

    for step in config.get("funnel_steps") or []:
        step_id = str(step.get("id") or "")
        page = next((by_page_type.get(item) for item in step.get("page_types") or [] if by_page_type.get(item)), None)
        action = next((by_action_role.get(item) for item in step.get("action_roles") or [] if by_action_role.get(item)), None)
        target = page or action or _fallback_target(step_id, by_page_type, by_action_role)
        if not target:
            continue
        probes.append(
            {
                "id": f"probe_{step_id}",
                "step_id": step_id,
                "label": step.get("label") or step_id,
                "start_path": target.get("path") or target.get("target_path") or "/",
                "action_role": action.get("action_role") if action else "",
                "fallback_used": not bool(page or action),
                "safe_mode": "checkout_handoff_only" if step.get("handoff_only") else "standard",
                "forbidden_actions": (config.get("safe_probe_rules") or {}).get("forbidden_actions") or [],
                "status": "planned",
            }
        )
    return probes


def _first_by(rows: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if value and value not in result:
            result[value] = row
    return result


def _fallback_target(
    step_id: str,
    by_page_type: Dict[str, Dict[str, Any]],
    by_action_role: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    if step_id == "collection_search":
        return (
            by_page_type.get("collection")
            or by_page_type.get("search")
            or by_page_type.get("homepage")
            or {}
        )
    if step_id in {"variant_selection", "add_to_cart"}:
        return by_page_type.get("product") or by_action_role.get("product_link") or {}
    if step_id == "cart":
        return (
            by_page_type.get("cart")
            or by_action_role.get("cart_open")
            or by_page_type.get("product")
            or by_action_role.get("add_to_cart")
            or {}
        )
    if step_id == "checkout_handoff":
        return (
            by_page_type.get("checkout_handoff")
            or by_action_role.get("checkout_link")
            or by_page_type.get("cart")
            or by_page_type.get("product")
            or {}
        )
    return {}
