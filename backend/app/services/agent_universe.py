"""Build the static 'universe' of actions and info nodes discoverable on a crawled site."""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urljoin

from ..models import NavigationTargetKind
from .gap_taxonomy import catalog_accessible_name


def build_site_universe(
    *,
    source_url: str,
    pages: List[Dict[str, Any]],
    navigation_graph: Dict[str, Any],
) -> Dict[str, Any]:
    """Catalog every action and info snippet found in the crawl (before live agent validation)."""
    graph_actions = navigation_graph.get("actions") or []
    strategy = navigation_graph.get("strategy") or {}
    page_segments = {
        str(row.get("page_id") or ""): row for row in strategy.get("page_segments") or []
    }
    page_by_id = {str(p.get("id")): p for p in pages}
    page_entries: List[Dict[str, Any]] = []
    all_actions: List[Dict[str, Any]] = []
    all_info: List[Dict[str, Any]] = []

    for page in pages:
        page_id = str(page.get("id") or "")
        path = str(page.get("path") or "/")
        summary = dict((page.get("metadata") or {}).get("summary") or {})
        page_actions = [a for a in graph_actions if str(a.get("page_id")) == page_id]
        page_info = _info_nodes_from_summary(page_id, path, summary)
        page_entries.append(
            {
                "page_id": page_id,
                "path": path,
                "title": page.get("title") or summary.get("headline") or path,
                "url": urljoin(source_url, path),
                "action_count": len(page_actions),
                "info_count": len(page_info),
                "strategy": page_segments.get(page_id)
                or (page.get("metadata") or {}).get("strategy")
                or {},
            }
        )
        for action in page_actions:
            row = _action_universe_row(action, source_url)
            all_actions.append(row)
        all_info.extend(page_info)

    internal_urls = _discovered_internal_urls(source_url, pages, graph_actions)
    counts = _universe_counts(all_actions)

    return {
        "source_url": source_url,
        "pages": page_entries,
        "page_count": len(page_entries),
        "discovered_internal_urls": sorted(internal_urls),
        "discovered_internal_url_count": len(internal_urls),
        "actions": all_actions,
        "info_nodes": all_info,
        "totals": {
            "actions": len(all_actions),
            "info_nodes": len(all_info),
            **counts,
        },
        "strategy": strategy,
    }


def _action_universe_row(action: Dict[str, Any], source_url: str) -> Dict[str, Any]:
    kind = str(action.get("target_kind") or "")
    path = str(action.get("target_path") or "")
    on_site = kind in {
        NavigationTargetKind.INTERNAL_PAGE.value,
        NavigationTargetKind.INTERNAL_LINK.value,
        NavigationTargetKind.SAME_PAGE_ANCHOR.value,
        NavigationTargetKind.MODAL_OR_STATE_CHANGE.value,
        NavigationTargetKind.FORM_SUBMIT.value,
        NavigationTargetKind.GOAL_REACHED.value,
    }
    return {
        "id": action.get("id") or action.get("graph_action_id"),
        "page_id": action.get("page_id"),
        "label": (catalog_accessible_name(action) or action.get("element_text") or action.get("text") or "")[
            :120
        ],
        "role": _infer_role(action),
        "selector": action.get("selector") or "",
        "target_kind": kind,
        "target_path": path,
        "target_url": urljoin(source_url, path) if path.startswith("/") else path,
        "on_site": on_site,
        "agent_priority": _agent_priority(action, on_site, kind),
        "strategy": (action.get("context") or {}).get("strategy") or {},
        "action_role": action.get("action_role") or ((action.get("context") or {}).get("strategy") or {}).get("action_role"),
        "buyer_step": action.get("buyer_step") or ((action.get("context") or {}).get("strategy") or {}).get("buyer_step"),
        "priority": action.get("priority") or ((action.get("context") or {}).get("strategy") or {}).get("priority"),
        "risk_flags": action.get("risk_flags") or [],
    }


def _infer_role(action: Dict[str, Any]) -> str:
    tag = str(action.get("tag") or action.get("element_tag") or "").lower()
    action_type = str(action.get("action_type") or "").upper()
    if tag == "button" or "CTA" in action_type:
        return "button"
    if tag in {"input", "textarea", "select"}:
        return "textbox"
    return "link"


def _agent_priority(action: Dict[str, Any], on_site: bool, kind: str) -> str:
    strategy_priority = action.get("priority") or ((action.get("context") or {}).get("strategy") or {}).get("priority")
    try:
        if int(strategy_priority or 0) >= 85:
            return "high"
    except Exception:
        pass
    if on_site and kind == NavigationTargetKind.INTERNAL_PAGE.value:
        return "high"
    return "medium"


def _info_nodes_from_summary(page_id: str, path: str, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    headline = str(summary.get("headline") or "").strip()
    if headline:
        nodes.append(
            {
                "page_id": page_id,
                "path": path,
                "kind": "headline",
                "text": headline[:240],
            }
        )
    text = str(summary.get("text_content") or "").strip()
    if text:
        chunks = [text[i : i + 400] for i in range(0, min(len(text), 2000), 400)]
        for index, chunk in enumerate(chunks):
            if chunk.strip():
                nodes.append(
                    {
                        "page_id": page_id,
                        "path": path,
                        "kind": "body_text",
                        "text": chunk.strip(),
                        "chunk": index,
                    }
                )
    headings = summary.get("headings") or {}
    if isinstance(headings, dict):
        for level in ("h1", "h2", "h3"):
            for label in (headings.get(level) or [])[:6]:
                text = str(label).strip()
                if text:
                    nodes.append(
                        {
                            "page_id": page_id,
                            "path": path,
                            "kind": level,
                            "text": text[:200],
                        }
                    )
    return nodes


def _discovered_internal_urls(
    source_url: str,
    pages: List[Dict[str, Any]],
    graph_actions: List[Dict[str, Any]],
) -> set[str]:
    urls: set[str] = set()
    for page in pages:
        path = str(page.get("path") or "/")
        urls.add(urljoin(source_url, path))
    for action in graph_actions:
        path = str(action.get("target_path") or "")
        if path.startswith("/"):
            urls.add(urljoin(source_url, path))
    return urls


def _universe_counts(actions: List[Dict[str, Any]]) -> Dict[str, int]:
    on_site = [a for a in actions if a.get("on_site")]
    return {
        "on_site_actions": len(on_site),
        "off_site_actions": len(actions) - len(on_site),
        "internal_page_actions": sum(
            1 for a in actions if a.get("target_kind") == NavigationTargetKind.INTERNAL_PAGE.value
        ),
        "dead_or_unknown_actions": sum(
            1
            for a in actions
            if a.get("target_kind")
            in {
                NavigationTargetKind.DEAD_TARGET.value,
                NavigationTargetKind.UNKNOWN_JS.value,
            }
        ),
    }
