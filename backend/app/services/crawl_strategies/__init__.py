"""Extensible crawl strategy framework."""

from __future__ import annotations

from .strategy import apply_strategy_to_crawl, build_strategy_for_payload

__all__ = ["apply_strategy_to_crawl", "build_strategy_for_payload"]
