"""Deterministic catalog activation during agent explore (brief activation budget)."""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from ..models import AGENT_ACCESSIBLE_TARGET_KINDS
from .gap_taxonomy import NAME_UNMATCHABLE, _is_name_unmatchable, _norm_label

# Page-type buckets: activate ≥1 catalogued link when visiting these paths.
_PAGE_TYPE_PATHS: Dict[str, Tuple[str, ...]] = {
    "home": ("/", "/home"),
    "work": ("/work",),
    "writing": ("/writing", "/blog"),
    "about": ("/about",),
}

_NAV_ACTIVATION_LABELS = ("home", "work", "writing", "about", "contact", "blog", "pricing")


def normalize_path(path: str) -> str:
    p = (path or "/").strip()
    if not p.startswith("/"):
        p = "/" + p
    return p.rstrip("/") or "/"


def page_type_for_path(path: str) -> Optional[str]:
    norm = normalize_path(path)
    for page_type, paths in _PAGE_TYPE_PATHS.items():
        for candidate in paths:
            if norm == normalize_path(candidate):
                return page_type
    return None


def pick_catalog_actions_for_page(
    path: str,
    actions: List[Dict[str, Any]],
    *,
    activated_ids: Set[str],
    budget_met: Set[str],
) -> List[Dict[str, Any]]:
    """Choose catalog actions to attempt on this page visit."""
    picks: List[Dict[str, Any]] = []
    page_type = page_type_for_path(path)
    norm = normalize_path(path)

    def eligible(action: Dict[str, Any]) -> bool:
        aid = str(action.get("id") or "")
        if aid in activated_ids:
            return False
        kind = str(action.get("target_kind") or "")
        if kind not in AGENT_ACCESSIBLE_TARGET_KINDS:
            return False
        label = _norm_label(action.get("label") or "")
        if not label or _is_name_unmatchable(label):
            return False
        return True

    pool = [a for a in actions if eligible(a)]

    if page_type and page_type not in budget_met:
        for nav_token in _NAV_ACTIVATION_LABELS:
            if page_type == "home" and nav_token not in {"home", "work", "writing", "about", "contact", "blog"}:
                continue
            for action in pool:
                label = _norm_label(action.get("label") or "").lower()
                if label == nav_token or (nav_token == "home" and label in {"home", "homepage"}):
                    picks.append(action)
                    break

    if page_type == "writing" and "writing_slug" not in budget_met:
        slug_actions = [
            a
            for a in pool
            if _is_writing_slug_action(a, norm)
        ]
        if slug_actions:
            picks.append(slug_actions[0])

    if not picks and pool:
        high = [a for a in pool if (a.get("agent_priority") or "") == "high"]
        picks.append((high or pool)[0])

    seen: Set[str] = set()
    unique: List[Dict[str, Any]] = []
    for action in picks:
        aid = str(action.get("id") or "")
        if aid in seen:
            continue
        seen.add(aid)
        unique.append(action)
    return unique[:4]


def _is_writing_slug_action(action: Dict[str, Any], current_path: str) -> bool:
    target = str(action.get("target_path") or action.get("path") or "")
    if not target.startswith("/"):
        return False
    parts = [p for p in target.split("/") if p]
    if len(parts) < 2:
        return False
    if parts[0] not in ("writing", "blog", "posts"):
        return False
    if normalize_path(current_path) not in ("/writing", "/blog"):
        return False
    return len(parts[-1]) > 2


def record_budget_progress(path: str, action: Dict[str, Any], budget_met: Set[str]) -> None:
    page_type = page_type_for_path(path)
    if page_type:
        budget_met.add(page_type)
    target = str(action.get("target_path") or "")
    if _is_writing_slug_action(action, path):
        budget_met.add("writing_slug")
    label = _norm_label(action.get("label") or "").lower()
    if label in _NAV_ACTIVATION_LABELS:
        budget_met.add(f"nav:{label}")


def activation_budget_summary(budget_met: Set[str], universe: Dict[str, Any]) -> Dict[str, Any]:
    """Report which page-type activations were satisfied."""
    paths = {normalize_path(str(p.get("path") or "/")) for p in (universe.get("pages") or [])}
    required: List[str] = []
    for page_type, type_paths in _PAGE_TYPE_PATHS.items():
        if any(normalize_path(tp) in paths for tp in type_paths):
            required.append(page_type)
    writing_paths = {"/writing", "/blog"}
    if paths & writing_paths:
        required.append("writing_slug")
    met = [key for key in required if key in budget_met]
    return {
        "required": required,
        "met": sorted(set(met)),
        "complete": not required or all(item in budget_met for item in required),
    }
