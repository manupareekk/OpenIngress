import urllib.error
from unittest import mock

from app.services.site_validation import SiteValidationError, assert_site_url, validate_site_url


def test_validate_site_accepts_generic_html():
    result = validate_site_url(
        "example.com",
        fetcher=lambda _url: (
            "https://example.com/",
            "<html><head><title>Example</title></head><body><a href='/about'>About</a><main>Hello</main></body></html>",
        ),
    )
    assert result["allowed"] is True
    assert result["platform"] == "website"


def test_validate_site_accepts_shopify_marker_as_commerce():
    result = validate_site_url(
        "shop.example",
        fetcher=lambda _url: (
            "https://shop.example/",
            '<script src="https://cdn.shopify.com/theme.js"></script><body>Shop</body>',
        ),
    )
    assert result["allowed"] is True
    assert result["platform"] == "commerce_platform"


def test_validate_site_accepts_ecommerce_markers_as_signal():
    result = validate_site_url(
        "shop.example",
        fetcher=lambda _url: (
            "https://shop.example/",
            "<html><body><button>Add to cart</button><a href='/checkout'>Checkout</a></body></html>",
        ),
    )
    assert result["allowed"] is True
    assert result["platform"] == "ecommerce"


def test_validate_site_falls_back_to_www_when_apex_fails():
    calls = []

    def fetcher(url):
        calls.append(url)
        if "://www." in url:
            return (
                "https://www.example.com/",
                "<html><body><main>Hello from www</main></body></html>",
            )
        raise RuntimeError("apex unreachable")

    result = validate_site_url("example.com", fetcher=fetcher)
    assert result["allowed"] is True
    assert result["url"].startswith("https://www.example.com")
    assert calls[0].startswith("https://example.com")
    assert any("www.example.com" in url for url in calls)


def test_fetch_html_follows_308_redirects():
    from app.services import site_validation

    class FakeHeaders(dict):
        def get_content_charset(self):
            return "utf-8"

    class FakeResponse:
        def __init__(self, url):
            self._url = url
            self.headers = FakeHeaders({"content-type": "text/html; charset=utf-8"})

        def geturl(self):
            return self._url

        def read(self, _n):
            return b"<html><body><main>ok</main></body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=8, context=None):
        url = request.full_url if hasattr(request, "full_url") else request.get_full_url()
        if "://www." not in url:
            raise urllib.error.HTTPError(
                url,
                308,
                "Permanent Redirect",
                {"Location": "https://www.example.com/"},
                None,
            )
        return FakeResponse(url)

    with mock.patch.object(site_validation.urllib.request, "urlopen", side_effect=fake_urlopen):
        final_url, html = site_validation._fetch_html("https://example.com/")
    assert final_url == "https://www.example.com/"
    assert "ok" in html


def test_validate_site_retries_ssl_certificate_failures():
    calls = {"n": 0}

    class FakeHeaders(dict):
        def get_content_charset(self):
            return "utf-8"

    class FakeResponse:
        def __init__(self):
            self.headers = FakeHeaders({"content-type": "text/html; charset=utf-8"})

        def geturl(self):
            return "https://shop.example/"

        def read(self, _n):
            return b'<html><body>ok</body><script src="https://cdn.shopify.com/theme.js"></script>'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    import ssl
    from app.services import site_validation

    def fake_urlopen(request, timeout=8, context=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ssl.SSLCertVerificationError("certificate verify failed")
        return FakeResponse()

    with mock.patch.object(site_validation.urllib.request, "urlopen", side_effect=fake_urlopen):
        result = validate_site_url("shop.example")
    assert result["allowed"] is True
    assert calls["n"] == 2


def test_validate_site_rejects_blocked_host():
    result = validate_site_url("google.com")
    assert result["allowed"] is False
    assert result["reason"] == "blocked_host"


def test_validate_site_rejects_empty_html():
    result = validate_site_url(
        "thin.example",
        fetcher=lambda _url: ("https://thin.example/", " "),
    )
    assert result["allowed"] is False
    assert result["reason"] == "empty_html"


def test_assert_site_url_raises_with_validation_payload():
    import pytest

    with pytest.raises(SiteValidationError) as exc:
        assert_site_url("google.com")
    assert exc.value.result["allowed"] is False
