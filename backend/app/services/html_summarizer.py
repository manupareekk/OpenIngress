"""Extract clickable actions from static HTML for navigation graph building."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict, List

from .selector_utils import build_element_selector


class _HtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.clickables: List[Dict[str, Any]] = []
        self.forms: List[Dict[str, Any]] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        norm = {k.lower(): (v or "") for k, v in attrs}
        norm["_tag"] = tag.lower()
        if tag.lower() == "title":
            self._in_title = True
        if tag.lower() in {"a", "button", "input"}:
            text = norm.get("value") or norm.get("aria-label") or ""
            self.clickables.append({"tag": tag.lower(), "text": text.strip(), "attrs": norm})
        if tag.lower() == "form":
            self.forms.append({"tag": "form", "text": norm.get("name") or "form", "attrs": norm})

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data


def summarize_html(page_html: str) -> Dict[str, Any]:
    parser = _HtmlParser()
    parser.feed((page_html or "")[:250_000])
    parser.close()
    actions: List[Dict[str, Any]] = []
    for index, item in enumerate(parser.clickables[:20]):
        attrs = item.get("attrs") or {}
        text = item.get("text") or attrs.get("aria-label") or attrs.get("title") or ""
        tag = item.get("tag") or "a"
        action_id = attrs.get("id") or attrs.get("data-testid") or f"action_{index + 1}"
        actions.append(
            {
                "id": action_id,
                "action_type": "CLICK_CTA" if tag == "button" else "CLICK_LINK",
                "element_text": text or tag,
                "target_path": attrs.get("href") or "",
                "tag": tag,
                "selector": build_element_selector(tag, attrs, html=page_html, fallback_id=action_id),
                "attributes": dict(attrs),
            }
        )
    for index, item in enumerate(parser.forms[:6]):
        attrs = item.get("attrs") or {}
        action_id = attrs.get("id") or f"form_{index + 1}"
        actions.append(
            {
                "id": action_id,
                "action_type": "SUBMIT_FORM",
                "element_text": item.get("text") or "Submit",
                "target_path": attrs.get("action") or "",
                "tag": "form",
                "selector": build_element_selector("form", attrs, html=page_html, fallback_id=action_id),
                "attributes": dict(attrs),
            }
        )
    return {"title": parser.title.strip(), "actions": actions}
