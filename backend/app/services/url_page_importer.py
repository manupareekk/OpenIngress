"""
URL import for visual website experiments.

This service fetches a URL or accepts provided HTML and returns a compact page
artifact that can be patched into variants. It deliberately keeps importing
separate from running browser sessions.
"""

from __future__ import annotations

import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from dataclasses import asdict, dataclass, field
from html import escape as escape_html
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List
from urllib.parse import parse_qs, urldefrag, urljoin, urlparse, urlunparse, urlencode

from .variant_html import summarize_variant_html
from ..models import FlowPage
from .navigation_graph_builder import NavigationGraphBuilder
from .crawl_strategies import apply_strategy_to_crawl
from .crawl_strategies.prioritizer import prioritize_urls
from .crawl_strategies.registry import detect_strategy


MAX_IMPORTED_HTML_CHARS = 750_000
DEFAULT_RENDERED_MAX_PAGES = 100


class ImportCancelled(Exception):
    """Raised when a crawl is cancelled mid-import."""

DEFAULT_RENDERED_MAX_DEPTH = 3
MAX_RENDERED_PAGES = 100
# Wall-clock cap for multi-page rendered crawls (SPA sites can exceed per-page timeouts).
CRAWL_WALL_CLOCK_CAP_SECONDS = 180
DOWNLOAD_EXTENSIONS = {
    ".pdf",
    ".zip",
    ".csv",
    ".xls",
    ".xlsx",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
}
CRAWL_URL_BLACKLIST_TOKENS = {
    "ccpa",
    "conditions",
    "cookie",
    "cookies",
    "gdpr",
    "legal",
    "privacy",
    "terms",
}


@dataclass
class ImportedElement:
    selector: str
    tag: str
    text: str = ""
    kind: str = "action"
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ImportedUrlPage:
    source_url: str
    final_url: str
    title: str
    html: str
    elements: List[ImportedElement] = field(default_factory=list)
    import_mode: str = "static_fetch"
    warnings: List[str] = field(default_factory=list)
    pages: List[Dict[str, Any]] = field(default_factory=list)
    navigation_graph: Dict[str, Any] = field(default_factory=dict)
    crawl: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["elements"] = [element.to_dict() for element in self.elements]
        return data


class UrlPageImporter:
    def import_page(
        self,
        url: str = "",
        html: str = "",
        timeout_seconds: int = 12,
        max_pages: int = DEFAULT_RENDERED_MAX_PAGES,
        render: bool = True,
        device_mix: str = "desktop",
        extra_headers: Dict[str, str] | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
        on_page: Callable[[List[Dict[str, Any]], Dict[str, Any], List[str]], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        require_browser_crawl: bool = False,
    ) -> ImportedUrlPage:
        pasted_html = str(html or "").strip()
        url_value = str(url or "").strip()
        fallback_warnings: List[str] = []
        render_available = playwright_render_available()
        use_render = bool(render) and render_available
        self._render_device_mix = _normalize_import_device_mix(device_mix)

        if render and not render_available:
            hint = _playwright_install_hint()
            if require_browser_crawl:
                raise RuntimeError(hint)
            fallback_warnings.append(hint)

        if pasted_html:
            source_url = normalize_url(url_value) if url_value else "https://uploaded.local"
            merged_headers = {str(k): str(v) for k, v in (extra_headers or {}).items() if k and v}
            merged_headers.update(_protection_bypass_headers_from_url(source_url))
            source_url = _ensure_vercel_bypass_query(source_url, merged_headers)
            self._extra_headers = merged_headers
            if use_render:
                try:
                    return self._import_rendered_html(source_url, pasted_html, timeout_seconds)
                except Exception as exc:
                    fallback_warnings.append(
                        f"Rendered browser import failed; used pasted HTML directly. {_short_error(exc)}"
                    )
            return self._build_imported_page(
                source_url=source_url,
                final_url=source_url,
                page_html=pasted_html,
                import_mode="provided_html",
                warnings=fallback_warnings,
            )

        if not url_value:
            raise ValueError(
                "URL is required. Enter a public https:// URL, or switch Source Mode to Pasted HTML."
            )

        source_url = normalize_url(url_value)
        merged_headers = {str(k): str(v) for k, v in (extra_headers or {}).items() if k and v}
        merged_headers.update(_protection_bypass_headers_from_url(source_url))
        source_url = _ensure_vercel_bypass_query(source_url, merged_headers)
        self._extra_headers = merged_headers
        self._crawl_on_progress = on_progress
        self._crawl_on_page = on_page
        self._crawl_should_cancel = should_cancel
        rendered_error: Exception | None = None

        if use_render:
            try:
                return self._import_rendered_url(source_url, timeout_seconds, max_pages)
            except Exception as exc:
                rendered_error = exc
                if require_browser_crawl:
                    raise RuntimeError(
                        f"Browser crawl failed for {source_url}. {_short_error(exc)}"
                    ) from exc
                fallback_warnings.append(
                    f"Rendered browser import failed; fell back to static fetch. {_short_error(exc)}"
                )

        if require_browser_crawl:
            raise RuntimeError(
                f"Browser crawl could not run for {source_url}. {_playwright_install_hint()}"
            )

        try:
            final_url, page_html, fetch_warnings = self._fetch(source_url, timeout_seconds)
        except Exception as fetch_exc:
            raise RuntimeError(
                _format_import_failure(source_url, rendered_error, fetch_exc, render_available)
            ) from fetch_exc

        return self._build_imported_page(
            source_url=source_url,
            final_url=final_url,
            page_html=page_html,
            import_mode="static_fetch",
            warnings=[*fallback_warnings, *fetch_warnings],
        )

    def _build_imported_page(
        self,
        source_url: str,
        final_url: str,
        page_html: str,
        import_mode: str,
        warnings: List[str] | None = None,
    ) -> ImportedUrlPage:
        page_html = prepare_static_session_html(page_html, final_url)
        parser = _PageElementParser(final_url)
        parser.feed(page_html[:500_000])
        parser.close()
        title = parser.title or _domain_title(final_url)
        page = {
            "id": "home",
            "path": _path_from_url(final_url),
            "title": title,
            "html": page_html,
            "is_start": True,
            "is_conversion": False,
            "metadata": {
                "source_url": source_url,
                "final_url": final_url,
                "import_mode": import_mode,
                "depth": 0,
            },
        }
        pages = [page]
        graph = self._navigation_graph_for_pages(pages, "static_html")
        combined_warnings = [*(warnings or []), *detect_import_warnings(page_html, parser.elements)]
        return ImportedUrlPage(
            source_url=source_url,
            final_url=final_url,
            title=title,
            html=page_html,
            elements=parser.elements[:80],
            import_mode=import_mode,
            warnings=combined_warnings,
            pages=pages,
            navigation_graph=graph,
            crawl={
                "mode": import_mode,
                "pages_found": 1,
                "max_pages": 1,
                "same_origin_only": True,
            },
        )

    def _import_rendered_html(self, source_url: str, html: str, timeout_seconds: int) -> ImportedUrlPage:
        from playwright.sync_api import sync_playwright

        timeout_ms = _timeout_ms(timeout_seconds)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=self._render_viewport(),
                user_agent=_browser_user_agent(),
                ignore_https_errors=True,
                extra_http_headers=self._playwright_headers(),
            )
            page = context.new_page()
            try:
                page.set_content(_ensure_base_href(html, source_url), wait_until="domcontentloaded", timeout=timeout_ms)
                self._settle_page(page, timeout_ms)
                title = page.title() or _domain_title(source_url)
                page_html = prepare_static_session_html(page.content(), source_url)
                elements = _imported_elements_from_rendered(_extract_rendered_elements(page, source_url))
            finally:
                page.close()
                browser.close()

        page_data = {
            "id": "home",
            "path": _path_from_url(source_url),
            "title": title,
            "html": page_html,
            "is_start": True,
            "is_conversion": False,
            "metadata": {
                "source_url": source_url,
                "final_url": source_url,
                "import_mode": "rendered_html",
                "depth": 0,
                "device_mix": self._render_device_mix,
                "viewport": self._render_viewport(),
            },
        }
        graph = self._navigation_graph_for_pages([page_data], "rendered_browser")
        return ImportedUrlPage(
            source_url=source_url,
            final_url=source_url,
            title=title,
            html=page_html,
            elements=elements[:80],
            import_mode="rendered_html",
            warnings=detect_import_warnings(page_html, elements),
            pages=[page_data],
            navigation_graph=graph,
            crawl={
                "mode": "rendered_html",
                "pages_found": 1,
                "max_pages": 1,
                "same_origin_only": True,
            },
        )

    def _import_rendered_url(self, source_url: str, timeout_seconds: int, max_pages: int) -> ImportedUrlPage:
        crawl = self._crawl_rendered_url(source_url, timeout_seconds, max_pages)
        pages = crawl["pages"]
        if not pages:
            fallback = self._capture_rendered_fallback(source_url, timeout_seconds)
            if fallback:
                pages = [fallback]
                crawl["warnings"] = [
                    *crawl["warnings"],
                    "Rendered crawl returned no pages; captured a single browser snapshot instead.",
                ]
            else:
                hint = _import_failure_hint(source_url, crawl["warnings"])
                raise ValueError(f"Rendered browser crawl did not return any pages. {hint}")

        start_page = pages[0]
        elements = _imported_elements_from_rendered(start_page.get("metadata", {}).get("rendered_elements") or [])
        graph = self._navigation_graph_for_pages(pages, "rendered_browser")
        warnings = [*crawl["warnings"], *detect_import_warnings(start_page["html"], elements)]
        return ImportedUrlPage(
            source_url=source_url,
            final_url=start_page.get("metadata", {}).get("final_url") or source_url,
            title=start_page.get("title") or _domain_title(source_url),
            html=start_page.get("html") or "",
            elements=elements[:80],
            import_mode="rendered_browser",
            warnings=warnings,
            pages=pages,
            navigation_graph=graph,
            crawl={
                "mode": "rendered_browser",
                "pages_found": len(pages),
                "max_pages": max(1, min(int(max_pages or DEFAULT_RENDERED_MAX_PAGES), MAX_RENDERED_PAGES)),
                "max_depth": DEFAULT_RENDERED_MAX_DEPTH,
                "same_origin_only": True,
                "warnings": crawl["warnings"],
            },
        )

    def _crawl_rendered_url(self, source_url: str, timeout_seconds: int, max_pages: int) -> Dict[str, Any]:
        from playwright.sync_api import sync_playwright

        timeout_ms = _timeout_ms(timeout_seconds)
        max_pages = max(1, min(int(max_pages or DEFAULT_RENDERED_MAX_PAGES), MAX_RENDERED_PAGES))
        stack = [(source_url, 0)]
        queued = {_url_key(source_url)}
        visited: set[str] = set()
        used_page_ids: set[str] = set()
        pages: List[Dict[str, Any]] = []
        warnings: List[str] = []
        deadline = time.monotonic() + _crawl_wall_clock_seconds(timeout_seconds, max_pages)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=self._render_viewport(),
                user_agent=_browser_user_agent(),
                ignore_https_errors=True,
                extra_http_headers=self._playwright_headers(),
            )
            context.set_default_timeout(min(timeout_ms, 10_000))
            context.route("**/*", lambda route, request: _guard_scoped_request(route, request, source_url))
            try:
                while stack and len(pages) < max_pages:
                    if self._crawl_should_cancel and self._crawl_should_cancel():
                        raise ImportCancelled("Crawl cancelled")
                    if time.monotonic() >= deadline:
                        warnings.append(
                            f"Import time budget reached; captured {len(pages)} of up to {max_pages} page(s). "
                            "Use fewer pages or paste HTML for a single-page import."
                        )
                        break
                    current_url, depth = stack.pop()
                    key = _url_key(current_url)
                    if key in visited:
                        continue
                    visited.add(key)
                    if not _same_crawl_scope(source_url, current_url):
                        continue

                    page = context.new_page()
                    try:
                        response = self._goto_and_settle(page, current_url, timeout_ms)
                        final_url = page.url
                        load_failed, load_message = _rendered_page_load_failed(
                            page, response, source_url, final_url
                        )
                        if load_failed:
                            warnings.append(load_message)
                            continue

                        outside_scope = not _same_crawl_scope(source_url, final_url)
                        if outside_scope:
                            warnings.append(
                                f"Page redirected outside {_origin_label(source_url)} to {final_url}. "
                                "Skipped the redirected page to keep the crawl on the submitted site."
                            )
                            continue

                        page_data = self._build_rendered_page_data(
                            source_url=source_url,
                            final_url=final_url,
                            page=page,
                            response=response,
                            depth=depth,
                            is_start=len(pages) == 0,
                            used_page_ids=used_page_ids,
                        )
                        if page_data:
                            pages.append(page_data)
                            if getattr(self, "_crawl_on_page", None):
                                self._crawl_on_page(
                                    [dict(page) for page in pages],
                                    self._navigation_graph_for_pages(pages, "rendered_browser"),
                                    list(warnings),
                                )
                            if self._crawl_on_progress:
                                self._crawl_on_progress(len(pages), max_pages, final_url or current_url)
                            rendered_elements = page_data.get("metadata", {}).get("rendered_elements") or []
                            if depth < DEFAULT_RENDERED_MAX_DEPTH and not outside_scope:
                                next_urls = list(
                                    dict.fromkeys(
                                        _crawl_candidate_urls(rendered_elements, final_url, source_url)
                                        + _crawl_candidate_urls_from_html(page_data.get("html") or "", final_url, source_url)
                                    )
                                )
                                strategy_config = detect_strategy(source_url=source_url, pages=pages)
                                if strategy_config:
                                    next_urls = prioritize_urls(next_urls, strategy_config)
                                for next_url in reversed(next_urls):
                                    next_key = _url_key(next_url)
                                    if next_key in queued or next_key in visited:
                                        continue
                                    queued.add(next_key)
                                    stack.append((next_url, depth + 1))
                                    if len(queued) >= max_pages * 3:
                                        break
                    except Exception as exc:
                        warnings.append(f"Could not render {current_url}: {_short_error(exc)}")
                        salvaged = self._salvage_rendered_page(
                            page=page,
                            source_url=source_url,
                            depth=depth,
                            is_start=len(pages) == 0,
                            used_page_ids=used_page_ids,
                            error=exc,
                        )
                        if salvaged:
                            pages.append(salvaged)
                            warnings.append(
                                f"Recovered partial HTML after render error for {current_url}."
                            )
                        elif len(pages) == 0:
                            warnings.append(
                                _browser_load_failure_hint(source_url, page.url, None, str(exc))
                            )
                    finally:
                        page.close()
            finally:
                browser.close()

        return {"pages": pages, "warnings": warnings}

    def _playwright_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        headers.update(getattr(self, "_extra_headers", {}) or {})
        if headers.get("x-vercel-protection-bypass") and not headers.get("x-vercel-set-bypass-cookie"):
            headers["x-vercel-set-bypass-cookie"] = "true"
        return headers

    def _render_viewport(self) -> Dict[str, int]:
        return _viewport_for_import_device(getattr(self, "_render_device_mix", "desktop"))

    def _build_rendered_page_data(
        self,
        source_url: str,
        final_url: str,
        page: Any,
        response: Any,
        depth: int,
        is_start: bool,
        used_page_ids: set[str],
    ) -> Dict[str, Any] | None:
        if _is_browser_error_url(final_url):
            return None
        rendered_elements = _extract_rendered_elements(page, final_url)
        rendered_html = page.content()
        if not str(rendered_html or "").strip():
            return None
        if _is_error_page_html(rendered_html, page.title() if page else ""):
            return None
        page_html = prepare_static_session_html(rendered_html, final_url)
        page_id = _unique_page_id(_page_id_from_url(final_url), used_page_ids)
        used_page_ids.add(page_id)
        return {
            "id": page_id,
            "path": _path_from_url(final_url),
            "title": page.title() or _domain_title(final_url),
            "html": page_html,
            "is_start": is_start,
            "is_conversion": False,
            "metadata": {
                "source_url": source_url,
                "final_url": final_url,
                "status": response.status if response else None,
                "import_mode": "rendered_browser",
                "depth": depth,
                "device_mix": self._render_device_mix,
                "viewport": self._render_viewport(),
                "rendered_elements": rendered_elements[:80],
            },
        }

    def _salvage_rendered_page(
        self,
        page: Any,
        source_url: str,
        depth: int,
        is_start: bool,
        used_page_ids: set[str],
        error: Exception,
    ) -> Dict[str, Any] | None:
        try:
            final_url = page.url or source_url
            if _is_browser_error_url(final_url):
                return None
            rendered_html = page.content()
            if len(str(rendered_html or "").strip()) < 32:
                return None
            if _is_error_page_html(rendered_html, page.title()):
                return None
            return self._build_rendered_page_data(
                source_url=source_url,
                final_url=final_url,
                page=page,
                response=None,
                depth=depth,
                is_start=is_start,
                used_page_ids=used_page_ids,
            )
        except Exception:
            return None

    def _capture_rendered_fallback(self, source_url: str, timeout_seconds: int) -> Dict[str, Any] | None:
        from playwright.sync_api import sync_playwright

        timeout_ms = _timeout_ms(timeout_seconds)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport=self._render_viewport(),
                user_agent=_browser_user_agent(),
                ignore_https_errors=True,
                extra_http_headers=self._playwright_headers(),
            )
            page = context.new_page()
            try:
                response = self._goto_and_settle(page, source_url, timeout_ms)
                load_failed, _ = _rendered_page_load_failed(page, response, source_url, page.url)
                if load_failed:
                    return None
                used_ids: set[str] = set()
                return self._build_rendered_page_data(
                    source_url=source_url,
                    final_url=page.url or source_url,
                    page=page,
                    response=response,
                    depth=0,
                    is_start=True,
                    used_page_ids=used_ids,
                )
            except Exception:
                return self._salvage_rendered_page(
                    page=page,
                    source_url=source_url,
                    depth=0,
                    is_start=True,
                    used_page_ids=set(),
                    error=Exception("fallback"),
                )
            finally:
                page.close()
                browser.close()

    def _goto_and_settle(self, page: Any, url: str, timeout_ms: int) -> Any:
        host = (urlparse(url).hostname or "").lower()
        wait_until = "load" if _prefer_load_settle(host) else "domcontentloaded"
        response = page.goto(url, wait_until=wait_until, timeout=timeout_ms)
        settle_cap = 6_000 if _prefer_load_settle(host) else 3_500
        self._settle_page(page, min(timeout_ms, settle_cap))
        return response

    def _settle_page(self, page: Any, timeout_ms: int) -> None:
        # Skip networkidle — SPAs with analytics often never idle and can hang imports.
        self._scroll_full_page(page)
        page.wait_for_timeout(700 if timeout_ms > 4_000 else 450)
        _reveal_animated_dom(page)
        page.wait_for_timeout(250)

    def _scroll_full_page(self, page: Any) -> None:
        try:
            page.evaluate(
                """async () => {
                  const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
                  let lastHeight = 0;
                  for (let step = 0; step < 8; step += 1) {
                    window.scrollTo(0, document.body.scrollHeight);
                    await delay(220);
                    const nextHeight = document.body.scrollHeight;
                    if (nextHeight === lastHeight) break;
                    lastHeight = nextHeight;
                  }
                  window.scrollTo(0, 0);
                }"""
            )
        except Exception:
            pass

    def _navigation_graph_for_pages(self, pages: List[Dict[str, Any]], extractor: str) -> Dict[str, Any]:
        flow_pages: List[FlowPage] = []
        for page in pages:
            html = str(page.get("html") or "")
            metadata = dict(page.get("metadata") or {})
            metadata["summary"] = summarize_variant_html(html) if html else {}
            flow_pages.append(
                FlowPage(
                    id=str(page.get("id") or "home"),
                    path=str(page.get("path") or "/"),
                    html=html,
                    title=str(page.get("title") or page.get("id") or "Imported Page"),
                    is_start=bool(page.get("is_start", False)),
                    is_conversion=bool(page.get("is_conversion", False)),
                    metadata=metadata,
                )
            )
        start_page_id = next((page.id for page in flow_pages if page.is_start), flow_pages[0].id if flow_pages else "home")
        graph = NavigationGraphBuilder().build("A", flow_pages, start_page_id)
        graph.extractor = extractor
        graph.quality["extractor"] = extractor
        graph_dict = graph.to_dict()
        source_url = ""
        for page in pages:
            metadata = page.get("metadata") or {}
            source_url = str(metadata.get("source_url") or metadata.get("final_url") or source_url)
            if source_url:
                break
        return apply_strategy_to_crawl(
            source_url=source_url,
            pages=pages,
            navigation_graph=graph_dict,
        )

    def _fetch(self, url: str, timeout_seconds: int) -> tuple[str, str, List[str]]:
        headers = {
            "User-Agent": _browser_user_agent(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        headers.update(getattr(self, "_extra_headers", {}) or {})
        if headers.get("x-vercel-protection-bypass") and not headers.get("x-vercel-set-bypass-cookie"):
            headers["x-vercel-set-bypass-cookie"] = "true"
        current_url = url
        warnings: List[str] = []
        last_error: Exception | None = None
        for verify in (True, False):
            try:
                context = _ssl_context(verify=verify)
                for _ in range(10):
                    request = urllib.request.Request(current_url, headers=headers)
                    try:
                        with urllib.request.urlopen(
                            request, timeout=timeout_seconds, context=context
                        ) as response:
                            status = getattr(response, "status", None) or response.getcode()
                            if status in {401, 403}:
                                raise ValueError(_http_access_hint(url, int(status)))
                            content_type = response.headers.get("content-type", "")
                            if "text/html" not in content_type and "application/xhtml" not in content_type:
                                raise ValueError(
                                    f"URL did not return HTML: {content_type or 'unknown content type'}"
                                )
                            charset = response.headers.get_content_charset() or "utf-8"
                            body = response.read(1_500_000).decode(charset, errors="replace")
                            if not verify:
                                warnings.append(
                                    "Static fetch skipped TLS certificate verification for this URL."
                                )
                            return response.geturl(), body, warnings
                    except urllib.error.HTTPError as exc:
                        if exc.code in {301, 302, 303, 307, 308}:
                            location = exc.headers.get("Location")
                            if location:
                                current_url = urljoin(current_url, location)
                                continue
                        if exc.code in {401, 403}:
                            raise ValueError(_http_access_hint(url, int(exc.code))) from exc
                        raise
                raise RuntimeError(f"Too many redirects while fetching {url}")
            except Exception as exc:
                last_error = exc
                if verify and _is_ssl_certificate_error(exc):
                    continue
                if isinstance(exc, urllib.error.HTTPError) and exc.code in {401, 403}:
                    raise ValueError(_http_access_hint(url, int(exc.code))) from exc
                raise
        raise last_error or RuntimeError(f"Could not fetch {url}")


class _PageElementParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self.elements: List[ImportedElement] = []
        self._captures: List[Dict[str, Any]] = []
        self._ignore_depth = 0

    def handle_starttag(self, tag: str, attrs_raw):
        tag = tag.lower()
        attrs = {str(key).lower(): str(value or "") for key, value in attrs_raw}
        if tag in {"script", "style", "template", "noscript", "svg"}:
            self._ignore_depth += 1
            return
        if self._ignore_depth:
            return

        if tag == "title":
            self._captures.append({"tag": tag, "attrs": attrs, "text": []})
            return

        if self._is_input_candidate(tag, attrs):
            self._append_element(tag, attrs)
            return

        if tag in {"a", "button", "textarea", "select", "form"}:
            self._captures.append({"tag": tag, "attrs": attrs, "text": []})

    def handle_startendtag(self, tag: str, attrs_raw):
        tag = tag.lower()
        attrs = {str(key).lower(): str(value or "") for key, value in attrs_raw}
        if self._ignore_depth:
            return
        if self._is_input_candidate(tag, attrs):
            self._append_element(tag, attrs)

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in {"script", "style", "template", "noscript", "svg"}:
            self._ignore_depth = max(0, self._ignore_depth - 1)
            return
        if self._ignore_depth:
            return
        capture = self._pop_matching(tag)
        if not capture:
            return
        text = compact_text(" ".join(capture["text"]))
        attrs = capture["attrs"]
        if tag == "title":
            self.title = text
            return
        self._append_element(tag, attrs, text)

    def handle_data(self, data: str):
        if self._ignore_depth:
            return
        text = data.strip()
        if not text:
            return
        for capture in self._captures:
            capture["text"].append(text)

    def _pop_matching(self, tag: str) -> Dict[str, Any] | None:
        for index in range(len(self._captures) - 1, -1, -1):
            if self._captures[index]["tag"] == tag:
                return self._captures.pop(index)
        return None

    def _is_input_candidate(self, tag: str, attrs: Dict[str, str]) -> bool:
        if tag != "input":
            return False
        input_type = (attrs.get("type") or "text").lower()
        return input_type in {"text", "search", "email", "submit", "button"}

    def _append_element(self, tag: str, attrs: Dict[str, str], text: str = ""):
        self.elements.append(
            ImportedElement(
                selector=selector_for(tag, attrs, len(self.elements) + 1),
                tag=tag,
                text=text or attrs.get("value") or attrs.get("placeholder") or attrs.get("aria-label") or attrs.get("name") or tag,
                kind=element_kind(tag, attrs),
                attributes=normalized_attrs(attrs, self.base_url),
            )
        )


def _protection_bypass_headers_from_url(url: str) -> Dict[str, str]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    headers: Dict[str, str] = {}
    bypass = (query.get("x-vercel-protection-bypass") or [""])[0]
    if bypass:
        headers["x-vercel-protection-bypass"] = str(bypass)
    return headers


def _ensure_vercel_bypass_query(url: str, headers: Dict[str, str]) -> str:
    bypass = str(headers.get("x-vercel-protection-bypass") or "").strip()
    if not bypass:
        return url
    host = (urlparse(url).hostname or "").lower()
    if "vercel.app" not in host:
        return url
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if (query.get("x-vercel-protection-bypass") or [""])[0]:
        return url
    query["x-vercel-protection-bypass"] = [bypass]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query, doseq=True),
            "",
        )
    )


def _is_browser_error_url(url: str) -> bool:
    scheme = (urlparse(url or "").scheme or "").lower()
    if scheme in {"chrome-error", "chrome", "edge", "devtools", "brave"}:
        return True
    if scheme == "about" and "error" in (urlparse(url).path or "").lower():
        return True
    return "chromewebdata" in (url or "").lower()


def _is_error_page_html(html: str, title: str = "") -> bool:
    sample = f"{title} {html}".lower()[:12_000]
    markers = (
        "this site can't be reached",
        "this site cant be reached",
        "err_connection",
        "err_name_not_resolved",
        "err_ssl",
        "chromewebdata",
        "dns_probe_finished",
        "deployment protection",
        "authentication required",
        "access to this page has been denied",
    )
    return any(marker in sample for marker in markers)


def _rendered_page_load_failed(
    page: Any,
    response: Any,
    source_url: str,
    final_url: str,
) -> tuple[bool, str]:
    if _is_browser_error_url(final_url):
        return True, _browser_load_failure_hint(source_url, final_url, response)
    try:
        html = page.content()
        title = page.title()
    except Exception:
        html = ""
        title = ""
    if _is_error_page_html(html, title):
        return True, _browser_load_failure_hint(source_url, final_url, response)
    status = response.status if response else None
    if status is not None and int(status) >= 400:
        return True, _browser_load_failure_hint(source_url, final_url, response, http_status=int(status))
    return False, ""


def _browser_load_failure_hint(
    source_url: str,
    final_url: str,
    response: Any,
    error: str = "",
    http_status: int | None = None,
) -> str:
    host = _origin_label(source_url)
    status_note = f" (HTTP {http_status})" if http_status else ""
    err_note = f" Browser error: {compact_text(error)}." if error else ""
    if "vercel.app" in host.lower() or "vercel.app" in (final_url or "").lower():
        return (
            f"Headless Chrome could not load {host}{status_note} — it hit a browser error page "
            f"({final_url or 'unknown'}), not your site.{err_note} "
            "For protected Vercel previews: click Use for Option A in the Vercel panel (applies bypass), "
            "or add ?x-vercel-protection-bypass=YOUR_SECRET to the URL, "
            "or export HTML from your browser and choose Pasted HTML."
        )
    if _is_browser_error_url(final_url):
        return (
            f"Headless Chrome could not load {host}{status_note} — navigation failed "
            f"({final_url}).{err_note} Use a public production URL or paste HTML."
        )
    return (
        f"Could not load {host}{status_note}.{err_note} "
        "Use a public URL or paste HTML under Source Mode."
    )


def normalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        raise ValueError("URL is required.")
    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = f"https://{value}"
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Unsupported URL: {url}")
    return value


def selector_for(tag: str, attrs: Dict[str, str], fallback_index: int) -> str:
    if attrs.get("id"):
        return f"#{css_escape(attrs['id'])}"
    if attrs.get("name"):
        return f"{tag}[name=\"{attrs['name']}\"]"
    for attr in ("data-testid", "data-track", "aria-label", "placeholder"):
        if attrs.get(attr):
            return f"{tag}[{attr}=\"{attrs[attr]}\"]"
    if attrs.get("href"):
        return f"{tag}[href=\"{attrs['href']}\"]"
    return f"{tag}:nth-of-type({fallback_index})"


def element_kind(tag: str, attrs: Dict[str, str]) -> str:
    if tag in {"textarea", "select"}:
        return "input"
    if tag == "input":
        input_type = (attrs.get("type") or "text").lower()
        if input_type in {"text", "search", "email"}:
            return "input"
        return "button"
    if tag == "form":
        return "form"
    if tag == "a":
        return "link"
    return "button"


def normalized_attrs(attrs: Dict[str, str], base_url: str) -> Dict[str, Any]:
    kept = {
        "id",
        "name",
        "type",
        "href",
        "action",
        "placeholder",
        "aria-label",
        "class",
        "role",
        "method",
        "onclick",
        "data-testid",
        "data-test",
        "data-track",
        "data-action",
        "data-cta",
        "data-href",
        "data-url",
        "data-target",
        "data-next-page",
        "data-page",
    }
    out = {key: value for key, value in attrs.items() if key in kept}
    if out.get("href"):
        out["resolved_href"] = urljoin(base_url, out["href"])
    if out.get("action"):
        out["resolved_action"] = urljoin(base_url, out["action"])
    if out.get("data-href"):
        out["resolved_data_href"] = urljoin(base_url, out["data-href"])
    if out.get("data-url"):
        out["resolved_data_url"] = urljoin(base_url, out["data-url"])
    return out


def css_escape(value: str) -> str:
    return re.sub(r"([^a-zA-Z0-9_-])", r"\\\1", value)


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def detect_import_warnings(html: str, elements: List[ImportedElement]) -> List[str]:
    warnings: List[str] = []
    source = (html or "").lower()
    if (
        "awswaf" in source
        or "challenge-container" in source
        or "verify that you're not a robot" in source
        or "validatecaptcha" in source
        or "opfcaptcha" in source
        or "to discuss automated access" in source
    ):
        warnings.append("The URL returned an anti-bot or WAF challenge page, not the usable website HTML.")
    if len(html or "") < 5_000 and not elements:
        warnings.append("No candidate controls were extracted from the imported HTML.")
    return warnings


def _domain_title(url: str) -> str:
    return urlparse(url).netloc or "Imported Website"


def _extract_rendered_elements(page: Any, base_url: str) -> List[Dict[str, Any]]:
    try:
        return page.evaluate(
            """
            (baseUrl) => {
              const ATTRS = [
                'id', 'name', 'type', 'href', 'action', 'placeholder', 'aria-label', 'class', 'role',
                'method', 'onclick', 'title', 'data-testid', 'data-test', 'data-track', 'data-action',
                'data-cta', 'data-href', 'data-url', 'data-target', 'data-next-page', 'data-page'
              ];
              const nodes = Array.from(document.querySelectorAll(
                'a,button,input,textarea,select,form,[role="button"],[role="link"],[onclick],[data-action],[data-href],[data-url],[data-next-page],[data-page]'
              ));
              const cssEscape = (value) => {
                if (window.CSS && CSS.escape) return CSS.escape(value);
                return String(value || '').replace(/([ #;?%&,.+*~\\':"!^$[\\]()=>|/@])/g, '\\\\$1');
              };
              const attrEscape = (value) => String(value || '').replace(/["\\\\]/g, '\\\\$&').replace(/\\s+/g, ' ').trim();
              const unique = (selector) => {
                try { return document.querySelectorAll(selector).length === 1; } catch (err) { return false; }
              };
              const selectorFor = (el, index) => {
                const tag = el.tagName.toLowerCase();
                if (el.id && unique('#' + cssEscape(el.id))) return '#' + cssEscape(el.id);
                for (const attr of ['data-testid', 'data-test', 'data-track', 'name', 'aria-label']) {
                  const value = el.getAttribute(attr);
                  if (!value) continue;
                  const selector = `${tag}[${attr}="${attrEscape(value)}"]`;
                  if (unique(selector)) return selector;
                }
                if (tag === 'a' && el.getAttribute('href')) {
                  const selector = `${tag}[href="${attrEscape(el.getAttribute('href'))}"]`;
                  if (unique(selector)) return selector;
                }
                const parts = [];
                let current = el;
                while (current && current.nodeType === Node.ELEMENT_NODE && parts.length < 4) {
                  const currentTag = current.tagName.toLowerCase();
                  if (current.id) {
                    parts.unshift('#' + cssEscape(current.id));
                    break;
                  }
                  const parent = current.parentElement;
                  if (!parent) {
                    parts.unshift(currentTag);
                    break;
                  }
                  const siblings = Array.from(parent.children).filter((item) => item.tagName === current.tagName);
                  const nth = siblings.length > 1 ? `:nth-of-type(${siblings.indexOf(current) + 1})` : '';
                  parts.unshift(currentTag + nth);
                  current = parent;
                }
                const selector = parts.join(' > ');
                return selector || `${tag}:nth-of-type(${index + 1})`;
              };
              const textFor = (el) => (
                el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') ||
                el.getAttribute('placeholder') || el.getAttribute('name') || el.tagName
              ).trim().replace(/\\s+/g, ' ').slice(0, 220);
              const kindFor = (el) => {
                const tag = el.tagName.toLowerCase();
                const role = (el.getAttribute('role') || '').toLowerCase();
                const type = (el.getAttribute('type') || '').toLowerCase();
                if (tag === 'a' || role === 'link') return 'link';
                if (['textarea', 'select'].includes(tag)) return 'input';
                if (tag === 'input') return ['submit', 'button'].includes(type) ? 'button' : 'input';
                if (tag === 'form') return 'form';
                return 'button';
              };
              const visibleFor = (el) => {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
              };
              return nodes.map((el, index) => {
                const tag = el.tagName.toLowerCase();
                const attrs = {};
                for (const attr of ATTRS) {
                  const value = el.getAttribute(attr);
                  if (value !== null && value !== '') attrs[attr] = value;
                }
                if (tag === 'a' && el.href) attrs.resolved_href = el.href;
                if (tag === 'form' && el.action) attrs.resolved_action = el.action;
                if (attrs['data-href']) attrs.resolved_data_href = new URL(attrs['data-href'], baseUrl).href;
                if (attrs['data-url']) attrs.resolved_data_url = new URL(attrs['data-url'], baseUrl).href;
                const rect = el.getBoundingClientRect();
                return {
                  selector: selectorFor(el, index),
                  tag,
                  text: textFor(el),
                  kind: kindFor(el),
                  visible: visibleFor(el),
                  attributes: attrs,
                  rect: {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    width: Math.round(rect.width),
                    height: Math.round(rect.height)
                  }
                };
              }).filter((item) => (
                item.visible || item.text || item.attributes.href || item.attributes.action ||
                item.attributes['data-href'] || item.attributes['data-url'] || item.attributes.onclick
              )).slice(0, 120);
            }
            """,
            base_url,
        )
    except Exception:
        return []


def _imported_elements_from_rendered(raw_elements: List[Dict[str, Any]]) -> List[ImportedElement]:
    elements = []
    for raw in raw_elements:
        attrs = dict(raw.get("attributes") or {})
        if raw.get("rect"):
            attrs["rect"] = raw["rect"]
        if raw.get("visible") is not None:
            attrs["visible"] = bool(raw.get("visible"))
        elements.append(
            ImportedElement(
                selector=str(raw.get("selector") or ""),
                tag=str(raw.get("tag") or ""),
                text=compact_text(str(raw.get("text") or "")),
                kind=str(raw.get("kind") or "action"),
                attributes=attrs,
            )
        )
    return elements


def _guard_scoped_request(route: Any, request: Any, source_url: str) -> None:
    if _is_browser_error_url(request.url):
        route.abort()
        return
    try:
        is_navigation = request.resource_type == "document" and request.is_navigation_request()
    except Exception:
        is_navigation = request.resource_type == "document"
    if is_navigation and not _same_crawl_scope(source_url, request.url):
        route.abort()
        return
    route.continue_()


def _crawl_candidate_urls_from_html(page_html: str, current_url: str, source_url: str) -> List[str]:
    """Discover same-origin links from static HTML (blog posts, footer links, etc.)."""
    candidates: List[str] = []
    for match in re.finditer(
        r"""<a\b[^>]*\bhref\s*=\s*(?:"([^"]+)"|'([^']+)')""",
        page_html or "",
        flags=re.IGNORECASE,
    ):
        href = match.group(1) or match.group(2) or ""
        next_url = _clean_crawl_url(urljoin(current_url, href))
        if (
            not next_url
            or not _same_crawl_scope(source_url, next_url)
            or _is_download_url(next_url)
            or _is_blacklisted_crawl_url(next_url)
        ):
            continue
        if next_url not in candidates:
            candidates.append(next_url)
    return candidates


def _crawl_candidate_urls(raw_elements: List[Dict[str, Any]], current_url: str, source_url: str) -> List[str]:
    candidates: List[str] = []
    for raw in raw_elements:
        attrs = raw.get("attributes") or {}
        for key in ("resolved_href", "resolved_data_href", "resolved_data_url", "href", "data-href", "data-url"):
            value = attrs.get(key)
            if not value:
                continue
            next_url = _clean_crawl_url(urljoin(current_url, str(value)))
            if (
                not next_url
                or not _same_crawl_scope(source_url, next_url)
                or _is_download_url(next_url)
                or _is_blacklisted_crawl_url(next_url)
            ):
                continue
            if next_url not in candidates:
                candidates.append(next_url)
    return candidates


def _clean_crawl_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    scheme = urlparse(value).scheme.lower()
    if scheme and scheme not in {"http", "https"}:
        return ""
    value, _fragment = urldefrag(value)
    parsed = urlparse(value)
    if not parsed.netloc:
        return ""
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def _url_key(url: str) -> str:
    parsed = urlparse(_clean_crawl_url(url) or url)
    host = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), host, path, "", parsed.query, ""))


def _same_origin(base_url: str, url: str) -> bool:
    base = urlparse(base_url)
    target = urlparse(urljoin(base_url, url))
    return (
        base.scheme.lower() == target.scheme.lower()
        and _normalized_host(base.hostname) == _normalized_host(target.hostname)
        and _normalized_port(base) == _normalized_port(target)
    )


def _same_crawl_scope(base_url: str, url: str) -> bool:
    return _same_origin(base_url, url) or _is_shopify_redirect_bridge(base_url, url)


def _is_shopify_redirect_bridge(base_url: str, url: str) -> bool:
    base = urlparse(base_url)
    target = urlparse(urljoin(base_url, url))
    base_host = _normalized_host(base.hostname)
    target_host = (target.hostname or "").lower()
    if not base_host or not target_host.endswith(f".{base_host}"):
        return False
    if base.scheme.lower() != target.scheme.lower():
        return False
    labels = target_host[: -len(base_host)].strip(".").split(".")
    return "checkout" in labels


def _normalized_host(hostname: str | None) -> str:
    value = (hostname or "").lower()
    return value[4:] if value.startswith("www.") else value


def _normalized_port(parsed: Any) -> int:
    if parsed.port:
        return int(parsed.port)
    return 443 if parsed.scheme.lower() == "https" else 80


def _path_from_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or "/"
    path = re.sub(r"/+", "/", path)
    if path.endswith("/index.html"):
        path = path[: -len("index.html")]
    if path.endswith(".html"):
        path = path[:-5]
    return path.rstrip("/") or "/"


def _page_id_from_url(url: str) -> str:
    path = _path_from_url(url).strip("/")
    if not path:
        return "home"
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_").lower()
    return slug or "page"


def _unique_page_id(base_id: str, used: set[str]) -> str:
    candidate = base_id or "page"
    suffix = 2
    while candidate in used:
        candidate = f"{base_id}_{suffix}"
        suffix += 1
    return candidate


def _is_download_url(url: str) -> bool:
    clean = urlparse(url).path.lower()
    return any(clean.endswith(ext) for ext in DOWNLOAD_EXTENSIONS)


def _is_blacklisted_crawl_url(url: str) -> bool:
    parsed = urlparse(_clean_crawl_url(url) or url)
    tokens = re.split(r"[^a-z0-9]+", f"{parsed.path} {parsed.query}".lower())
    return any(token in CRAWL_URL_BLACKLIST_TOKENS for token in tokens)


def _ensure_base_href(html: str, final_url: str) -> str:
    source = html or ""
    if not final_url or re.search(r"<base\s", source, flags=re.IGNORECASE):
        return source
    base = f'<base href="{escape_html(final_url, quote=True)}">'
    head_match = re.search(r"<head[^>]*>", source, flags=re.IGNORECASE)
    if head_match:
        index = head_match.end()
        return f"{source[:index]}{base}{source[index:]}"
    if re.search(r"<html[\s>]", source, flags=re.IGNORECASE):
        html_match = re.search(r"<html[^>]*>", source, flags=re.IGNORECASE)
        index = html_match.end() if html_match else 0
        return f"{source[:index]}<head>{base}</head>{source[index:]}"
    return f"<!doctype html><html><head>{base}</head><body>{source}</body></html>"


def _reveal_animated_dom(page: Any) -> None:
    try:
        page.evaluate(
            """() => {
              document.querySelectorAll('[style]').forEach((el) => {
                const style = el.getAttribute('style') || '';
                if (!/opacity\\s*:\\s*0/i.test(style)) return;
                el.style.opacity = '1';
                el.style.filter = 'none';
                el.style.transform = 'none';
              });
            }"""
        )
    except Exception:
        pass


def _reveal_hidden_markup(html: str) -> str:
    source = html or ""
    if not source:
        return source

    def _reveal_style_attr(match: re.Match[str]) -> str:
        style = match.group(1)
        if not re.search(r"opacity\s*:\s*0", style, flags=re.IGNORECASE):
            return match.group(0)
        style = re.sub(r"opacity\s*:\s*0", "opacity:1", style, flags=re.IGNORECASE)
        style = re.sub(r"filter\s*:\s*blur\([^)]+\)", "filter:none", style, flags=re.IGNORECASE)
        return f'style="{style}"'

    return re.sub(r'style="([^"]*)"', _reveal_style_attr, source)


_SESSION_REVEAL_STYLES = """
<style id="mf-session-reveal">
  [style*="opacity:0"], [style*="opacity: 0"] {
    opacity: 1 !important;
    filter: none !important;
    transform: none !important;
  }
  template[data-dgst] { display: none !important; }
  #__next-build-watcher, nextjs-portal { display: none !important; }
</style>
"""

_SESSION_LINK_GUARD = """
<script id="mf-session-link-guard">
(function () {
  document.addEventListener('click', function (event) {
    var link = event.target.closest('a[href]');
    if (!link) return;
    var href = link.getAttribute('href') || '';
    if (!href || href.charAt(0) === '#' || /^(mailto|tel|javascript):/i.test(href)) return;
    event.preventDefault();
    event.stopPropagation();
  }, true);
})();
</script>
"""


def _strip_preview_scripts(html: str) -> str:
    source = html or ""
    source = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", source, flags=re.IGNORECASE)
    source = re.sub(r"<script\b[^>]*\/>", "", source, flags=re.IGNORECASE)
    source = re.sub(
        r'<link\b[^>]*\brel=["\']modulepreload["\'][^>]*>',
        "",
        source,
        flags=re.IGNORECASE,
    )
    return source


def _inject_session_helpers(html: str) -> str:
    bundle = f"{_SESSION_REVEAL_STYLES}{_SESSION_LINK_GUARD}"
    head_match = re.search(r"<head[^>]*>", html or "", flags=re.IGNORECASE)
    if head_match:
        index = head_match.end()
        return f"{html[:index]}{bundle}{html[index:]}"
    if re.search(r"<html[\s>]", html or "", flags=re.IGNORECASE):
        html_match = re.search(r"<html[^>]*>", html or "", flags=re.IGNORECASE)
        index = html_match.end() if html_match else 0
        return f"{html[:index]}<head>{bundle}</head>{html[index:]}"
    return f"{bundle}{html}"


def prepare_static_session_html(html: str, base_url: str = "") -> str:
    """
    Make imported HTML safe for Playwright sessions and iframe previews.

    Next.js and similar SPAs crash or blank out when their client bundles run
    outside the original origin. Agents should always see flattened static HTML.
    """
    source = html or ""
    if base_url:
        source = _ensure_base_href(source, base_url)
    source = _strip_preview_scripts(source)
    source = _reveal_hidden_markup(source)
    source = _inject_session_helpers(source)
    return source[:MAX_IMPORTED_HTML_CHARS]


def _trim_html(html: str) -> str:
    return prepare_static_session_html(html)


def _timeout_ms(timeout_seconds: int) -> int:
    return max(1_000, min(int(timeout_seconds or 12) * 1000, 45_000))


def _crawl_wall_clock_seconds(timeout_seconds: int, max_pages: int) -> int:
    per_page = max(8, int(timeout_seconds or 12) + 4)
    budget = per_page * max(1, min(int(max_pages or DEFAULT_RENDERED_MAX_PAGES), MAX_RENDERED_PAGES))
    return min(CRAWL_WALL_CLOCK_CAP_SECONDS, budget)


def _prefer_load_settle(host: str) -> bool:
    """Use load + scroll settle for hosts that are usually client-rendered."""
    if not host:
        return False
    # Vercel / Next-style hosts often need a full load + scroll before content appears.
    if "vercel.app" in host or host.endswith(".vercel.app"):
        return True
    return False


def _browser_user_agent() -> str:
    return "Mozilla/5.0 (MiroFish rendered browser importer; +https://mirofish.local)"


def _normalize_import_device_mix(value: str) -> str:
    normalized = str(value or "desktop").lower()
    if normalized in {"mobile", "desktop"}:
        return normalized
    return "desktop"


def _viewport_for_import_device(value: str) -> Dict[str, int]:
    if _normalize_import_device_mix(value) == "mobile":
        return {"width": 390, "height": 844}
    return {"width": 1440, "height": 900}


def _ssl_context(*, verify: bool) -> ssl.SSLContext:
    if not verify:
        return ssl._create_unverified_context()
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _origin_label(url: str) -> str:
    parsed = urlparse(url)
    return parsed.netloc or url


def _http_access_hint(url: str, status: int) -> str:
    host = _origin_label(url)
    if status == 401:
        if "vercel.app" in host.lower():
            return (
                f"{host} returned 401 (deployment protection). In the Vercel panel, paste your "
                "Protection Bypass for Automation secret from: Project → Settings → Deployment Protection "
                "(section: Protection Bypass for Automation). Then click Use for Option A again and re-import. "
                "Or use https://www.manupareek.com / Pasted HTML."
            )
        return (
            f"{host} returned 401 Unauthorized. The URL is behind login or deployment protection. "
            "Use a publicly accessible URL, disable protection for preview imports, or switch Source Mode to Pasted HTML."
        )
    return (
        f"{host} returned {status} Forbidden. The server blocked automated fetch. "
        "Use a public URL or paste the rendered HTML instead."
    )


def _import_failure_hint(source_url: str, warnings: List[str]) -> str:
    joined = " ".join(warnings).lower()
    host = _origin_label(source_url)
    if "401" in joined or "unauthorized" in joined:
        return _http_access_hint(source_url, 401)
    if "403" in joined or "forbidden" in joined:
        return _http_access_hint(source_url, 403)
    if "chrome-error" in joined or "browser error page" in joined or "headless chrome could not load" in joined:
        return (
            f"{host} did not load in the headless browser. "
            "Re-apply the deployment from the Vercel panel, add the protection-bypass query param, or paste HTML."
        )
    if "redirect" in joined or "login" in joined:
        return (
            f"{host} redirected to a login or external page. "
            "Paste HTML from your browser or use a public production URL."
        )
    return (
        f"Check that {host} is reachable without authentication, or paste HTML under Source Mode."
    )


def _is_ssl_certificate_error(exc: Exception) -> bool:
    if isinstance(exc, ssl.SSLError):
        return True
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, ssl.SSLError):
        return True
    message = str(exc).upper()
    return "CERTIFICATE_VERIFY_FAILED" in message or "SSL: CERTIFICATE" in message


def _short_error(exc: Exception) -> str:
    message = compact_text(str(exc))
    if len(message) > 180:
        message = f"{message[:177]}..."
    return f"{type(exc).__name__}: {message}"


def playwright_render_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            return Path(playwright.chromium.executable_path).exists()
    except Exception:
        return False


def _playwright_install_hint() -> str:
    return (
        "Playwright Chromium is not installed. Skipped browser render. "
        "From the backend folder run: python -m playwright install chromium"
    )


def _format_import_failure(
    source_url: str,
    rendered_error: Exception | None,
    fetch_exc: Exception,
    render_available: bool,
) -> str:
    parts: List[str] = []
    if rendered_error is not None:
        parts.append(f"Rendered browser import failed: {_short_error(rendered_error)}.")
    parts.append(f"Static fetch failed: {_short_error(fetch_exc)}.")

    fetch_hint = _static_fetch_hint(fetch_exc, source_url)
    if fetch_hint:
        parts.append(fetch_hint)

    if not render_available:
        parts.append(_playwright_install_hint())

    parts.append(
        "Workarounds: install Chromium for full multi-page capture, use a public production URL, "
        "or switch Source Mode to Pasted HTML."
    )
    return " ".join(parts)


def _static_fetch_hint(exc: Exception, source_url: str) -> str:
    message = str(exc).lower()
    host = urlparse(source_url).netloc or source_url
    if "nodename nor servname" in message or "name or service not known" in message:
        return (
            f"Could not resolve host for {host}. Check the URL spelling and that the backend "
            "process has network access."
        )
    if "network is unreachable" in message or "connection refused" in message:
        return "The backend could not reach the internet. Run the API outside a network-restricted sandbox."
    if _is_ssl_certificate_error(exc):
        return (
            "TLS verification failed. Retry after fixing local certificates, or paste HTML under Source Mode."
        )
    if "timed out" in message:
        return f"Request to {host} timed out. Try again or paste HTML."
    return ""
