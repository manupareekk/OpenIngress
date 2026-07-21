"""HTML summarization for site import (from audience simulation flow engine)."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict, List

from ..models import FlowPage
from .selector_utils import build_element_selector


def _parse_flow_pages(raw_variant: Dict[str, Any], variant_id: str, fallback_html: str) -> tuple[List[FlowPage], str]:
    raw_pages = raw_variant.get("pages") or []
    pages: List[FlowPage] = []

    if isinstance(raw_pages, list) and raw_pages:
        for index, raw_page in enumerate(raw_pages):
            if not isinstance(raw_page, dict):
                continue
            page_id = str(raw_page.get("id") or f"page_{index + 1}")
            html = str(raw_page.get("html") or raw_page.get("page_html") or raw_page.get("body_html") or "")
            path = str(raw_page.get("path") or ("/" if index == 0 else f"/{page_id}"))
            summary = summarize_variant_html(html) if html else {}
            metadata = dict(raw_page.get("metadata") or {})
            metadata["summary"] = summary
            pages.append(
                FlowPage(
                    id=page_id,
                    path=path,
                    html=html,
                    title=str(raw_page.get("title") or summary.get("headline") or page_id),
                    is_start=bool(raw_page.get("is_start", False)),
                    is_conversion=bool(raw_page.get("is_conversion", False) or raw_page.get("conversion", False)),
                    metadata=metadata,
                )
            )
    else:
        html = fallback_html or str(raw_variant.get("html") or "")
        summary = summarize_variant_html(html) if html else {}
        pages.append(
            FlowPage(
                id=str(raw_variant.get("page_id") or "home"),
                path=str(raw_variant.get("path") or raw_variant.get("page_path") or "/"),
                html=html,
                title=str(raw_variant.get("name") or summary.get("headline") or f"Option {variant_id}"),
                is_start=True,
                is_conversion=bool(raw_variant.get("is_conversion", False) or raw_variant.get("conversion", False)),
                metadata={"summary": summary},
            )
        )

    if not pages:
        pages = [
            FlowPage(
                id="home",
                path="/",
                html="",
                title=f"Option {variant_id}",
                is_start=True,
                metadata={"summary": {}},
            )
        ]

    start_page_id = str(raw_variant.get("start_page_id") or "")
    if not start_page_id:
        start_page_id = next((page.id for page in pages if page.is_start), pages[0].id)

    for page in pages:
        page.is_start = page.id == start_page_id

    _resolve_page_actions(pages)
    return pages, start_page_id


class _VariantHtmlParser(HTMLParser):
    _IGNORED_TAGS = {"script", "style", "template", "noscript", "svg"}
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.meta_description = ""
        self.headings: Dict[str, List[str]] = {"h1": [], "h2": [], "h3": []}
        self.paragraphs: List[str] = []
        self.list_items: List[str] = []
        self.clickables: List[Dict[str, Any]] = []
        self.forms: List[Dict[str, Any]] = []
        self.sections: List[Dict[str, Any]] = []
        self.text_parts: List[str] = []
        self._captures: List[Dict[str, Any]] = []
        self._sections: List[Dict[str, Any]] = []
        self._forms: List[Dict[str, Any]] = []
        self._ignore_depth = 0
        self.node_count = 0
        self.current_depth = 0
        self.max_depth = 0
        self.interactive_nodes = 0
        self.landmark_nodes = 0

    def handle_starttag(self, tag: str, attrs_raw):
        tag = tag.lower()
        attrs = {str(key).lower(): str(value or "") for key, value in attrs_raw}
        if tag in self._IGNORED_TAGS:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return

        self.node_count += 1
        if tag in {"main", "section", "article", "nav", "header", "footer", "aside", "form"}:
            self.landmark_nodes += 1
        if tag in {"a", "button", "input", "select", "textarea", "summary"} or _is_interactive_attrs(attrs):
            self.interactive_nodes += 1
        if tag not in self._VOID_TAGS:
            self.current_depth += 1
            self.max_depth = max(self.max_depth, self.current_depth)

        if tag == "meta":
            name = (attrs.get("name") or attrs.get("property") or "").lower()
            if name in {"description", "og:description"} and attrs.get("content"):
                self.meta_description = attrs["content"]
            return

        if tag == "input" and (attrs.get("type") or "").lower() in {"button", "submit"}:
            attrs["_tag"] = tag
            text = _compact_text(attrs.get("value") or attrs.get("aria-label") or attrs.get("name") or "")
            if self._forms:
                self._forms[-1]["text"].append(text)
                return
            self.clickables.append({"tag": tag, "attrs": attrs, "text": text})
            return

        if tag == "form":
            attrs["_tag"] = tag
            self._forms.append({"tag": tag, "attrs": attrs, "text": []})

        should_capture = tag in {"title", "h1", "h2", "h3", "p", "li", "a", "button"} or _is_interactive_attrs(attrs)
        if self._forms and tag == "button":
            should_capture = False
        if should_capture:
            attrs["_tag"] = tag
            self._captures.append({"tag": tag, "attrs": attrs, "text": []})

        if tag in {"main", "section", "article"}:
            self._sections.append({"tag": tag, "attrs": attrs, "text": []})

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in self._IGNORED_TAGS:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if self._ignore_depth:
            return

        if tag not in self._VOID_TAGS:
            self.current_depth = max(0, self.current_depth - 1)

        capture = self._pop_matching(self._captures, tag)
        if capture:
            text = _compact_text(" ".join(capture["text"]))
            if text:
                if tag == "title":
                    self.title = text
                elif tag in self.headings:
                    self.headings[tag].append(text)
                elif tag == "p":
                    self.paragraphs.append(text)
                elif tag == "li":
                    self.list_items.append(text)
                elif tag in {"a", "button"} or _is_interactive_attrs(capture["attrs"]):
                    self.clickables.append({"tag": tag, "attrs": capture["attrs"], "text": text})

        section = self._pop_matching(self._sections, tag)
        if section:
            text = _compact_text(" ".join(section["text"]))
            if text:
                attrs = section["attrs"]
                section_id = attrs.get("id") or attrs.get("data-section") or f"section_{len(self.sections) + 1}"
                self.sections.append(
                    {
                        "id": section_id,
                        "title": text[:90],
                        "text": text[:900],
                    }
                )

        form = self._pop_matching(self._forms, tag)
        if form:
            text = _compact_text(" ".join(form["text"]))
            attrs = form["attrs"]
            self.forms.append({"tag": tag, "attrs": attrs, "text": text})

    def handle_data(self, data: str):
        if self._ignore_depth:
            return
        text = data.strip()
        if not text:
            return
        self.text_parts.append(text)
        for capture in self._captures:
            capture["text"].append(text)
        for section in self._sections:
            section["text"].append(text)
        for form in self._forms:
            form["text"].append(text)

    @staticmethod
    def _pop_matching(stack: List[Dict[str, Any]], tag: str) -> Dict[str, Any] | None:
        for index in range(len(stack) - 1, -1, -1):
            if stack[index]["tag"] == tag:
                return stack.pop(index)
        return None


def summarize_variant_html(page_html: str) -> Dict[str, Any]:
    parser = _VariantHtmlParser()
    parser.feed(page_html[:200_000])
    parser.close()

    headline = _first(parser.headings["h1"]) or _first(parser.headings["h2"]) or parser.title
    subheadline = _first(item for item in parser.paragraphs if item != headline) or parser.meta_description
    cta = _choose_cta(parser.clickables)
    text_content = _compact_text(" ".join(parser.text_parts))[:4000]

    value_props = parser.list_items[:8]
    if not value_props:
        value_props = [item for item in parser.headings["h2"] + parser.headings["h3"] if item != headline][:6]

    trust_elements = _extract_trust_elements(parser)

    return {
        "headline": headline,
        "subheadline": subheadline,
        "cta_text": cta.get("text") or "",
        "cta_id": _element_id(cta.get("attrs") or {}),
        "trust_elements": trust_elements,
        "value_props": value_props,
        "sections": parser.sections[:8],
        "actions": _extract_actions(parser, page_html),
        "text_content": text_content,
        "structure": {
            "dom_node_count": parser.node_count,
            "max_dom_depth": parser.max_depth,
            "interactive_node_count": parser.interactive_nodes,
            "landmark_node_count": parser.landmark_nodes,
            "text_char_count": len(text_content),
            "text_word_count": len(text_content.split()) if text_content else 0,
            "interactive_density_percent": round(
                100.0 * parser.interactive_nodes / max(parser.node_count, 1),
                2,
            ) if parser.node_count else 0.0,
        },
    }


def _extract_actions(parser: _VariantHtmlParser, page_html: str = "") -> List[Dict[str, Any]]:
    actions = []
    for index, item in enumerate(parser.clickables):
        attrs = item.get("attrs") or {}
        text = item.get("text") or attrs.get("aria-label") or attrs.get("title") or ""
        if not text and not any(attrs.get(key) for key in ("href", "data-next-page", "data-action", "onclick", "data-href", "data-url", "role")):
            continue
        is_cta = _is_cta(item)
        action_type = "CLICK_CTA" if is_cta else "CLICK_LINK"
        tag = item.get("tag") or attrs.get("_tag") or "button"
        actions.append(
            {
                "id": _action_id("action", index, attrs),
                "action_type": action_type,
                "element_id": _element_id(attrs),
                "element_text": text or action_type,
                "target_page_id": attrs.get("data-next-page") or attrs.get("data-page") or "",
                "target_path": attrs.get("href") or attrs.get("data-href") or attrs.get("data-url") or attrs.get("action") or attrs.get("data-target") or "",
                "is_conversion": _is_conversion(attrs),
                "role": "primary_cta" if is_cta else "link",
                "tag": tag,
                "selector": _selector_for(
                    tag, attrs, _action_id("action", index, attrs), html=page_html
                ),
                "attributes": dict(attrs),
            }
        )

    for index, item in enumerate(parser.forms):
        attrs = item.get("attrs") or {}
        text = item.get("text") or attrs.get("aria-label") or attrs.get("name") or "Submit form"
        tag = item.get("tag") or attrs.get("_tag") or "form"
        action_id = _action_id("form", index, attrs)
        actions.append(
            {
                "id": action_id,
                "action_type": "SUBMIT_FORM",
                "element_id": _element_id(attrs) if _element_id(attrs) != "hero_cta" else attrs.get("id") or attrs.get("name") or f"form_{index + 1}",
                "element_text": text[:80],
                "target_page_id": attrs.get("data-next-page") or attrs.get("data-page") or "",
                "target_path": attrs.get("action") or "",
                "is_conversion": _is_conversion(attrs),
                "role": "form_submit",
                "tag": tag,
                "selector": _selector_for(tag, attrs, action_id, html=page_html),
                "method": attrs.get("method") or "GET",
                "attributes": dict(attrs),
            }
        )
    return actions[:16]


def _resolve_page_actions(pages: List[FlowPage]) -> None:
    by_id = {page.id: page for page in pages}
    by_path = {_normalize_path(page.path): page for page in pages if page.path}

    for page in pages:
        summary = dict(page.metadata.get("summary") or {})
        resolved = []
        for action in summary.get("actions") or []:
            item = dict(action)
            target_page = None
            raw_target_page_id = str(item.get("target_page_id") or "")
            raw_target_path = str(item.get("target_path") or "")
            normalized_target_path = _normalize_path(raw_target_path)
            target_requested = bool(raw_target_page_id or normalized_target_path)
            target_external = _is_external_target(raw_target_path)
            if item.get("target_page_id"):
                target_page = by_id.get(str(item["target_page_id"]))
            if not target_page and item.get("target_path"):
                target_page = by_path.get(_normalize_path(str(item["target_path"])))
            if target_page:
                item["target_page_id"] = target_page.id
                item["target_path"] = target_page.path
                item["target_is_conversion"] = target_page.is_conversion
                item["target_missing"] = False
                item["target_external"] = False
            else:
                item["target_is_conversion"] = False
                item["target_missing"] = target_requested and not target_external
                item["target_external"] = target_requested and target_external
            if item.get("is_conversion"):
                item["target_is_conversion"] = True
                item["target_missing"] = False
            resolved.append(item)
        summary["actions"] = resolved
        page.metadata["summary"] = summary


def _normalize_path(path: str) -> str:
    path = (path or "").strip()
    if not path:
        return ""
    path = path.split("#", 1)[0].split("?", 1)[0]
    if path.startswith("http://") or path.startswith("https://"):
        return path.rstrip("/")
    if not path.startswith("/"):
        path = f"/{path}"
    return path.rstrip("/") or "/"


def _is_external_target(path: str) -> bool:
    value = (path or "").strip().lower()
    if not value or value.startswith("#"):
        return False
    return bool(re.match(r"^[a-z][a-z0-9+.-]*:", value)) or value.startswith("//")


def _action_id(prefix: str, index: int, attrs: Dict[str, str]) -> str:
    return attrs.get("id") or attrs.get("data-track") or attrs.get("data-testid") or attrs.get("name") or f"{prefix}_{index + 1}"


def _selector_for(tag: str, attrs: Dict[str, str], fallback_id: str, *, html: str = "") -> str:
    return build_element_selector(tag, attrs, html=html, fallback_id=fallback_id)


def _is_interactive_attrs(attrs: Dict[str, str]) -> bool:
    return bool(
        attrs.get("role") == "button"
        or attrs.get("onclick")
        or attrs.get("data-action")
        or attrs.get("data-cta")
        or attrs.get("data-next-page")
        or attrs.get("data-href")
        or attrs.get("data-url")
        or attrs.get("data-track")
    )


def _is_cta(item: Dict[str, Any]) -> bool:
    attrs = item.get("attrs") or {}
    text = (item.get("text") or "").lower()
    haystack = f"{text} {_attribute_blob(attrs)}"
    if "data-cta" in attrs or attrs.get("data-action") in {"cta", "signup", "convert", "purchase"}:
        return True
    return any(keyword in haystack for keyword in ("start", "try", "demo", "signup", "sign up", "free", "buy", "subscribe", "contact", "get started"))


def _is_conversion(attrs: Dict[str, str]) -> bool:
    value = " ".join(
        attrs.get(key, "")
        for key in ("data-conversion", "data-action", "id", "class", "name")
    ).lower()
    return "conversion" in value or "thank" in value or "complete" in value


def _choose_cta(clickables: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not clickables:
        return {}

    def score(item: Dict[str, Any]) -> int:
        attrs = item.get("attrs") or {}
        text = (item.get("text") or "").lower()
        attr_blob = _attribute_blob(attrs)
        haystack = f"{text} {attr_blob}"
        total = 0
        if "data-cta" in attrs or attrs.get("data-action") in {"cta", "signup", "convert", "purchase"}:
            total += 8
        if item.get("tag") == "button":
            total += 2
        for keyword in ("start", "try", "demo", "signup", "sign up", "free", "buy", "subscribe", "contact", "get started"):
            if keyword in haystack:
                total += 3
        if attrs.get("href", "").startswith("#"):
            total += 1
        return total

    return max(clickables, key=score)


def _extract_trust_elements(parser: _VariantHtmlParser) -> List[str]:
    trust_keywords = (
        "trusted",
        "security",
        "secure",
        "soc",
        "gdpr",
        "hipaa",
        "testimonial",
        "review",
        "customers",
        "case study",
        "guarantee",
        "certified",
    )
    candidates = parser.paragraphs + parser.list_items + parser.headings["h2"] + parser.headings["h3"]
    out = []
    for text in candidates:
        lowered = text.lower()
        if any(keyword in lowered for keyword in trust_keywords):
            out.append(text)
    return out[:6]


def _attribute_blob(attrs: Dict[str, str]) -> str:
    return " ".join(
        attrs.get(key, "")
        for key in ("id", "class", "name", "href", "aria-label", "data-action", "data-track", "data-testid", "data-url", "data-href", "role")
    ).lower()


def _element_id(attrs: Dict[str, str]) -> str:
    return attrs.get("id") or attrs.get("data-track") or attrs.get("data-testid") or attrs.get("name") or "hero_cta"


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _first(items) -> str:
    for item in items:
        if item:
            return item
    return ""


def _coerce_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _coerce_str_list(value: Any) -> List[str]:
    return [str(item).strip() for item in _coerce_list(value) if str(item).strip()]
