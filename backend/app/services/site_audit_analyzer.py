"""Score agent accessibility, speed, and operability gaps for an imported site."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .agent_readiness_score import compute_overall_agent_score
from .selector_utils import selector_matches_html
from .variant_html import summarize_variant_html

AUTH_PATH_HINTS = ("login", "log-in", "signin", "sign-in", "auth", "account")


@dataclass
class ActionCandidate:
    selector: str
    label: str
    score: float
    reason: str
    target_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SiteAudit:
    page_type: str = "general"
    headline: str = ""
    audit_focus: str = "Maximize agent accessibility and speed."
    agent_accessibility_score: float = 0.0
    agent_speed_score: float = 0.0
    overall_score: float = 0.0
    crawl_base_score: float = 0.0
    score_breakdown: Dict[str, Any] = field(default_factory=dict)
    score_methodology: str = ""
    speed_summary: Dict[str, Any] = field(default_factory=dict)
    speed_findings: List[str] = field(default_factory=list)
    top_action_label: str = ""
    top_action_selector: str = ""
    confidence: float = 0.5
    rationale: List[str] = field(default_factory=list)
    secondary_signals: List[str] = field(default_factory=list)
    funnel_summary: str = ""
    top_actions: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    probe_tasks: List[Dict[str, Any]] = field(default_factory=list)
    static_audit_summary: Dict[str, Any] = field(default_factory=dict)
    coverage: Dict[str, Any] = field(default_factory=dict)
    navigation_issues: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SiteAuditAnalyzer:
    def analyze(
        self,
        *,
        imported: Dict[str, Any],
        navigation_graph: Dict[str, Any],
        coverage: Dict[str, Any],
        static_audits: Dict[str, Any],
        phase: str = "site",
    ) -> SiteAudit:
        start = _start_page(imported)
        html = str(start.get("html") or imported.get("html") or "")
        if not html.strip():
            return SiteAudit(
                page_type="unknown",
                headline=str(imported.get("title") or "this site"),
                audit_focus="Could not analyze accessibility or speed because no HTML was captured.",
                rationale=[
                    "The crawl returned empty page content.",
                    "Try a public URL, disable bot protection, or check that Playwright is installed.",
                ],
                recommendations=[
                    "Ensure the URL is reachable without login.",
                    "If the site blocks bots, allow automation or use a staging URL.",
                ],
                coverage=coverage,
            )

        summary = summarize_variant_html(html)
        if start.get("metadata", {}).get("summary"):
            summary = {**summary, **dict(start["metadata"]["summary"])}

        graph = navigation_graph or {}
        candidates = _rank_candidates(summary, graph, html, imported.get("elements") or [])
        page_type = _detect_page_type(summary, html, graph)
        headline = str(summary.get("headline") or imported.get("title") or "this site").strip()
        top = candidates[0] if candidates else None
        success_label = top.label if top else ""
        success_selector = top.selector if top else ""
        speed_summary, speed_findings = _speed_assessment(imported, graph, html)
        accessibility_score = float(coverage.get("action_accessibility_percent") or 0)
        speed_score = float(speed_summary.get("score") or 0)
        scored = compute_overall_agent_score(
            agent_accessibility_score=accessibility_score,
            agent_speed_score=speed_score,
            static_audits=static_audits,
        )
        overall_score = float(scored["overall_score"])
        crawl_base_score = float(scored.get("crawl_base_score") or 0)
        score_breakdown = scored.get("score_breakdown") or {}
        score_methodology = str(scored.get("score_methodology") or "")

        rationale = [
            f"Page type: {page_type.replace('_', ' ')}.",
            f"Agent accessibility score: {accessibility_score}%.",
            f"Agent speed score: {speed_score}%.",
            f"Overall agent score: {overall_score}/100 (crawl base {crawl_base_score}).",
        ]
        if top:
            rationale.append(f'Top action to preserve while optimizing: "{top.label}" ({top.reason}).')

        funnel_summary, secondary = _funnel_insights(imported, graph)
        if funnel_summary:
            rationale.append(funnel_summary)

        recommendations = _build_recommendations(coverage, graph, static_audits, candidates, speed_findings)
        tasks = _infer_operator_tasks(top, success_label)

        confidence = _confidence(candidates, page_type, coverage)

        nav_issues = [
            {
                "page_id": issue.get("page_id"),
                "label": issue.get("label") or issue.get("action_label"),
                "selector": issue.get("selector"),
                "code": issue.get("code"),
                "message": issue.get("message"),
            }
            for issue in (graph.get("issues") or [])
        ]

        return SiteAudit(
            page_type=page_type,
            headline=headline,
            audit_focus="Maximize agent accessibility and speed across the captured site.",
            agent_accessibility_score=accessibility_score,
            agent_speed_score=speed_score,
            overall_score=overall_score,
            crawl_base_score=crawl_base_score,
            score_breakdown=score_breakdown,
            score_methodology=score_methodology,
            speed_summary=speed_summary,
            speed_findings=speed_findings,
            top_action_label=success_label,
            top_action_selector=success_selector,
            confidence=confidence,
            rationale=rationale,
            secondary_signals=secondary,
            funnel_summary=funnel_summary,
            top_actions=[c.to_dict() for c in candidates[:5]],
            recommendations=recommendations,
            navigation_issues=nav_issues,
            probe_tasks=tasks,
            static_audit_summary={
                "pass_ratio": static_audits.get("pass_ratio"),
                "passed": static_audits.get("passed"),
                "total": static_audits.get("total"),
            },
            coverage=coverage,
        )


def _start_page(imported: Dict[str, Any]) -> Dict[str, Any]:
    pages = imported.get("pages") or []
    if not pages:
        return {"html": imported.get("html") or "", "title": imported.get("title") or "", "path": "/"}
    return next((p for p in pages if p.get("is_start")), pages[0])


def _rank_candidates(
    summary: Dict[str, Any],
    graph: Dict[str, Any],
    html: str,
    elements: List[Any],
) -> List[ActionCandidate]:
    seen: Dict[str, ActionCandidate] = {}
    in_graph = {
        str(a.get("target_path") or "").lower()
        for a in (graph.get("actions") or [])
        if a.get("target_kind") == "internal_page"
    }

    def ingest(action: Dict[str, Any], index: int) -> None:
        selector = str(action.get("selector") or "").strip()
        if not selector or not selector_matches_html(selector, html):
            return
        label = str(action.get("element_text") or action.get("text") or "").strip()[:80]
        score, reason = _score_action(action, index, in_graph)
        if selector not in seen or seen[selector].score < score:
            seen[selector] = ActionCandidate(
                selector=selector,
                label=label or selector,
                score=round(score, 3),
                reason=reason,
                target_path=str(action.get("target_path") or ""),
            )

    for index, action in enumerate(summary.get("actions") or []):
        ingest(action, index)
    for index, element in enumerate(elements[:40]):
        if isinstance(element, dict):
            attrs = element.get("attributes") or {}
            ingest(
                {
                    "selector": element.get("selector"),
                    "element_text": element.get("text"),
                    "tag": element.get("tag") or "button",
                    "attributes": attrs,
                    "action_type": "CLICK_CTA",
                    "target_path": attrs.get("href") or "",
                },
                index + 20,
            )
    return sorted(seen.values(), key=lambda item: item.score, reverse=True)[:8]


def _score_action(action: Dict[str, Any], index: int, in_graph_paths: set) -> Tuple[float, str]:
    score = 0.35
    reasons: List[str] = []
    text = str(action.get("element_text") or "").lower()
    target_path = str(action.get("target_path") or "").lower()
    if action.get("action_type") == "CLICK_CTA":
        score += 0.35
        reasons.append("primary CTA")
    if target_path in in_graph_paths:
        score += 0.15
        reasons.append("leads to captured page")
    if any(h in target_path for h in AUTH_PATH_HINTS):
        score -= 0.4
        reasons.append("auth-gated")
    if target_path.startswith("http"):
        score -= 0.3
        reasons.append("external")
    score -= min(0.15, index * 0.02)
    return max(0.05, min(1.0, score)), ", ".join(reasons[:2]) or "interactive"


def _detect_page_type(summary: Dict[str, Any], html: str, graph: Dict[str, Any]) -> str:
    blob = " ".join(
        [
            str(summary.get("headline") or ""),
            str(summary.get("text_content") or "")[:3000],
            " ".join(str(p.get("path") or "") for p in (graph.get("pages") or [])[:12]),
        ]
    ).lower()
    # Prefer whole-phrase commerce signals; avoid substring false positives
    # (e.g. "workshop", "shopify" CSS noise, "buy-in").
    if any(
        k in blob
        for k in (
            "add to cart",
            "add-to-cart",
            "/cart",
            "/checkout",
            "product variant",
            "buy now",
        )
    ):
        return "ecommerce"
    if any(k in blob for k in ("docs", "documentation", "api", "developer")):
        return "developer_tool"
    if any(k in blob for k in ("pricing", "trial", "demo", "signup", "saas")):
        return "saas_landing"
    return "general"


def _speed_assessment(
    imported: Dict[str, Any],
    graph: Dict[str, Any],
    html: str,
) -> Tuple[Dict[str, Any], List[str]]:
    pages = imported.get("pages") or graph.get("pages") or []
    html_bytes = sum(len(str(page.get("html") or "")) for page in pages) or len(html or "")
    script_count = sum(len(re.findall(r"<script\b", str(page.get("html") or ""), re.IGNORECASE)) for page in pages)
    stylesheet_count = sum(
        len(re.findall(r"<link\b[^>]*rel=[\"']?stylesheet", str(page.get("html") or ""), re.IGNORECASE))
        for page in pages
    )
    image_count = sum(len(re.findall(r"<img\b", str(page.get("html") or ""), re.IGNORECASE)) for page in pages)
    structure_rows = []
    for page in pages:
        summary = ((page.get("metadata") or {}).get("summary") or {}) if isinstance(page, dict) else {}
        if not summary:
            summary = summarize_variant_html(str(page.get("html") or ""))
        structure = summary.get("structure") or {}
        structure_rows.append(structure)
    if not structure_rows:
        structure_rows.append((summarize_variant_html(html) if html else {}).get("structure") or {})

    dom_node_count = sum(int(row.get("dom_node_count") or 0) for row in structure_rows)
    max_dom_depth = max((int(row.get("max_dom_depth") or 0) for row in structure_rows), default=0)
    interactive_node_count = sum(int(row.get("interactive_node_count") or 0) for row in structure_rows)
    landmark_node_count = sum(int(row.get("landmark_node_count") or 0) for row in structure_rows)
    text_char_count = sum(int(row.get("text_char_count") or 0) for row in structure_rows)
    text_word_count = sum(int(row.get("text_word_count") or 0) for row in structure_rows)
    interactive_density_percent = round(
        100.0 * interactive_node_count / max(dom_node_count, 1),
    2,
    ) if dom_node_count else 0.0
    density_penalty = (
        min(8.0, max(0.0, interactive_density_percent - 12.0) * 0.8)
        if dom_node_count > 120 and interactive_node_count > 20
        else 0.0
    )
    actions = graph.get("actions") or []
    blocked_actions = len(
        [
            action
            for action in actions
            if action.get("target_kind") in {"unknown_js", "dead_target", "auth_required"}
        ]
    )

    score = 100.0
    score -= min(18.0, max(0, html_bytes - 250_000) / 20_000)
    score -= min(18.0, max(0, dom_node_count - 400) / 70)
    score -= min(10.0, max(0, text_char_count - 12_000) / 2_000)
    score -= min(12.0, max(0, script_count - 12) * 1.5)
    score -= min(8.0, max(0, stylesheet_count - 6) * 1.5)
    score -= min(8.0, max(0, image_count - 24) * 0.5)
    score -= min(8.0, max(0, interactive_node_count - 40) * 0.25)
    score -= min(8.0, max(0, max_dom_depth - 18) * 0.8)
    score -= density_penalty
    score -= min(10.0, max(0, blocked_actions) * 2.0)
    score = round(max(0.0, min(100.0, score)), 1)

    findings: List[str] = []
    if html_bytes > 450_000:
        findings.append("Reduce the initial HTML payload; large snapshots slow agent parsing before the first action.")
    elif html_bytes > 250_000:
        findings.append("Trim non-essential HTML before first interaction so the page is cheaper for agents to parse.")
    if dom_node_count > 1_200:
        findings.append("Simplify the DOM tree; very large page structures raise agent scan cost even before clicks begin.")
    elif dom_node_count > 400:
        findings.append("Reduce DOM node count on the initial page to lower structural overhead for agents.")
    if text_char_count > 18_000:
        findings.append("Shorten the initial text payload or defer low-value copy so agents can orient faster.")
    if script_count > 12:
        findings.append("Defer non-critical scripts and remove duplicate bundles from the initial page.")
    if stylesheet_count > 6:
        findings.append("Consolidate render-blocking stylesheets so agents reach interactive state faster.")
    if image_count > 24:
        findings.append("Lazy-load below-the-fold images and keep the initial viewport lightweight.")
    if interactive_node_count > 60 or density_penalty > 0:
        findings.append("Reduce interactive crowding in the first view; dense action clusters increase agent selection cost.")
    if max_dom_depth > 18:
        findings.append("Flatten deeply nested layout wrappers; excessive nesting makes the page structurally heavier for agents.")
    if blocked_actions:
        findings.append("Resolve blocked actions; failed clicks and dead targets increase structural interaction cost.")
    if not findings:
        findings.append("Structural speed posture looks lightweight for agent browsing; the initial page is small, shallow, and low-friction.")

    return (
        {
            "score": score,
            "proxy_label": "structural_speed_proxy",
            "html_bytes": html_bytes,
            "page_count": len(pages) or 1,
            "dom_node_count": dom_node_count,
            "max_dom_depth": max_dom_depth,
            "interactive_node_count": interactive_node_count,
            "interactive_density_percent": interactive_density_percent,
            "landmark_node_count": landmark_node_count,
            "text_char_count": text_char_count,
            "text_word_count": text_word_count,
            "script_count": script_count,
            "stylesheet_count": stylesheet_count,
            "image_count": image_count,
            "blocked_action_count": blocked_actions,
        },
        findings,
    )


def _funnel_insights(imported: Dict[str, Any], graph: Dict[str, Any]) -> Tuple[str, List[str]]:
    pages = imported.get("pages") or graph.get("pages") or []
    if len(pages) < 2:
        return "", []
    paths = [str(p.get("path") or p.get("id") or "") for p in pages[:6] if p.get("path") or p.get("id")]
    secondary: List[str] = []
    blob = " ".join(paths).lower()
    if "pricing" in blob:
        secondary.append("Also track whether agents can reach /pricing.")
    if any(k in blob for k in ("signup", "checkout", "docs")):
        secondary.append("Also track progression into signup, checkout, or docs.")
    summary = f"Captured {len(pages)} pages: {' → '.join(paths[:4])}."
    return summary, secondary


def _build_recommendations(
    coverage: Dict[str, Any],
    graph: Dict[str, Any],
    static_audits: Dict[str, Any],
    candidates: List[ActionCandidate],
    speed_findings: List[str],
) -> List[str]:
    recs: List[str] = []
    pct = float(coverage.get("action_accessibility_percent") or 0)
    blocked = int(coverage.get("blocked_actions") or 0)
    total = int(coverage.get("total_actions") or 0)
    external = int(coverage.get("external_actions") or 0)
    on_site_total = max(0, total - external)

    recs.append(
        f"{pct}% of on-site captured actions are agent-navigable "
        f"({coverage.get('accessible_actions', 0)}/{on_site_total or total})."
    )
    if pct < 70:
        recs.append("Priority: replace JS-only controls with real links or explicit machine-readable actions.")
    recs.extend(speed_findings[:3])
    kinds = coverage.get("by_target_kind") or {}
    if kinds.get("unknown_js", 0) > 0:
        recs.append(f"Fix {kinds['unknown_js']} actions that depend on JavaScript without a resolved target.")
    if kinds.get("dead_target", 0) > 0:
        recs.append(f"Resolve {kinds['dead_target']} dead links or broken hrefs in the captured flow.")
    if kinds.get("auth_required", 0) > 0:
        recs.append("Expose a test login path or document credentials for agent access to gated pages.")
    external = int(kinds.get("external_exit", 0) or 0)
    if external > 0:
        on_site = coverage.get("on_site_only_percent")
        if on_site is not None:
            recs.append(
                f"{external} actions leave the audited origin. "
                f"On-site-only accessibility is {on_site}% excluding those exits."
            )
        else:
            recs.append(
                f"{external} actions leave the site — agents may still click them but they do not count as on-site navigation."
            )

    for issue in (graph.get("issues") or [])[:4]:
        msg = issue.get("message") or issue.get("code")
        if msg:
            recs.append(f"Nav issue on {issue.get('page_id', '?')}: {msg}")

    static_ratio = static_audits.get("pass_ratio")
    if static_ratio is not None and static_ratio < 0.8:
        recs.append("Improve static operability checks (labels, llms.txt, DOM size) — see static audit details.")

    if not candidates:
        recs.append("No strong interactive action detected — add labeled buttons or links with clear accessible names.")

    if static_audits.get("checks"):
        failed = [c for c in static_audits["checks"] if not c.get("passed")]
        for check in failed[:3]:
            recs.append(f"Static check failed: {check.get('title')} — {check.get('detail', '')[:120]}")

    return recs


def _infer_operator_tasks(top: Optional[ActionCandidate], success_label: str) -> List[Dict[str, Any]]:
    if not top:
        return [
            {
                "id": "probe_1",
                "name": "Accessibility and speed probe",
                "instruction": (
                    "Act like a browser agent (accessibility tree): explore by role and name, "
                    "stay on-site, and report whether main actions are accessible."
                ),
                "success_text": "",
                "success_url_contains": "",
            }
        ]
    instruction = (
        "Act like a browser agent (accessibility tree): explore the site by role and name, "
        f"prefer on-site navigation, and verify “{success_label}” is reachable."
    )
    success_url = ""
    if top.target_path and not top.target_path.startswith("http"):
        success_url = top.target_path.split("?")[0]
    return [
        {
            "id": "accessibility_speed_probe",
            "name": "Accessibility and speed probe",
            "instruction": instruction,
            "success_url_contains": success_url,
            "success_text": success_label[:40] if success_label else "",
            "success_selector": top.selector,
        }
    ]


def _confidence(candidates: List[ActionCandidate], page_type: str, coverage: Dict[str, Any]) -> float:
    if not candidates:
        return 0.3
    top = candidates[0].score
    gap = top - (candidates[1].score if len(candidates) > 1 else 0)
    score = top * 0.65 + min(0.2, gap) + (0.05 if page_type != "general" else 0)
    pct = float(coverage.get("action_accessibility_percent") or 0) / 100.0
    score = score * 0.7 + pct * 0.3
    return round(max(0.2, min(0.95, score)), 2)
