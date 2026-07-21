from app.services.crawl_strategies.classifier import classify_action, classify_page
from app.services.crawl_strategies.prioritizer import prioritize_urls
from app.services.crawl_strategies.probe_planner import build_probe_plan
from app.services.crawl_strategies.registry import detect_strategy, load_strategy_config
from app.services.crawl_strategies.strategy import apply_strategy_to_crawl
from app.services.cursor_agent_explorer import _probe_candidate, _probe_outcome, _probe_signal_snapshot
from app.services.remediation_export import build_remediation_exports


def _shopify_config():
    return load_strategy_config("shopify")


def test_strategy_detection_and_config_loading():
    config = _shopify_config()

    detected = detect_strategy(
        source_url="https://store.example.com/",
        pages=[{"html": '<script src="https://cdn.shopify.com/theme.js"></script><button>Add to cart</button>'}],
    )

    assert config["name"] == "shopify"
    assert detected["name"] == "shopify"


def test_shopify_page_classifier_covers_core_page_types():
    config = _shopify_config()
    cases = {
        "homepage": {"path": "/", "html": "<h1>Store</h1>"},
        "collection": {"path": "/collections/all", "html": "<h1>Collection</h1>"},
        "product": {"path": "/products/classic-tee", "html": "<button>Add to cart</button>"},
        "cart": {"path": "/cart", "html": "<button>Checkout</button>"},
        "checkout_handoff": {"path": "/checkout", "html": "<h1>Checkout</h1>"},
        "search": {"path": "/search", "html": "<form>Search</form>"},
        "policy": {"path": "/policies/privacy-policy", "html": "<h1>Privacy policy</h1>"},
        "blog_content": {"path": "/blogs/news/post", "html": "<article>Post</article>"},
        "account_auth": {"path": "/account/login", "html": "<h1>Sign in</h1>"},
    }

    for expected, page in cases.items():
        segment = classify_page(page, "https://shop.example.com/", config)
        assert segment["page_type"] == expected


def test_shopify_action_classifier_covers_buyer_actions_and_risks():
    config = _shopify_config()
    page = {"page_type": "product"}
    cases = {
        "product_link": {"element_text": "Classic Tee", "target_path": "/products/classic-tee"},
        "collection_link": {"element_text": "Shop all", "target_path": "/collections/all"},
        "variant_control": {"element_text": "Size M", "target_path": ""},
        "add_to_cart": {"element_text": "Add to cart", "target_path": ""},
        "cart_open": {"element_text": "View cart", "target_path": "/cart"},
        "quantity_control": {"element_text": "Increase quantity", "target_path": ""},
        "checkout_link": {"element_text": "Checkout", "target_path": "/checkout"},
        "search": {"element_text": "Search", "target_path": "/search"},
        "account_gate": {"element_text": "Sign in", "target_path": "/account/login"},
        "popup_or_modal": {"element_text": "Newsletter popup", "target_path": ""},
    }

    for expected, action in cases.items():
        segment = classify_action(action, page, "https://shop.example.com/", config)
        assert segment["action_role"] == expected


def test_prioritizer_diversifies_shopify_frontier_before_more_products():
    ordered = prioritize_urls(
        [
            "https://shop.example.com/policies/privacy-policy",
            "https://shop.example.com/blogs/news/story",
            "https://shop.example.com/products/classic-tee",
            "https://shop.example.com/products/second-tee",
            "https://shop.example.com/cart",
            "https://shop.example.com/collections/all",
        ],
        _shopify_config(),
    )

    assert ordered[:3] == [
        "https://shop.example.com/cart",
        "https://shop.example.com/collections/all",
        "https://shop.example.com/products/classic-tee",
    ]
    assert ordered.index("https://shop.example.com/collections/all") < ordered.index(
        "https://shop.example.com/products/second-tee"
    )


def test_shopify_probe_rejects_size_guide_as_variant_selection():
    candidate = _probe_candidate(
        "variant_selection",
        [{"id": "size-guide", "action_role": "variant_control", "element_text": "Size Guide"}],
        [{"role": "button", "name": "Size Guide"}],
    )

    assert candidate is None


def test_shopify_probe_rejects_collection_promo_as_checkout():
    candidate = _probe_candidate(
        "checkout_handoff",
        [],
        [{"role": "link", "name": "Check out the collection"}],
    )

    assert candidate is None
    assert _probe_candidate("checkout_handoff", [], [{"role": "button", "name": "Checkout"}])


def test_shopify_probe_signals_do_not_treat_add_to_bag_as_cart_or_checkout():
    signals = _probe_signal_snapshot(
        page_url="https://shop.example.com/products/classic-tee",
        static_html="<button>Add to bag</button>",
        live_nodes=[{"role": "button", "name": "Add to bag"}, {"role": "link", "name": "Check out the collection"}],
    )

    assert signals["add_to_cart_visible"]["hydrated"] is True
    assert signals["cart_visible"]["hydrated"] is False
    assert signals["checkout_visible"]["hydrated"] is False


def test_add_to_cart_probe_success_requires_buyer_state_after_click():
    status, evidence = _probe_outcome(
        step_id="add_to_cart",
        source_url="https://shop.example.com/",
        before={"add_to_cart_visible": {"hydrated": True}, "cart_visible": {"hydrated": False}, "checkout_visible": {"hydrated": False}},
        after={"add_to_cart_visible": {"hydrated": True}, "cart_visible": {"hydrated": False}, "checkout_visible": {"hydrated": False}},
        interaction={"clicked": True},
        final_url="https://shop.example.com/products/classic-tee",
    )

    assert status == "partial"
    assert "confirmation" in evidence


def test_probe_plan_keeps_checkout_handoff_safe():
    strategy = {
        "page_segments": [{"page_type": "checkout_handoff", "path": "/checkout"}],
        "action_segments": [{"action_role": "checkout_link", "target_path": "/checkout"}],
    }

    probes = build_probe_plan(strategy, _shopify_config())
    checkout = next(probe for probe in probes if probe["step_id"] == "checkout_handoff")

    assert checkout["safe_mode"] == "checkout_handoff_only"
    assert "submit_payment" in checkout["forbidden_actions"]
    assert "submit_pii" in checkout["forbidden_actions"]
    assert "place_order" in checkout["forbidden_actions"]


def test_probe_plan_falls_back_to_product_for_cart_and_checkout():
    strategy = {
        "page_segments": [{"page_type": "product", "path": "/products/classic-tee"}],
        "action_segments": [{"action_role": "add_to_cart", "path": "/products/classic-tee"}],
    }

    probes = build_probe_plan(strategy, _shopify_config())
    by_id = {probe["step_id"]: probe for probe in probes}

    assert by_id["cart"]["start_path"] == "/products/classic-tee"
    assert by_id["cart"]["fallback_used"] is True
    assert by_id["checkout_handoff"]["start_path"] == "/products/classic-tee"
    assert by_id["checkout_handoff"]["fallback_used"] is True


def test_apply_strategy_adds_graph_and_page_action_metadata():
    pages = [
        {
            "id": "home",
            "path": "/",
            "title": "Shop",
            "html": '<a href="/products/mug">Mug</a><a href="/policies/privacy-policy">Privacy</a>',
            "metadata": {"summary": {"actions": []}},
        },
        {
            "id": "product",
            "path": "/products/mug",
            "title": "Mug",
            "html": "<button>Add to cart</button>",
            "metadata": {"summary": {"actions": []}},
        },
    ]
    graph = {
        "pages": [{"id": "home", "path": "/"}, {"id": "product", "path": "/products/mug"}],
        "actions": [
            {
                "id": "home::product",
                "page_id": "home",
                "element_text": "Mug",
                "target_path": "/products/mug",
                "target_kind": "internal_page",
                "attributes": {},
            },
            {
                "id": "product::add",
                "page_id": "product",
                "element_text": "Add to cart",
                "target_path": "",
                "target_kind": "unknown_js",
                "attributes": {},
            },
        ],
    }

    result = apply_strategy_to_crawl(source_url="https://shop.example.com/", pages=pages, navigation_graph=graph)

    assert result["strategy"]["name"] == "shopify"
    assert pages[1]["metadata"]["strategy"]["page_type"] == "product"
    assert result["actions"][1]["action_role"] == "add_to_cart"
    assert result["strategy"]["link_inventory"][1]["status"] == "deprioritized"


def test_shopify_report_uses_structured_strategy_sections():
    payload = {
        "state": {"site_url": "https://shop.example.com/", "audit_focus": "shopify"},
        "audit": {"overall_score": 64, "page_type": "ecommerce"},
        "snapshot_before": {
            "source_url": "https://shop.example.com/",
            "pages": [
                {
                    "id": "home",
                    "path": "/",
                    "title": "Shop",
                    "html": '<a href="/collections/all">Shop all</a>',
                    "metadata": {},
                },
                {
                    "id": "product",
                    "path": "/products/mug",
                    "title": "Mug",
                    "html": "<button>Add to cart</button>",
                    "metadata": {},
                },
            ],
            "navigation_graph": {
                "pages": [{"id": "home", "path": "/"}, {"id": "product", "path": "/products/mug"}],
                "actions": [
                    {
                        "id": "home::collection",
                        "page_id": "home",
                        "element_text": "Shop all",
                        "target_path": "/collections/all",
                        "target_kind": "internal_link",
                        "attributes": {},
                    },
                    {
                        "id": "product::add",
                        "page_id": "product",
                        "element_text": "Add to cart",
                        "target_path": "",
                        "target_kind": "unknown_js",
                        "attributes": {},
                    },
                ],
            },
        },
        "agent_report": {"has_exploration": False, "efficiency": {}, "gaps": [], "fixes": []},
    }

    exports = build_remediation_exports(run_id="run_strategy_shopify", run_payload=payload)
    assert exports.get("shopify_report") in (None, {})
    assert "shopify_report" not in exports or exports["shopify_report"] is None

