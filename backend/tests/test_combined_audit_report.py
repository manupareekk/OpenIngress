from app.services.combined_audit_report import build_combined_audit_report, combine_audit_states


def test_combined_state_does_not_reach_100_until_both_audits_complete():
    state = combine_audit_states(
        {"status": "completed", "progress_pct": 100, "progress": "Agent navigability scan complete"},
        {"status": "running", "progress_pct": 50, "progress": "Crawl complete"},
    )

    assert state["status"] == "running"
    assert state["progress_pct"] == 75
    assert state["progress"] == "Generating report..."

    completed = combine_audit_states(
        {"status": "completed", "progress_pct": 100},
        {"status": "completed", "progress_pct": 100},
    )

    assert completed["status"] == "completed"
    assert completed["progress_pct"] == 100


def test_combined_report_uses_playwright_summary_when_codex_inconclusive():
    codex = {
        "url": "https://example.com",
        "score": 0,
        "verdict": "inconclusive",
        "confidence": "low",
        "executive_summary": "Without the rendered page state, there is insufficient evidence.",
        "recommended_fixes": [
            {
                "priority": "high",
                "title": "Provide SSR critical structure",
                "detail": "Static-only recommendation.",
            }
        ],
    }
    playwright = {
        "audit": {"overall_score": 100},
        "exports": {
            "verdict": "agent-ready",
            "business_summary": ["Agents can navigate most primary flows on this site."],
            "skill_md": "# Existing remediation skill\n\nFix the rendered gaps.",
            "llms_txt": "# Example\n",
            "report_md": "# Rendered report\n\nAgents complete the path.",
        },
        "agent_report": {
            "fixes": [
                {
                    "priority": "medium",
                    "title": "Add llms.txt",
                    "detail": "Expose machine-readable site guidance.",
                }
            ]
        },
    }

    report = build_combined_audit_report(codex, playwright)

    assert report["scores"]["codex"] is None
    assert report["scores"]["playwright"] == 100
    assert report["score"] == 100
    assert report["verdict"] == "Agent ready"
    assert report["assessment"]["basis"].startswith("Weighted from rendered")
    assert report["metrics"][0] == {"label": "Agent readiness", "value": "100/100"}
    assert report["summary"][0].startswith("Codex static inspection was inconclusive")
    assert "insufficient evidence" not in " ".join(report["summary"])
    assert report["fixes"] == [
        {
            "source": "playwright",
            "priority": "medium",
            "title": "Add llms.txt",
            "detail": "Expose machine-readable site guidance.",
        }
    ]
    assert report["artifact"]["title"] == "Combined agent readiness artifact"
    assert "Rendered-browser audit" in report["artifact"]["report_md"]
    assert "Existing remediation skill" in report["artifact"]["skill_md"]
    assert "Codex semantic note" in report["artifact"]["skill_md"]
    assert report["artifact"]["llms_txt"] == "# Example\n"
    assert report["score_explanation"]["headline"]
    assert report["score_explanation"]["score_pressure"]
    assert report["improvement_forecast"]["headline"]
    assert len(report["improvement_forecast"]["items"]) == 3


def test_combined_report_omits_commerce_packaging():
    contract = {
        "artifact_type": "commerce_contract",
        "score": 69,
        "step_results": [{"id": "checkout_handoff", "status": "blocked"}],
    }
    report = build_combined_audit_report(
        {"url": "https://shop.example.com", "score": 70, "verdict": "fragile", "confidence": "medium"},
        {
            "audit": {"overall_score": 70},
            "agent_report": {"efficiency": {"actions_lost_percent": 20, "gap_count": 1}},
            "exports": {
                "commerce_contract": contract,
                "shopify_report": {"shopper_funnel": []},
            },
        },
    )

    assert "commerce_contract" not in report
    assert "shopify_report" not in report
    assert "AI shopper" not in (report.get("artifact") or {}).get("report_md", "")



def test_combined_report_weights_rendered_and_semantic_evidence():
    codex = {
        "url": "https://example.com",
        "score": 76,
        "verdict": "mostly-navigable",
        "confidence": "medium",
        "executive_summary": "Static inspection found a fragile accordion.",
        "what_agents_can_do": ["Open primary navigation links."],
        "blockers": [
            {
                "title": "Clickable div",
                "detail": "A row is clickable but not a button.",
            }
        ],
        "recommended_fixes": [
            {
                "priority": "high",
                "title": "Use a real button",
                "detail": "Expose role, name, and expanded state.",
            }
        ],
    }
    playwright = {
        "audit": {
            "overall_score": 100,
            "coverage": {"accessible_actions": 3, "total_actions": 3, "action_accessibility_percent": 100},
        },
        "agent_report": {
            "efficiency": {"actions_lost_percent": 0, "gap_count": 1},
            "job_results": [{"job": "Open docs", "status": "success", "result": "reached /docs"}],
        },
        "exports": {"verdict": "Agents completed the rendered path."},
    }

    report = build_combined_audit_report(codex, playwright)

    assert report["score"] == 96
    assert report["verdict"] == "Agent ready"
    assert report["confidence"] == "high"
    assert report["assessment"]["basis"].startswith("Weighted from rendered")
    assert report["assessment"]["components"][0]["label"] == "Rendered task performance"
    assert "Reached 3/3" in report["access"]["reached"][0]
    assert "A row is clickable" in report["access"]["missed"][0]


def test_low_combined_score_uses_not_ready_verdict():
    report = build_combined_audit_report(
        {"url": "https://example.com", "score": 89, "verdict": "agent-ready", "confidence": "high"},
        {
            "audit": {
                "overall_score": 31.6,
                "agent_accessibility_score": 0,
                "agent_speed_score": 100,
                "coverage": {"action_accessibility_percent": 0},
            },
            "agent_report": {
                "efficiency": {"actions_lost_percent": 100, "step_waste_percent": 0, "gap_count": 1},
                "gaps": [{"type": "llms_txt", "severity": "high", "impact": "llms missing"}],
                "job_results": [{"id": "orient", "job": "Orient on homepage", "status": "success", "result": "reached /"}],
            },
        },
    )

    assert report["score"] == 45
    assert report["verdict"] == "Not ready"
    assert "agent reach" in report["score_explanation"]["score_pressure"].lower()
    assert report["improvement_forecast"]["projected_score"] >= report["score"]
    assert report["improvement_forecast"]["projected_score_lift_percent"] > 0


def test_combined_report_builds_evidence_tiered_actions():
    codex = {"url": "https://example.com", "score": 72, "verdict": "fragile", "confidence": "medium"}
    playwright = {
        "audit": {
            "overall_score": 78,
            "page_type": "marketing",
            "top_actions": [
                {"label": "See pricing", "target_path": "/pricing"},
                {"label": "Start trial", "target_path": "/signup"},
            ],
            "coverage": {"accessible_actions": 2, "total_actions": 3, "action_accessibility_percent": 66.7},
        },
        "agent_report": {
            "efficiency": {"actions_lost_percent": 33.3, "gap_count": 1},
            "explore_jobs": [
                {
                    "id": "product",
                    "job": "Explore product offer",
                    "goal": "Reach a primary product or feature page and confirm it is agent-navigable.",
                    "path_prefixes": ("/product", "/features"),
                    "nav_keywords": ("product", "feature", "learn more"),
                },
                {
                    "id": "pricing",
                    "job": "View pricing",
                    "goal": "Reach pricing/plans and confirm offer details are agent-navigable.",
                    "path_prefixes": ("/pricing",),
                    "nav_keywords": ("pricing", "plans", "see pricing"),
                },
                {
                    "id": "about",
                    "job": "Reach about",
                    "goal": "Reach the about/company page and confirm company info is agent-navigable.",
                    "path_prefixes": ("/about",),
                    "nav_keywords": ("about",),
                },
            ],
            "job_results": [
                {
                    "id": "product",
                    "job": "Explore product offer",
                    "status": "partial",
                    "result": "partial activation",
                    "blocker": "could not fully complete job",
                    "goal": "Reach a primary product or feature page and confirm it is agent-navigable.",
                }
            ],
        },
        "exports": {"verdict": "fragile"},
    }

    report = build_combined_audit_report(codex, playwright)
    evidence = report["action_evidence"]

    assert evidence["validated_actions"][0]["title"] == "Reach a product or feature page"
    assert evidence["validated_actions"][0]["status"] == "partial"
    assert evidence["business_actions"][0]["title"] == "View pricing or plans"
    assert evidence["business_actions"][0]["confidence"] == "high"
    assert evidence["business_actions"][0]["basis_inline"].startswith('Inferred from /pricing and CTA labels "See pricing"')
    assert all(item["title"] != "Explore product offer" for item in evidence["business_actions"])
    assert any(item["title"] == "Reach the company or about page" for item in evidence["possible_journeys"])
    assert report["insights"]["wins"][1]["title"] == "Reach a product or feature page"


def test_combined_report_keeps_weak_single_signal_product_guess_collapsed():
    report = build_combined_audit_report(
        {"url": "https://example.com"},
        {
            "audit": {
                "overall_score": 60,
                "page_type": "general",
                "top_actions": [{"label": "Learn more", "target_path": "/agent"}],
            },
            "agent_report": {
                "explore_jobs": [
                    {
                        "id": "product",
                        "job": "Explore product offer",
                        "goal": "Reach a primary product or feature page and confirm it is agent-navigable.",
                        "path_prefixes": ("/agent",),
                        "nav_keywords": ("learn more", "agent"),
                    }
                ],
                "job_results": [],
            },
        },
    )

    evidence = report["action_evidence"]

    assert evidence["business_actions"] == []
    assert evidence["possible_journeys"][0]["title"] == "Reach a product or feature page"
    assert evidence["possible_journeys"][0]["confidence"] in {"low", "medium"}
    assert evidence["possible_journeys"][0]["basis_inline"].startswith("Inferred from /agent")


def test_combined_report_omits_shopify_report_when_exports_omit_it():
    report = build_combined_audit_report(
        {"url": "https://shop.example.com", "score": 80},
        {
            "audit": {"overall_score": 72, "page_type": "ecommerce"},
            "exports": {"report_md": "# Agent report"},
            "agent_report": {"efficiency": {"gap_count": 1}},
        },
    )

    assert not report.get("shopify_report")
    assert "AI shopper funnel" not in (report.get("artifact") or {}).get("report_md", "")


def test_business_dashboard_estimates_risk_for_partial_b2b_conversion_path():
    report = build_combined_audit_report(
        {"url": "https://b2b.example.com", "score": 70, "verdict": "fragile", "confidence": "medium"},
        {
            "audit": {
                "overall_score": 72,
                "page_type": "marketing",
                "coverage": {"action_accessibility_percent": 66},
            },
            "agent_report": {
                "efficiency": {"actions_lost_percent": 34, "step_waste_percent": 20},
                "job_results": [
                    {"id": "product", "job": "Explore product", "status": "success", "result": "reached /product"},
                    {"id": "pricing", "job": "View pricing", "status": "partial", "result": "saw pricing CTA"},
                    {"id": "book_demo", "job": "Book demo", "status": "partial", "result": "scheduler opened", "blocker": "scheduler handoff not validated"},
                ],
            },
        },
    )

    dashboard = report["business_dashboard"]

    assert dashboard["revenue_at_risk_percent"] > 0
    assert dashboard["risk_label"] in {"Moderate", "High", "Critical"}
    assert dashboard["headline"].endswith("estimated agent path loss")
    assert [row["id"] for row in dashboard["funnel"]] == ["discover", "evaluate", "convert", "handoff", "recover"]
    assert any(row["id"] == "convert" and row["status"] == "partial" for row in dashboard["funnel"])
    assert "Business funnel dashboard" in report["artifact"]["report_md"]


def test_business_dashboard_reports_low_risk_when_business_paths_succeed():
    report = build_combined_audit_report(
        {"url": "https://ready.example.com", "score": 95, "verdict": "agent-ready", "confidence": "high"},
        {
            "audit": {
                "overall_score": 96,
                "page_type": "marketing",
                "coverage": {"action_accessibility_percent": 100},
            },
            "agent_report": {
                "efficiency": {"actions_lost_percent": 0, "step_waste_percent": 0},
                "job_results": [
                    {"id": "product", "job": "Explore product", "status": "success", "result": "reached /product"},
                    {"id": "pricing", "job": "View pricing", "status": "success", "result": "reached /pricing"},
                    {"id": "book_demo", "job": "Book demo", "status": "success", "result": "demo form reached"},
                    {"id": "contact", "job": "Find contact", "status": "success", "result": "contact path reached"},
                ],
            },
        },
    )

    dashboard = report["business_dashboard"]

    assert dashboard["revenue_at_risk_percent"] == 0
    assert dashboard["risk_label"] == "Low"
    assert all(row["status"] == "success" for row in dashboard["funnel"])


def test_business_dashboard_marks_missing_conversion_evidence_as_critical():
    report = build_combined_audit_report(
        {"url": "https://blocked.example.com", "score": 20, "verdict": "not-ready", "confidence": "medium"},
        {
            "audit": {"overall_score": 20, "coverage": {"action_accessibility_percent": 0}},
            "agent_report": {
                "efficiency": {"actions_lost_percent": 100, "step_waste_percent": 80},
                "job_results": [],
            },
        },
    )

    dashboard = report["business_dashboard"]

    assert dashboard["revenue_at_risk_percent"] == 100
    assert dashboard["risk_label"] == "Critical"
    assert any(row["status"] == "not_detected" for row in dashboard["funnel"])


def test_business_dashboard_ignores_shopify_funnel_packaging():
    shopify_report = {
        "shopper_funnel": [
            {"id": "homepage", "label": "Homepage", "status": "success", "evidence": "home reached"},
            {
                "id": "checkout_handoff",
                "label": "Checkout handoff",
                "status": "blocked",
                "evidence": "checkout hidden",
                "blocker": "cart drawer checkout hidden",
            },
        ],
        "revenue_blockers": [{"buyer_step": "Checkout handoff", "merchant_summary": "AI shoppers cannot reach checkout."}],
    }

    report = build_combined_audit_report(
        {"url": "https://shop.example.com", "score": 80},
        {
            "audit": {"overall_score": 72, "page_type": "ecommerce"},
            "exports": {"shopify_report": shopify_report},
            "agent_report": {"efficiency": {"step_waste_percent": 5}},
        },
    )

    dashboard = report["business_dashboard"]
    assert "shopify_report" not in report
    funnel_ids = {row.get("id") for row in dashboard.get("funnel") or []}
    assert "checkout_handoff" not in funnel_ids
    assert "homepage" not in funnel_ids
    assert "agent path loss" in str(dashboard.get("headline") or "").lower()



def test_business_dashboard_handles_missing_evidence_without_crashing():
    report = build_combined_audit_report({}, {})

    dashboard = report["business_dashboard"]

    assert dashboard["revenue_at_risk_percent"] == 100
    assert dashboard["confidence"] == "low"
    assert len(dashboard["funnel"]) == 5
    assert len(dashboard["health_kpis"]) >= 4
