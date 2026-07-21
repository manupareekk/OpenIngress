"""Tests for static audit helpers."""

import urllib.error
from unittest.mock import MagicMock, patch

from app.services.static_audits import _check_interactive_labels, _fetch_llms_with_redirects, run_static_audits


class _FakeResponse:
    def __init__(self, status: int, headers: dict, body: bytes, url: str):
        self.status = status
        self.headers = headers
        self._body = body
        self._url = url

    def getcode(self) -> int:
        return self.status

    def read(self, size: int = -1) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_buttons_check_na_when_zero():
    checks = _check_interactive_labels("<div><a href='/'>Home</a></div>")
    button_check = next(c for c in checks if c["id"] == "button-labels")
    assert button_check.get("not_applicable") is True
    assert "N/A" in button_check["detail"]


def test_llms_redirect_follow_same_domain():
    responses = [
        (308, {"Location": "https://www.example.com/llms.txt"}, b"Redirecting..."),
        (200, {}, b"# Site\n\nSummary for agents.\n"),
    ]

    def fake_open(req, timeout=8):
        status, headers, body = responses.pop(0)
        url = req.full_url
        if status in {301, 302, 303, 307, 308}:
            raise urllib.error.HTTPError(url, status, "redirect", headers, None)
        return _FakeResponse(status, headers, body, url)

    with patch("urllib.request.build_opener") as build_opener:
        opener = MagicMock()
        opener.open.side_effect = fake_open
        build_opener.return_value = opener
        final_url, body, chain, reason, ok = _fetch_llms_with_redirects("https://example.com/llms.txt")
    assert ok is True
    assert reason == "ok"
    assert "200" in chain[-1]
    assert "Summary" in body


def test_run_static_audits_includes_llms_meta():
    with patch(
        "app.services.static_audits._fetch_llms_with_redirects",
        return_value=("https://x.com/llms.txt", "ok", ["200"], "ok", True),
    ):
        result = run_static_audits("https://x.com", "<html></html>")
    llms = next(c for c in result["checks"] if c["id"] == "llms-txt")
    assert llms["passed"] is True
    assert llms["llms_meta"]["pass"] is True
