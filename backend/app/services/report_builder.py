"""Markdown agent site audit reports."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List


def build_report_markdown(run_id: str, metrics: Dict[str, Any], events: List[Dict[str, Any]]) -> str:
    audit_bundle = metrics.get("audit") or {}
    primary_audit = audit_bundle.get("site") or audit_bundle.get("before") or {}
    lines = [
        f"# Agent site audit — `{run_id}`",
        "",
    ]
    if primary_audit:
        lines.extend(_audit_section(primary_audit))
    else:
        lines.append("_No audit metadata found._")
        lines.append("")

    coverage = metrics.get("coverage_by_phase") or {}
    if coverage:
        lines.append("## Operability coverage")
        lines.append("")
        for phase, row in coverage.items():
            lines.append(
                f"- **{phase}**: {row.get('action_accessibility_percent', 0)}% actions accessible "
                f"({row.get('accessible_actions', 0)}/{row.get('total_actions', 0)}), "
                f"{row.get('blocked_actions', 0)} blocked"
            )
        lines.append("")

    comparison = metrics.get("before_after") or {}
    if comparison.get("summary"):
        lines.extend(["## Before vs after", "", comparison["summary"], ""])

    task_by_phase = metrics.get("task_metrics_by_phase") or {}
    if task_by_phase:
        lines.append("## Live operator probe (optional)")
        lines.append("")
        for phase, tasks in task_by_phase.items():
            for task_id, row in tasks.items():
                lines.append(
                    f"- **{task_id}** ({phase}): {int((row.get('success_rate') or 0) * 100)}% success, "
                    f"median {row.get('median_steps', 0)} steps"
                )
        lines.append("")

    lines.extend(_fix_suggestions(metrics, events, primary_audit))
    return "\n".join(lines)


def _audit_section(audit: Dict[str, Any]) -> List[str]:
    lines = [
        "## Agent experience score",
        "",
        f"**Overall:** {audit.get('overall_score', '—')}/100",
        f"**Accessibility:** {audit.get('agent_accessibility_score', '—')}%",
        f"**Structural speed proxy:** {audit.get('agent_speed_score', '—')}%",
        "",
        audit.get("audit_focus") or "Maximize agent accessibility and speed.",
        "",
    ]
    speed = audit.get("speed_summary") or {}
    if speed:
        lines.append("### Structural speed signals")
        lines.append("")
        lines.append(f"- HTML payload: {int(speed.get('html_bytes') or 0):,} bytes")
        if speed.get("dom_node_count") is not None:
            lines.append(f"- DOM nodes: {int(speed.get('dom_node_count') or 0):,}")
        if speed.get("max_dom_depth") is not None:
            lines.append(f"- Max DOM depth: {int(speed.get('max_dom_depth') or 0)}")
        if speed.get("interactive_node_count") is not None:
            lines.append(f"- Interactive nodes: {int(speed.get('interactive_node_count') or 0):,}")
        if speed.get("interactive_density_percent") is not None:
            lines.append(f"- Interactive density: {float(speed.get('interactive_density_percent') or 0):.1f}%")
        if speed.get("text_char_count") is not None:
            lines.append(f"- Text payload: {int(speed.get('text_char_count') or 0):,} chars")
        lines.append(f"- Scripts: {speed.get('script_count', 0)}")
        lines.append(f"- Stylesheets: {speed.get('stylesheet_count', 0)}")
        lines.append(f"- Images: {speed.get('image_count', 0)}")
        lines.append("")
    if audit.get("rationale"):
        lines.append("### Audit summary")
        lines.append("")
        for item in audit["rationale"]:
            lines.append(f"- {item}")
        lines.append("")
    if audit.get("recommendations"):
        lines.append("## What to fix")
        lines.append("")
        for index, item in enumerate(audit["recommendations"], 1):
            lines.append(f"{index}. {item}")
        lines.append("")
    if audit.get("top_actions"):
        lines.append("## Top actions detected")
        lines.append("")
        for action in audit["top_actions"][:5]:
            lines.append(
                f"- **{action.get('label')}** — score {action.get('score')} ({action.get('reason')})"
            )
        lines.append("")
    return lines


def _fix_suggestions(
    metrics: Dict[str, Any],
    events: List[Dict[str, Any]],
    audit: Dict[str, Any],
) -> List[str]:
    if audit.get("recommendations"):
        return []
    lines = ["## Additional notes", ""]
    coverage = metrics.get("coverage_by_phase") or {}
    after = coverage.get("after") or coverage.get("before") or coverage.get("site") or {}
    percent = float(after.get("action_accessibility_percent") or 0)
    if percent < 85:
        lines.append("- Improve agent-navigable actions across the captured flow.")
    failures = Counter(
        event.get("element_name")
        for event in events
        if event.get("action") == "EXIT" and event.get("element_name")
    )
    if failures.get("no_actionable_node"):
        lines.append("- Add accessible names to interactive controls (aria-label or visible text).")
    return lines
