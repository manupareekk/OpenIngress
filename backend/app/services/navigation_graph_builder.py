"""
Static website navigation graph extraction for product experiments.

This layer turns imported/pasted HTML pages into an explicit graph of actions
and resolved targets. It deliberately does not execute page scripts; rendered
DOM extraction can be added behind a separate Playwright pass.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from ..models import (
    ExperimentGoal,
    FlowPage,
    NavigationAction,
    NavigationGraph,
    NavigationIssue,
    NavigationTargetKind,
    ProductActionType,
)
from .selector_utils import build_element_selector, selector_matches_html


DOWNLOAD_EXTENSIONS = {
    ".pdf",
    ".zip",
    ".csv",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
}

AUTH_PATH_HINTS = ("login", "log-in", "signin", "sign-in", "auth", "account")
MODAL_ATTRS = ("data-modal", "data-toggle", "data-bs-toggle", "data-target", "popovertarget", "aria-expanded")


class NavigationGraphBuilder:
    def build(
        self,
        variant_id: str,
        pages: List[FlowPage],
        start_page_id: str,
        goal: Optional[ExperimentGoal] = None,
        success_selector: str = "",
    ) -> NavigationGraph:
        variant_success_selector = str(success_selector or "").strip()
        by_id = {page.id: page for page in pages}
        by_path = {normalize_path(page.path): page for page in pages if page.path}
        graph_actions: List[NavigationAction] = []
        issues: List[NavigationIssue] = []

        for page in pages:
            summary = dict(page.metadata.get("summary") or {})
            resolved_actions = []
            for index, raw_action in enumerate(summary.get("actions") or []):
                action = self._resolve_action(
                    variant_id=variant_id,
                    page=page,
                    action=dict(raw_action),
                    index=index,
                    by_id=by_id,
                    by_path=by_path,
                    goal=goal,
                    variant_success_selector=variant_success_selector,
                )
                graph_actions.append(action)
                resolved = dict(raw_action)
                resolved.update(action.to_dict())
                resolved["id"] = raw_action.get("id") or action.id
                resolved["graph_action_id"] = action.id
                resolved["target_missing"] = action.target_kind in {
                    NavigationTargetKind.DEAD_TARGET.value,
                    NavigationTargetKind.UNKNOWN_JS.value,
                }
                resolved["target_external"] = action.target_kind in {
                    NavigationTargetKind.EXTERNAL_EXIT.value,
                    NavigationTargetKind.DOWNLOAD_EXIT.value,
                    NavigationTargetKind.AUTH_REQUIRED.value,
                }
                resolved["target_is_conversion"] = action.target_kind == NavigationTargetKind.GOAL_REACHED.value
                if action.target_page_id:
                    target_page = by_id.get(action.target_page_id)
                    resolved["target_is_conversion"] = bool(
                        resolved["target_is_conversion"] or (target_page and target_page.is_conversion)
                    )
                if action.issue_code:
                    issues.append(
                        NavigationIssue(
                            code=action.issue_code,
                            severity=self._issue_severity(action.target_kind),
                            page_id=page.id,
                            action_id=action.id,
                            message=self._issue_message(action),
                            details={
                                "text": action.element_text,
                                "raw_target": action.raw_target,
                                "selector": action.selector,
                            },
                        )
                    )
                resolved_actions.append(resolved)
            summary["actions"] = resolved_actions
            page.metadata["summary"] = summary

        graph = NavigationGraph(
            variant_id=variant_id,
            start_page_id=start_page_id,
            pages=[
                {
                    "id": page.id,
                    "path": normalize_path(page.path),
                    "title": page.title,
                    "is_start": page.id == start_page_id or page.is_start,
                    "is_conversion": page.is_conversion,
                    "action_count": len((page.metadata.get("summary") or {}).get("actions") or []),
                }
                for page in pages
            ],
            actions=graph_actions,
            issues=issues,
        )
        graph.quality = self._quality(graph, pages, goal)
        return graph

    def _resolve_action(
        self,
        variant_id: str,
        page: FlowPage,
        action: Dict[str, Any],
        index: int,
        by_id: Dict[str, FlowPage],
        by_path: Dict[str, FlowPage],
        goal: Optional[ExperimentGoal],
        variant_success_selector: str = "",
    ) -> NavigationAction:
        attrs = {str(key).lower(): str(value or "") for key, value in (action.get("attributes") or {}).items()}
        action_id = action.get("id") or _action_id("action", index, attrs)
        graph_action_id = f"{page.id}::{action_id}"
        raw_target = str(
            attrs.get("href")
            or attrs.get("action")
            or attrs.get("data-href")
            or attrs.get("data-url")
            or attrs.get("data-target")
            or action.get("target_path")
            or ""
        )
        target_page_id = str(attrs.get("data-next-page") or attrs.get("data-page") or "")
        if not target_page_id and not raw_target.startswith("#"):
            target_page_id = str(action.get("target_page_id") or "")
        target_path = normalize_path(raw_target, base_path=page.path)
        action_type = str(action.get("action_type") or ProductActionType.CLICK_LINK.value)
        tag = str(action.get("tag") or attrs.get("_tag") or "")
        selector = str(
            action.get("selector")
            or _selector_for(tag, attrs, action_id, html=page.html or "")
        )
        text = str(action.get("element_text") or action.get("text") or attrs.get("aria-label") or attrs.get("title") or "")
        target_kind = NavigationTargetKind.DEAD_TARGET.value
        issue_code = ""
        resolved_page_id = ""
        resolved_path = target_path

        if action.get("is_conversion"):
            target_kind = NavigationTargetKind.GOAL_REACHED.value
        elif target_page_id and target_page_id in by_id:
            target_kind = NavigationTargetKind.INTERNAL_PAGE.value
            resolved_page_id = target_page_id
            resolved_path = normalize_path(by_id[target_page_id].path)
        elif raw_target.strip().startswith("#"):
            target_kind = NavigationTargetKind.SAME_PAGE_ANCHOR.value
            resolved_page_id = page.id
            resolved_path = f"{normalize_path(page.path)}{raw_target.strip()}"
        elif target_path and target_path in by_path:
            target_kind = NavigationTargetKind.INTERNAL_PAGE.value
            resolved_page_id = by_path[target_path].id
            resolved_path = normalize_path(by_path[target_path].path)
        elif _is_external(raw_target):
            target_kind = NavigationTargetKind.EXTERNAL_EXIT.value
            resolved_path = raw_target.strip()
        elif _is_download(raw_target):
            target_kind = NavigationTargetKind.DOWNLOAD_EXIT.value
        elif self._looks_auth_required(raw_target):
            target_kind = NavigationTargetKind.AUTH_REQUIRED.value
        elif action_type == ProductActionType.SUBMIT_FORM.value:
            target_kind = NavigationTargetKind.FORM_SUBMIT.value
            resolved_page_id = page.id
            resolved_path = target_path or normalize_path(page.path)
        elif self._looks_modal_or_state_change(attrs):
            target_kind = NavigationTargetKind.MODAL_OR_STATE_CHANGE.value
            resolved_page_id = page.id
            resolved_path = normalize_path(page.path)
        elif self._action_matches_goal(action, goal, variant_success_selector, page.html):
            target_kind = NavigationTargetKind.GOAL_REACHED.value
        elif target_path.startswith("/") and raw_target.strip():
            target_kind = NavigationTargetKind.INTERNAL_LINK.value
        elif attrs.get("onclick") or attrs.get("data-action"):
            target_kind = NavigationTargetKind.UNKNOWN_JS.value
            issue_code = "unknown_js_action"
        elif raw_target or target_page_id:
            target_kind = NavigationTargetKind.DEAD_TARGET.value
            issue_code = "dead_target"
        elif tag in {"button", "input"} or action_type == ProductActionType.CLICK_CTA.value:
            target_kind = NavigationTargetKind.UNKNOWN_JS.value
            issue_code = "button_without_resolved_target"
        else:
            issue_code = "unresolved_action"

        if not issue_code and target_kind in {
            NavigationTargetKind.DEAD_TARGET.value,
            NavigationTargetKind.UNKNOWN_JS.value,
        }:
            issue_code = "unresolved_action"

        return NavigationAction(
            id=graph_action_id,
            page_id=page.id,
            action_type=action_type,
            selector=selector,
            tag=tag,
            element_id=str(action.get("element_id") or attrs.get("id") or action_id),
            element_text=text[:180],
            role=str(action.get("role") or ""),
            raw_target=raw_target,
            target_kind=target_kind,
            target_page_id=resolved_page_id,
            target_path=resolved_path,
            method=str(attrs.get("method") or action.get("method") or "GET").upper(),
            issue_code=issue_code,
            attributes={key: value for key, value in attrs.items() if not key.startswith("_")},
            context={
                "variant_id": variant_id,
                "source_action_id": action_id,
            },
        )

    def _action_matches_goal(
        self,
        action: Dict[str, Any],
        goal: Optional[ExperimentGoal],
        variant_success_selector: str = "",
        page_html: str = "",
    ) -> bool:
        selector = str(action.get("selector") or "").strip()
        if variant_success_selector and selector and selector == variant_success_selector:
            return True
        if goal and selector and selector in {item.strip() for item in goal.success_selectors if item}:
            if not page_html or selector_matches_html(selector, page_html):
                return True
        if not goal:
            return False
        action_type = str(action.get("action_type") or "").upper()
        return bool(action_type and action_type in {item.upper() for item in goal.success_actions})

    def _looks_auth_required(self, raw_target: str) -> bool:
        target = (raw_target or "").lower()
        return bool(target and any(hint in target for hint in AUTH_PATH_HINTS))

    def _looks_modal_or_state_change(self, attrs: Dict[str, str]) -> bool:
        return any(attrs.get(attr) for attr in MODAL_ATTRS)

    def _issue_severity(self, target_kind: str) -> str:
        if target_kind == NavigationTargetKind.DEAD_TARGET.value:
            return "error"
        if target_kind == NavigationTargetKind.UNKNOWN_JS.value:
            return "warning"
        return "info"

    def _issue_message(self, action: NavigationAction) -> str:
        if action.target_kind == NavigationTargetKind.DEAD_TARGET.value:
            return f"Action target could not be resolved: {action.raw_target or action.target_page_id or action.element_text}"
        if action.target_kind == NavigationTargetKind.UNKNOWN_JS.value:
            return f"Action likely depends on JavaScript and has no resolved navigation target: {action.element_text or action.selector}"
        return f"Navigation issue: {action.issue_code}"

    def _quality(self, graph: NavigationGraph, pages: List[FlowPage], goal: Optional[ExperimentGoal]) -> Dict[str, Any]:
        total_actions = len(graph.actions)
        counts: Dict[str, int] = {}
        for action in graph.actions:
            counts[action.target_kind] = counts.get(action.target_kind, 0) + 1
        unresolved = counts.get(NavigationTargetKind.DEAD_TARGET.value, 0) + counts.get(NavigationTargetKind.UNKNOWN_JS.value, 0)
        goal_reachable = any(page.is_conversion for page in pages)
        if goal and not goal_reachable:
            goal_paths = {normalize_path(path) for path in goal.success_page_paths}
            goal_reachable = any(
                page.id in set(goal.success_page_ids)
                or normalize_path(page.path) in goal_paths
                or any(text.lower() in page.html.lower() for text in goal.success_text if text)
                for page in pages
            )
        if not goal_reachable:
            goal_reachable = any(action.target_kind == NavigationTargetKind.GOAL_REACHED.value for action in graph.actions)
        return {
            "pages": len(pages),
            "actions": total_actions,
            "target_kind_counts": counts,
            "issues": len(graph.issues),
            "unresolved_actions": unresolved,
            "static_coverage": round(1 - unresolved / total_actions, 4) if total_actions else 1.0,
            "goal_reachable": bool(goal_reachable),
            "extractor": graph.extractor,
        }


def normalize_path(path: str, base_path: str = "") -> str:
    value = (path or "").strip()
    if not value:
        return ""
    if _is_external(value) or value.startswith("//"):
        return value.rstrip("/")
    if value.startswith("#"):
        return value
    value = value.split("#", 1)[0].split("?", 1)[0]
    if not value:
        return normalize_path(base_path)
    if not value.startswith("/"):
        base = normalize_path(base_path)
        if base and base != "/":
            parent = base.rsplit("/", 1)[0] or "/"
            value = f"{parent.rstrip('/')}/{value}"
        else:
            value = f"/{value}"
    value = re.sub(r"/+", "/", value)
    if value.endswith("/index.html"):
        value = value[: -len("index.html")]
    if value.endswith(".html"):
        value = value[:-5]
    return value.rstrip("/") or "/"


def graph_from_variant_metadata(variant_metadata: Dict[str, Any]) -> Dict[str, Any]:
    graph = variant_metadata.get("navigation_graph") or {}
    return graph if isinstance(graph, dict) else {}


def _selector_for(tag: str, attrs: Dict[str, str], fallback_id: str, *, html: str = "") -> str:
    return build_element_selector(tag, attrs, html=html, fallback_id=fallback_id)


def _action_id(prefix: str, index: int, attrs: Dict[str, str]) -> str:
    return attrs.get("id") or attrs.get("data-track") or attrs.get("data-testid") or attrs.get("name") or f"{prefix}_{index + 1}"


def _is_external(path: str) -> bool:
    value = (path or "").strip().lower()
    if not value or value.startswith("#"):
        return False
    return value.startswith("//") or bool(re.match(r"^[a-z][a-z0-9+.-]*:", value))


def _is_download(path: str) -> bool:
    clean = (path or "").strip().lower().split("?", 1)[0].split("#", 1)[0]
    return any(clean.endswith(ext) for ext in DOWNLOAD_EXTENSIONS)


def summarize_graphs(variants: Iterable[Any]) -> Dict[str, Any]:
    summaries = {}
    for variant in variants:
        graph = graph_from_variant_metadata(getattr(variant, "metadata", {}) or {})
        if graph:
            summaries[getattr(variant, "id", "")] = graph.get("quality") or {}
    return summaries
