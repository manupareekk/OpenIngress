"""Config-driven crawl strategy registry."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional


CONFIG_DIR = Path(__file__).with_name("config")


@lru_cache(maxsize=16)
def load_strategy_config(name: str) -> Dict[str, Any]:
    safe_name = "".join(ch for ch in str(name or "").lower() if ch.isalnum() or ch in {"_", "-"})
    if not safe_name:
        return {}
    path = CONFIG_DIR / f"{safe_name}.json"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def available_strategy_configs() -> List[Dict[str, Any]]:
    configs: List[Dict[str, Any]] = []
    for path in sorted(CONFIG_DIR.glob("*.json")):
        data = load_strategy_config(path.stem)
        if data:
            configs.append(data)
    return configs


def detect_strategy(
    *,
    source_url: str = "",
    pages: Optional[List[Dict[str, Any]]] = None,
    audit: Optional[Dict[str, Any]] = None,
    state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Return the strongest matching strategy config, or None for generic crawl behavior."""
    pages = pages or []
    audit = audit or {}
    state = state or {}
    joined_html = " ".join(str(page.get("html") or "")[:12000] for page in pages[:8]).lower()
    url_text = str(source_url or "").lower()
    focus = str(state.get("audit_focus") or audit.get("audit_focus") or "").lower()
    platform = str(state.get("platform") or audit.get("platform") or "").lower()

    best: tuple[int, Dict[str, Any]] | None = None
    for config in available_strategy_configs():
        detection = config.get("detection") or {}
        score = 0
        if focus and focus in {str(item).lower() for item in detection.get("audit_focus") or []}:
            score += 100
        if platform and platform in {str(item).lower() for item in detection.get("platform") or []}:
            score += 90
        score += sum(30 for token in detection.get("url_contains") or [] if str(token).lower() in url_text)
        score += sum(12 for token in detection.get("html_contains") or [] if str(token).lower() in joined_html)
        if score and (best is None or score > best[0]):
            best = (score, config)
    return best[1] if best else None
