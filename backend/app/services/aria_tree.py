"""Shared accessibility-tree parsing for live operators and Cursor simulation."""

from __future__ import annotations

import re
from typing import Any, Dict, List

_INTERACTIVE_ROLES = {"link", "button", "textbox", "combobox", "menuitem", "tab"}


def aria_snapshot_for_page(page: Any) -> str:
    if hasattr(page, "aria_snapshot"):
        return page.aria_snapshot()
    return page.locator("body").aria_snapshot()


def candidates_from_aria_snapshot(snapshot: str) -> List[Dict[str, str]]:
    candidates: List[Dict[str, str]] = []
    for line in (snapshot or "").splitlines():
        stripped = line.strip()
        match = re.match(
            r"^-?\s*(link|button|textbox|combobox|menuitem|tab)\s+\"([^\"]+)\"",
            stripped,
            flags=re.IGNORECASE,
        )
        if match:
            role = match.group(1).lower()
            if role in _INTERACTIVE_ROLES:
                candidates.append({"role": role, "name": match.group(2).strip()})
    return candidates


def format_candidates_for_llm(candidates: List[Dict[str, str]], limit: int = 40) -> str:
    lines = []
    for index, item in enumerate(candidates[:limit]):
        lines.append(f"{index}: {item['role']} \"{item['name']}\"")
    if len(candidates) > limit:
        lines.append(f"... and {len(candidates) - limit} more")
    return "\n".join(lines) if lines else "(no interactive nodes)"
