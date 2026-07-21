"""Tests for job-driven explore."""

from app.services.explore_jobs import (
    ExploreJobTracker,
    _gaps_for_job,
    build_explore_visit_urls,
    finalize_job_results,
    infer_explore_jobs,
    job_success_accessibility_note,
    merge_job_progress,
)


def test_infer_explore_jobs_portfolio_site():
    universe = {
        "pages": [
            {"page_id": "home", "path": "/"},
            {"page_id": "work", "path": "/work"},
            {"page_id": "writing", "path": "/writing"},
            {"page_id": "post", "path": "/writing/example-post"},
            {"page_id": "about", "path": "/about"},
        ],
        "actions": [],
    }
    jobs = infer_explore_jobs(universe)
    ids = {job["id"] for job in jobs}
    assert "orient" in ids
    assert "portfolio" in ids
    assert "blog" in ids
    assert "about" in ids
    assert "contact" not in ids


def test_infer_explore_jobs_about_and_contact_split():
    universe = {
        "pages": [
            {"page_id": "home", "path": "/"},
            {"page_id": "about", "path": "/about"},
            {"page_id": "contact", "path": "/contact"},
        ],
        "actions": [],
    }
    jobs = infer_explore_jobs(universe)
    ids = {job["id"] for job in jobs}
    assert "about" in ids
    assert "contact" in ids


def test_infer_explore_jobs_no_contact_from_blog_slug():
    universe = {
        "pages": [
            {"page_id": "home", "path": "/"},
            {"page_id": "post", "path": "/blog/contact-us-tips"},
        ],
        "actions": [],
    }
    jobs = infer_explore_jobs(universe)
    ids = {job["id"] for job in jobs}
    assert "contact" not in ids


def test_infer_explore_jobs_ecommerce():
    universe = {
        "pages": [
            {"page_id": "home", "path": "/"},
            {"page_id": "shop", "path": "/shop"},
            {"page_id": "product", "path": "/shop/widget", "action_count": 2},
            {"page_id": "checkout", "path": "/checkout", "action_count": 1},
        ],
        "actions": [],
    }
    audit = {"page_type": "ecommerce"}
    jobs = infer_explore_jobs(universe, audit=audit)
    ids = {job["id"] for job in jobs}
    assert "find_product" in ids
    assert "add_to_cart" in ids
    assert "checkout" in ids


def test_infer_explore_jobs_products_path_is_not_ecommerce_by_itself():
    universe = {
        "pages": [
            {"page_id": "home", "path": "/"},
            {"page_id": "products", "path": "/products", "action_count": 3},
        ],
        "actions": [
            {"page_id": "products", "label": "Chat with Gemini", "target_path": "#gemini"},
            {"page_id": "products", "label": "Explore more products", "target_path": "#more"},
        ],
    }
    audit = {"page_type": "general"}
    jobs = infer_explore_jobs(universe, audit=audit)
    ids = {job["id"] for job in jobs}
    assert "product" in ids
    assert "find_product" not in ids
    assert "add_to_cart" not in ids


def test_infer_explore_jobs_products_path_with_cart_cta_is_ecommerce():
    universe = {
        "pages": [
            {"page_id": "home", "path": "/"},
            {"page_id": "products", "path": "/products", "action_count": 3},
        ],
        "actions": [
            {"page_id": "products", "label": "Add to cart", "target_path": "/cart"},
        ],
    }
    audit = {"page_type": "general"}
    jobs = infer_explore_jobs(universe, audit=audit)
    ids = {job["id"] for job in jobs}
    assert "find_product" in ids
    assert "add_to_cart" in ids


def test_infer_explore_jobs_product_pages_from_audit():
    universe = {
        "pages": [
            {"page_id": "home", "path": "/"},
            {"page_id": "agent", "path": "/receptionist-agent", "action_count": 3},
        ],
        "actions": [],
    }
    audit = {
        "top_actions": [
            {"target_path": "./receptionist-agent", "label": "Receptionist Agent"},
        ]
    }
    jobs = infer_explore_jobs(universe, audit=audit)
    assert any(job["id"] == "product" for job in jobs)


def test_infer_explore_jobs_ecommerce_demotes_accessibility_page():
    universe = {
        "pages": [
            {"page_id": "home", "path": "/"},
            {"page_id": "accessibility", "path": "/pages/commitment-to-accessibility", "action_count": 1},
            {"page_id": "product", "path": "/products/classic-tee", "action_count": 3},
        ],
        "actions": [{"page_id": "product", "label": "Add to cart", "target_path": "/cart"}],
    }
    audit = {
        "page_type": "ecommerce",
        "top_actions": [{"target_path": "/pages/commitment-to-accessibility", "label": "Accessibility Statement"}],
    }

    jobs = infer_explore_jobs(universe, audit=audit)
    product_job = next(job for job in jobs if job["id"] == "product")

    assert "/products/classic-tee" in product_job["path_prefixes"]
    assert "/pages/commitment-to-accessibility" not in product_job["path_prefixes"]


def test_gaps_for_job_orient_does_not_collect_all_gaps():
    job = {
        "id": "orient",
        "path_prefixes": ("/",),
        "page_ids": ["home"],
    }
    gaps = [
        {"id": "g1", "page_id": "home", "selector": "a", "label": "Home"},
        {"id": "g2", "page_id": "blog", "selector": "a[href='../demo']", "label": ""},
    ]
    matched = _gaps_for_job(gaps, job)
    assert len(matched) == 1
    assert matched[0]["page_id"] == "home"


def test_finalize_job_results_from_tracker():
    jobs = [
        {
            "id": "portfolio",
            "job": "Find portfolio work",
            "goal": "Reach work",
            "path_prefixes": ("/work",),
            "page_ids": ["work"],
            "nav_keywords": ("work",),
            "require_deep_path": False,
            "require_page_view": True,
        },
        {
            "id": "blog",
            "job": "Open a blog post",
            "goal": "Read a post",
            "path_prefixes": ("/writing",),
            "page_ids": ["writing"],
            "nav_keywords": ("writing",),
            "require_deep_path": True,
            "deep_path_prefixes": ("/writing/",),
            "require_page_view": True,
        },
    ]
    tracker = ExploreJobTracker(jobs)
    tracker.record_page_view("/work")
    tracker.record_click("WORK", "/work")
    tracker.record_page_view("/writing")
    tracker.record_page_view("/writing/example-post")

    results = finalize_job_results(jobs, tracker.progress_payload(), gaps=[])
    by_id = {row["id"]: row for row in results}
    assert by_id["portfolio"]["status"] == "success"
    assert by_id["blog"]["status"] == "success"


def test_finalize_job_results_partial_with_gaps():
    jobs = [
        {
            "id": "blog",
            "job": "Open a blog post",
            "goal": "Read a post",
            "path_prefixes": ("/writing",),
            "page_ids": ["writing"],
            "nav_keywords": ("writing",),
            "require_deep_path": True,
            "deep_path_prefixes": ("/writing/",),
            "require_page_view": True,
        }
    ]
    progress = {
        "state": {
            "blog": {
                "paths": ["/writing", "/writing/example-post"],
                "clicks": [],
                "deep_reached": True,
                "attempted": True,
            }
        }
    }
    gaps = [
        {
            "page_id": "writing",
            "severity": "high",
            "impact": "missing in live tree",
            "label": "Post link",
        }
    ]
    results = finalize_job_results(jobs, progress, gaps)
    assert results[0]["status"] == "partial"
    assert "missing in live tree" in results[0]["blocker"].lower()
    assert results[0]["gap_count"] == 1
    assert results[0]["gaps"][0]["impact"] == "missing in live tree"
    assert results[0]["gaps"][0]["label"] == "Post link"


def test_infer_explore_jobs_demo_not_pricing():
    universe = {
        "pages": [
            {"page_id": "home", "path": "/"},
            {"page_id": "demo", "path": "/demo", "action_count": 0},
            {"page_id": "contact", "path": "/contact"},
        ],
        "actions": [
            {
                "label": "Book a Demo",
                "target_kind": "external_exit",
                "on_site": False,
            }
        ],
    }
    jobs = infer_explore_jobs(universe)
    ids = {job["id"] for job in jobs}
    assert "book_demo" in ids
    assert "pricing" not in ids
    demo = next(job for job in jobs if job["id"] == "book_demo")
    assert demo["job"] == "Book a demo"


def test_finalize_book_demo_click_without_page_view():
    universe = {
        "pages": [{"page_id": "demo", "path": "/demo", "action_count": 0}],
        "actions": [
            {
                "label": "Book a Demo",
                "target_kind": "external_exit",
                "on_site": False,
            }
        ],
    }
    jobs = [
        {
            "id": "book_demo",
            "job": "Book a demo",
            "goal": "Reach demo page",
            "path_prefixes": ("/demo",),
            "page_ids": ["demo"],
            "nav_keywords": ("book a demo",),
            "require_deep_path": False,
            "require_page_view": True,
        }
    ]
    progress = {
        "state": {
            "book_demo": {
                "paths": [],
                "clicks": [{"name": "Book a Demo", "path": "/demo", "success": True, "navigated": False}],
                "deep_reached": False,
                "attempted": True,
            }
        }
    }
    results = finalize_job_results(jobs, progress, gaps=[], universe=universe)
    assert results[0]["status"] == "partial"
    assert "did not load demo page" in results[0]["result"]


def test_finalize_book_demo_external_booking():
    universe = {
        "pages": [{"page_id": "demo", "path": "/demo", "action_count": 0}],
        "actions": [
            {
                "label": "Book a Demo",
                "target_kind": "external_exit",
                "on_site": False,
            }
        ],
    }
    jobs = [
        {
            "id": "book_demo",
            "job": "Book a demo",
            "goal": "Reach demo page",
            "path_prefixes": ("/demo",),
            "page_ids": ["demo"],
            "nav_keywords": ("book a demo",),
            "require_deep_path": False,
        }
    ]
    progress = {
        "state": {
            "book_demo": {
                "paths": ["/demo"],
                "clicks": [],
                "deep_reached": False,
                "attempted": True,
            }
        }
    }
    results = finalize_job_results(jobs, progress, gaps=[], universe=universe)
    assert results[0]["status"] == "partial"
    assert "leaves site" in results[0]["blocker"]


def test_finalize_contact_external_flow():
    universe = {
        "pages": [{"page_id": "contact", "path": "/contact", "action_count": 2}],
        "actions": [
            {
                "page_id": "contact",
                "label": "Book a Demo",
                "target_kind": "external_exit",
                "on_site": False,
            }
        ],
    }
    jobs = [
        {
            "id": "contact",
            "job": "Contact / hire",
            "goal": "Reach contact",
            "path_prefixes": ("/contact",),
            "page_ids": ["contact"],
            "nav_keywords": ("contact",),
            "require_page_view": True,
        }
    ]
    progress = {
        "state": {
            "contact": {
                "paths": ["/contact"],
                "clicks": [],
                "deep_reached": False,
                "attempted": True,
            }
        }
    }
    results = finalize_job_results(jobs, progress, gaps=[], universe=universe)
    assert results[0]["status"] == "partial"
    assert "leaves site" in results[0]["blocker"]


def test_build_explore_visit_urls_caps_archives():
    universe = {
        "discovered_internal_urls": [
            "https://example.com/",
            "https://example.com/contact",
            "https://example.com/demo",
            "https://example.com/blog/post-1",
            "https://example.com/blog/post-2",
            "https://example.com/blog/post-3",
            "https://example.com/docs/page-1",
            "https://example.com/docs/page-2",
            "https://example.com/docs/page-3",
        ],
    }
    jobs = [
        {"path_prefixes": ("/contact",)},
        {"path_prefixes": ("/demo",)},
    ]
    urls = build_explore_visit_urls("https://example.com/", universe, jobs, max_pages=20, max_archive_deep=2)
    blog_urls = [u for u in urls if "/blog/" in u]
    doc_urls = [u for u in urls if "/docs/" in u]
    assert len(blog_urls) <= 2
    assert len(doc_urls) <= 2
    assert urls[0] == "https://example.com/"
    assert any("/contact" in u for u in urls[:5])
    assert any("/demo" in u for u in urls[:5])


def test_build_explore_visit_urls_prioritizes_revenue_paths_for_shopify():
    universe = {
        "strategy": {"name": "shopify"},
        "discovered_internal_urls": [
            "https://shop.example.com/pages/commitment-to-accessibility",
            "https://shop.example.com/collections/all",
            "https://shop.example.com/products/classic-tee",
            "https://shop.example.com/cart",
        ],
    }
    jobs = [{"path_prefixes": ("/products", "/collections")}]

    urls = build_explore_visit_urls("https://shop.example.com/", universe, jobs, max_pages=10)

    assert urls[1] == "https://shop.example.com/products/classic-tee"
    assert urls[2] in {
        "https://shop.example.com/cart",
        "https://shop.example.com/collections/all",
    }
    assert urls[-1] == "https://shop.example.com/pages/commitment-to-accessibility"


def test_merge_job_progress_migrates_pricing_to_book_demo():
    jobs = [
        {
            "id": "book_demo",
            "path_prefixes": ("/demo",),
            "page_ids": ["demo"],
        }
    ]
    stored = {
        "state": {
            "pricing": {
                "paths": ["/demo"],
                "clicks": [{"name": "Book a Demo", "path": "/demo", "success": True}],
                "deep_reached": False,
                "attempted": True,
            }
        }
    }
    merged = merge_job_progress(jobs, stored)
    assert merged["state"]["book_demo"]["paths"] == ["/demo"]
    assert merged["state"]["book_demo"]["attempted"] is True


def test_job_success_accessibility_note():
    note = job_success_accessibility_note(
        [{"status": "success"}, {"status": "success"}],
        0.0,
    )
    assert note is not None
    assert "accessibility" in note.lower()
