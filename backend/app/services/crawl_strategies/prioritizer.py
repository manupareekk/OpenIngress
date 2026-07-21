"""URL prioritization for configured crawl strategies."""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlparse


def priority_for_url(url: str, config: Dict[str, Any]) -> int:
    parsed = urlparse(url or "")
    path = (parsed.path or "/").rstrip("/") or "/"
    host = (parsed.hostname or "").lower()
    best = 0
    for _role, spec in (config.get("page_types") or {}).items():
        score = int(spec.get("priority") or 0)
        if path in {str(item).rstrip("/") or "/" for item in spec.get("path_exact") or []}:
            best = max(best, score)
        for prefix in spec.get("path_prefixes") or []:
            clean = str(prefix).rstrip("/")
            if path == clean or path.startswith(f"{clean}/"):
                best = max(best, score)
        for token in spec.get("host_contains") or []:
            if str(token).lower() in host:
                best = max(best, score)
    return best or int(((config.get("page_types") or {}).get("unknown") or {}).get("priority") or 0)


def prioritize_urls(urls: List[str], config: Dict[str, Any]) -> List[str]:
    if str(config.get("name") or "").lower() == "shopify":
        return _prioritize_shopify_urls(urls, config)
    indexed = list(enumerate(dict.fromkeys(urls)))
    ranked = sorted(indexed, key=lambda item: (-priority_for_url(item[1], config), item[0]))
    return [url for _index, url in ranked]


def _prioritize_shopify_urls(urls: List[str], config: Dict[str, Any]) -> List[str]:
    """Diversify early Shopify crawl slots across buyer-funnel page types."""
    indexed = list(enumerate(dict.fromkeys(urls)))
    buckets: Dict[str, List[tuple[int, str]]] = {
        "checkout": [],
        "cart": [],
        "collection": [],
        "product": [],
        "storefront": [],
        "other": [],
    }
    for index, url in indexed:
        path = (urlparse(url or "").path or "/").rstrip("/") or "/"
        first = path.strip("/").split("/", 1)[0].lower()
        if first in {"checkout", "checkouts"}:
            bucket = "checkout"
        elif first == "cart":
            bucket = "cart"
        elif first in {"collections", "collection", "search"}:
            bucket = "collection"
        elif first in {"products", "product"}:
            bucket = "product"
        elif first in {"shop", "store", "pages"}:
            bucket = "storefront"
        else:
            bucket = "other"
        buckets[bucket].append((index, url))

    for name, rows in buckets.items():
        buckets[name] = sorted(
            rows,
            key=lambda item: (-priority_for_url(item[1], config), _shopify_path_depth(item[1]), item[0]),
        )

    ordered: List[str] = []
    seen: set[str] = set()

    def take(bucket: str, limit: int = 1) -> None:
        rows = buckets.get(bucket) or []
        taken = 0
        while rows and taken < limit:
            _index, url = rows.pop(0)
            if url not in seen:
                seen.add(url)
                ordered.append(url)
                taken += 1

    # Reserve the earliest slots for distinct revenue-funnel surfaces.
    for bucket in ("checkout", "cart", "collection", "product", "storefront"):
        take(bucket)

    while any(buckets.values()):
        for bucket in ("checkout", "cart", "collection", "product", "storefront", "other"):
            take(bucket)

    return ordered


def _shopify_path_depth(url: str) -> int:
    path = (urlparse(url or "").path or "/").strip("/")
    return len([part for part in path.split("/") if part])
