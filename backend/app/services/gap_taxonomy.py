"""OpenIngress gap taxonomy, explore validity, and recommendation templates."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

from ..models import NavigationTargetKind
from .selector_utils import is_generic_selector, selector_matches_html

# Canonical gap_type values (exactly one per finding).
UNLABELED_STATIC = "unlabeled_static"
CLIENT_ONLY = "client_only"
CATALOG_NOT_ACTIVATED = "catalog_not_activated"
NAME_UNMATCHABLE = "name_unmatchable"
OFF_SITE_EXIT = "off_site_exit"
DEAD_TARGET = "dead_target"
AUTH_REQUIRED = "auth_required"
LLMS_TXT = "llms_txt"
STATIC_AUDIT = "static_audit"

SITE_FIX_GAP_TYPES = {
    UNLABELED_STATIC,
    CLIENT_ONLY,
    NAME_UNMATCHABLE,
    DEAD_TARGET,
    AUTH_REQUIRED,
    LLMS_TXT,
}

INFORMATIONAL_GAP_TYPES = {OFF_SITE_EXIT, CATALOG_NOT_ACTIVATED}

NAME_LENGTH_LIMIT = 120
_NAV_LABELS = ("home", "work", "writing", "about", "contact", "blog", "pricing", "demo")

_LEGACY_KIND_MAP = {
    NavigationTargetKind.UNKNOWN_JS.value: CLIENT_ONLY,
    NavigationTargetKind.EXTERNAL_EXIT.value: OFF_SITE_EXIT,
    NavigationTargetKind.DOWNLOAD_EXIT.value: OFF_SITE_EXIT,
    NavigationTargetKind.DEAD_TARGET.value: DEAD_TARGET,
    NavigationTargetKind.AUTH_REQUIRED.value: AUTH_REQUIRED,
    "invisible_in_live_tree": CATALOG_NOT_ACTIVATED,
    "catalog_mismatch": CATALOG_NOT_ACTIVATED,
}


def explore_min_steps(pages_crawled: int) -> int:
    return max(15, 2 * max(1, int(pages_crawled or 1)))


def explore_is_valid(total_steps: int, pages_crawled: int) -> bool:
    return int(total_steps or 0) >= explore_min_steps(pages_crawled)


def registrable_domain(host: str) -> str:
    host = (host or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def same_registrable_domain(url_a: str, url_b: str) -> bool:
    try:
        return registrable_domain(urlparse(url_a).netloc) == registrable_domain(urlparse(url_b).netloc)
    except Exception:
        return False


def _norm_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _is_unlabeled(label: str) -> bool:
    lower = _norm_label(label).lower()
    return not lower or lower in {"span", "link", "button", "a", "div", "unlabeled"}


def _is_name_unmatchable(label: str) -> bool:
    text = _norm_label(label)
    if len(text) > NAME_LENGTH_LIMIT:
        return True
    if re.search(r"\d{1,2}\s*(?:min|mins|minute|hour|read)", text, re.I) and len(text) > 60:
        return True
    return False


def _href_from_selector(selector: str) -> str:
    match = re.search(r"""href=["']([^"']+)["']""", selector or "")
    return match.group(1) if match else ""


def aria_label_from_selector(selector: str) -> str:
    match = re.search(r"""aria-label=["']([^"']+)["']""", selector or "", flags=re.IGNORECASE)
    return _norm_label(match.group(1)) if match else ""


def catalog_accessible_name(action: Dict[str, Any]) -> str:
    """Name agents should use (aria-label wins over visible text)."""
    aria = aria_label_from_selector(str(action.get("selector") or ""))
    if aria:
        return aria
    return _norm_label(action.get("label") or action.get("name") or action.get("element_text") or "")


def match_names_for_action(action: Dict[str, Any]) -> List[str]:
    """All names worth trying for getByRole / event matching."""
    names: List[str] = []
    primary = catalog_accessible_name(action)
    if primary:
        names.append(_norm_label(primary))
    visible = _norm_label(action.get("label") or action.get("element_text") or "")
    if visible and visible not in names:
        names.append(visible)
    lower_joined = " ".join(names).lower()
    if "back" in lower_joined or "back" in str(action.get("selector") or "").lower():
        for alias in ("back", "back to writing", "← back"):
            if alias not in names:
                names.append(alias)
    href = str(action.get("target_path") or action.get("path") or "") or _href_from_selector(
        str(action.get("selector") or "")
    )
    if href and href.count("/") >= 3:
        slug = href.rstrip("/").split("/")[-1].replace("-", " ")
        if slug and len(slug) > 3:
            names.append(slug)
    return names


def names_compatible(catalog_name: str, live_name: str) -> bool:
    a = _norm_label(catalog_name).lower()
    b = _norm_label(live_name).lower()
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 4 and (a in b or b in a):
        return True
    if "back" in a and "back" in b:
        return True
    return False


def names_compatible_with_action(action: Dict[str, Any], live_name: str) -> bool:
    return any(names_compatible(name, live_name) for name in match_names_for_action(action))


def _href_in_static_html(href: str, page_html: str) -> bool:
    if not href or not page_html:
        return False
    path = href.split("?", 1)[0].split("#", 1)[0]
    if not path:
        return False
    esc = re.escape(path)
    patterns = [
        rf'href\s*=\s*["\']{esc}["\']',
        rf'href\s*=\s*["\'][^"\']*{esc}[^"\']*["\']',
    ]
    if path != "/":
        patterns.append(rf'href\s*=\s*["\']{esc}/?["\']')
    return any(re.search(p, page_html, flags=re.IGNORECASE) for p in patterns)


def _label_in_accessible_static_markup(label: str, page_html: str) -> bool:
    """Match label only inside likely accessible markup, not arbitrary body copy."""
    if not label or len(label) < 2:
        return False
    esc = re.escape(label)
    patterns = [
        rf'aria-label\s*=\s*["\']{esc}["\']',
        rf'title\s*=\s*["\']{esc}["\']',
        rf'>\s*{esc}\s*</a\b',
        rf'>\s*{esc}\s*</button\b',
        rf'>\s*{esc}\s*</h[1-6]\b',
    ]
    return any(re.search(p, page_html, flags=re.IGNORECASE) for p in patterns)


def action_in_static_html(action: Dict[str, Any], page_html: str) -> bool:
    html = page_html or ""
    if not html.strip():
        return False

    selector = str(action.get("selector") or "").strip()
    if selector and not is_generic_selector(selector) and selector_matches_html(selector, html):
        return True

    href = str(action.get("target_path") or action.get("path") or "") or _href_from_selector(selector)
    if href and _href_in_static_html(href, html):
        return True

    label = _norm_label(action.get("label") or "")
    if label and _label_in_accessible_static_markup(label, html):
        return True

    # Nav tokens: require href or aria-label evidence, not bare word in page text.
    if label.lower() in _NAV_LABELS:
        return _href_in_static_html(f"/{label.lower()}", html) or _label_in_accessible_static_markup(label, html)

    return False


def static_html_missing_main_nav(page_html: str) -> bool:
    html = (page_html or "").lower()
    if not html:
        return True
    hits = sum(1 for label in ("home", "work", "writing", "about") if label in html)
    return hits < 2


def page_html_has_csr_bailout(page_html: str) -> bool:
    return "BAILOUT_TO_CLIENT_SIDE_RENDERING" in (page_html or "")


def classify_action_gap(
    action: Dict[str, Any],
    row: Dict[str, Any],
    *,
    in_static_html: bool,
    in_hydrated_tree: bool,
    explore_valid: bool,
) -> Optional[str]:
    """Return exactly one gap_type or None if no gap."""
    kind = str(action.get("target_kind") or row.get("target_kind") or "")
    label = _norm_label(row.get("label") or action.get("label") or "")

    if kind in (NavigationTargetKind.EXTERNAL_EXIT.value, NavigationTargetKind.DOWNLOAD_EXIT.value):
        return OFF_SITE_EXIT
    if kind == NavigationTargetKind.DEAD_TARGET.value:
        return DEAD_TARGET
    if kind == NavigationTargetKind.AUTH_REQUIRED.value:
        return AUTH_REQUIRED

    if _is_unlabeled(label):
        return UNLABELED_STATIC

    if _is_name_unmatchable(label):
        return NAME_UNMATCHABLE

    activated = bool(row.get("agent_activated"))
    matched = bool(row.get("aria_matched"))

    if activated:
        return None

    if kind == NavigationTargetKind.UNKNOWN_JS.value or (in_hydrated_tree and not in_static_html):
        if _is_unlabeled(label):
            return UNLABELED_STATIC
        return CLIENT_ONLY

    if row.get("catalog_accessible") and label:
        return CATALOG_NOT_ACTIVATED

    return _LEGACY_KIND_MAP.get(kind) or CATALOG_NOT_ACTIVATED


def map_legacy_gap_type(legacy_type: str) -> str:
    return _LEGACY_KIND_MAP.get(legacy_type, legacy_type)


def allows_accessible_name_fix(gap_type: str) -> bool:
    return gap_type in {UNLABELED_STATIC, NAME_UNMATCHABLE}


def site_fix_eligible(
    gap_type: str,
    *,
    in_static_html: bool = True,
    also_client_only: bool = False,
    name_unmatchable: bool = False,
    live_tree_miss: bool = False,
    explore_valid: bool = True,
) -> bool:
    if gap_type == CATALOG_NOT_ACTIVATED:
        if also_client_only or not in_static_html:
            return True
        if name_unmatchable or live_tree_miss:
            return True
        return False
    if gap_type in INFORMATIONAL_GAP_TYPES:
        return False
    return gap_type in SITE_FIX_GAP_TYPES


def product_fix_eligible(gap_type: str, *, in_static_html: bool = True, explore_valid: bool = True) -> bool:
    """Explorer-side fixes when static HTML is fine but activation failed."""
    return gap_type == CATALOG_NOT_ACTIVATED and in_static_html and explore_valid


def recommendation_for_gap(
    gap: Dict[str, Any],
    *,
    explore_steps: int = 0,
    in_static_html: bool = True,
    hydrated_name: str = "",
) -> Optional[str]:
    gap_type = str(gap.get("type") or gap.get("gap_type") or "")
    label = _norm_label(gap.get("label") or "")
    selector = str(gap.get("selector") or "")
    page_id = str(gap.get("page_id") or "")
    href = _href_from_selector(selector) or str(gap.get("href") or "")

    if gap_type == OFF_SITE_EXIT:
        return None

    if gap_type == LLMS_TXT:
        meta = gap.get("llms_meta") or {}
        return (
            f"[high][llms_txt] Requested: {meta.get('requested_url')} → "
            f"{meta.get('status_chain')} → final {meta.get('final_url')} "
            f"Pass: {meta.get('pass')} — {meta.get('reason')}"
        )

    if gap_type == CLIENT_ONLY:
        name = label or "control"
        return (
            f"[high][client_only] {name} — {selector} on {page_id or 'page'}\n"
            f"  Static HTML: missing. Hydrated tree: \"{hydrated_name or name}\".\n"
            f"  Site fix: Server-render this control (remove client-only dynamic import without SSR)."
        )

    if gap_type == NAME_UNMATCHABLE:
        title = label[:80] + ("…" if len(label) > 80 else "")
        return (
            f"[high][name_unmatchable] {href or selector} on {page_id or 'page'}\n"
            f"  Computed name length: {len(label)} chars.\n"
            f"  Site fix: aria-label=\"{title}\" on the link; keep visible date/description as children."
        )

    if gap_type == CATALOG_NOT_ACTIVATED:
        also_csr = not in_static_html or bool(gap.get("also_client_only"))
        live_miss = bool(gap.get("live_tree_miss"))
        lines = [
            f"[medium][catalog_not_activated] {label or 'control'} — {selector}",
        ]
        if live_miss and in_static_html:
            lines.append(
                "  In crawl/static HTML but not exposed in the live accessibility tree during explore."
            )
        elif not explore_steps:
            lines.append("  Explore did not run — activation not scored.")
        else:
            lines.append(
                f"  Named in catalog but not activated within explore budget ({explore_steps} steps)."
            )
        if also_csr:
            lines.append(
                "  Site fix: Server-render this control (remove client-only dynamic import without SSR)."
            )
        elif live_miss and in_static_html and not aria_label_from_selector(selector):
            title = label[:80] + ("…" if len(label) > 80 else "")
            lines.append(
                f'  Site fix: aria-label="{title}" on the link; keep date/description as visible children.'
            )
        elif _is_name_unmatchable(label):
            title = label[:80] + ("…" if len(label) > 80 else "")
            lines.append(
                f'  Site fix: aria-label="{title}" on the link; match agents with title substring only.'
            )
        elif in_static_html and not live_miss:
            lines.append(
                "  Product fix: Use getByRole with title substring / exact nav regex; control is in static HTML."
            )
        elif not also_csr:
            lines.append("  Not a labeling defect unless hydration-only (then also client_only).")
        return "\n".join(lines)

    if gap_type == UNLABELED_STATIC:
        return (
            f"[high][unlabeled_static] {selector or 'control'} on {page_id or 'page'}\n"
            f"  Site fix: Add aria-label or visible text so getByRole can target this control."
        )

    if gap_type == DEAD_TARGET:
        return (
            f"[high][dead_target] {label or 'link'} — {selector} on {page_id or 'page'}\n"
            f"  Site fix: Fix broken href or route so the control resolves to a reachable same-origin page."
        )

    if gap_type == AUTH_REQUIRED:
        return (
            f"[high][auth_required] {label or 'route'} on {page_id or 'page'}\n"
            f"  Site fix: Expose a public preview path or document login requirement in llms.txt."
        )

    if gap_type == STATIC_AUDIT:
        check_id = gap.get("label") or ""
        if check_id == "button-labels":
            return None
        return gap.get("impact")

    # Never emit generic discoverable-via-role copy.
    if not allows_accessible_name_fix(gap_type):
        return None

    return (
        f"[high][{gap_type}] {label} — {selector} on {page_id or 'page'}\n"
        f"  Site fix: Add aria-label or visible text for this control."
    )


def dedupe_gaps(gaps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop nav_issue duplicates when an action-row gap already covers the same control."""
    seen_keys: Set[str] = set()
    action_gaps: List[Dict[str, Any]] = []
    other: List[Dict[str, Any]] = []

    for gap in gaps:
        gap_id = str(gap.get("id") or "")
        if gap_id.startswith("nav::"):
            other.append(gap)
            continue
        key = _gap_dedupe_key(gap)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        action_gaps.append(gap)

    for gap in other:
        key = _gap_dedupe_key(gap)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        action_gaps.append(gap)

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    action_gaps.sort(key=lambda item: (severity_order.get(item.get("severity") or "low", 9), item.get("label") or ""))
    return action_gaps


def _gap_dedupe_key(gap: Dict[str, Any]) -> str:
    page_id = str(gap.get("page_id") or "")
    label = _norm_label(gap.get("label") or "").lower()
    gap_type = str(gap.get("type") or "")
    selector = str(gap.get("selector") or "")
    path = str(gap.get("path") or "") or _href_from_selector(selector)
    if path:
        return f"{gap_type}::{path}"
    href = _href_from_selector(selector)
    if href:
        return f"{gap_type}::{href}"
    if "back" in label or "back to writing" in selector.lower():
        return f"{gap_type}::back-to-writing"
    return f"{page_id}::{gap_type}::{label}::{selector}"


def audit_recommendation_to_fix(text: str) -> Optional[Dict[str, Any]]:
    """Map crawl audit recommendation strings to brief-eligible fixes (no generic aria spam)."""
    lower = text.lower()
    blocked = (
        "discoverable via role",
        "accessible name",
        "getbyrole",
        "make this control",
    )
    if any(phrase in lower for phrase in blocked):
        return None
    gap_type = ""
    priority = "medium"
    if "llms.txt" in lower or "llms txt" in lower:
        gap_type = LLMS_TXT
        priority = "high"
    elif "ssr" in lower or "client-side" in lower or "client side" in lower or "hydration" in lower:
        gap_type = CLIENT_ONLY
        priority = "high"
    elif "lazy" in lower or "payload" in lower or "dom size" in lower or "speed" in lower:
        gap_type = STATIC_AUDIT
    elif "dead" in lower or "404" in lower or "broken" in lower:
        gap_type = DEAD_TARGET
        priority = "high"
    elif "aria-label" in lower and "title" in lower:
        gap_type = NAME_UNMATCHABLE
        priority = "high"
    else:
        return None
    return {
        "priority": priority,
        "gap_type": gap_type or "audit_recommendation",
        "label": "",
        "selector": "",
        "page_id": "",
        "change": text.strip(),
    }


def cap_site_fixes(fixes: List[Dict[str, Any]], max_catalog_not_activated_share: float = 0.2) -> List[Dict[str, Any]]:
    if not fixes:
        return fixes
    catalog = [f for f in fixes if f.get("gap_type") == CATALOG_NOT_ACTIVATED]
    other = [f for f in fixes if f.get("gap_type") != CATALOG_NOT_ACTIVATED]
    if not catalog:
        return fixes
    max_catalog = max(1, int(len(fixes) * max_catalog_not_activated_share))
    if len(catalog) <= max_catalog:
        return fixes
    return other + catalog[:max_catalog]


def group_gaps_by_section(gaps: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    sections: Dict[str, List[Dict[str, Any]]] = {
        "static_operability": [],
        "hydrated_accessibility": [],
        "explore_activation": [],
        "speed": [],
        "off_site_exits": [],
    }
    for gap in gaps:
        gt = str(gap.get("type") or "")
        if gt in {UNLABELED_STATIC, LLMS_TXT, STATIC_AUDIT, DEAD_TARGET} and gt != CATALOG_NOT_ACTIVATED:
            if gt == LLMS_TXT or gap.get("static_check"):
                sections["static_operability"].append(gap)
            elif gt == UNLABELED_STATIC:
                sections["static_operability"].append(gap)
            else:
                sections["static_operability"].append(gap)
        elif gt in {CLIENT_ONLY, NAME_UNMATCHABLE}:
            sections["hydrated_accessibility"].append(gap)
        elif gt == CATALOG_NOT_ACTIVATED:
            sections["explore_activation"].append(gap)
        elif gt == OFF_SITE_EXIT:
            sections["off_site_exits"].append(gap)
        elif gt in {DEAD_TARGET, AUTH_REQUIRED}:
            sections["static_operability"].append(gap)
        else:
            sections["explore_activation"].append(gap)
    return sections


def compute_navigability_pcts(
    catalog_rows: List[Dict[str, Any]],
    page_html_by_id: Dict[str, str],
    exploration: Dict[str, Any],
) -> Dict[str, float]:
    if not catalog_rows:
        return {"static_navigable_pct": 0.0, "hydrated_navigable_pct": 0.0}
    static_ok = 0
    hydrated_ok = 0
    aria_ids: Set[str] = set(exploration.get("aria_matched_action_ids") or [])
    activated: Set[str] = set(exploration.get("activated_action_ids") or [])
    for row in catalog_rows:
        page_id = str(row.get("page_id") or "")
        html = page_html_by_id.get(page_id, "")
        aid = str(row.get("id") or "")
        gt = str(row.get("target_kind") or "")
        if gt in (OFF_SITE_EXIT, DEAD_TARGET, AUTH_REQUIRED):
            continue
        if not _is_unlabeled(row.get("label") or "") and not _is_name_unmatchable(row.get("label") or ""):
            action_stub = {"label": row.get("label"), "selector": row.get("selector")}
            if action_in_static_html(action_stub, html):
                static_ok += 1
        if aid in aria_ids or aid in activated or row.get("aria_matched") or row.get("agent_activated"):
            hydrated_ok += 1
    total = len(catalog_rows) or 1
    return {
        "static_navigable_pct": round(100.0 * static_ok / total, 1),
        "hydrated_navigable_pct": round(100.0 * hydrated_ok / total, 1),
    }
