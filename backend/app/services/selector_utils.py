"""Shared CSS selector matching and generation against static HTML snapshots."""

from __future__ import annotations

import re

_BARE_TAG_SELECTOR = re.compile(
    r"^(button|a|input|textarea|select|div|span|label|form|img|p|li|h[1-6])$",
    re.IGNORECASE,
)
_BARE_TAG_WITH_NTH = re.compile(
    r"^(button|a|input|textarea|select|div|span|label|form|img|p|li|h[1-6]):nth-of-type\(\d+\)$",
    re.IGNORECASE,
)


def is_generic_selector(selector: str) -> bool:
    """True when the selector is only a bare tag (or tag + nth) with no attributes."""
    s = (selector or "").strip()
    if not s:
        return True
    if _BARE_TAG_SELECTOR.fullmatch(s):
        return True
    if _BARE_TAG_WITH_NTH.fullmatch(s):
        return True
    if re.match(r"^(button|a|input)(\s*[,>]|$)", s, flags=re.IGNORECASE) and len(s) < 16:
        return True
    return False


def _escape_attr_value(value: str) -> str:
    return str(value or "").replace('"', '\\"')


def selector_matches_html(selector: str, html: str) -> bool:
    return count_selector_matches_html(selector, html) > 0


def count_selector_matches_html(selector: str, html: str) -> int:
    selector = (selector or "").strip()
    if not selector or not html:
        return 0

    try:
        from bs4 import BeautifulSoup

        css_matches = BeautifulSoup(html, "html.parser").select(selector)
        if css_matches:
            return len(css_matches)
    except Exception:
        pass

    if selector.startswith("#") and len(selector) > 1:
        token = re.escape(selector[1:])
        return len(re.findall(rf"\bid\s*=\s*['\"]{token}['\"]", html, flags=re.IGNORECASE))

    if selector.startswith(".") and len(selector) > 1:
        token = selector[1:]
        count = 0
        for match in re.finditer(r"\bclass\s*=\s*['\"]([^'\"]*)['\"]", html, flags=re.IGNORECASE):
            if token in match.group(1).split():
                count += 1
        return count

    compound_match = re.fullmatch(
        r"([a-zA-Z][a-zA-Z0-9-]*)\[([a-zA-Z0-9_:-]+)(?:=['\"]?([^'\"]+)['\"]?)?\]",
        selector,
    )
    if compound_match:
        tag = compound_match.group(1)
        attr = re.escape(compound_match.group(2))
        value = compound_match.group(3)
        if value is None:
            pattern = rf"<\s*{re.escape(tag)}[^>]*\b{attr}(?:\s*=\s*['\"][^'\"]*['\"])?"
        else:
            pattern = (
                rf"<\s*{re.escape(tag)}[^>]*\b{attr}\s*=\s*"
                rf"(?:['\"]{re.escape(value)}['\"]|{re.escape(value)})(?=\s|>|/)"
            )
        return len(re.findall(pattern, html, flags=re.IGNORECASE))

    attr_match = re.fullmatch(r"\[([a-zA-Z0-9_:-]+)(?:=['\"]?([^'\"]+)['\"]?)?\]", selector)
    if attr_match:
        attr = re.escape(attr_match.group(1))
        value = attr_match.group(2)
        if value is None:
            pattern = rf"\b{attr}(?:\s*=\s*['\"][^'\"]*['\"])?"
        else:
            pattern = rf"\b{attr}\s*=\s*(?:['\"]{re.escape(value)}['\"]|{re.escape(value)})(?=\s|>|/)"
        return len(re.findall(pattern, html, flags=re.IGNORECASE))

    if re.fullmatch(r"[a-zA-Z][a-zA-Z0-9-]*", selector):
        return len(re.findall(rf"<\s*{re.escape(selector)}(?:\s|>)", html, flags=re.IGNORECASE))

    return html.lower().count(selector.lower())


def build_element_selector(
    tag: str,
    attrs: dict[str, str],
    *,
    html: str = "",
    fallback_id: str = "",
) -> str:
    """Build a specific selector for an element; never returns a bare tag name."""
    tag = (tag or attrs.get("_tag") or "button").lower()
    norm_attrs = {str(key).lower(): str(value or "") for key, value in attrs.items()}

    def pick(candidates: list[str], *, allow_ambiguous: bool = False) -> str | None:
        for candidate in candidates:
            if not candidate or is_generic_selector(candidate):
                continue
            if not html:
                return candidate
            count = count_selector_matches_html(candidate, html)
            if count == 1:
                return candidate
            if count > 1:
                continue
        if allow_ambiguous:
            for candidate in candidates:
                if not candidate or is_generic_selector(candidate):
                    continue
                if html and count_selector_matches_html(candidate, html) >= 1:
                    return candidate
        return None

    candidates: list[str] = []
    if norm_attrs.get("id"):
        candidates.append(f"#{norm_attrs['id']}")
    for attr in (
        "data-testid",
        "data-test",
        "data-track",
        "name",
        "aria-label",
        "placeholder",
        "title",
    ):
        value = norm_attrs.get(attr)
        if value:
            candidates.append(f'{tag}[{attr}="{_escape_attr_value(value)}"]')
    if tag == "a" and norm_attrs.get("href"):
        candidates.append(f'{tag}[href="{_escape_attr_value(norm_attrs["href"])}"]')
    if norm_attrs.get("type"):
        candidates.append(f'{tag}[type="{_escape_attr_value(norm_attrs["type"])}"]')
    if norm_attrs.get("role"):
        candidates.append(f'{tag}[role="{_escape_attr_value(norm_attrs["role"])}"]')
    class_value = norm_attrs.get("class", "")
    if class_value:
        normalized = " ".join(class_value.split())
        candidates.append(f'{tag}[class="{_escape_attr_value(normalized)}"]')
        for token in normalized.split():
            if len(token) >= 3:
                candidates.append(f".{token}")

    chosen = pick(candidates)
    if chosen:
        return chosen

    chosen = pick(candidates, allow_ambiguous=True)
    if chosen:
        return chosen

    if fallback_id:
        return f'{tag}[data-mf-action="{_escape_attr_value(fallback_id)}"]'
    return f'{tag}[data-mf-action="target"]'
