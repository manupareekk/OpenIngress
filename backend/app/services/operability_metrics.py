"""Metrics for agent accessibility coverage and before/after comparison."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List

from ..models import AGENT_ACCESSIBLE_TARGET_KINDS, NavigationTargetKind


def accessibility_from_graph(graph: Dict[str, Any]) -> Dict[str, Any]:
    actions = graph.get("actions") or []
    if not actions:
        return {
            "action_accessibility_percent": 100.0,
            "accessible_actions": 0,
            "total_actions": 0,
            "blocked_actions": 0,
            "by_target_kind": {},
        }
    counts = Counter(str(item.get("target_kind") or "") for item in actions)
    accessible = sum(counts.get(kind, 0) for kind in AGENT_ACCESSIBLE_TARGET_KINDS)
    total = len(actions)
    blocked_kinds = {
        NavigationTargetKind.DEAD_TARGET.value,
        NavigationTargetKind.UNKNOWN_JS.value,
        NavigationTargetKind.AUTH_REQUIRED.value,
    }
    blocked = sum(counts.get(kind, 0) for kind in blocked_kinds)
    external = counts.get(NavigationTargetKind.EXTERNAL_EXIT.value, 0) + counts.get(
        NavigationTargetKind.DOWNLOAD_EXIT.value, 0
    )
    on_site_total = total - external
    percent = round(100.0 * accessible / max(1, on_site_total), 2) if total else 100.0
    pages = graph.get("pages") or []
    pages_with_actions = {str(item.get("page_id")) for item in actions}
    page_ids = {str(item.get("id")) for item in pages}
    reachable_pages = len(pages_with_actions & page_ids) if page_ids else len(pages_with_actions)
    page_percent = round(100.0 * reachable_pages / len(page_ids), 2) if page_ids else 100.0
    return {
        "action_accessibility_percent": percent,
        "page_coverage_percent": page_percent,
        "accessible_actions": accessible,
        "total_actions": total,
        "blocked_actions": blocked,
        "external_actions": external,
        "on_site_only_percent": percent,
        "by_target_kind": dict(counts),
        "static_coverage": (graph.get("quality") or {}).get("static_coverage"),
    }


def task_metrics(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_task: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in events:
        by_task[str(event.get("task_id") or "default")].append(event)

    results = {}
    for task_id, task_events in by_task.items():
        sessions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for event in task_events:
            sessions[str(event.get("session_id"))].append(event)
        successes = 0
        steps_list: List[int] = []
        durations: List[int] = []
        for session_events in sessions.values():
            ordered = sorted(session_events, key=lambda item: int(item.get("step") or 0))
            if any(item.get("action") == "TASK_SUCCESS" for item in ordered):
                successes += 1
            steps_list.append(len(ordered))
            durations.append(sum(int(item.get("duration_ms") or 0) for item in ordered))
        total_sessions = len(sessions) or 1
        results[task_id] = {
            "sessions": len(sessions),
            "success_rate": round(successes / total_sessions, 4),
            "median_steps": _median(steps_list),
            "median_duration_ms": _median(durations),
        }
    return results


def compare_before_after(
    before: Dict[str, Any],
    after: Dict[str, Any],
    *,
    before_tasks: Dict[str, Any],
    after_tasks: Dict[str, Any],
) -> Dict[str, Any]:
    action_delta = round(
        after.get("action_accessibility_percent", 0) - before.get("action_accessibility_percent", 0),
        2,
    )
    page_delta = round(after.get("page_coverage_percent", 0) - before.get("page_coverage_percent", 0), 2)
    task_improvements = {}
    for task_id, after_row in after_tasks.items():
        before_row = before_tasks.get(task_id) or {}
        task_improvements[task_id] = {
            "success_rate_delta": round(
                after_row.get("success_rate", 0) - before_row.get("success_rate", 0),
                4,
            ),
            "median_steps_delta": (after_row.get("median_steps") or 0) - (before_row.get("median_steps") or 0),
        }
    return {
        "action_accessibility_delta": action_delta,
        "page_coverage_delta": page_delta,
        "before": before,
        "after": after,
        "task_improvements": task_improvements,
        "summary": _comparison_summary(action_delta, task_improvements),
    }


def _comparison_summary(action_delta: float, task_improvements: Dict[str, Any]) -> str:
    parts = []
    if action_delta > 0:
        parts.append(f"Agent-accessible actions improved by {action_delta}%.")
    elif action_delta < 0:
        parts.append(f"Agent-accessible actions decreased by {abs(action_delta)}%.")
    else:
        parts.append("Agent-accessible action share unchanged.")
    improved_tasks = [
        task_id
        for task_id, row in task_improvements.items()
        if (row.get("success_rate_delta") or 0) > 0
    ]
    if improved_tasks:
        parts.append(f"Task success improved for: {', '.join(improved_tasks)}.")
    return " ".join(parts)


def _median(values: List[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return int(ordered[mid])
    return int((ordered[mid - 1] + ordered[mid]) / 2)
