"""Validate that a URL is a crawlable public site before launching a run."""

from __future__ import annotations

import ipaddress
import socket
import ssl
import urllib.error
import urllib.request
from typing import Callable
from urllib.parse import urljoin, urlparse, urlunparse

from .url_page_importer import normalize_url

MAX_VALIDATION_HTML_CHARS = 300_000
# Domains that are not useful crawl targets for agent readiness studies.
_BLOCKED_HOSTS = {
    "google.com",
    "bing.com",
    "yahoo.com",
    "duckduckgo.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "x.com",
    "twitter.com",
    "youtube.com",
    "wikipedia.org",
    "github.com",
    "medium.com",
    "nytimes.com",
}

# Optional commerce signals — recorded when present, never required.
_PLATFORM_MARKERS = (
    "cdn.shopify.com",
    "shopify.theme",
    "shopify-section",
    "myshopify.com",
    "woocommerce",
    "wp-content/plugins/woocommerce",
    "bigcommerce",
    "magento",
)

_COMMERCE_MARKERS = (
    "add to cart",
    "add-to-cart",
    "add to bag",
    "/cart",
    "checkout",
    "buy now",
    "/products/",
    "/collections/",
)


class SiteValidationError(ValueError):
    def __init__(self, result: dict):
        super().__init__(str(result.get("message") or "Site validation failed."))
        self.result = result


# Backward-compatible aliases
StorefrontValidationError = SiteValidationError


def validate_site_url(
    url: str,
    *,
    fetcher: Callable[[str], tuple[str, str]] | None = None,
) -> dict:
    normalized = normalize_url(url)
    host = _host(normalized)
    if _is_blocked_host(host):
        return _rejected(
            normalized,
            "This domain is not a useful crawl target. Paste a public website URL you control or want to study.",
            reason="blocked_host",
        )
    if not _is_public_host(host):
        return _rejected(
            normalized,
            "This does not look like a public website URL.",
            reason="non_public_host",
        )

    candidates = _fetch_candidates(normalized)
    final_url = ""
    html = ""
    resolved_input = normalized
    fetch_error: Exception | None = None
    for candidate in candidates:
        try:
            final_url, html = (fetcher or _fetch_html)(candidate)
            resolved_input = candidate
            fetch_error = None
            break
        except Exception as exc:
            fetch_error = exc
            continue

    if fetch_error is not None or not final_url:
        return _rejected(
            normalized,
            "We could not fetch HTML from this URL. Check that the site is publicly reachable.",
            reason="fetch_failed",
        )

    if not html or len(html.strip()) < 20:
        return _rejected(
            normalized,
            "The URL did not return enough HTML to crawl.",
            reason="empty_html",
        )

    text = f"{final_url}\n{html[:MAX_VALIDATION_HTML_CHARS]}".lower()
    platform_evidence = _matched_markers(text, _PLATFORM_MARKERS)
    commerce_evidence = _matched_markers(text, _COMMERCE_MARKERS)
    if platform_evidence:
        platform = "commerce_platform"
        evidence = platform_evidence
    elif len(commerce_evidence) >= 2:
        platform = "ecommerce"
        evidence = commerce_evidence
    else:
        platform = "website"
        evidence = []

    # Prefer the live host (often www after apex → www redirects) for the study URL.
    canonical = _prefer_reachable_url(resolved_input, final_url)
    return _accepted(canonical, final_url, evidence, platform=platform)


def validate_storefront_url(
    url: str,
    *,
    fetcher: Callable[[str], tuple[str, str]] | None = None,
) -> dict:
    """Alias kept for existing API/callers."""
    return validate_site_url(url, fetcher=fetcher)


def assert_storefront_url(url: str) -> dict:
    result = validate_site_url(url)
    if not result.get("allowed"):
        raise SiteValidationError(result)
    return result


assert_site_url = assert_storefront_url


def _fetch_candidates(url: str) -> list[str]:
    """Apex hosts often only serve (or 308 to) www — try both."""
    candidates = [url]
    www_url = _with_www_host(url)
    if www_url and www_url not in candidates:
        candidates.append(www_url)
    return candidates


def _with_www_host(url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host or host.startswith("www.") or "." not in host:
        return None
    # Only rewrite bare registrable hosts (example.com), not already-subdomained hosts.
    if host.count(".") != 1:
        return None
    netloc = parsed.netloc
    if "@" in netloc:
        userinfo, _, hostport = netloc.rpartition("@")
        prefix = f"{userinfo}@"
    else:
        hostport = netloc
        prefix = ""
    if hostport.lower().startswith("www."):
        return None
    new_netloc = f"{prefix}www.{hostport}"
    return urlunparse(parsed._replace(netloc=new_netloc))


def _prefer_reachable_url(requested: str, final_url: str) -> str:
    final = (final_url or "").strip()
    if not final:
        return requested
    req_host = _host(requested)
    final_host = _host(final)
    if not final_host:
        return requested
    if final_host == req_host or final_host == f"www.{req_host}" or req_host == f"www.{final_host}":
        # Keep path/query from the resolved response when hosts only differ by www.
        return final.rstrip("/") or requested
    return requested


def _fetch_html(url: str) -> tuple[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    last_error: Exception | None = None
    for verify in (True, False):
        try:
            context = ssl.create_default_context() if verify else ssl._create_unverified_context()
            current_url = url
            for _ in range(10):
                request = urllib.request.Request(current_url, headers=headers)
                try:
                    with urllib.request.urlopen(request, timeout=8, context=context) as response:
                        content_type = response.headers.get("content-type", "")
                        if "text/html" not in content_type and "application/xhtml" not in content_type:
                            raise ValueError("URL did not return HTML.")
                        charset = response.headers.get_content_charset() or "utf-8"
                        body = response.read(MAX_VALIDATION_HTML_CHARS).decode(charset, errors="replace")
                        return response.geturl(), body
                except urllib.error.HTTPError as exc:
                    # Python's urllib does not follow 308; many apex→www hosts use it.
                    if exc.code in {301, 302, 303, 307, 308}:
                        location = exc.headers.get("Location") or exc.headers.get("location")
                        if location:
                            current_url = urljoin(current_url, location)
                            continue
                    raise
            raise RuntimeError(f"Too many redirects while fetching {url}")
        except Exception as exc:
            last_error = exc
            if verify and _is_ssl_certificate_error(exc):
                continue
            raise
    raise last_error or RuntimeError(f"Could not fetch {url}")


def _is_ssl_certificate_error(exc: Exception) -> bool:
    current: BaseException | None = exc
    while current:
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        current = current.__cause__ or current.__context__
    return "certificate verify failed" in str(exc).lower()


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().strip(".")


def _is_blocked_host(host: str) -> bool:
    return any(host == blocked or host.endswith(f".{blocked}") for blocked in _BLOCKED_HOSTS)


def _is_public_host(host: str) -> bool:
    if not host or host == "localhost":
        return False
    try:
        ip = ipaddress.ip_address(host)
        return _is_public_ip(ip)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True
    ips = []
    for info in infos:
        try:
            ips.append(ipaddress.ip_address(info[4][0]))
        except (IndexError, ValueError):
            continue
    return bool(ips) and all(_is_public_ip(ip) for ip in ips)


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _matched_markers(text: str, markers: tuple[str, ...]) -> list[str]:
    return [marker for marker in markers if marker in text]


def _accepted(normalized: str, final_url: str, evidence: list[str], *, platform: str) -> dict:
    return {
        "allowed": True,
        "url": normalized,
        "final_url": final_url,
        "platform": platform,
        "evidence": evidence[:6],
        "message": "Site looks crawlable.",
    }


def _rejected(normalized: str, message: str, *, reason: str) -> dict:
    return {
        "allowed": False,
        "url": normalized,
        "reason": reason,
        "message": message,
    }
