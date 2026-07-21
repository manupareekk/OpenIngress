"""Tests for remediation export builder."""

from app.services.remediation_export import build_remediation_exports


def test_build_remediation_exports_crawl_only():
    payload = {
        "state": {
            "run_id": "run_test123",
            "site_url": "https://www.manupareek.com/",
            "status": "failed",
            "error": "Cancelled by user",
        },
        "audit": {
            "overall_score": 80.6,
            "agent_accessibility_score": 75.76,
            "agent_speed_score": 91.9,
            "headline": "Manu Pareek",
            "recommendations": [
                "Static check failed: llms.txt at domain root — Missing https://manupareek.com/llms.txt"
            ],
            "coverage": {"action_accessibility_percent": 75.76, "blocked_actions": 0},
            "speed_summary": {"score": 91.9, "html_bytes": 293251, "page_count": 11},
        },
        "snapshot_before": {
            "source_url": "https://www.manupareek.com/",
            "pages": [{"path": "/"}, {"path": "/work"}, {"path": "/writing"}],
            "static_audits": {
                "checks": [
                    {
                        "id": "llms-txt",
                        "title": "llms.txt at domain root",
                        "passed": False,
                        "detail": "Missing https://manupareek.com/llms.txt",
                    }
                ]
            },
        },
    }

    exports = build_remediation_exports(run_id="run_test123", run_payload=payload)

    assert exports["skill_name"] == "fix-manupareek-com-agent-gaps"
    assert "llms.txt" in exports["skill_md"]
    assert exports["llms_txt"].startswith("# Manu Pareek")
    assert any(c["status"] == "fail" for c in exports["checks"])
    assert exports["fixes"]
    assert "crawl only" in exports["verdict"].lower() or "80" in exports["verdict"]
    explore_checks = [c for c in exports["checks"] if c.get("group") == "explore"]
    assert len(explore_checks) == 1
    assert explore_checks[0]["status"] == "warn"


def test_explore_check_warns_on_gaps():
    payload = {
        "state": {"site_url": "https://example.com/"},
        "audit": {"overall_score": 82, "agent_accessibility_score": 90, "agent_speed_score": 88},
        "agent_report": {
            "has_exploration": True,
            "efficiency": {
                "actions_lost_percent": 3.6,
                "step_waste_percent": 77.5,
                "gap_count": 4,
                "high_gaps": 2,
                "critical_gaps": 0,
            },
            "gaps": [{}, {}, {}, {}],
        },
    }

    exports = build_remediation_exports(run_id="run_gap", run_payload=payload)
    explore = next(c for c in exports["checks"] if c["id"] == "agent-activation")
    assert explore["status"] == "warn"
    assert "4 gap" in explore["detail"]


def test_actionable_exports():
    payload = {
        "state": {"site_url": "https://www.manupareek.com/", "run_id": "run_new"},
        "audit": {
            "overall_score": 81,
            "agent_accessibility_score": 76,
            "agent_speed_score": 92,
        },
        "events": [
            {"action": "VIEW_PAGE", "metadata": {"path": "/work"}},
            {"action": "CLICK", "element_name": "WORK", "success": True},
        ],
        "agent_report": {
            "has_exploration": True,
            "findings": [{"kind": "action", "text": 'Activated link "WORK".'}],
            "efficiency": {"actions_lost_percent": 4, "step_waste_percent": 65, "gap_count": 2},
            "gaps": [
                {
                    "id": "g1",
                    "severity": "high",
                    "type": "catalog_not_activated",
                    "page_id": "writing",
                    "label": "Blog post",
                    "selector": 'a[href="/writing/post"]',
                    "impact": "missing from live tree",
                }
            ],
            "fixes": [
                {
                    "priority": "high",
                    "gap_type": "catalog_not_activated",
                    "label": "Blog post",
                    "selector": 'a[href="/writing/post"]',
                    "page_id": "writing",
                    "change": "Ensure link is visible in live tree.",
                }
            ],
        },
    }
    prior = {"run_id": "run_old", "created_at": "2026-01-01T00:00:00Z", "overall_score": 75, "gap_count": 4}

    exports = build_remediation_exports(run_id="run_new", run_payload=payload, prior_run=prior)

    assert exports["business_summary"]
    assert any(
        "on-site" in line.lower() or "never reached" in line.lower() or "missed" in line.lower()
        for line in exports["business_summary"]
    )
    assert exports["user_journeys"]
    assert exports["cursor_prompt"]
    assert "run_new" in exports["cursor_prompt"]
    assert exports["github_issue_md"]
    assert exports["reaudit_diff"]["gaps_closed"] == 2
    assert exports["fixes"][0].get("patch")


def test_skill_md_uses_gap_taxonomy_rules():
    payload = {
        "state": {"site_url": "https://www.manupareek.com/"},
        "audit": {"overall_score": 81, "agent_accessibility_score": 76, "agent_speed_score": 92},
        "agent_report": {
            "has_exploration": True,
            "gap_sections": {"explore_activation": [{"type": "catalog_not_activated", "severity": "medium", "label": "Post"}]},
            "fixes": [
                {
                    "priority": "high",
                    "gap_type": "name_unmatchable",
                    "fix_scope": "site",
                    "label": "Post title",
                    "change": 'Set aria-label="Post title" on the post link.',
                },
                {
                    "priority": "low",
                    "gap_type": "catalog_not_activated",
                    "fix_scope": "product",
                    "label": "Post",
                    "change": "Increase explore step budget (product).",
                },
            ],
        },
    }
    exports = build_remediation_exports(run_id="run_skill", run_payload=payload)
    skill = exports["skill_md"]
    assert "name_unmatchable" in skill
    assert "Do NOT" in skill
    assert "Post title" in skill
    assert "Explorer / product" in skill
    assert "generic accessible name" in skill.lower()
    site_block = skill.split("## Site changes only")[1].split("## Explorer")[0]
    assert "Increase explore step budget" not in site_block
    assert "Increase explore step budget" in skill


def test_shopify_report_sections_and_exports():
    payload = {
        "state": {
            "site_url": "https://shop.example.com/",
            "audit_focus": "shopify",
            "commerce_inputs": {
                "monthly_sessions": 50000,
                "average_order_value": 85,
                "conversion_rate": 2.4,
                "agent_traffic_share": 5,
            },
        },
        "audit": {
            "overall_score": 62,
            "agent_accessibility_score": 58,
            "agent_speed_score": 74,
            "page_type": "ecommerce",
            "coverage": {"action_accessibility_percent": 58, "blocked_actions": 3},
            "speed_summary": {"score": 74, "html_bytes": 360000, "page_count": 6},
        },
        "snapshot_before": {
            "source_url": "https://shop.example.com/",
            "strategy": {
                "name": "shopify",
                "confidence": "high",
                "high_value_skipped_links": [
                    {
                        "label": "All products",
                        "path": "/collections/all",
                        "source_path": "/",
                        "reason": "not_selected_within_crawl_budget",
                        "priority": 86,
                    }
                ],
            },
            "pages": [
                {
                    "path": "/products/classic-tee",
                    "html": (
                        '<script type="application/ld+json">{"@type":"Product","name":"Classic Tee"}</script>'
                        '<button class="drawer-checkout">Checkout</button>'
                    ),
                },
                {"path": "/collections/all", "html": "<a>Classic Tee</a>"},
            ],
            "static_audits": {
                "checks": [
                    {
                        "id": "llms-txt",
                        "title": "llms.txt at domain root",
                        "passed": False,
                        "detail": "Missing llms.txt",
                    }
                ]
            },
        },
        "agent_report": {
            "has_exploration": True,
            "efficiency": {
                "actions_lost_percent": 42,
                "step_waste_percent": 31,
                "gap_count": 4,
                "high_gaps": 2,
                "crawler_quality": {
                    "product_page_hit_rate": 100.0,
                    "collection_page_hit_rate": 50.0,
                    "add_to_cart_probe_success_rate": 0.0,
                    "cart_visibility_rate": 100.0,
                    "checkout_handoff_validation_rate": 0.0,
                    "top_funnel_evidence_rate": 66.7,
                },
            },
            "job_results": [
                {"id": "orient", "job": "Orient on homepage", "status": "success", "result": "reached /"},
                {"id": "find_product", "job": "Find a product", "status": "success", "result": "reached /products/classic-tee"},
                {
                    "id": "add_to_cart",
                    "job": "Add to cart",
                    "status": "partial",
                    "result": "clicked Add to cart",
                    "blocker": "cart drawer checkout hidden",
                },
                {
                    "id": "checkout",
                    "job": "Reach checkout",
                    "status": "failed",
                    "result": "not attempted",
                    "blocker": "checkout handoff hidden by cart drawer",
                },
            ],
            "gaps": [
                {
                    "severity": "high",
                    "type": "client_only",
                    "page_id": "product",
                    "label": "Size swatch",
                    "impact": "variant size swatch is client-only",
                },
                {
                    "severity": "medium",
                    "type": "client_only",
                    "page_id": "cart",
                    "label": "Newsletter popup",
                    "impact": "popup obscures checkout",
                },
            ],
            "fixes": [
                {
                    "priority": "high",
                    "gap_type": "client_only",
                    "label": "Checkout",
                    "selector": 'button[name="checkout"]',
                    "change": "Cart drawer checkout is hidden behind a popup; expose a named checkout button.",
                },
                {
                    "priority": "high",
                    "gap_type": "client_only",
                    "label": "Add to cart",
                    "selector": 'button[name="add"]',
                    "change": "Add to cart button is JS-only; wire it to the product form and expose state.",
                },
                {
                    "priority": "medium",
                    "gap_type": "catalog_not_activated",
                    "label": "Accessibility Statement",
                    "selector": 'a[title="Accessibility Statement"]',
                    "change": "[product][catalog_not_activated] Accessibility Statement — present in static HTML but not activated. Improve explorer matching and step budget.",
                },
                {
                    "priority": "medium",
                    "gap_type": "catalog_not_activated",
                    "label": "Skip to content",
                    "selector": 'a[title="Skip to content"]',
                    "change": "[product][catalog_not_activated] Skip to content — present in static HTML but not activated. Improve explorer matching and step budget.",
                },
            ],
        },
    }
    prior = {"run_id": "old", "overall_score": 51, "gap_count": 7}

    exports = build_remediation_exports(run_id="run_shopify", run_payload=payload, prior_run=prior)

    # Product packaging hard-cut: Shopify/commerce report is never attached.
    assert exports.get("shopify_report") in (None, {})
    assert "shopify_report" not in exports or exports["shopify_report"] is None
    assert "commerce_contract" not in exports
    assert exports.get("checks")
    assert exports.get("report_md")
    assert "AI shopper" not in (exports.get("report_md") or "")
    assert "AI shopper" not in (exports.get("github_issue_md") or "")


def test_shopify_report_successful_checkout_handoff():
    payload = {
        "state": {"site_url": "https://shop.example.com/", "audit_focus": "shopify"},
        "audit": {"overall_score": 91, "agent_accessibility_score": 94, "agent_speed_score": 86, "page_type": "ecommerce"},
        "agent_report": {
            "has_exploration": True,
            "efficiency": {"actions_lost_percent": 0, "step_waste_percent": 4, "gap_count": 0},
            "job_results": [
                {"id": "orient", "job": "Orient on homepage", "status": "success", "result": "reached /"},
                {"id": "find_product", "job": "Find a product", "status": "success", "result": "reached /products/mug"},
                {"id": "add_to_cart", "job": "Add to cart", "status": "success", "result": "clicked Add to cart"},
                {"id": "checkout", "job": "Reach checkout", "status": "success", "result": "reached /checkout"},
            ],
        },
    }

    exports = build_remediation_exports(run_id="run_shopify_pass", run_payload=payload)
    assert exports.get("shopify_report") in (None, {})
    assert "shopify_report" not in exports or exports["shopify_report"] is None
    assert "commerce_contract" not in exports


def test_shopify_funnel_backfills_missing_steps_from_strategy_coverage():
    payload = {
        "state": {"site_url": "https://shop.example.com/", "audit_focus": "shopify"},
        "audit": {"overall_score": 55, "page_type": "ecommerce"},
        "snapshot_before": {
            "source_url": "https://shop.example.com/",
            "strategy": {
                "name": "shopify",
                "page_segments": [
                    {"page_id": "home", "page_type": "homepage", "path": "/"},
                    {"page_id": "product", "page_type": "product", "path": "/products/mug"},
                ],
                "action_segments": [
                    {
                        "action_id": "home::product",
                        "page_id": "home",
                        "action_role": "product_link",
                        "target_path": "/products/mug",
                        "path": "/",
                        "label": "Classic mug",
                    }
                ],
                "link_inventory": [
                    {
                        "source_page_id": "home",
                        "source_path": "/",
                        "label": "Classic mug",
                        "href": "/products/mug",
                        "resolved_url": "https://shop.example.com/products/mug",
                        "path": "/products/mug",
                        "external": False,
                        "status": "followed",
                        "reason": "",
                    }
                ],
                "link_inventory_stats": {
                    "total": 1,
                    "followed": 1,
                    "skipped": 0,
                    "deprioritized": 0,
                    "external": 0,
                },
                "scores": {
                    "funnel_steps": [
                        {"id": "homepage", "label": "Homepage", "status": "pass", "weight": 8},
                        {"id": "collection_search", "label": "Collection/search", "status": "not_detected", "weight": 14},
                        {"id": "product_page", "label": "Product page", "status": "pass", "weight": 18},
                        {"id": "variant_selection", "label": "Variant selection", "status": "not_detected", "weight": 14},
                        {"id": "add_to_cart", "label": "Add to cart", "status": "partial", "weight": 18},
                        {"id": "cart", "label": "Cart drawer or cart page", "status": "not_detected", "weight": 14},
                        {"id": "checkout_handoff", "label": "Checkout handoff", "status": "not_detected", "weight": 14},
                    ]
                },
            }
        },
        "agent_report": {
            "has_exploration": True,
            "job_results": [
                {"id": "orient", "job": "Orient on homepage", "status": "success", "result": "reached /"},
                {"id": "product", "job": "Explore product offer", "status": "partial", "result": "reached /products/mug"},
            ],
            "gaps": [],
            "fixes": [],
        },
    }

    exports = build_remediation_exports(run_id="run_shopify_backfill", run_payload=payload)
    assert exports.get("shopify_report") in (None, {})
    assert "shopify_report" not in exports or exports["shopify_report"] is None


def test_shopify_funnel_prefers_probe_results_over_inference():
    payload = {
        "state": {"site_url": "https://shop.example.com/", "audit_focus": "shopify"},
        "audit": {"overall_score": 61, "page_type": "ecommerce"},
        "exploration": {
            "strategy_probe_results": [
                {
                    "step_id": "add_to_cart",
                    "status": "pass",
                    "evidence": "Probe clicked add-to-cart and observed cart/checkout state in the hydrated DOM.",
                    "interaction": {"clicked": True, "navigated": False, "error": ""},
                },
                {
                    "step_id": "checkout_handoff",
                    "status": "partial",
                    "evidence": "Probe found checkout visibility, but handoff was not validated end-to-end.",
                    "interaction": {"clicked": True, "navigated": False, "error": ""},
                },
            ]
        },
        "agent_report": {
            "has_exploration": True,
            "job_results": [
                {"id": "orient", "job": "Orient on homepage", "status": "success", "result": "reached /"},
                {"id": "product", "job": "Explore product offer", "status": "partial", "result": "reached /products/mug"},
            ],
            "gaps": [],
            "fixes": [],
        },
    }

    exports = build_remediation_exports(run_id="run_shopify_probe", run_payload=payload)
    assert exports.get("shopify_report") in (None, {})
    assert "shopify_report" not in exports or exports["shopify_report"] is None
