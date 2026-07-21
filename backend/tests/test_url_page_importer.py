from app.services.url_page_importer import (
    DEFAULT_RENDERED_MAX_DEPTH,
    _crawl_candidate_urls,
    _crawl_candidate_urls_from_html,
    _is_blacklisted_crawl_url,
    _same_crawl_scope,
    _same_origin,
)
from app.services.crawl_strategies.prioritizer import prioritize_urls
from app.services.crawl_strategies.registry import load_strategy_config


def test_rendered_crawl_default_depth_is_three():
    assert DEFAULT_RENDERED_MAX_DEPTH == 3


def test_crawl_candidates_skip_legal_privacy_and_download_urls():
    html = """
    <a href="/pricing">Pricing</a>
    <a href="/privacy">Privacy</a>
    <a href="/terms-and-conditions">Terms</a>
    <a href="/files/report.pdf">Report</a>
    <a href="https://other.example/demo">External</a>
    """

    candidates = _crawl_candidate_urls_from_html(
        html,
        "https://example.com/",
        "https://example.com/",
    )

    assert candidates == ["https://example.com/pricing"]


def test_rendered_element_candidates_use_same_blacklist():
    elements = [
        {"attributes": {"resolved_href": "https://example.com/contact"}},
        {"attributes": {"resolved_href": "https://example.com/legal/privacy-policy"}},
        {"attributes": {"href": "/cookie-policy"}},
    ]

    candidates = _crawl_candidate_urls(
        elements,
        "https://example.com/",
        "https://example.com/",
    )

    assert candidates == ["https://example.com/contact"]


def test_crawl_scope_allows_www_alias_but_not_other_google_hosts():
    assert _same_origin("https://google.com/", "https://www.google.com/search")
    assert _same_origin("https://www.google.com/", "https://google.com/search")
    assert not _same_origin("https://google.com/", "https://about.google/products/")
    assert not _same_origin("https://google.com/", "https://business.google.com/en-all/google-ads/")


def test_crawl_scope_allows_shopify_checkout_redirect_bridge():
    assert _same_crawl_scope("https://gymshark.com/", "https://us.checkout.gymshark.com/")
    assert _same_crawl_scope("https://gymshark.com/", "https://www.gymshark.com/collections/mens")
    assert not _same_origin("https://gymshark.com/", "https://us.checkout.gymshark.com/")
    assert not _same_crawl_scope("https://gymshark.com/", "https://checkout.other-shop.com/")


def test_blacklist_matches_common_legal_paths():
    assert _is_blacklisted_crawl_url("https://example.com/privacy-policy")
    assert _is_blacklisted_crawl_url("https://example.com/terms-of-service")
    assert _is_blacklisted_crawl_url("https://example.com/legal/cookie-notice")
    assert not _is_blacklisted_crawl_url("https://example.com/product-tour")


def test_shopify_frontier_keeps_collection_before_more_product_variants():
    html = """
    <a href="/products/a">Product A</a>
    <a href="/products/b">Product B</a>
    <a href="/products/c">Product C</a>
    <a href="/collections/all">All products</a>
    """
    candidates = _crawl_candidate_urls_from_html(
        html,
        "https://shop.example.com/",
        "https://shop.example.com/",
    )
    ordered = prioritize_urls(candidates, load_strategy_config("shopify"))

    assert "https://shop.example.com/collections/all" in ordered[:2]
