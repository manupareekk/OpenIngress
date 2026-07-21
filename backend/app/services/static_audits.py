"""Deterministic operability checks for machine-facing sites."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin, urlparse

from .gap_taxonomy import LLMS_TXT, registrable_domain, same_registrable_domain


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def run_static_audits(source_url: str, page_html: str) -> Dict[str, Any]:
    checks = []
    checks.append(_check_llms_txt(source_url))
    checks.extend(_check_interactive_labels(page_html))
    checks.append(_check_page_size(page_html))
    passed = sum(1 for item in checks if item.get("passed"))
    return {
        "pass_ratio": round(passed / len(checks), 4) if checks else 0.0,
        "passed": passed,
        "total": len(checks),
        "checks": checks,
    }


def _fetch_llms_with_redirects(llms_url: str, max_hops: int = 3) -> Tuple[str, str, List[str], str, bool]:
    """Returns final_url, body, status_chain, reason, ok."""
    current = llms_url
    status_chain: List[str] = []
    body = ""
    for hop in range(max_hops + 1):
        req = urllib.request.Request(
            current,
            headers={"User-Agent": "OpenIngress-Audit/1.0", "Accept": "text/plain,*/*"},
        )
        try:
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(req, timeout=8) as response:
                status = int(
                    response.getcode()
                    if hasattr(response, "getcode")
                    else getattr(response, "status", 200) or 200
                )
                status_chain.append(str(status))
                body = response.read(131072).decode("utf-8", errors="replace")
                final_url = response.geturl() or current
                if 200 <= status < 300 and status not in {301, 302, 303, 307, 308}:
                    return final_url, body, status_chain, _llms_pass_reason(body, response.headers), True
                if status in {301, 302, 303, 307, 308} and hop < max_hops:
                    location = response.headers.get("Location") or response.headers.get("location")
                    if not location:
                        return final_url, body, status_chain, "redirect_missing_location", False
                    next_url = urljoin(current, location)
                    if not same_registrable_domain(llms_url, next_url):
                        return final_url, body, status_chain, "redirect_off_domain", False
                    current = next_url
                    continue
                return final_url, body, status_chain, f"http_{status}", False
        except urllib.error.HTTPError as exc:
            status_chain.append(str(exc.code))
            if exc.code in {301, 302, 303, 307, 308} and hop < max_hops:
                location = exc.headers.get("Location") or exc.headers.get("location")
                if location:
                    next_url = urljoin(current, location)
                    if same_registrable_domain(llms_url, next_url):
                        current = next_url
                        continue
                    return current, "", status_chain, "redirect_off_domain", False
            return current, "", status_chain, f"http_{exc.code}", False
        except (urllib.error.URLError, TimeoutError) as exc:
            return current, "", status_chain, f"fetch_error:{exc.reason if hasattr(exc, 'reason') else exc}", False
    return current, body, status_chain, "redirect_limit_exceeded", False


def _llms_pass_reason(body: str, headers: Any) -> str:
    text = (body or "").strip()
    if not text:
        return "empty_body"
    content_type = ""
    if headers:
        content_type = str(headers.get("Content-Type") or headers.get("content-type") or "").lower()
    if "text/html" in content_type and len(text) < 800:
        return "wrong_content_type"
    lower = text.lower()[:300]
    if lower.startswith("<!doctype") or lower.startswith("<html"):
        return "wrong_content_type"
    if "redirecting" in lower and len(text) < 400:
        return "redirect_not_followed"
    return "ok"


def _check_llms_txt(source_url: str) -> Dict[str, Any]:
    parsed = urlparse(source_url or "")
    if not parsed.scheme or not parsed.netloc:
        return {
            "id": "llms-txt",
            "title": "llms.txt at domain root",
            "passed": False,
            "severity": "info",
            "detail": "No base URL to probe.",
            "gap_type": LLMS_TXT,
        }
    llms_url = f"{parsed.scheme}://{parsed.netloc}/llms.txt"
    final_url, body, status_chain, reason, ok = _fetch_llms_with_redirects(llms_url)
    chain_text = " → ".join(status_chain) if status_chain else "—"
    detail = (
        f"Requested: {llms_url} → {chain_text} → final {final_url}. "
        f"Pass: {ok} — {reason}."
    )
    return {
        "id": "llms-txt",
        "title": "llms.txt at domain root",
        "passed": ok,
        "severity": "high" if not ok else "info",
        "detail": detail,
        "gap_type": LLMS_TXT,
        "llms_meta": {
            "requested_url": llms_url,
            "final_url": final_url,
            "status_chain": chain_text,
            "pass": ok,
            "reason": reason,
        },
    }


def _check_interactive_labels(page_html: str) -> list[Dict[str, Any]]:
    results = []
    buttons = len(re.findall(r"<button\b", page_html, flags=re.IGNORECASE))
    labeled = len(
        re.findall(
            r"<button[^>]+(?:aria-label|title)\s*=",
            page_html,
            flags=re.IGNORECASE,
        )
    )
    unlabeled = max(0, buttons - labeled)
    if buttons == 0:
        results.append(
            {
                "id": "button-labels",
                "title": "Buttons have accessible names",
                "passed": True,
                "severity": "info",
                "detail": "N/A — no buttons in static HTML.",
                "counts": {"buttons": 0, "labeled": 0, "unlabeled": 0},
                "not_applicable": True,
            }
        )
    else:
        results.append(
            {
                "id": "button-labels",
                "title": "Buttons have accessible names",
                "passed": unlabeled == 0,
                "severity": "warning" if unlabeled else "info",
                "detail": f"{labeled}/{buttons} buttons have aria-label or title.",
                "counts": {"buttons": buttons, "labeled": labeled, "unlabeled": unlabeled},
            }
        )
    links = len(re.findall(r"<a\b[^>]+href\s*=", page_html, flags=re.IGNORECASE))
    link_labeled = len(
        re.findall(
            r"<a\b[^>]+href\s*=[^>]+(?:aria-label|title|>[^<]{2,})",
            page_html,
            flags=re.IGNORECASE,
        )
    )
    results.append(
        {
            "id": "link-labels",
            "title": "Links have discernible text or labels",
            "passed": links == 0 or link_labeled >= max(1, int(links * 0.7)),
            "severity": "warning",
            "detail": f"~{link_labeled}/{links} links appear labeled in static HTML.",
            "counts": {"links": links, "labeled_estimate": link_labeled},
        }
    )
    return results


def _check_page_size(page_html: str) -> Dict[str, Any]:
    size = len(page_html or "")
    return {
        "id": "dom-size",
        "title": "DOM size suitable for agent snapshots",
        "passed": size < 600_000,
        "severity": "warning" if size >= 600_000 else "info",
        "detail": f"HTML payload {size:,} bytes.",
    }
