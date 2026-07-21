"""Orchestrate strategy classification, scoring, and report metadata."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from .classifier import classify_action, classify_page
from .prioritizer import priority_for_url
from .probe_planner import build_probe_plan
from .registry import detect_strategy, load_strategy_config
from .score import score_strategy


def apply_strategy_to_crawl(
    *,
    source_url: str,
    pages: List[Dict[str, Any]],
    navigation_graph: Dict[str, Any],
    audit: Optional[Dict[str, Any]] = None,
    state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Classify pages/actions and attach strategy metadata to crawl artifacts."""
    config = detect_strategy(source_url=source_url, pages=pages, audit=audit, state=state)
    if not config:
        return navigation_graph

    strategy = _build_strategy(source_url=source_url, pages=pages, navigation_graph=navigation_graph, config=config)
    navigation_graph["strategy"] = strategy
    _attach_page_metadata(pages, navigation_graph, strategy)
    _attach_action_metadata(navigation_graph, strategy)
    return navigation_graph


def build_strategy_for_payload(run_payload: Dict[str, Any], *, strategy_name: str = "") -> Dict[str, Any]:
    snapshot = run_payload.get("snapshot_before") or {}
    pages = snapshot.get("pages") or []
    graph = snapshot.get("navigation_graph") or {}
    existing = graph.get("strategy") or snapshot.get("strategy") or {}
    if existing and ("high_value_skipped_links" in existing or not (pages and graph)):
        return existing

    config = load_strategy_config(strategy_name) if strategy_name else detect_strategy(
        source_url=snapshot.get("source_url") or (run_payload.get("state") or {}).get("site_url") or "",
        pages=pages,
        audit=run_payload.get("audit") or {},
        state=run_payload.get("state") or {},
    )
    if not config:
        return {}
    return _build_strategy(
        source_url=snapshot.get("source_url") or (run_payload.get("state") or {}).get("site_url") or "",
        pages=pages,
        navigation_graph=graph,
        config=config,
    )


def _build_strategy(
    *,
    source_url: str,
    pages: List[Dict[str, Any]],
    navigation_graph: Dict[str, Any],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    page_by_id = {str(page.get("id") or page.get("page_id") or ""): page for page in pages}
    page_segments = []
    for page in pages:
        segment = classify_page(page, source_url, config)
        segment.update(
            {
                "page_id": str(page.get("id") or page.get("page_id") or ""),
                "path": str(page.get("path") or "/"),
                "title": str(page.get("title") or ""),
            }
        )
        page_segments.append(segment)

    segment_by_page = {row.get("page_id"): row for row in page_segments}
    action_segments = []
    for action in navigation_graph.get("actions") or []:
        page_segment = segment_by_page.get(str(action.get("page_id") or "")) or {}
        segment = classify_action(action, page_segment, source_url, config)
        segment.update(
            {
                "action_id": str(action.get("id") or ""),
                "page_id": str(action.get("page_id") or ""),
                "path": str((page_by_id.get(str(action.get("page_id") or "")) or {}).get("path") or ""),
                "label": str(action.get("element_text") or action.get("label") or "")[:140],
                "target_path": str(action.get("target_path") or ""),
                "target_kind": str(action.get("target_kind") or ""),
            }
        )
        action_segments.append(segment)

    link_inventory, link_inventory_stats = _build_link_inventory(source_url, pages, navigation_graph, config)
    strategy = {
        "name": config.get("name") or "unknown",
        "platform_detected": config.get("platform") or config.get("name") or "",
        "confidence": _confidence(page_segments, action_segments),
        "page_segments": page_segments,
        "action_segments": action_segments,
        "link_inventory": link_inventory,
        "link_inventory_stats": link_inventory_stats,
        "high_value_skipped_links": _high_value_skipped_links(link_inventory, config),
        "priority_paths": _priority_paths(page_segments, action_segments, link_inventory),
        "risks": _risk_signals(action_segments, config),
        "probe_results": [],
    }
    strategy["probe_plan"] = build_probe_plan(strategy, config)
    strategy["scores"] = score_strategy(strategy, config)
    return strategy


def _attach_page_metadata(pages: List[Dict[str, Any]], navigation_graph: Dict[str, Any], strategy: Dict[str, Any]) -> None:
    by_page = {str(row.get("page_id") or ""): row for row in strategy.get("page_segments") or []}
    for page in pages:
        page_id = str(page.get("id") or page.get("page_id") or "")
        segment = by_page.get(page_id)
        if not segment:
            continue
        metadata = dict(page.get("metadata") or {})
        metadata["strategy"] = {
            "name": strategy.get("name"),
            "page_type": segment.get("page_type"),
            "strategy_role": segment.get("strategy_role"),
            "priority": segment.get("priority"),
            "signals": segment.get("signals") or [],
        }
        page["metadata"] = metadata

    for page in navigation_graph.get("pages") or []:
        segment = by_page.get(str(page.get("id") or ""))
        if not segment:
            continue
        page["page_type"] = segment.get("page_type")
        page["strategy_role"] = segment.get("strategy_role")
        page["priority"] = segment.get("priority")
        page["signals"] = segment.get("signals") or []


def _attach_action_metadata(navigation_graph: Dict[str, Any], strategy: Dict[str, Any]) -> None:
    by_action = {str(row.get("action_id") or ""): row for row in strategy.get("action_segments") or []}
    for action in navigation_graph.get("actions") or []:
        segment = by_action.get(str(action.get("id") or ""))
        if not segment:
            continue
        action["action_role"] = segment.get("action_role")
        action["buyer_step"] = segment.get("buyer_step")
        action["priority"] = segment.get("priority")
        action["risk_flags"] = segment.get("risk_flags") or []
        action["skip_reason"] = segment.get("skip_reason") or ""
        context = dict(action.get("context") or {})
        context["strategy"] = {
            "name": strategy.get("name"),
            "action_role": segment.get("action_role"),
            "buyer_step": segment.get("buyer_step"),
            "priority": segment.get("priority"),
            "risk_flags": segment.get("risk_flags") or [],
        }
        action["context"] = context


def _build_link_inventory(
    source_url: str,
    pages: List[Dict[str, Any]],
    navigation_graph: Dict[str, Any],
    config: Dict[str, Any],
) -> tuple[List[Dict[str, Any]], Dict[str, int]]:
    captured = {
        _url_key(urljoin(source_url, str(page.get("path") or "/")))
        for page in pages
        if page.get("path") is not None
    }
    inventory: List[Dict[str, Any]] = []
    for page in pages:
        page_path = str(page.get("path") or "/")
        for link in _extract_links(str(page.get("html") or "")):
            href = str(link.get("href") or "")
            resolved = urljoin(urljoin(source_url, page_path), href)
            parsed = urlparse(resolved)
            path = parsed.path or "/"
            external = not _same_host(source_url, resolved)
            low_priority = _looks_low_priority(path, config)
            key = _url_key(resolved)
            if external:
                status = "skipped"
                reason = "external"
            elif key in captured:
                status = "followed"
                reason = ""
            elif low_priority:
                status = "deprioritized"
                reason = "low_priority_page_type"
            else:
                status = "skipped"
                reason = "not_selected_within_crawl_budget"
            inventory.append(
                {
                    "source_page_id": str(page.get("id") or page.get("page_id") or ""),
                    "source_path": page_path,
                    "label": str(link.get("text") or "")[:140],
                    "href": href,
                    "resolved_url": resolved,
                    "path": path,
                    "external": external,
                    "status": status,
                    "reason": reason,
                }
            )
    deduped = _dedupe_inventory(inventory)
    stats = {
        "total": len(deduped),
        "followed": sum(1 for item in deduped if item.get("status") == "followed"),
        "skipped": sum(1 for item in deduped if item.get("status") == "skipped"),
        "deprioritized": sum(1 for item in deduped if item.get("status") == "deprioritized"),
        "external": sum(1 for item in deduped if item.get("external")),
    }
    return deduped[:500], stats


def _high_value_skipped_links(
    link_inventory: List[Dict[str, Any]],
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen_paths: set[str] = set()
    min_priority = int(((config.get("page_types") or {}).get("collection") or {}).get("priority") or 70)
    for item in link_inventory:
        if item.get("external") or item.get("status") == "followed":
            continue
        path = str(item.get("path") or "")
        if not path:
            continue
        if path in seen_paths:
            continue
        priority = priority_for_url(str(item.get("resolved_url") or path), config)
        if priority < min_priority:
            continue
        seen_paths.add(path)
        rows.append(
            {
                "label": item.get("label") or path,
                "path": path,
                "source_path": item.get("source_path") or "",
                "reason": item.get("reason") or "not_captured",
                "priority": priority,
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            _shopify_high_value_bucket(str(row.get("path") or "")),
            -int(row.get("priority") or 0),
            str(row.get("path") or ""),
        ),
    )[:20]


def _shopify_high_value_bucket(path: str) -> int:
    first = (path or "/").strip("/").split("/", 1)[0].lower()
    if first in {"checkout", "checkouts", "cart"}:
        return 0
    if first in {"collections", "collection", "search"}:
        return 1
    if first in {"products", "product"}:
        return 2
    return 3


def _priority_paths(
    page_segments: List[Dict[str, Any]],
    action_segments: List[Dict[str, Any]],
    link_inventory: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for segment in page_segments:
        rows.append(
            {
                "kind": "page",
                "role": segment.get("page_type"),
                "path": segment.get("path"),
                "priority": int(segment.get("priority") or 0),
            }
        )
    for segment in action_segments:
        rows.append(
            {
                "kind": "action",
                "role": segment.get("action_role"),
                "path": segment.get("target_path") or segment.get("path"),
                "priority": int(segment.get("priority") or 0),
            }
        )
    for item in link_inventory:
        if item.get("status") == "followed":
            continue
        rows.append(
            {
                "kind": "link",
                "role": "external" if item.get("external") else item.get("reason") or "link",
                "path": item.get("path"),
                "priority": 5 if item.get("reason") == "low_priority_page_type" else 20,
            }
        )
    return sorted(rows, key=lambda row: int(row.get("priority") or 0), reverse=True)[:40]


def _risk_signals(action_segments: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    risk_roles = set(config.get("risk_roles") or [])
    return [
        {
            "risk": row.get("action_role"),
            "action_role": row.get("action_role"),
            "label": row.get("label"),
            "path": row.get("path"),
            "target_path": row.get("target_path"),
            "detail": f"{str(row.get('action_role') or '').replace('_', ' ')} detected around {row.get('path') or row.get('target_path') or 'storefront'}.",
        }
        for row in action_segments
        if row.get("action_role") in risk_roles
    ][:20]


def _confidence(page_segments: List[Dict[str, Any]], action_segments: List[Dict[str, Any]]) -> str:
    strong_pages = sum(1 for row in page_segments if row.get("page_type") in {"product", "collection", "cart", "checkout_handoff"})
    strong_actions = sum(1 for row in action_segments if row.get("action_role") in {"add_to_cart", "checkout_link", "product_link", "collection_link"})
    if strong_pages >= 2 or strong_actions >= 3:
        return "high"
    if strong_pages or strong_actions:
        return "medium"
    return "low"


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[Dict[str, str]] = []
        self._captures: List[Dict[str, Any]] = []
        self._ignore_depth = 0

    def handle_starttag(self, tag: str, attrs_raw: Any) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "template", "noscript", "svg"}:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return
        attrs = {str(key).lower(): str(value or "") for key, value in attrs_raw}
        href = attrs.get("href") or attrs.get("data-href") or attrs.get("data-url")
        if tag == "a" and href:
            self._captures.append({"href": href, "text": []})

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "template", "noscript", "svg"}:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if tag != "a" or not self._captures:
            return
        capture = self._captures.pop()
        self.links.append({"href": capture["href"], "text": _compact(" ".join(capture["text"]))})

    def handle_data(self, data: str) -> None:
        if self._ignore_depth or not self._captures:
            return
        if data.strip():
            self._captures[-1]["text"].append(data.strip())


def _extract_links(html: str) -> List[Dict[str, str]]:
    parser = _LinkParser()
    try:
        chunk_size = 250_000
        for start in range(0, len(html), chunk_size):
            parser.feed(html[start : start + chunk_size])
        parser.close()
    except Exception:
        return []
    return parser.links


def _same_host(source_url: str, url: str) -> bool:
    source = urlparse(source_url)
    target = urlparse(urljoin(source_url, url))
    return _norm_host(source.hostname) == _norm_host(target.hostname)


def _norm_host(host: str | None) -> str:
    value = (host or "").lower()
    return value[4:] if value.startswith("www.") else value


def _looks_low_priority(path: str, config: Dict[str, Any]) -> bool:
    path = (path or "/").rstrip("/") or "/"
    low_types = set(config.get("low_priority_page_types") or [])
    for role, spec in (config.get("page_types") or {}).items():
        if role not in low_types:
            continue
        for prefix in spec.get("path_prefixes") or []:
            clean = str(prefix).rstrip("/")
            if path == clean or path.startswith(f"{clean}/"):
                return True
    return False


def _dedupe_inventory(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: set[str] = set()
    result: List[Dict[str, Any]] = []
    for row in rows:
        key = f"{row.get('source_path')}::{row.get('resolved_url')}"
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _url_key(url: str) -> str:
    parsed = urlparse(url or "")
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return f"{_norm_host(parsed.hostname)}{path}"


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
