"""Build agent-ready exports: checks, SKILL.md, llms.txt, verdict."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse


_FIX_HINTS = {
    "llms-txt": "Add `/llms.txt` at domain root (200 on apex and www, or follow redirects). See fix-recipes § llms.txt.",
    "button-labels": "Give every `<button>` visible text or `aria-label` (icon-only controls).",
    "link-labels": "Ensure links have discernible text — not empty, URL-only, or generic “click here”.",
    "dom-size": "Trim HTML payload: lazy-load images, defer non-critical JS, paginate long lists.",
    "unknown_js": "Replace JS-only controls with `<a href=\"/path\">` or a labelled button wired to a dialog.",
    "dead_target": "Fix broken `href` or route so the control resolves to a reachable same-origin page.",
    "client_only": "Server-render the control (remove client-only dynamic import / CSR-only nav).",
    "name_unmatchable": "Set `aria-label` to post title only; keep date/description as visible children.",
    "catalog_not_activated": "See impact text — may be SSR, aria-label, or explorer matching (not always labeling).",
    "unlabeled_static": "Add `aria-label` or visible text so getByRole can target this control.",
    "llms_txt": "Publish `/llms.txt` with redirect from apex to www if needed.",
}


def build_remediation_exports(
    *,
    run_id: str,
    run_payload: Dict[str, Any],
    run_dir: Optional[str] = None,
    prior_run: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    audit = run_payload.get("audit") or {}
    agent_report = run_payload.get("agent_report") or audit.get("agent_report") or {}
    state = run_payload.get("state") or {}
    snapshot = run_payload.get("snapshot_before") or {}
    static_audits = snapshot.get("static_audits") or {}

    source_url = (
        str(state.get("site_url") or "")
        or str(snapshot.get("source_url") or "")
        or str(agent_report.get("source_url") or "")
    )
    host = _host_from_url(source_url) or "site"
    has_explore = bool(agent_report.get("has_exploration"))

    checks = _build_checks(audit, static_audits, agent_report)
    fixes = _enrich_fixes_with_patches(_collect_fixes(audit, agent_report))
    user_journeys = _build_user_journeys(agent_report, audit, run_payload.get("events") or [])
    reaudit_diff = _build_reaudit_diff(audit, agent_report, prior_run)
    verdict = _build_verdict(audit, checks, has_explore, state)
    business_summary = _build_business_summary(audit, agent_report, has_explore)
    cursor_prompt = _build_cursor_prompt(
        host,
        run_id,
        source_url,
        fixes,
        gaps=agent_report.get("gaps") or [],
    )
    github_issue_md = _build_github_issue_md(
        run_id=run_id,
        host=host,
        source_url=source_url,
        verdict=verdict,
        business_summary=business_summary,
        user_journeys=user_journeys,
        gaps=agent_report.get("gaps") or [],
        fixes=fixes,
    )
    skill_md = _build_skill_md(
        run_id=run_id,
        host=host,
        source_url=source_url,
        audit=audit,
        agent_report=agent_report,
        fixes=fixes,
        checks=checks,
        has_explore=has_explore,
    )
    llms_txt = _build_llms_txt(
        run_id=run_id,
        host=host,
        source_url=source_url,
        audit=audit,
        snapshot=snapshot,
    )
    report_md = _build_report_md(
        run_id=run_id,
        host=host,
        source_url=source_url,
        audit=audit,
        agent_report=agent_report,
        checks=checks,
        fixes=fixes,
        verdict=verdict,
    )

    exports = {
        "verdict": verdict,
        "business_summary": business_summary,
        "user_journeys": user_journeys,
        "reaudit_diff": reaudit_diff,
        "cursor_prompt": cursor_prompt,
        "github_issue_md": github_issue_md,
        "checks": checks,
        "fixes": fixes,
        "has_exploration": has_explore,
        "skill_md": skill_md,
        "llms_txt": llms_txt,
        "report_md": report_md,
        "skill_name": _skill_name(host),
    }

    if run_dir:
        _persist_exports(run_dir, exports)

    return exports


def _persist_exports(run_dir: str, exports: Dict[str, Any]) -> None:
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "remediation_skill.md"), "w", encoding="utf-8") as handle:
        handle.write(exports.get("skill_md") or "")
    with open(os.path.join(run_dir, "llms.txt"), "w", encoding="utf-8") as handle:
        handle.write(exports.get("llms_txt") or "")
    with open(os.path.join(run_dir, "report_export.md"), "w", encoding="utf-8") as handle:
        handle.write(exports.get("report_md") or "")


def _host_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").replace("www.", "") or ""
    except Exception:
        return ""


def _skill_name(host: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", host.lower()).strip("-") or "site"
    return f"fix-{slug}-agent-gaps"


def _build_checks(
    audit: Dict[str, Any],
    static_audits: Dict[str, Any],
    agent_report: Dict[str, Any],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []

    llms_gap = next((g for g in (agent_report.get("gaps") or []) if g.get("type") == "llms_txt"), None)
    if llms_gap:
        meta = llms_gap.get("llms_meta") or {}
        passed = bool(meta.get("pass"))
        rows.append(
            {
                "id": "llms-txt",
                "title": "llms.txt at domain root",
                "status": "pass" if passed else "fail",
                "detail": str(llms_gap.get("impact") or meta.get("reason") or ""),
                "fix_hint": _FIX_HINTS.get("llms-txt", ""),
                "group": "static",
            }
        )
    for check in static_audits.get("checks") or []:
        check_id = str(check.get("id") or "")
        if check_id == "llms-txt" and llms_gap:
            continue
        passed = bool(check.get("passed"))
        rows.append(
            {
                "id": check_id,
                "title": check.get("title") or check_id,
                "status": "pass" if passed else "fail",
                "detail": check.get("detail") or "",
                "fix_hint": _FIX_HINTS.get(check_id, ""),
                "group": "static",
            }
        )

    coverage = audit.get("coverage") or {}
    accessibility = float(audit.get("agent_accessibility_score") or coverage.get("action_accessibility_percent") or 0)
    rows.append(
        {
            "id": "action-accessibility",
            "title": "On-site actions agent-navigable",
            "status": "pass" if accessibility >= 85 else ("warn" if accessibility >= 65 else "fail"),
            "detail": f"{accessibility}% of captured on-site actions resolve in the crawl graph.",
            "fix_hint": "Replace JS-only CTAs with real links and unique accessible names.",
            "group": "crawl",
        }
    )

    speed = audit.get("speed_summary") or {}
    speed_score = float(audit.get("agent_speed_score") or speed.get("score") or 0)
    rows.append(
        {
            "id": "agent-speed",
            "title": "Agent speed posture",
            "status": "pass" if speed_score >= 80 else ("warn" if speed_score >= 60 else "fail"),
            "detail": f"Speed score {speed_score}%. HTML {int(speed.get('html_bytes') or 0):,} bytes across {speed.get('page_count', 1)} page(s).",
            "fix_hint": "Defer scripts, consolidate CSS, lazy-load below-fold media.",
            "group": "crawl",
        }
    )

    blocked = int(coverage.get("blocked_actions") or 0)
    if blocked:
        rows.append(
            {
                "id": "blocked-actions",
                "title": "Blocked navigation targets",
                "status": "fail",
                "detail": f"{blocked} action(s) point to dead or JS-only targets.",
                "fix_hint": _FIX_HINTS["unknown_js"],
                "group": "crawl",
            }
        )

    for finding in audit.get("speed_findings") or []:
        text = str(finding)
        if not any(r.get("detail") == text for r in rows):
            rows.append(
                {
                    "id": f"speed-{len(rows)}",
                    "title": "Speed optimization",
                    "status": "warn",
                    "detail": text,
                    "fix_hint": "",
                    "group": "speed",
                }
            )

    if agent_report.get("has_exploration"):
        eff = agent_report.get("efficiency") or {}
        lost = float(eff.get("actions_lost_percent") or 0)
        gap_count = int(eff.get("gap_count") or len(agent_report.get("gaps") or []))
        step_waste = float(eff.get("step_waste_percent") or 0)
        critical = int(eff.get("critical_gaps") or 0)
        high = int(eff.get("high_gaps") or 0)
        explore_valid = agent_report.get("explore_valid", True)
        min_steps = agent_report.get("explore_min_steps")
        static_pct = agent_report.get("static_navigable_pct")
        hydrated_pct = agent_report.get("hydrated_navigable_pct")
        if not explore_valid:
            status = "warn"
            detail = (
                f"Explore inconclusive — step budget below minimum ({min_steps} steps required). "
                f"Catalog activation not scored as failed."
            )
        elif critical > 0 or lost > 35:
            status = "fail"
            detail = (
                f"{100 - lost:.1f}% of catalog actions activated. {gap_count} gap(s), "
                f"~{step_waste:.0f}% step waste."
            )
        elif high > 0 or gap_count > 0 or lost > 15 or step_waste > 50:
            status = "warn"
            detail = (
                f"{100 - lost:.1f}% of catalog actions activated. {gap_count} gap(s), "
                f"~{step_waste:.0f}% step waste."
            )
        else:
            status = "pass"
            detail = f"{100 - lost:.1f}% of catalog actions activated during explore."
        if static_pct is not None and hydrated_pct is not None:
            detail += f" Static navigable: {static_pct}%. Hydrated: {hydrated_pct}%."
        rows.append(
            {
                "id": "agent-activation",
                "title": "Agent activated catalog actions",
                "status": status,
                "detail": detail,
                "fix_hint": "Fix gaps below so live accessibility tree matches crawl catalog.",
                "group": "explore",
            }
        )
    elif audit.get("overall_score") is not None or audit.get("agent_accessibility_score") is not None:
        rows.append(
            {
                "id": "agent-activation",
                "title": "Agent activated catalog actions",
                "status": "warn",
                "detail": "Agent explore did not run or did not complete — activation metrics unavailable.",
                "fix_hint": "Re-run agent explore from the report to measure live activation.",
                "group": "explore",
            }
        )

    status_order = {"fail": 0, "warn": 1, "pass": 2}
    rows.sort(key=lambda row: (status_order.get(row.get("status", "pass"), 9), row.get("title") or ""))
    return rows


def _collect_fixes(audit: Dict[str, Any], agent_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    fixes: List[Dict[str, Any]] = []
    seen: set[str] = set()

    for fix in agent_report.get("fixes") or []:
        change = str(fix.get("change") or "").strip()
        if not change or change in seen:
            continue
        seen.add(change)
        fixes.append(
            {
                "priority": fix.get("priority") or "medium",
                "change": change,
                "label": fix.get("label") or "",
                "selector": fix.get("selector") or "",
                "page_id": fix.get("page_id") or "",
                "gap_type": fix.get("gap_type") or "",
                "fix_scope": fix.get("fix_scope") or "site",
            }
        )

    if fixes:
        return fixes

    for index, rec in enumerate(audit.get("recommendations") or [], 1):
        text = str(rec).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        priority = "high" if "failed" in text.lower() or "fix" in text.lower()[:20] else "medium"
        fixes.append(
            {
                "priority": priority,
                "change": text,
                "label": "",
                "selector": "",
                "page_id": "",
                "gap_type": "recommendation",
            }
        )

    return fixes[:20]


def _build_verdict(
    audit: Dict[str, Any],
    checks: List[Dict[str, Any]],
    has_explore: bool,
    state: Dict[str, Any],
) -> str:
    score = round(float(audit.get("overall_score") or audit.get("readiness_score") or 0))
    accessibility = float(audit.get("agent_accessibility_score") or 0)
    fails = [c for c in checks if c.get("status") == "fail"]

    if state.get("status") == "failed" and not has_explore:
        top = fails[0]["title"] if fails else "agent explore did not complete"
        return f"Score {score}/100 from crawl only. {top} — re-run agent explore for live gap analysis."

    if fails:
        return f"Score {score}/100. Agents reach {accessibility:.0f}% of actions; fix {fails[0]['title'].lower()} first."

    if not has_explore:
        return f"Score {score}/100 from crawl. Site looks agent-navigable on paper — run explore to verify live."

    return f"Score {score}/100. Agents can navigate most flows; address remaining gaps below."


def _build_skill_md(
    *,
    run_id: str,
    host: str,
    source_url: str,
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    fixes: List[Dict[str, Any]],
    checks: List[Dict[str, Any]],
    has_explore: bool,
) -> str:
    name = _skill_name(host)
    score = round(float(audit.get("overall_score") or 0))
    site_fixes = [f for f in fixes if f.get("fix_scope") != "product"]
    product_fixes = [f for f in fixes if f.get("fix_scope") == "product"]

    lines = [
        "---",
        f"name: {name}",
        "description: >-",
        f"  Fix agent accessibility gaps on {host} from OpenIngress audit {run_id}.",
        "  Follow gap_type recipes — do not add generic accessible names when the tree already has one.",
        "---",
        "",
        f"# Fix agent gaps — {host}",
        "",
        f"- **Audit:** `{run_id}`",
        f"- **Site:** {source_url or host}",
        f"- **Score:** {score}/100",
        f"- **Explore:** {'complete' if has_explore else 'crawl only — re-run agent explore after fixes'}",
        "",
        "## Context",
        "",
        "Agents navigate via the **accessibility tree** (`getByRole`, aria snapshots) — not pixels.",
        "OpenIngress uses one `gap_type` per finding. Map each fix to the recipe for that type.",
        "",
        "## Site changes only (implement these)",
        "",
        "Include ONLY:",
        "- `llms_txt` / `llms-txt` — `/llms.txt` at domain root (apex 200 or redirect to www).",
        "- `client_only` — SSR header/nav (no `dynamic(..., { ssr: false })` without SSR).",
        "- `name_unmatchable` — `aria-label=\"{title}\"` on writing/list links; keep date blurb as children.",
        "- `unlabeled_static` — `aria-label` on icon-only links/buttons.",
        "- `dead_target` — fix broken routes.",
        "- Speed — lazy images, defer blocking CSS when audit flags DOM size.",
        "",
        "Do NOT:",
        "- Add accessible names when gap is `catalog_not_activated` and control is already named in the hydrated tree.",
        "- Treat `off_site_exit` as a site defect.",
        "- Use full date+title+description as the link accessible name.",
        "",
    ]

    if site_fixes:
        for index, fix in enumerate(site_fixes[:14], 1):
            gap_type = fix.get("gap_type") or "site"
            lines.append(
                f"### {index}. [{fix.get('priority', 'medium')}][{gap_type}] "
                f"{fix.get('label') or 'Site change'}"
            )
            if fix.get("page_id"):
                lines.append(f"**Page:** `{fix['page_id']}`")
            if fix.get("selector"):
                lines.append(f"**Selector:** `{fix['selector']}`")
            lines.append("")
            lines.append(fix.get("change") or "")
            lines.append("")
    else:
        lines.append("_No site-level fixes in export — see failed checks._")
        lines.append("")

    if product_fixes:
        lines.extend(
            [
                "## Explorer / product notes (optional — not HTML changes)",
                "",
                "These mean the control is likely fine in static HTML; improve explore matching or step budget:",
                "",
            ]
        )
        for fix in product_fixes[:5]:
            lines.append(f"- {fix.get('change')}")
        lines.append("")

    gap_sections = agent_report.get("gap_sections") or {}
    if gap_sections:
        lines.extend(["## Gaps by section", ""])
        section_titles = {
            "static_operability": "Static operability",
            "hydrated_accessibility": "Hydrated accessibility",
            "explore_activation": "Explore activation",
            "speed": "Speed",
            "off_site_exits": "Off-site (informational)",
        }
        for key, title in section_titles.items():
            items = gap_sections.get(key) or []
            if not items:
                continue
            lines.append(f"### {title}")
            for gap in items[:6]:
                lines.append(
                    f"- [{gap.get('severity')}] `{gap.get('type')}` — "
                    f"{gap.get('label') or gap.get('impact', '')[:80]}"
                )
            lines.append("")

    failed_checks = [c for c in checks if c.get("status") == "fail"]
    if failed_checks:
        lines.extend(["## Failed checks", ""])
        for check in failed_checks:
            lines.append(f"- **{check.get('title')}** — {check.get('detail')}")
            hint = check.get("fix_hint") or _FIX_HINTS.get(check.get("id", ""), "")
            if hint:
                lines.append(f"  - {hint}")
        lines.append("")

    lines.extend(
        [
            "## Recipe index (gap_type -> fix)",
            "",
            "| gap_type | Site fix? | Recipe |",
            "|----------|-----------|--------|",
            "| `llms_txt` | Yes | `fix-recipes.md` section Missing llms.txt |",
            "| `client_only` | Yes | SSR nav / remove CSR-only dynamic import |",
            "| `name_unmatchable` | Yes | `aria-label` = title on `<a>` |",
            "| `unlabeled_static` | Yes | Visible text or `aria-label` |",
            "| `dead_target` | Yes | Fix `href` / route |",
            "| `catalog_not_activated` | Only if also `client_only` or missing `aria-label` | See impact line |",
            "| `off_site_exit` | No | Informational |",
            "",
            "## Verification checklist",
            "",
            "- [ ] Nav links in **static HTML** (view source: HOME/WORK/WRITING/ABOUT)",
            "- [ ] Writing cards: `aria-label=\"{title}\"` on each post `<a>`",
            "- [ ] Back links: `aria-label=\"Back to writing\"` (agents may match `/back/i`)",
            "- [ ] `/llms.txt` returns 200 on apex and www",
            "- [ ] `getByRole('link', { name: /^HOME$/i })` works for primary nav",
            "",
        ]
    )
    return "\n".join(lines)


def _build_llms_txt(
    *,
    run_id: str,
    host: str,
    source_url: str,
    audit: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> str:
    pages = snapshot.get("pages") or []
    paths = []
    for page in pages[:15]:
        path = str(page.get("path") or "").strip()
        if path and path not in paths:
            paths.append(path)

    title = str(audit.get("headline") or host).strip() or host
    if title in {"►", "▶"}:
        title = host

    lines = [
        f"# {title}",
        "",
        f"Agent-facing summary for {source_url or host}.",
        f"OpenIngress audit score: {round(float(audit.get('overall_score') or 0))}/100.",
        "",
        "## Entry points",
    ]
    for path in paths[:12]:
        lines.append(f"- {path}")
    if not paths:
        lines.append(f"- /")

    lines.extend(
        [
            "",
            "## Agent notes",
            "- Primary nav uses labelled links in the accessibility tree.",
            "- External portfolio/social links may leave the site — prefer on-site paths for tasks.",
            "",
            "## OpenIngress",
            f"- Audit: https://openingress.dev/app/runs/{run_id}",
            "",
        ]
    )
    return "\n".join(lines)


def _build_report_md(
    *,
    run_id: str,
    host: str,
    source_url: str,
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    checks: List[Dict[str, Any]],
    fixes: List[Dict[str, Any]],
    verdict: str,
) -> str:
    score = round(float(audit.get("overall_score") or audit.get("readiness_score") or 0))
    lines = [
        f"# Agent report — {host}",
        "",
        verdict,
        "",
        f"- Run: `{run_id}`",
        f"- URL: {source_url}",
        f"- Score: **{score}/100**",
        f"- Accessibility: {audit.get('agent_accessibility_score', '—')}%",
        f"- Speed: {audit.get('agent_speed_score', '—')}%",
        "",
        "## Checks",
        "",
    ]

    for check in checks:
        icon = {"pass": "✓", "warn": "⚠", "fail": "✗"}.get(check.get("status"), "·")
        lines.append(f"- {icon} **{check.get('title')}** — {check.get('detail')}")
    lines.append("")

    if agent_report.get("summary"):
        lines.extend(["## Agent explore summary", "", agent_report["summary"], ""])

    if fixes:
        lines.extend(["## Recommended changes", ""])
        for index, fix in enumerate(fixes, 1):
            lines.append(f"{index}. [{fix.get('priority')}] {fix.get('change')}")
        lines.append("")

    return "\n".join(lines)


_HREF_RE = re.compile(r"""href=["']([^"']+)["']""")


_JOURNEY_TEMPLATES = [
    {
        "id": "portfolio",
        "job": "Find portfolio work",
        "page_ids": {"work"},
        "path_prefixes": ("/work",),
        "action_keywords": ("work", "view project", "project"),
    },
    {
        "id": "blog",
        "job": "Open a blog post",
        "page_ids": {"writing"},
        "path_prefixes": ("/writing",),
        "action_keywords": ("writing", "back"),
    },
    {
        "id": "about",
        "job": "Contact / hire",
        "page_ids": {"about"},
        "path_prefixes": ("/about",),
        "action_keywords": ("about", "contact", "email", "hire"),
    },
]


def _href_from_selector(selector: str) -> str:
    match = _HREF_RE.search(selector or "")
    return match.group(1) if match else ""


def _short_label(label: str, limit: int = 48) -> str:
    text = re.sub(r"\s+", " ", str(label or "").strip())
    if len(text) <= limit:
        return text or "Link"
    return text[: limit - 1].rstrip() + "…"


def _build_patch_suggestion(fix: Dict[str, Any]) -> Optional[Dict[str, str]]:
    gap_type = str(fix.get("gap_type") or "")
    selector = str(fix.get("selector") or "")
    label = _short_label(fix.get("label") or "")
    href = _href_from_selector(selector)
    page_id = str(fix.get("page_id") or "")

    if gap_type in {"catalog_not_activated", "invisible_in_live_tree"} and href:
        return {
            "current": f'<a href="{href}">{label}</a>',
            "suggested": (
                f'<a href="{href}" aria-label="{label}">{label}</a>\n'
                f"<!-- ensure link is in static HTML and live accessibility tree -->"
            ),
        }
    if gap_type in {"client_only", "unknown_js"}:
        return {
            "current": f"<!-- client-only / JS -->\n{selector or label}",
            "suggested": f"<!-- SSR nav/control -->\n<a href=\"{href or '/'}\">{label}</a>",
        }
    if gap_type == "name_unmatchable" and href:
        return {
            "current": f'<a href="{href}">…long visible text…</a>',
            "suggested": f'<a href="{href}" aria-label="{label}">{label}</a>',
        }
    if gap_type == "dead_target":
        target = href or (f"/{page_id}" if page_id else "/")
        return {
            "current": f'<div onclick="...">{label}</div>',
            "suggested": f'<a href="{target}">{label}</a>',
        }
    if gap_type == "static_audit" and "llms" in label.lower():
        return {
            "current": "# /llms.txt — file missing at domain root",
            "suggested": (
                "# Site name\n\n"
                "Brief summary for agents.\n\n"
                "## Entry points\n"
                "- /\n"
                "- /work\n"
                "- /writing\n"
            ),
        }
    if href:
        return {
            "current": selector or f'<a href="{href}">…</a>',
            "suggested": f'<a href="{href}">{label}</a>',
        }
    return None


def _enrich_fixes_with_patches(fixes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for fix in fixes:
        row = dict(fix)
        patch = _build_patch_suggestion(row)
        if patch:
            row["patch"] = patch
        enriched.append(row)
    return enriched


def _visited_paths(events: List[Dict[str, Any]]) -> set[str]:
    paths: set[str] = set()
    for event in events:
        meta = event.get("metadata") or {}
        path = str(meta.get("path") or event.get("url") or "").strip()
        if not path:
            continue
        if path.startswith("http"):
            try:
                path = urlparse(path).path or "/"
            except Exception:
                continue
        paths.add(path.rstrip("/") or "/")
    return paths


def _finding_actions(agent_report: Dict[str, Any]) -> List[str]:
    return [
        str(item.get("text") or "").lower()
        for item in (agent_report.get("findings") or [])
        if item.get("kind") == "action"
    ]


def _gaps_for_journey(gaps: List[Dict[str, Any]], template: Dict[str, Any]) -> List[Dict[str, Any]]:
    matched: List[Dict[str, Any]] = []
    for gap in gaps:
        page_id = str(gap.get("page_id") or "")
        label = str(gap.get("label") or "").lower()
        if page_id in template["page_ids"]:
            matched.append(gap)
            continue
        selector = str(gap.get("selector") or "").lower()
        if any(prefix.strip("/") in selector or prefix in label for prefix in template["path_prefixes"]):
            matched.append(gap)
    return matched


def _build_user_journeys(
    agent_report: Dict[str, Any],
    audit: Dict[str, Any],
    events: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    job_results = agent_report.get("job_results") or []
    if job_results:
        return job_results

    gaps = agent_report.get("gaps") or []
    paths = _visited_paths(events)
    actions = _finding_actions(agent_report)
    rows: List[Dict[str, Any]] = []

    for template in _JOURNEY_TEMPLATES:
        reached_path = next(
            (
                path
                for path in paths
                if any(path.startswith(prefix.rstrip("/") or "/") for prefix in template["path_prefixes"])
            ),
            None,
        )
        action_hit = any(any(kw in action for kw in template["action_keywords"]) for action in actions)
        attempted = bool(reached_path or action_hit)
        journey_gaps = _gaps_for_journey(gaps, template)
        high_gaps = [g for g in journey_gaps if g.get("severity") in {"critical", "high"}]

        if attempted and not journey_gaps:
            status = "success"
            result = f"reached {reached_path}" if reached_path else "agent activated target"
            blocker = "—"
        elif attempted and journey_gaps:
            status = "partial"
            result = f"reached {reached_path}" if reached_path else "partial activation"
            if template["id"] == "blog":
                blocker = f"{len(journey_gaps)} post(s) invisible in live tree"
            elif high_gaps:
                blocker = f"{len(high_gaps)} high-severity gap(s) on this journey"
            else:
                blocker = f"{len(journey_gaps)} gap(s) on this journey"
        else:
            status = "failed"
            result = "not attempted"
            if journey_gaps:
                blocker = journey_gaps[0].get("impact") or "blocked in crawl catalog"
            elif template["id"] == "about":
                blocker = "no clear contact CTA in agent tree"
            else:
                blocker = "agent did not reach this flow"

        rows.append(
            {
                "id": template["id"],
                "job": template["job"],
                "status": status,
                "result": result,
                "blocker": blocker,
                "gap_count": len(journey_gaps),
            }
        )

    if not rows and audit.get("funnel_summary"):
        rows.append(
            {
                "id": "crawl",
                "job": "Browse site catalog",
                "status": "partial",
                "result": str(audit.get("funnel_summary") or ""),
                "blocker": "—",
                "gap_count": len(gaps),
            }
        )
    return rows


def _build_business_summary(
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    has_explore: bool,
) -> List[str]:
    lines: List[str] = []
    accessibility = float(audit.get("agent_accessibility_score") or 0)
    score = round(float(audit.get("overall_score") or audit.get("readiness_score") or 0))
    gaps = agent_report.get("gaps") or []

    if has_explore:
        eff = agent_report.get("efficiency") or {}
        lost = float(eff.get("actions_lost_percent") or 0)
        step_waste = float(eff.get("step_waste_percent") or 0)
        if lost > 0:
            if eff.get("actions_lost_basis") == "catalog":
                lines.append(f"~{lost:.0f}% of catalog actions missed or unreachable by the agent")
            else:
                lines.append(f"~{lost:.0f}% of on-site actions never reached by the agent")
        if step_waste > 0:
            lines.append(f"~{step_waste:.0f}% of agent time lost to retries and dead ends")
    elif accessibility:
        miss = round(100 - accessibility)
        if miss > 0:
            lines.append(
                f"Crawl-only audit: ~{miss:.0f}% of catalog actions may be unreachable — run agent explore to verify."
            )

    writing_gaps = [g for g in gaps if str(g.get("page_id") or "") == "writing"]
    if writing_gaps:
        lines.append(f"{len(writing_gaps)} writing pages invisible during live agent browse")

    if not lines:
        if score >= 85:
            lines.append("Agents can navigate most primary flows on this site.")
        else:
            lines.append(f"Agent readiness score is {score}/100 — address gaps below to improve activation.")

    return lines


def _build_reaudit_diff(
    audit: Dict[str, Any],
    agent_report: Dict[str, Any],
    prior_run: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not prior_run:
        return None

    current_score = round(float(audit.get("overall_score") or audit.get("readiness_score") or 0))
    prior_score = round(float(prior_run.get("overall_score") or prior_run.get("readiness_score") or 0))
    current_gaps = int((agent_report.get("efficiency") or {}).get("gap_count") or len(agent_report.get("gaps") or []))
    prior_gaps = int(prior_run.get("gap_count") or 0)
    gaps_closed = max(0, prior_gaps - current_gaps)
    gaps_opened = max(0, current_gaps - prior_gaps)
    score_delta = current_score - prior_score

    parts = [f"Score {prior_score} → {current_score}"]
    if gaps_closed:
        parts.append(f"{gaps_closed} gap{'s' if gaps_closed != 1 else ''} closed")
    if gaps_opened:
        parts.append(f"{gaps_opened} new gap{'s' if gaps_opened != 1 else ''}")
    if score_delta > 0 and not gaps_closed:
        parts.append(f"+{score_delta} pts")
    elif score_delta < 0:
        parts.append(f"{score_delta} pts")

    return {
        "prior_run_id": prior_run.get("run_id"),
        "prior_created_at": prior_run.get("created_at"),
        "prior_score": prior_score,
        "current_score": current_score,
        "score_delta": score_delta,
        "prior_gaps": prior_gaps,
        "current_gaps": current_gaps,
        "gaps_closed": gaps_closed,
        "gaps_opened": gaps_opened,
        "summary": ", ".join(parts),
    }


def _build_cursor_prompt(
    host: str,
    run_id: str,
    source_url: str,
    fixes: List[Dict[str, Any]],
    *,
    gaps: List[Dict[str, Any]],
) -> str:
    lines = [
        f"Fix agent accessibility gaps on {host} ({source_url}).",
        f"OpenIngress audit: {run_id}",
        "",
        "Agents navigate via the accessibility tree (getByRole, aria snapshots).",
        "",
        "Rules:",
        "- Only implement **site** fixes from the list (skip [product] catalog_not_activated unless impact says SSR/aria-label).",
        "- Never add generic 'accessible name' when the hydrated tree already has a name.",
        "- llms.txt at domain root; apex may redirect to www.",
        "- Writing list links: aria-label = post title only.",
        "",
        "Apply these site changes:",
        "",
    ]
    for index, fix in enumerate(fixes[:10], 1):
        lines.append(f"{index}. [{fix.get('priority', 'medium')}] {fix.get('change')}")
        patch = fix.get("patch") or {}
        if patch.get("suggested"):
            lines.append("   Suggested patch:")
            for patch_line in str(patch["suggested"]).splitlines():
                lines.append(f"   {patch_line}")
        lines.append("")

    if gaps and not fixes:
        lines.append("Gaps to fix:")
        for gap in gaps[:8]:
            lines.append(f"- [{gap.get('severity')}] {gap.get('label') or gap.get('type')}: {gap.get('impact')}")

    lines.extend(
        [
            "",
            "After changes, re-run the OpenIngress audit on the same URL to verify.",
        ]
    )
    return "\n".join(lines).strip()


def _build_github_issue_md(
    *,
    run_id: str,
    host: str,
    source_url: str,
    verdict: str,
    business_summary: List[str],
    user_journeys: List[Dict[str, Any]],
    gaps: List[Dict[str, Any]],
    fixes: List[Dict[str, Any]],
) -> str:
    lines = [
        f"## Agent accessibility gaps — {host}",
        "",
        verdict,
        "",
    ]
    for sentence in business_summary:
        lines.append(f"- {sentence}")
    lines.extend(["", f"**Audit:** https://openingress.dev/app/runs/{run_id}", f"**Site:** {source_url}", ""])

    if user_journeys:
        lines.extend(["## Agent journeys", "", "| Job | Result | Blocker |", "| --- | --- | --- |"])
        for row in user_journeys:
            icon = {"success": "✅", "partial": "⚠️", "failed": "❌"}.get(row.get("status"), "·")
            lines.append(f"| {row.get('job')} | {icon} {row.get('result')} | {row.get('blocker')} |")
        lines.append("")

    if gaps:
        lines.extend(["## Gaps", ""])
        for gap in gaps[:12]:
            lines.append(
                f"- **[{gap.get('severity')}]** {gap.get('label') or gap.get('type')} — {gap.get('impact')}"
            )
            if gap.get("selector"):
                lines.append(f"  - Selector: `{gap['selector']}`")
        lines.append("")

    if fixes:
        lines.extend(["## Recommended fixes", ""])
        for index, fix in enumerate(fixes[:12], 1):
            lines.append(f"{index}. **[{fix.get('priority')}]** {fix.get('change')}")
            patch = fix.get("patch") or {}
            if patch.get("suggested"):
                lines.append("   ```html")
                lines.append(f"   {patch['suggested']}")
                lines.append("   ```")
        lines.append("")

    lines.append("_Generated by OpenIngress — attach trace screenshots from the audit report if filing in GitHub._")
    return "\n".join(lines)

