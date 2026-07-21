"""Page and action classification for configured crawl strategies."""

from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urljoin, urlparse


def classify_page(page: Dict[str, Any], source_url: str, config: Dict[str, Any]) -> Dict[str, Any]:
    url = str((page.get("metadata") or {}).get("final_url") or urljoin(source_url, str(page.get("path") or "/")))
    parsed = urlparse(url)
    path = (parsed.path or "/").rstrip("/") or "/"
    query = parsed.query.lower()
    host = (parsed.hostname or "").lower()
    html = str(page.get("html") or "").lower()[:220000]
    title = str(page.get("title") or "").lower()
    haystack = f"{path} {query} {title} {html}"

    best_role = "unknown"
    best_score = -1
    best_signals: List[str] = []
    for role, spec in (config.get("page_types") or {}).items():
        score = 0
        signals: List[str] = []
        if path in {str(item).rstrip("/") or "/" for item in spec.get("path_exact") or []}:
            score += 80
            signals.append("path_exact")
        for prefix in spec.get("path_prefixes") or []:
            if path == prefix or path.startswith(f"{str(prefix).rstrip('/')}/"):
                score += 60
                signals.append(f"path:{prefix}")
        for token in spec.get("query_contains") or []:
            if str(token).lower() in query:
                score += 24
                signals.append(f"query:{token}")
        for token in spec.get("host_contains") or []:
            if str(token).lower() in host:
                score += 70
                signals.append(f"host:{token}")
        for token in spec.get("html_contains") or []:
            if str(token).lower() in haystack:
                score += 12
                signals.append(f"html:{token}")
        if role == "unknown":
            score = int(spec.get("priority") or 0)
        if score > best_score:
            best_role = role
            best_score = score
            best_signals = signals

    role_spec = (config.get("page_types") or {}).get(best_role) or {}
    return {
        "page_type": best_role,
        "strategy_role": best_role,
        "priority": int(role_spec.get("priority") or 0),
        "signals": best_signals[:8],
    }


def classify_action(action: Dict[str, Any], page_segment: Dict[str, Any], source_url: str, config: Dict[str, Any]) -> Dict[str, Any]:
    attrs = action.get("attributes") or {}
    target = str(action.get("target_path") or action.get("raw_target") or attrs.get("href") or attrs.get("resolved_href") or "")
    target_url = urljoin(source_url, target) if target and not _is_external(target) else target
    target_path = urlparse(target_url).path if target_url else target
    label = str(action.get("element_text") or action.get("label") or action.get("text") or attrs.get("aria-label") or "")
    selector = str(action.get("selector") or "")
    action_type = str(action.get("action_type") or "")
    haystack = _compact(f"{label} {selector} {target} {target_path} {action_type} {attrs}")
    target_kind = str(action.get("target_kind") or "")

    best_role = "external_app" if "external" in target_kind else "unknown"
    best_score = -1
    best_spec: Dict[str, Any] = {}
    flags: List[str] = []
    for role, spec in (config.get("action_roles") or {}).items():
        score = 0
        if spec.get("external") and "external" in target_kind:
            score += 45
        for prefix in spec.get("target_prefixes") or []:
            clean_prefix = str(prefix).rstrip("/")
            if target_path == clean_prefix or target_path.startswith(f"{clean_prefix}/"):
                score += 70
        for token in spec.get("tokens") or []:
            if str(token).lower() in haystack:
                score += 30 + min(len(str(token)), 20)
        if score > best_score or (
            score == best_score and int(spec.get("priority") or 0) > int(best_spec.get("priority") or 0)
        ):
            best_role = role
            best_score = score
            best_spec = spec

    if best_score <= 0:
        best_role = "unknown"
        best_spec = {}
    if best_role in set(config.get("risk_roles") or []):
        flags.append(best_role)
    if best_role == "checkout_link":
        flags.append("checkout_handoff_only")
    if page_segment.get("page_type") in set(config.get("low_priority_page_types") or []):
        flags.append("low_priority_page")

    priority = int(best_spec.get("priority") or 20)
    return {
        "action_role": best_role,
        "buyer_step": best_spec.get("buyer_step") or "",
        "priority": priority,
        "risk_flags": flags,
        "skip_reason": "",
    }


def _is_external(value: str) -> bool:
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", str(value or "").lower())) or str(value or "").startswith("//")


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()
