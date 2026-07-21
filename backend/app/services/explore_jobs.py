"""Infer user jobs from crawl catalog and track explore progress against them."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse

_WORK_SEGMENTS = ("work", "projects", "portfolio", "case-studies", "case_studies")
_BLOG_SEGMENTS = ("writing", "blog", "posts", "news", "articles")
_ABOUT_SEGMENTS = ("about", "company", "team")
_CONTACT_SEGMENTS = ("contact", "hire", "sales")
_PRICING_SEGMENTS = ("pricing", "plans")
_DEMO_SEGMENTS = ("demo", "request-demo", "book-demo")
_CONVERT_PATH_SEGMENTS = ("signup", "sign-up", "waitlist", "register")
_PRODUCT_SEGMENTS = ("product", "products", "features", "feature", "solutions", "platform")
_ECOMMERCE_SEGMENTS = ("shop", "store", "cart", "checkout", "collections")
_ECOMMERCE_REVENUE_SEGMENTS = ("products", "product", "collections", "collection", "cart", "checkout", "shop", "store")
_ECOMMERCE_LOW_INTENT_SEGMENTS = (
    "accessibility",
    "article",
    "articles",
    "blog",
    "blogs",
    "careers",
    "commitment-to-accessibility",
    "contact",
    "delivery",
    "faq",
    "help",
    "legal",
    "policies",
    "privacy",
    "returns",
    "shipping",
    "studentbeans",
    "support",
    "terms",
)
_ARCHIVE_ROOTS: Dict[str, tuple[str, ...]] = {
    "blog": _BLOG_SEGMENTS,
    "docs": ("docs", "documentation", "help", "support", "changelog", "articles"),
}
_DEMO_CTA_TOKENS = ("book a demo", "book demo", "request demo", "schedule demo", "get a demo")
_CONVERT_CTA_TOKENS = ("waitlist", "sign up", "signup", "get started", "register")
_PRICING_CTA_TOKENS = ("pricing", "plans", "compare plans")
_CONTACT_CTA_TOKENS = ("contact", "email", "hire", "get in touch", "talk to sales", "mail")
_CART_CTA_TOKENS = ("add to cart", "add to bag", "buy now", "buy")
_CHECKOUT_CTA_TOKENS = ("checkout", "check out", "place order")
_AUTH_PATH_HINTS = ("login", "log-in", "signin", "sign-in", "auth", "account")

# Funnel order for display and agent explore priority.
_JOB_DISPLAY_ORDER = {
    "orient": 0,
    "portfolio": 10,
    "product": 15,
    "find_product": 18,
    "add_to_cart": 19,
    "pricing": 20,
    "checkout": 21,
    "book_demo": 22,
    "convert": 25,
    "blog": 30,
    "about": 35,
    "contact": 40,
}


def _sort_jobs(jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        jobs,
        key=lambda job: (_JOB_DISPLAY_ORDER.get(str(job.get("id") or ""), 99), str(job.get("job") or "")),
    )


def _norm_path(path: str) -> str:
    text = str(path or "/").strip()
    if text.startswith("http"):
        try:
            text = urlparse(text).path or "/"
        except Exception:
            text = "/"
    return text.rstrip("/") or "/"


def _path_segments(path: str) -> List[str]:
    return [seg for seg in _norm_path(path).strip("/").split("/") if seg]


def _paths_first_segment(pages: Set[str], segments: tuple[str, ...]) -> List[str]:
    matched: List[str] = []
    for path in sorted(pages):
        segs = _path_segments(path)
        if segs and segs[0].lower() in segments:
            matched.append(path)
    return matched


def _archive_deep_path(path: str) -> Optional[str]:
    segs = _path_segments(path)
    if len(segs) < 2:
        return None
    root = segs[0].lower()
    for archive_root, segments in _ARCHIVE_ROOTS.items():
        if root in segments:
            return archive_root
    return None


def _is_reserved_path(path: str) -> bool:
    segs = _path_segments(path)
    if not segs:
        return True
    first = segs[0].lower()
    reserved = set(
        _WORK_SEGMENTS
        + _BLOG_SEGMENTS
        + _ABOUT_SEGMENTS
        + _CONTACT_SEGMENTS
        + _PRICING_SEGMENTS
        + _DEMO_SEGMENTS
        + _CONVERT_PATH_SEGMENTS
        + _ECOMMERCE_SEGMENTS
    )
    return first in reserved


def _page_ids_for_paths(universe: Dict[str, Any], paths: Set[str]) -> Set[str]:
    ids: Set[str] = set()
    for page in universe.get("pages") or []:
        if _norm_path(str(page.get("path") or "/")) in paths:
            page_id = str(page.get("page_id") or "").strip()
            if page_id:
                ids.add(page_id)
    return ids


def _demo_nav_keywords(actions: List[Dict[str, Any]]) -> List[str]:
    keywords = ["book a demo", "book demo", "request demo", "schedule demo", "demo"]
    for action in actions:
        label = str(action.get("label") or "").strip()
        lower = label.lower()
        if label and any(token in lower for token in _DEMO_CTA_TOKENS):
            keywords.append(lower)
    return list(dict.fromkeys(keywords))


def _has_commerce_cta(actions: List[Dict[str, Any]]) -> bool:
    for action in actions:
        label = str(action.get("label") or "").lower()
        if any(token in label for token in _CART_CTA_TOKENS + _CHECKOUT_CTA_TOKENS):
            return True
    return False


def _is_low_intent_ecommerce_path(path: str) -> bool:
    segs = [seg.lower() for seg in _path_segments(path)]
    if not segs:
        return False
    return any(seg in _ECOMMERCE_LOW_INTENT_SEGMENTS for seg in segs)


def _product_path_rank(path: str, *, page_type_ecommerce: bool) -> tuple[int, int, str]:
    segs = [seg.lower() for seg in _path_segments(path)]
    first = segs[0] if segs else ""
    if page_type_ecommerce:
        if first in {"products", "product"}:
            return (0, len(segs), path)
        if first in {"collections", "collection"}:
            return (1, len(segs), path)
        if first in {"shop", "store"}:
            return (2, len(segs), path)
        if first in {"cart", "checkout"}:
            return (3, len(segs), path)
    if first in _PRODUCT_SEGMENTS:
        return (4, len(segs), path)
    return (5, len(segs), path)


def _infer_product_paths(
    path_set: Set[str],
    audit: Optional[Dict[str, Any]],
    reserved: Set[str],
    *,
    page_type_ecommerce: bool = False,
) -> List[str]:
    candidates: Set[str] = set()
    for path in path_set:
        if path in reserved or _is_reserved_path(path):
            continue
        if page_type_ecommerce and _is_low_intent_ecommerce_path(path):
            continue
        segs = _path_segments(path)
        if not segs or len(segs) > 2:
            continue
        first = segs[0].lower()
        if first in _PRODUCT_SEGMENTS or (page_type_ecommerce and first in _ECOMMERCE_REVENUE_SEGMENTS):
            candidates.add(path)
        if not page_type_ecommerce and any("agent" in seg or "product" in seg for seg in segs):
            candidates.add(path)
    for action in (audit or {}).get("top_actions") or []:
        tp = _norm_path(str(action.get("target_path") or ""))
        if not tp or tp == "/" or tp in reserved or _is_reserved_path(tp):
            continue
        if page_type_ecommerce and _is_low_intent_ecommerce_path(tp):
            continue
        if page_type_ecommerce:
            first = (_path_segments(tp) or [""])[0].lower()
            if first not in _ECOMMERCE_REVENUE_SEGMENTS:
                continue
        if tp:
            candidates.add(tp)
    ranked = sorted(candidates, key=lambda path: _product_path_rank(path, page_type_ecommerce=page_type_ecommerce))
    return ranked[:4]


def _cta_job_from_actions(actions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for action in actions:
        label = str(action.get("label") or "").strip()
        lower = label.lower()
        if not label:
            continue
        if any(token in lower for token in _DEMO_CTA_TOKENS):
            return {
                "id": "book_demo",
                "job": "Book a demo",
                "goal": f"Reach the demo page and confirm booking is agent-navigable ({label}).",
                "path_prefixes": ("/demo",),
                "page_ids": [],
                "nav_keywords": _demo_nav_keywords(actions),
                "require_deep_path": False,
                "require_page_view": True,
                "cta_label": label,
            }
        if any(token in lower for token in _CONVERT_CTA_TOKENS):
            return {
                "id": "convert",
                "job": "Start signup or waitlist",
                "goal": f"Find and activate the primary conversion action ({label}).",
                "path_prefixes": ("/",),
                "page_ids": [],
                "nav_keywords": [label.lower(), "waitlist", "sign up", "get started"],
                "require_deep_path": False,
                "require_page_view": True,
                "cta_label": label,
            }
        if any(token in lower for token in _PRICING_CTA_TOKENS):
            return {
                "id": "pricing",
                "job": "View pricing",
                "goal": "Reach pricing/plans and confirm plans are visible to agents.",
                "path_prefixes": ("/pricing", "/plans"),
                "page_ids": [],
                "nav_keywords": ["pricing", "plans"],
                "require_deep_path": False,
                "require_page_view": True,
            }
    return None


def infer_explore_jobs(
    universe: Dict[str, Any],
    audit: Optional[Dict[str, Any]] = None,
    *,
    max_jobs: int = 8,
) -> List[Dict[str, Any]]:
    pages = universe.get("pages") or []
    path_set = {_norm_path(str(page.get("path") or "/")) for page in pages}
    all_actions = universe.get("actions") or []
    page_type = str((audit or {}).get("page_type") or "").lower()
    page_type_ecommerce = (
        page_type == "ecommerce"
        or bool(_paths_first_segment(path_set, _ECOMMERCE_SEGMENTS))
        or _has_commerce_cta(all_actions)
    )
    jobs: List[Dict[str, Any]] = []
    reserved_paths: Set[str] = set()

    if "/" in path_set:
        jobs.append(
            {
                "id": "orient",
                "job": "Orient on homepage",
                "goal": "Land on the homepage and confirm primary navigation is visible in the accessibility tree.",
                "path_prefixes": ("/",),
                "page_ids": sorted(_page_ids_for_paths(universe, {"/"})),
                "nav_keywords": ("home",),
                "require_deep_path": False,
                "require_page_view": True,
            }
        )

    work_paths = _paths_first_segment(path_set, _WORK_SEGMENTS)
    reserved_paths.update(work_paths)
    work_deep_prefixes = sorted(
        {f"/{segs[0]}/" for path in path_set if len(segs := _path_segments(path)) >= 2 and segs[0].lower() in _WORK_SEGMENTS}
    )
    if work_paths:
        jobs.append(
            {
                "id": "portfolio",
                "job": "Find portfolio work",
                "goal": "Reach the work/projects section and open a project if available.",
                "path_prefixes": tuple(work_paths[:4]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(work_paths))),
                "nav_keywords": ("work", "project", "portfolio", "view project", "case study"),
                "require_deep_path": bool(work_deep_prefixes),
                "deep_path_prefixes": tuple(work_deep_prefixes),
                "require_page_view": True,
            }
        )

    product_paths = _infer_product_paths(
        path_set,
        audit,
        reserved_paths,
        page_type_ecommerce=page_type_ecommerce,
    )
    reserved_paths.update(product_paths)
    if product_paths:
        jobs.append(
            {
                "id": "product",
                "job": "Explore product offer",
                "goal": "Reach a primary product or feature page and confirm it is agent-navigable.",
                "path_prefixes": tuple(product_paths),
                "page_ids": sorted(_page_ids_for_paths(universe, set(product_paths))),
                "nav_keywords": ("product", "feature", "solution", "agent", "learn more"),
                "require_deep_path": False,
                "require_page_view": True,
            }
        )

    shop_paths = _paths_first_segment(path_set, ("shop", "store", "products", "product", "collections"))
    checkout_paths = _paths_first_segment(path_set, ("checkout", "cart"))
    if page_type_ecommerce and shop_paths:
        jobs.append(
            {
                "id": "find_product",
                "job": "Find a product",
                "goal": "Reach the shop/catalog and open a product page.",
                "path_prefixes": tuple(shop_paths[:3]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(shop_paths))),
                "nav_keywords": ("shop", "product", "collection", "buy", "add to cart"),
                "require_deep_path": True,
                "deep_path_prefixes": tuple(f"/{ _path_segments(p)[0]}/" for p in shop_paths[:1]),
                "require_page_view": True,
            }
        )
        jobs.append(
            {
                "id": "add_to_cart",
                "job": "Add to cart",
                "goal": "Activate an add-to-cart or buy action from a product page.",
                "path_prefixes": tuple(shop_paths[:3]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(shop_paths))),
                "nav_keywords": _CART_CTA_TOKENS,
                "require_deep_path": False,
                "require_page_view": False,
            }
        )
    if page_type_ecommerce and checkout_paths:
        jobs.append(
            {
                "id": "checkout",
                "job": "Reach checkout",
                "goal": "Reach checkout/cart and confirm purchase flow is agent-navigable.",
                "path_prefixes": tuple(checkout_paths[:2]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(checkout_paths))),
                "nav_keywords": _CHECKOUT_CTA_TOKENS,
                "require_deep_path": False,
                "require_page_view": True,
            }
        )
        reserved_paths.update(checkout_paths)

    blog_roots = _paths_first_segment(path_set, _BLOG_SEGMENTS)
    blog_roots = [p for p in blog_roots if len(_path_segments(p)) <= 1] or blog_roots[:1]
    blog_deep_prefixes = sorted(
        {f"/{segs[0]}/" for path in path_set if len(segs := _path_segments(path)) >= 2 and segs[0].lower() in _BLOG_SEGMENTS}
    )
    if blog_roots or blog_deep_prefixes:
        reserved_paths.update(blog_roots)
        jobs.append(
            {
                "id": "blog",
                "job": "Open a blog post",
                "goal": "Open the writing/blog index and read at least one full article.",
                "path_prefixes": tuple(blog_roots or ["/writing", "/blog"]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(blog_roots))),
                "nav_keywords": ("writing", "blog", "read", "back"),
                "require_deep_path": True,
                "deep_path_prefixes": tuple(blog_deep_prefixes),
                "require_page_view": True,
            }
        )

    about_paths = _paths_first_segment(path_set, _ABOUT_SEGMENTS)
    if about_paths:
        reserved_paths.update(about_paths)
        jobs.append(
            {
                "id": "about",
                "job": "Learn about company",
                "goal": "Reach the about/company page and confirm company info is agent-navigable.",
                "path_prefixes": tuple(about_paths[:3]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(about_paths))),
                "nav_keywords": ("about", "company", "team", "story"),
                "require_deep_path": False,
                "require_page_view": True,
            }
        )

    contact_paths = _paths_first_segment(path_set, _CONTACT_SEGMENTS)
    if contact_paths:
        reserved_paths.update(contact_paths)
        jobs.append(
            {
                "id": "contact",
                "job": "Contact / hire",
                "goal": "Reach contact and find a clear on-site way to get in touch or hire.",
                "path_prefixes": tuple(contact_paths[:4]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(contact_paths))),
                "nav_keywords": _CONTACT_CTA_TOKENS,
                "require_deep_path": False,
                "require_page_view": True,
            }
        )

    demo_paths = _paths_first_segment(path_set, _DEMO_SEGMENTS)
    demo_paths = [p for p in demo_paths if _path_segments(p)[-1].lower() in _DEMO_SEGMENTS] or demo_paths
    if demo_paths:
        reserved_paths.update(demo_paths)
        jobs.append(
            {
                "id": "book_demo",
                "job": "Book a demo",
                "goal": "Reach the demo page and confirm booking/scheduling is agent-navigable.",
                "path_prefixes": tuple(demo_paths[:3]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(demo_paths))),
                "nav_keywords": tuple(_demo_nav_keywords(all_actions)),
                "require_deep_path": False,
                "require_page_view": True,
            }
        )

    pricing_paths = _paths_first_segment(path_set, _PRICING_SEGMENTS)
    pricing_paths = [p for p in pricing_paths if p not in set(demo_paths)]
    if pricing_paths:
        reserved_paths.update(pricing_paths)
        jobs.append(
            {
                "id": "pricing",
                "job": "View pricing",
                "goal": "Reach pricing/plans and confirm offer details are agent-navigable.",
                "path_prefixes": tuple(pricing_paths[:3]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(pricing_paths))),
                "nav_keywords": _PRICING_CTA_TOKENS,
                "require_deep_path": False,
                "require_page_view": True,
            }
        )

    convert_paths = _paths_first_segment(path_set, _CONVERT_PATH_SEGMENTS)
    convert_paths = [p for p in convert_paths if p not in set(demo_paths)]
    if convert_paths:
        reserved_paths.update(convert_paths)
        jobs.append(
            {
                "id": "convert",
                "job": "Start signup or waitlist",
                "goal": "Reach signup/waitlist and confirm conversion flow is agent-navigable.",
                "path_prefixes": tuple(convert_paths[:3]),
                "page_ids": sorted(_page_ids_for_paths(universe, set(convert_paths))),
                "nav_keywords": _CONVERT_CTA_TOKENS,
                "require_deep_path": False,
                "require_page_view": True,
            }
        )

    cta_job = _cta_job_from_actions(all_actions)
    if cta_job and not any(job["id"] == cta_job["id"] for job in jobs):
        jobs.append(cta_job)

    deduped: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for job in jobs:
        if job["id"] in seen:
            continue
        seen.add(job["id"])
        deduped.append(job)
    return _sort_jobs(deduped[:max_jobs])


def _path_matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    norm = _norm_path(path)
    for prefix in prefixes:
        p = _norm_path(prefix)
        if p == "/":
            if norm == "/":
                return True
            continue
        if norm == p or norm.startswith(f"{p}/"):
            return True
    return False


def _deep_path_reached(path: str, job: Dict[str, Any]) -> bool:
    norm = _norm_path(path)
    prefixes = job.get("deep_path_prefixes") or ()
    if not prefixes:
        return len(_path_segments(norm)) >= 2 and _path_matches_prefix(norm, job.get("path_prefixes") or ())
    for prefix in prefixes:
        p = _norm_path(prefix)
        if norm.startswith(f"{p}") and len(_path_segments(norm)) >= 2:
            return True
    return False


class ExploreJobTracker:
    def __init__(self, jobs: List[Dict[str, Any]]) -> None:
        self.jobs = jobs
        self._state: Dict[str, Dict[str, Any]] = {
            job["id"]: {
                "paths": set(),
                "clicks": [],
                "deep_reached": False,
                "attempted": False,
            }
            for job in jobs
        }

    def record_page_view(self, path: str) -> None:
        norm = _norm_path(path)
        for job in self.jobs:
            state = self._state[job["id"]]
            if _path_matches_prefix(norm, tuple(job.get("path_prefixes") or ())):
                state["paths"].add(norm)
                state["attempted"] = True
            if job.get("require_deep_path") and _deep_path_reached(norm, job):
                state["deep_reached"] = True
                state["attempted"] = True

    def record_click(
        self,
        name: str,
        path: str,
        *,
        success: bool = True,
        navigated: Optional[bool] = None,
    ) -> None:
        lower = str(name or "").lower()
        for job in self.jobs:
            state = self._state[job["id"]]
            keywords = tuple(k.lower() for k in (job.get("nav_keywords") or ()))
            if keywords and any(kw in lower for kw in keywords):
                state["attempted"] = True
                state["clicks"].append(
                    {
                        "name": name,
                        "path": _norm_path(path),
                        "success": success,
                        "navigated": navigated,
                    }
                )

    def active_job(self) -> Optional[Dict[str, Any]]:
        for job in self.jobs:
            if not self._job_complete(job):
                return job
        return None

    def _job_complete(self, job: Dict[str, Any]) -> bool:
        state = self._state[job["id"]]
        if job.get("id") == "add_to_cart":
            return any(
                any(token in str(c.get("name") or "").lower() for token in _CART_CTA_TOKENS)
                for c in state.get("clicks") or []
            )
        if job.get("require_deep_path"):
            return bool(state["deep_reached"])
        if job.get("require_page_view", True):
            return bool(state["paths"])
        return bool(state["paths"] or state["clicks"])

    def prompt_context(self) -> str:
        if not self.jobs:
            return ""
        lines = [
            "User jobs to complete (work through in order; prefer the first incomplete job):",
        ]
        for job in self.jobs:
            state = self._state[job["id"]]
            if self._job_complete(job):
                mark = "done"
            elif state["attempted"]:
                mark = "in progress"
            else:
                mark = "pending"
            lines.append(f"- [{mark}] {job['job']}: {job['goal']}")
        active = self.active_job()
        if active:
            lines.append(f"\nFocus this step on: {active['job']}.")
            keywords = ", ".join(active.get("nav_keywords") or ())
            if keywords:
                lines.append(f"Helpful link/button names: {keywords}.")
        return "\n".join(lines)

    def progress_payload(self) -> Dict[str, Any]:
        return {
            "jobs": self.jobs,
            "state": {
                job_id: {
                    "paths": sorted(state["paths"]),
                    "clicks": state["clicks"],
                    "deep_reached": state["deep_reached"],
                    "attempted": state["attempted"],
                }
                for job_id, state in self._state.items()
            },
        }


def _prefix_matches_gap(prefix: str, gap: Dict[str, Any], page_ids: Set[str]) -> bool:
    p = _norm_path(prefix)
    page_id = str(gap.get("page_id") or "")
    if p == "/":
        return page_id in page_ids
    token = p.strip("/")
    if not token:
        return False
    selector = str(gap.get("selector") or "").lower()
    label = str(gap.get("label") or "").lower()
    return token in selector or token in label



def _gap_summaries(gaps: List[Dict[str, Any]], *, limit: int = 8) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for gap in gaps[:limit]:
        rows.append(
            {
                "id": gap.get("id") or "",
                "label": gap.get("label") or gap.get("type") or "Gap",
                "impact": gap.get("impact") or "",
                "severity": gap.get("severity") or "medium",
                "path": gap.get("path") or "",
                "type": gap.get("type") or "",
            }
        )
    return rows


def _blocker_from_gaps(
    *,
    journey_gaps: List[Dict[str, Any]],
    high_gaps: List[Dict[str, Any]],
    job_id: str,
) -> str:
    if job_id == "blog":
        live_miss = sum(
            1
            for g in journey_gaps
            if g.get("type") == "catalog_not_activated" and g.get("live_tree_miss")
        )
        if live_miss:
            return f"{live_miss} writing link(s) missing from live accessibility tree"
        if journey_gaps:
            first = journey_gaps[0].get("impact") or journey_gaps[0].get("label")
            if first and len(journey_gaps) == 1:
                return str(first)
            return f"{len(journey_gaps)} explore activation gap(s) on writing"
    primary = high_gaps[0] if high_gaps else (journey_gaps[0] if journey_gaps else None)
    if not primary:
        return "—"
    detail = str(primary.get("impact") or primary.get("label") or "").strip()
    count = len(high_gaps) if high_gaps else len(journey_gaps)
    if detail and count <= 1:
        return detail
    if detail:
        kind = "high-severity gap" if high_gaps else "gap"
        return f"{detail} (+{count - 1} more {kind}{'s' if count != 2 else ''})"
    if high_gaps:
        return f"{len(high_gaps)} high-severity gap(s) on this journey"
    return f"{len(journey_gaps)} gap(s) on this journey"


def _gaps_for_job(gaps: List[Dict[str, Any]], job: Dict[str, Any]) -> List[Dict[str, Any]]:
    page_ids = set(job.get("page_ids") or [])
    prefixes = tuple(job.get("path_prefixes") or ())
    deep_prefixes = tuple(job.get("deep_path_prefixes") or ())
    matched: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for gap in gaps:
        gap_id = str(gap.get("id") or gap.get("impact") or id(gap))
        page_id = str(gap.get("page_id") or "")
        if page_id in page_ids:
            if gap_id not in seen_ids:
                seen_ids.add(gap_id)
                matched.append(gap)
            continue
        if any(_prefix_matches_gap(prefix, gap, page_ids) for prefix in prefixes):
            if gap_id not in seen_ids:
                seen_ids.add(gap_id)
                matched.append(gap)
            continue
        selector = str(gap.get("selector") or "").lower()
        if deep_prefixes and any(p.strip("/") in selector for p in deep_prefixes if p.strip("/")):
            if gap_id not in seen_ids:
                seen_ids.add(gap_id)
                matched.append(gap)
    return matched


def _actions_for_page_ids(universe: Dict[str, Any], page_ids: Set[str]) -> List[Dict[str, Any]]:
    if not page_ids:
        return []
    return [a for a in (universe.get("actions") or []) if str(a.get("page_id") or "") in page_ids]


def _page_action_counts(universe: Dict[str, Any], page_ids: Set[str]) -> int:
    total = 0
    for page in universe.get("pages") or []:
        if str(page.get("page_id") or "") in page_ids:
            total += int(page.get("action_count") or 0)
    return total


def _actions_matching_tokens(
    actions: List[Dict[str, Any]],
    tokens: tuple[str, ...],
    *,
    on_site_only: bool = False,
    target_kinds: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for action in actions:
        if on_site_only and not action.get("on_site"):
            continue
        kind = str(action.get("target_kind") or "")
        if target_kinds and kind not in target_kinds:
            continue
        label = str(action.get("label") or "").lower()
        if any(token in label for token in tokens):
            matched.append(action)
    return matched


def _auth_related_actions(universe: Dict[str, Any], page_ids: Set[str]) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for action in _actions_for_page_ids(universe, page_ids):
        kind = str(action.get("target_kind") or "")
        path = str(action.get("target_path") or action.get("target_url") or "").lower()
        if kind == "auth_required" or any(hint in path for hint in _AUTH_PATH_HINTS):
            matched.append(action)
    return matched


def _cta_clicks(state: Dict[str, Any], tokens: tuple[str, ...]) -> List[Dict[str, Any]]:
    clicks = state.get("clicks") or []
    return [c for c in clicks if any(token in str(c.get("name") or "").lower() for token in tokens)]


def _conversion_job_outcome(
    job: Dict[str, Any],
    state: Dict[str, Any],
    universe: Optional[Dict[str, Any]],
    *,
    cta_tokens: tuple[str, ...],
    empty_blocker: str,
    external_blocker: str,
    click_no_view_result: str,
    auth_blocker: str = "primary flow requires login or leaves site",
) -> Optional[Dict[str, str]]:
    paths = state.get("paths") or []
    attempted = bool(state.get("attempted"))
    viewed = bool(paths)
    page_ids = set(job.get("page_ids") or [])
    uni = universe or {}
    page_actions = _actions_for_page_ids(uni, page_ids)
    on_site_ctas = _actions_matching_tokens(page_actions, cta_tokens, on_site_only=True)
    external_ctas = _actions_matching_tokens(
        page_actions or uni.get("actions") or [],
        cta_tokens,
        target_kinds={"external_exit"},
    )
    auth_ctas = _auth_related_actions(uni, page_ids)
    cta_clicks = _cta_clicks(state, cta_tokens)
    navigated_clicks = [c for c in cta_clicks if c.get("navigated") is not False]
    action_count = _page_action_counts(uni, page_ids)

    if not viewed and not cta_clicks and not attempted:
        return None
    if not viewed and cta_clicks and not navigated_clicks:
        return {
            "status": "partial",
            "result": click_no_view_result,
            "blocker": "target page visit not confirmed",
        }
    if not viewed and cta_clicks:
        return {
            "status": "partial",
            "result": click_no_view_result,
            "blocker": "target page visit not confirmed",
        }
    if viewed and auth_ctas and not on_site_ctas:
        return {
            "status": "partial",
            "result": f"reached {paths[0]}",
            "blocker": auth_blocker,
        }
    if viewed and not on_site_ctas and external_ctas:
        return {
            "status": "partial",
            "result": f"reached {paths[0]}",
            "blocker": external_blocker,
        }
    if viewed and action_count == 0 and not on_site_ctas:
        return {
            "status": "partial",
            "result": f"reached {paths[0]}",
            "blocker": empty_blocker,
        }
    return None


def _job_specific_outcome(
    job_id: str,
    job: Dict[str, Any],
    state: Dict[str, Any],
    universe: Optional[Dict[str, Any]],
) -> Optional[Dict[str, str]]:
    if job_id == "book_demo":
        return _conversion_job_outcome(
            job,
            state,
            universe,
            cta_tokens=_DEMO_CTA_TOKENS,
            empty_blocker="no bookable form in agent tree",
            external_blocker="demo booking leaves site or form not in agent tree",
            click_no_view_result="clicked demo CTA but did not load demo page",
        )
    if job_id == "contact":
        uni = universe or {}
        page_ids = set(job.get("page_ids") or [])
        page_actions = _actions_for_page_ids(uni, page_ids)
        on_site_any = [a for a in page_actions if a.get("on_site")]
        external_any = [a for a in page_actions if str(a.get("target_kind") or "") == "external_exit"]
        paths = state.get("paths") or []
        if paths and not on_site_any and external_any:
            return {
                "status": "partial",
                "result": f"reached {paths[0]}",
                "blocker": "contact flow leaves site (external form or app)",
            }
        return _conversion_job_outcome(
            job,
            state,
            universe,
            cta_tokens=_CONTACT_CTA_TOKENS,
            empty_blocker="no on-site contact form or email action in agent tree",
            external_blocker="contact flow leaves site (external form or app)",
            click_no_view_result="clicked contact CTA but did not load contact page",
        )
    if job_id == "pricing":
        return _conversion_job_outcome(
            job,
            state,
            universe,
            cta_tokens=_PRICING_CTA_TOKENS,
            empty_blocker="no pricing/plan details in agent tree",
            external_blocker="pricing comparison leaves site",
            click_no_view_result="clicked pricing CTA but did not load pricing page",
        )
    if job_id == "convert":
        return _conversion_job_outcome(
            job,
            state,
            universe,
            cta_tokens=_CONVERT_CTA_TOKENS,
            empty_blocker="no signup/waitlist action in agent tree",
            external_blocker="signup flow leaves site",
            click_no_view_result="clicked signup CTA but did not load signup page",
            auth_blocker="signup requires login or auth gate",
        )
    if job_id == "checkout":
        return _conversion_job_outcome(
            job,
            state,
            universe,
            cta_tokens=_CHECKOUT_CTA_TOKENS,
            empty_blocker="checkout page has no agent-navigable purchase actions",
            external_blocker="checkout redirects off-site or to payment provider",
            click_no_view_result="clicked checkout CTA but did not load checkout page",
            auth_blocker="checkout requires login",
        )
    if job_id == "add_to_cart":
        clicks = _cta_clicks(state, _CART_CTA_TOKENS)
        if not clicks:
            return None
        if not any(c.get("navigated") is not False for c in clicks):
            return {
                "status": "partial",
                "result": "clicked add-to-cart but action did not activate",
                "blocker": "buy action not confirmed in agent tree",
            }
        return None
    if job_id == "about":
        if not (state.get("paths") or []):
            return None
        page_ids = set(job.get("page_ids") or [])
        if _page_action_counts(universe or {}, page_ids) == 0:
            return {
                "status": "partial",
                "result": f"reached {(state.get('paths') or [''])[0]}",
                "blocker": "about page has little agent-navigable content",
            }
    return None


def build_explore_visit_urls(
    source_url: str,
    universe: Dict[str, Any],
    jobs: List[Dict[str, Any]],
    *,
    max_pages: int,
    max_archive_deep: int = 2,
) -> List[str]:
    """Order crawl URLs for explore: job targets first, cap deep archive pages."""
    strategy_name = str((universe.get("strategy") or {}).get("name") or "").lower()
    page_type = str(universe.get("page_type") or (universe.get("strategy") or {}).get("page_type") or "").lower()
    ecommerce_bias = strategy_name == "shopify" or page_type == "ecommerce"
    priority_paths: Set[str] = set()
    for job in jobs:
        for prefix in job.get("path_prefixes") or ():
            p = _norm_path(str(prefix))
            if p != "/":
                priority_paths.add(p)
    strategy_priority = []
    for item in ((universe.get("strategy") or {}).get("priority_paths") or []):
        path = _norm_path(str(item.get("path") or ""))
        if path and path != "/":
            strategy_priority.append((int(item.get("priority") or 0), path))
    for _priority, path in sorted(strategy_priority, reverse=True)[:12]:
        priority_paths.add(path)

    seen: Set[str] = set()
    priority: List[str] = []
    other: List[str] = []
    archive_buckets: Dict[str, List[str]] = {key: [] for key in _ARCHIVE_ROOTS}

    for url in [source_url, *(universe.get("discovered_internal_urls") or [])]:
        parsed = urlparse(url)
        key = f"{parsed.scheme}://{parsed.netloc}{(parsed.path or '/').rstrip('/') or '/'}"
        if key in seen:
            continue
        seen.add(key)
        path = _norm_path(parsed.path or "/")
        archive = _archive_deep_path(path)
        if path in priority_paths or any(
            path.startswith(f"{p}/") for p in priority_paths if p != "/"
        ):
            priority.append(url)
        elif archive:
            archive_buckets[archive].append(url)
        else:
            other.append(url)

    archive_tail: List[str] = []
    for bucket in archive_buckets.values():
        archive_tail.extend(bucket[:max_archive_deep])

    priority.sort(key=lambda url: _visit_url_rank(url, ecommerce_bias=ecommerce_bias))
    other.sort(key=lambda url: _visit_url_rank(url, ecommerce_bias=ecommerce_bias))
    ordered = priority + other + archive_tail
    deduped: List[str] = []
    seen_order: Set[str] = set()
    for url in [source_url, *ordered]:
        parsed = urlparse(url)
        key = f"{parsed.scheme}://{parsed.netloc}{(parsed.path or '/').rstrip('/') or '/'}"
        if key in seen_order:
            continue
        seen_order.add(key)
        deduped.append(url)
    return deduped[:max_pages]


def _visit_url_rank(url: str, *, ecommerce_bias: bool) -> tuple[int, int, str]:
    path = _norm_path(urlparse(url).path or "/")
    segs = [seg.lower() for seg in _path_segments(path)]
    first = segs[0] if segs else ""
    if path == "/":
        return (-1, 0, path)
    if ecommerce_bias:
        if first in {"checkout", "cart"}:
            return (0, len(segs), path)
        if first in {"products", "product"}:
            return (1, len(segs), path)
        if first in {"collections", "collection"}:
            return (2, len(segs), path)
        if first in {"shop", "store"}:
            return (3, len(segs), path)
        if _is_low_intent_ecommerce_path(path):
            return (8, len(segs), path)
    archive = _archive_deep_path(path)
    if archive:
        return (6, len(segs), path)
    return (4, len(segs), path)


def _migrate_stored_job_state(
    jobs: List[Dict[str, Any]],
    state_map: Dict[str, Any],
) -> Dict[str, Any]:
    """Carry progress forward when job ids change (e.g. pricing → book_demo for /demo)."""
    migrated = {job_id: dict(state) for job_id, state in state_map.items()}
    job_by_id = {job["id"]: job for job in jobs}

    if "book_demo" in job_by_id and "pricing" in migrated and "book_demo" not in migrated:
        pricing = migrated.pop("pricing")
        demo_prefixes = tuple(job_by_id["book_demo"].get("path_prefixes") or ())
        demo_paths = [p for p in pricing.get("paths") or [] if _path_matches_prefix(p, demo_prefixes)]
        if demo_paths or pricing.get("attempted"):
            migrated["book_demo"] = {
                **pricing,
                "paths": demo_paths or pricing.get("paths") or [],
            }

    if "pricing" in job_by_id and "pricing" in migrated:
        pricing_job = job_by_id["pricing"]
        pricing_prefixes = tuple(pricing_job.get("path_prefixes") or ())
        kept = [p for p in migrated["pricing"].get("paths") or [] if _path_matches_prefix(p, pricing_prefixes)]
        if kept:
            migrated["pricing"] = {**migrated["pricing"], "paths": kept}
        elif migrated["pricing"].get("paths"):
            migrated.pop("pricing", None)

    return migrated


def merge_job_progress(
    jobs: List[Dict[str, Any]],
    stored: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Map stored tracker state onto a possibly re-inferred job list."""
    stored = stored or {}
    state_map = _migrate_stored_job_state(jobs, (stored.get("state") or {}).copy())
    merged_state: Dict[str, Any] = {}
    for job in jobs:
        job_id = job["id"]
        merged_state[job_id] = state_map.get(job_id) or {
            "paths": [],
            "clicks": [],
            "deep_reached": False,
            "attempted": False,
        }
    return {"jobs": jobs, "state": merged_state}


def finalize_job_results(
    jobs: List[Dict[str, Any]],
    progress: Dict[str, Any],
    gaps: Optional[List[Dict[str, Any]]] = None,
    universe: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    gaps = gaps or []
    progress = merge_job_progress(jobs, progress)
    state_map = progress.get("state") or {}
    rows: List[Dict[str, Any]] = []

    for job in jobs:
        job_id = job["id"]
        state = state_map.get(job_id) or {}
        paths = state.get("paths") or []
        attempted = bool(state.get("attempted"))
        deep_reached = bool(state.get("deep_reached"))
        journey_gaps = _gaps_for_job(gaps, job)
        high_gaps = [g for g in journey_gaps if g.get("severity") in {"critical", "high"}]

        override = _job_specific_outcome(job_id, job, state, universe)
        if override:
            rows.append(
                {
                    "id": job_id,
                    "job": job["job"],
                    "status": override["status"],
                    "result": override["result"],
                    "blocker": override["blocker"],
                    "gap_count": len(journey_gaps),
                    "gaps": _gap_summaries(journey_gaps),
                    "goal": job.get("goal") or "",
                }
            )
            continue

        if job.get("require_deep_path"):
            reached = deep_reached or any(_deep_path_reached(p, job) for p in paths)
            result = f"opened {paths[-1]}" if reached and paths else ("not attempted" if not attempted else "index only")
        elif job_id == "add_to_cart":
            cart_clicks = _cta_clicks(state, _CART_CTA_TOKENS)
            reached = bool(cart_clicks)
            result = f"activated {cart_clicks[0]['name']}" if cart_clicks else ("not attempted" if not attempted else "not activated")
        else:
            reached = bool(paths)
            result = f"reached {paths[0]}" if paths else ("not attempted" if not attempted else "partial activation")

        if reached and not journey_gaps:
            status = "success"
            blocker = "—"
        elif reached and journey_gaps:
            status = "partial"
            blocker = _blocker_from_gaps(journey_gaps=journey_gaps, high_gaps=high_gaps, job_id=job_id)
        elif attempted:
            status = "partial"
            blocker = journey_gaps[0].get("impact") if journey_gaps else "could not fully complete job"
        else:
            status = "failed"
            result = "not attempted"
            if journey_gaps:
                blocker = journey_gaps[0].get("impact") or "blocked in crawl catalog"
            elif job_id == "contact":
                blocker = "no clear contact CTA in agent tree"
            elif job_id == "book_demo":
                blocker = "agent did not attempt demo booking"
            else:
                blocker = "agent did not attempt this job"

        rows.append(
            {
                "id": job_id,
                "job": job["job"],
                "status": status,
                "result": result,
                "blocker": blocker,
                "gap_count": len(journey_gaps),
                "gaps": _gap_summaries(journey_gaps),
                "goal": job.get("goal") or "",
            }
        )
    return _sort_jobs(rows)


def job_success_accessibility_note(
    job_results: List[Dict[str, Any]],
    accessibility_score: Optional[float],
) -> Optional[str]:
    """Flag when green job rows disagree with very low accessibility."""
    if accessibility_score is None:
        return None
    successes = sum(1 for row in job_results if row.get("status") == "success")
    if accessibility_score <= 10 and successes >= 2:
        return (
            f"Job table shows {successes} success(es) but site accessibility is {accessibility_score:.0f}% "
            "— most catalog actions are still not agent-navigable."
        )
    return None
