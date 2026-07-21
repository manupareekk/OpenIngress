"""Simulate a Cursor-style browser agent via accessibility tree + optional LLM policy."""

from __future__ import annotations

import os
import re
import time
import uuid
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

from ..models import OperatorActionType, OperatorEvent, SiteSnapshot
from .aria_tree import aria_snapshot_for_page, candidates_from_aria_snapshot
from .cursor_llm_agent import decide_next_browser_action, llm_explorer_enabled
from .explore_jobs import ExploreJobTracker, build_explore_visit_urls, infer_explore_jobs
from .catalog_activation import (
    activation_budget_summary,
    pick_catalog_actions_for_page,
    record_budget_progress,
)
from .gap_taxonomy import (
    action_in_static_html,
    catalog_accessible_name,
    explore_min_steps,
    match_names_for_action,
    names_compatible,
    page_html_has_csr_bailout,
    static_html_missing_main_nav,
)
from .live_operator_runner import _resolve_start_url
from .url_page_importer import normalize_url

EXPLORE_AGENT_APPENDIX = """
You audit sites via the accessibility tree (getByRole, aria snapshots), not pixels.
Use getByRole('link', { name: /^HOME$/i }) for primary nav.
For article lists, match title substring only — not full date+title+description.
For "← back", use getByRole('link', { name: /back/i }).
Do not recommend adding accessible names when the hydrated tree already has one.
"""

_VARIANT_TOKENS = ("size", "color", "colour", "swatch", "option", "subscription")
_VARIANT_DECOY_TOKENS = ("size guide", "fit guide", "guide", "chart")
_ADD_TO_CART_TOKENS = ("add to cart", "add-to-cart", "add to bag", "buy now")
_CART_TOKENS = ("cart", "bag", "view cart")
_CART_STATE_TOKENS = ("cart drawer", "cart item", "line item", "subtotal", "view cart")
_CART_CONTROL_TOKENS = ("cart", "view cart", "shopping bag")
_CHECKOUT_TOKENS = ("checkout", "check out", "proceed to checkout", "place order")
_CHECKOUT_DECOY_TOKENS = ("check out the collection", "check out our", "check out the gymshark", "collection")
_LINE_ITEM_TOKENS = ("quantity", "qty", "line item", "cart item", "remove", "subtotal")
_PROBE_ACTION_ROLES = {
    "collection_search": ("collection_link", "search"),
    "product_page": ("product_link",),
    "variant_selection": ("variant_control",),
    "add_to_cart": ("add_to_cart",),
    "cart": ("cart_open", "quantity_control", "add_to_cart"),
    "checkout_handoff": ("checkout_link", "cart_open", "add_to_cart"),
}


def explore_like_cursor_agent(
    *,
    run_id: str,
    snapshot: SiteSnapshot,
    universe: Dict[str, Any],
    run_dir: str,
    max_pages: int = 12,
    max_steps_per_page: int = 8,
    max_total_steps: int = 40,
    device: str = "desktop",
    use_llm: Optional[bool] = None,
    audit: Optional[Dict[str, Any]] = None,
    on_progress: Optional[Callable[[str, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    from playwright.sync_api import sync_playwright

    source_url = _resolve_start_url(snapshot.source_url)
    screenshot_dir = os.path.join(run_dir, "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    all_actions = universe.get("actions") or []
    on_site_actions = [a for a in all_actions if a.get("on_site")]
    action_by_path = _actions_by_path(on_site_actions, source_url)
    probe_actions_by_page = _actions_by_page(all_actions)
    explore_jobs = infer_explore_jobs(universe, audit=audit)
    probe_plan = (universe.get("strategy") or {}).get("probe_plan") or []
    job_tracker = ExploreJobTracker(explore_jobs)
    visit_urls = build_explore_visit_urls(source_url, universe, explore_jobs, max_pages=max_pages)
    visit_queue: deque = deque(visit_urls)
    visited_urls: Set[str] = set()
    pages_crawled = len(universe.get("pages") or []) or 1
    min_steps_required = explore_min_steps(pages_crawled)
    max_total_steps = max(max_total_steps, min_steps_required + _probe_step_budget(probe_plan))

    page_html_by_id = _page_html_by_id(snapshot)
    viewport = {"width": 390, "height": 844} if device == "mobile" else {"width": 1440, "height": 900}
    events: List[OperatorEvent] = []
    page_results: List[Dict[str, Any]] = []
    activation_log: List[Dict[str, Any]] = []
    activated_ids: Set[str] = set()
    aria_matched_ids: Set[str] = set()
    history: List[Dict[str, Any]] = []
    policy_counts: Dict[str, int] = {}
    total_steps = 0
    llm_active = llm_explorer_enabled(use_llm)
    activation_budget_met: Set[str] = set()

    session_id = f"cursor_llm_{uuid.uuid4().hex[:8]}"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport=viewport, ignore_https_errors=True)
        page = context.new_page()

        try:
            while visit_queue and len(visited_urls) < max_pages and total_steps < max_total_steps:
                if should_cancel and should_cancel():
                    raise RuntimeError("CANCELLED")
                if explore_jobs and job_tracker.active_job() is None:
                    break
                page_url = visit_queue.popleft()
                url_key = _url_key(page_url)
                if url_key in visited_urls:
                    continue
                visited_urls.add(url_key)

                path = urlparse(page_url).path or "/"
                page_id = _page_id_for_path(path, universe)
                expected = action_by_path.get(path) or action_by_path.get(path.rstrip("/") or "/") or []

                page_step = 0
                page_activated: List[str] = []
                page_aria_matched: List[str] = []
                page_error = ""
                initial_signals: Dict[str, Any] = {}

                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=30_000)
                    _wait_after_dom(page)
                    static_html = page_html_by_id.get(page_id, "")
                    aria_text, hydrated = _aria_after_hydration(page, static_html)
                    initial_signals = _probe_signal_snapshot(
                        page_url=page.url,
                        static_html=static_html,
                        live_nodes=candidates_from_aria_snapshot(aria_text),
                        expected_page_type=_strategy_page_type_for_path(universe, path),
                    )
                    total_steps += 1
                    page_step += 1
                    job_tracker.record_page_view(path)
                    if on_progress:
                        on_progress(f"Visiting {urlparse(page_url).path or '/'}", total_steps)
                    shot_path = _save_screenshot(page, screenshot_dir, page_id, total_steps)
                    events.append(
                        _explore_event(
                            run_id,
                            session_id,
                            snapshot.phase,
                            total_steps,
                            page_url,
                            OperatorActionType.VIEW_PAGE.value,
                            metadata={
                                "screenshots": {"viewport": _shot_ref(run_id, shot_path)},
                                "path": path,
                                "policy": "llm" if llm_active else "heuristic",
                            },
                        )
                    )

                    total_steps, page_step = _run_catalog_activation_pass(
                        page=page,
                        path=path,
                        page_url=page_url,
                        page_id=page_id,
                        expected=expected,
                        static_html=static_html,
                        source_url=source_url,
                        run_id=run_id,
                        session_id=session_id,
                        phase=snapshot.phase,
                        screenshot_dir=screenshot_dir,
                        activated_ids=activated_ids,
                        aria_matched_ids=aria_matched_ids,
                        page_activated=page_activated,
                        page_aria_matched=page_aria_matched,
                        activation_log=activation_log,
                        activation_budget_met=activation_budget_met,
                        visit_queue=visit_queue,
                        visited_urls=visited_urls,
                        events=events,
                        job_tracker=job_tracker,
                        total_steps=total_steps,
                        page_step=page_step,
                        max_total_steps=max_total_steps,
                        max_steps_per_page=max_steps_per_page,
                    )

                    while page_step < max_steps_per_page and total_steps < max_total_steps:
                        aria_text = aria_snapshot_for_page(page)
                        live_nodes = candidates_from_aria_snapshot(aria_text)

                        for action in expected:
                            match = _match_action_to_aria(action, live_nodes)
                            if match:
                                aid = str(action.get("id"))
                                aria_matched_ids.add(aid)
                                if aid not in page_aria_matched:
                                    page_aria_matched.append(aid)

                        active_job = job_tracker.active_job()
                        active_keywords = list(active_job.get("nav_keywords") or []) if active_job else []

                        decision = decide_next_browser_action(
                            page_url=page.url,
                            page_path=path,
                            aria_snapshot=aria_text,
                            candidates=live_nodes,
                            step=total_steps,
                            max_steps=max_total_steps,
                            history=history,
                            universe_totals=universe.get("totals") or {},
                            pages_remaining=len(visit_queue),
                            explore_job_context=job_tracker.prompt_context(),
                            active_nav_keywords=active_keywords,
                        )
                        policy = str(decision.get("policy") or "unknown")
                        policy_counts[policy] = policy_counts.get(policy, 0) + 1

                        if decision.get("action") in {"done", "stop"}:
                            history.append(
                                {
                                    "step": total_steps,
                                    "action": decision.get("action"),
                                    "url": page.url,
                                    "reason": decision.get("reason"),
                                }
                            )
                            break

                        role = str(decision.get("role") or "")
                        name = str(decision.get("name") or "")
                        if not role or not name:
                            break

                        action_id = _resolve_action_id(expected, role, name, activated_ids)
                        try:
                            before_url = page.url
                            locator = _role_locator(page, role, name, action_id, expected)
                            locator.first.click(timeout=5000)
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=3000)
                            except Exception:
                                pass
                            _wait_after_dom(page)
                            after_url = page.url
                            navigated = _url_key(before_url) != _url_key(after_url)
                            link_like = role.lower() == "link"
                            click_success = navigated or not link_like
                            activated_ids.add(action_id)
                            page_activated.append(action_id)
                            activation_log.append(
                                _activation_log_row(
                                    _action_for_id(expected, action_id),
                                    page.url,
                                    step_index=total_steps,
                                    in_static_html=action_in_static_html(
                                        _action_for_id(expected, action_id) or {},
                                        static_html,
                                    ),
                                    in_hydrated_tree=True,
                                    activation_attempted=True,
                                    activation_result="clicked",
                                )
                            )
                            job_tracker.record_click(
                                name,
                                page.url,
                                success=click_success,
                                navigated=navigated,
                            )
                            total_steps += 1
                            page_step += 1
                            shot_path = _save_screenshot(page, screenshot_dir, page_id, total_steps)
                            events.append(
                                _explore_event(
                                    run_id,
                                    session_id,
                                    snapshot.phase,
                                    total_steps,
                                    page.url,
                                    OperatorActionType.CLICK.value,
                                    element_role=role,
                                    element_name=name,
                                    success=click_success,
                                    metadata={
                                        "action_id": action_id,
                                        "policy": policy,
                                        "reason": decision.get("reason"),
                                        "navigated": navigated,
                                        "screenshots": {"after_click": _shot_ref(run_id, shot_path)},
                                    },
                                )
                            )
                            history.append(
                                {
                                    "step": total_steps,
                                    "action": "click",
                                    "role": role,
                                    "name": name,
                                    "url": page.url,
                                    "reason": decision.get("reason"),
                                }
                            )
                            _enqueue_same_origin(page.url, visit_queue, visited_urls, source_url)
                        except Exception as exc:
                            activation_log.append(
                                {
                                    "action_id": action_id,
                                    "page_url": page.url,
                                    "role": role,
                                    "accessible_name": name,
                                    "activation_attempted": True,
                                    "activation_result": "timeout",
                                    "step_index": total_steps,
                                    "error": str(exc),
                                }
                            )
                            total_steps += 1
                            events.append(
                                _explore_event(
                                    run_id,
                                    session_id,
                                    snapshot.phase,
                                    total_steps,
                                    page.url,
                                    OperatorActionType.EXIT.value,
                                    element_role=role,
                                    element_name=name,
                                    metadata={"error": str(exc), "policy": policy},
                                )
                            )
                            break

                except Exception as exc:
                    if str(exc) == "CANCELLED":
                        raise
                    page_error = str(exc)
                    events.append(
                        _explore_event(
                            run_id,
                            session_id,
                            snapshot.phase,
                            total_steps,
                            page_url,
                            OperatorActionType.EXIT.value,
                            element_name="navigation_failed",
                            metadata={"error": page_error, "path": path},
                        )
                    )

                page_results.append(
                    {
                        "page_id": page_id,
                        "path": path,
                        "url": page_url,
                        "expected_on_site_actions": len(expected),
                        "aria_matched_actions": len(page_aria_matched),
                        "activated_actions": len(page_activated),
                        "strategy_page_type": _strategy_page_type_for_path(universe, path),
                        "signals": initial_signals if page_error == "" else {},
                        "error": page_error or None,
                    }
                )

            probe_results, total_steps = _run_strategy_probes(
                page=page,
                run_id=run_id,
                session_id=session_id,
                phase=snapshot.phase,
                source_url=source_url,
                probe_plan=probe_plan,
                universe=universe,
                page_html_by_id=page_html_by_id,
                probe_actions_by_page=probe_actions_by_page,
                screenshot_dir=screenshot_dir,
                events=events,
                activation_log=activation_log,
                activated_ids=activated_ids,
                aria_matched_ids=aria_matched_ids,
                total_steps=total_steps,
                max_total_steps=max_total_steps,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )

        finally:
            page.close()
            context.close()
            browser.close()

    on_site_total = len(on_site_actions) or 1
    mode = "cursor_llm_agent" if llm_active else "cursor_aria_heuristic"
    crawler_quality = _crawler_quality_metrics(universe, page_results, probe_results)
    return {
        "mode": mode,
        "llm_enabled": llm_active,
        "strategy_probe_plan": probe_plan,
        "strategy_probe_results": probe_results,
        "crawler_quality": crawler_quality,
        "policy_counts": policy_counts,
        "pages_visited": len(page_results),
        "total_steps": total_steps,
        "on_site_actions": len(on_site_actions),
        "aria_match_rate": round(len(aria_matched_ids) / on_site_total, 4),
        "activation_rate": round(len(activated_ids) / on_site_total, 4),
        "aria_matched_action_ids": sorted(aria_matched_ids),
        "activated_action_ids": sorted(activated_ids),
        "page_results": page_results,
        "events_count": len(events),
        "events": [e.to_dict() for e in events],
        "explore_jobs": explore_jobs,
        "job_progress": job_tracker.progress_payload(),
        "explore_min_steps": min_steps_required,
        "explore_valid": total_steps >= min_steps_required,
        "activation_log": activation_log[:200],
        "explore_prompt_appendix": EXPLORE_AGENT_APPENDIX.strip(),
        "activation_budget": activation_budget_summary(activation_budget_met, universe),
        "note": (
            "Cursor-style simulation: Playwright aria_snapshot + getByRole. "
            + (
                "LLM chooses each click from the accessibility tree."
                if llm_active
                else "Set LLM_API_KEY for LLM-driven policy (heuristic fallback active)."
            )
        ),
    }


def _run_catalog_activation_pass(
    *,
    page: Any,
    path: str,
    page_url: str,
    page_id: str,
    expected: List[Dict[str, Any]],
    static_html: str,
    source_url: str,
    run_id: str,
    session_id: str,
    phase: str,
    screenshot_dir: str,
    activated_ids: Set[str],
    aria_matched_ids: Set[str],
    page_activated: List[str],
    page_aria_matched: List[str],
    activation_log: List[Dict[str, Any]],
    activation_budget_met: Set[str],
    visit_queue: deque,
    visited_urls: Set[str],
    events: List[OperatorEvent],
    job_tracker: ExploreJobTracker,
    total_steps: int,
    page_step: int,
    max_total_steps: int,
    max_steps_per_page: int,
) -> Tuple[int, int]:
    picks = pick_catalog_actions_for_page(
        path,
        expected,
        activated_ids=activated_ids,
        budget_met=activation_budget_met,
    )
    for action in picks:
        if page_step >= max_steps_per_page or total_steps >= max_total_steps:
            break
        total_steps, page_step, clicked = _try_activate_catalog_action(
            page=page,
            action=action,
            static_html=static_html,
            run_id=run_id,
            session_id=session_id,
            phase=phase,
            page_id=page_id,
            screenshot_dir=screenshot_dir,
            source_url=source_url,
            activated_ids=activated_ids,
            aria_matched_ids=aria_matched_ids,
            page_activated=page_activated,
            page_aria_matched=page_aria_matched,
            activation_log=activation_log,
            visit_queue=visit_queue,
            visited_urls=visited_urls,
            events=events,
            job_tracker=job_tracker,
            total_steps=total_steps,
            page_step=page_step,
            policy="catalog_activation",
        )
        if clicked:
            record_budget_progress(path, action, activation_budget_met)
    return total_steps, page_step


def _try_activate_catalog_action(
    *,
    page: Any,
    action: Dict[str, Any],
    static_html: str,
    run_id: str,
    session_id: str,
    phase: str,
    page_id: str,
    screenshot_dir: str,
    source_url: str,
    activated_ids: Set[str],
    aria_matched_ids: Set[str],
    page_activated: List[str],
    page_aria_matched: List[str],
    activation_log: List[Dict[str, Any]],
    visit_queue: deque,
    visited_urls: Set[str],
    events: List[OperatorEvent],
    job_tracker: ExploreJobTracker,
    total_steps: int,
    page_step: int,
    policy: str,
) -> Tuple[int, int, bool]:
    label = str(action.get("label") or "")
    role = str(action.get("role") or "link")
    aid = str(action.get("id") or "")
    in_static = action_in_static_html(action, static_html)
    aria_text = aria_snapshot_for_page(page)
    live_nodes = candidates_from_aria_snapshot(aria_text)
    match = _match_action_to_aria(action, live_nodes)
    in_hydrated = bool(match)
    if match:
        aria_matched_ids.add(aid)
        if aid not in page_aria_matched:
            page_aria_matched.append(aid)

    if not in_hydrated:
        activation_log.append(
            _activation_log_row(
                action,
                page.url,
                step_index=total_steps,
                in_static_html=in_static,
                in_hydrated_tree=False,
                activation_attempted=True,
                activation_result="not_found",
            )
        )
        return total_steps, page_step, False

    try:
        before_url = page.url
        _role_locator(page, role, label).first.click(timeout=5000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        _wait_after_dom(page)
        navigated = _url_key(before_url) != _url_key(page.url)
        activated_ids.add(aid)
        page_activated.append(aid)
        activation_log.append(
            _activation_log_row(
                action,
                page.url,
                step_index=total_steps + 1,
                in_static_html=in_static,
                in_hydrated_tree=True,
                activation_attempted=True,
                activation_result="clicked",
            )
        )
        job_tracker.record_click(label, page.url, success=navigated or role.lower() != "link", navigated=navigated)
        total_steps += 1
        page_step += 1
        events.append(
            _explore_event(
                run_id,
                session_id,
                phase,
                total_steps,
                page.url,
                OperatorActionType.CLICK.value,
                element_role=role,
                element_name=label,
                success=True,
                metadata={
                    "action_id": aid,
                    "policy": policy,
                    "navigated": navigated,
                    "catalog_activation": True,
                },
            )
        )
        _enqueue_same_origin(page.url, visit_queue, visited_urls, source_url)
        return total_steps, page_step, True
    except Exception as exc:
        err = str(exc).lower()
        result = "obscured" if "intercepts" in err or "not visible" in err else "timeout"
        activation_log.append(
            _activation_log_row(
                action,
                page.url,
                step_index=total_steps,
                in_static_html=in_static,
                in_hydrated_tree=True,
                activation_attempted=True,
                activation_result=result,
            )
        )
        return total_steps, page_step, False


def _run_strategy_probes(
    *,
    page: Any,
    run_id: str,
    session_id: str,
    phase: str,
    source_url: str,
    probe_plan: List[Dict[str, Any]],
    universe: Dict[str, Any],
    page_html_by_id: Dict[str, str],
    probe_actions_by_page: Dict[str, List[Dict[str, Any]]],
    screenshot_dir: str,
    events: List[OperatorEvent],
    activation_log: List[Dict[str, Any]],
    activated_ids: Set[str],
    aria_matched_ids: Set[str],
    total_steps: int,
    max_total_steps: int,
    on_progress: Optional[Callable[[str, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    results: List[Dict[str, Any]] = []
    for probe in probe_plan:
        step_id = str(probe.get("step_id") or "")
        label = str(probe.get("label") or step_id)
        start_path = str(probe.get("start_path") or "/")
        start_url = urljoin(source_url, start_path)

        if should_cancel and should_cancel():
            raise RuntimeError("CANCELLED")
        if total_steps >= max_total_steps:
            results.append(
                {
                    "id": probe.get("id") or f"probe_{step_id}",
                    "step_id": step_id,
                    "label": label,
                    "start_path": start_path,
                    "final_path": "",
                    "final_url": "",
                    "status": "not_attempted",
                    "attempted": False,
                    "safe_mode": probe.get("safe_mode") or "standard",
                    "fallback_used": bool(probe.get("fallback_used")),
                    "evidence": "Probe budget exhausted before this step ran.",
                    "signals_before": {},
                    "signals_after": {},
                    "interaction": {"attempted": False, "clicked": False, "navigated": False},
                }
            )
            continue

        if on_progress:
            on_progress(f"Probing {label}", total_steps + 1)

        before: Dict[str, Any] = {}
        after: Dict[str, Any] = {}
        interaction: Dict[str, Any] = {"attempted": False, "clicked": False, "navigated": False}
        current_page_id = ""
        static_html = ""
        try:
            page.goto(start_url, wait_until="domcontentloaded", timeout=30_000)
            _wait_after_dom(page)
            total_steps += 1
            current_path = urlparse(page.url).path or "/"
            current_page_id = _page_id_for_path(current_path, universe)
            static_html = page_html_by_id.get(current_page_id, "")
            before_nodes = candidates_from_aria_snapshot(aria_snapshot_for_page(page))
            before = _probe_signal_snapshot(
                page_url=page.url,
                static_html=static_html,
                live_nodes=before_nodes,
                expected_page_type=_strategy_page_type_for_path(universe, current_path),
            )
            shot_path = _save_screenshot(page, screenshot_dir, f"probe_{step_id}", total_steps)
            events.append(
                _explore_event(
                    run_id,
                    session_id,
                    phase,
                    total_steps,
                    page.url,
                    OperatorActionType.VIEW_PAGE.value,
                    element_name=label,
                    metadata={
                        "strategy_probe": step_id,
                        "path": current_path,
                        "screenshots": {"probe": _shot_ref(run_id, shot_path)},
                    },
                )
            )

            interaction = _execute_strategy_probe_step(
                step_id=step_id,
                label=label,
                page=page,
                source_url=source_url,
                page_actions=probe_actions_by_page.get(current_page_id) or [],
                static_html=static_html,
                run_id=run_id,
                session_id=session_id,
                phase=phase,
                events=events,
                activation_log=activation_log,
                activated_ids=activated_ids,
                aria_matched_ids=aria_matched_ids,
                total_steps_ref=[total_steps],
            )
            total_steps = int(interaction.get("total_steps") or total_steps)
            after_nodes = candidates_from_aria_snapshot(aria_snapshot_for_page(page))
            after = _probe_signal_snapshot(
                page_url=page.url,
                static_html=static_html,
                live_nodes=after_nodes,
                expected_page_type=_strategy_page_type_for_path(universe, urlparse(page.url).path or "/"),
            )
            status, evidence = _probe_outcome(
                step_id=step_id,
                source_url=source_url,
                before=before,
                after=after,
                interaction=interaction,
                final_url=page.url,
            )
            results.append(
                {
                    "id": probe.get("id") or f"probe_{step_id}",
                    "step_id": step_id,
                    "label": label,
                    "start_path": start_path,
                    "final_path": urlparse(page.url).path or "/",
                    "final_url": page.url,
                    "status": status,
                    "attempted": True,
                    "safe_mode": probe.get("safe_mode") or "standard",
                    "fallback_used": bool(probe.get("fallback_used")),
                    "evidence": evidence,
                    "signals_before": before,
                    "signals_after": after,
                    "interaction": {
                        "attempted": bool(interaction.get("attempted")),
                        "clicked": bool(interaction.get("clicked")),
                        "navigated": bool(interaction.get("navigated")),
                        "action_id": interaction.get("action_id") or "",
                        "error": interaction.get("error") or "",
                    },
                }
            )
        except Exception as exc:
            if str(exc) == "CANCELLED":
                raise
            results.append(
                {
                    "id": probe.get("id") or f"probe_{step_id}",
                    "step_id": step_id,
                    "label": label,
                    "start_path": start_path,
                    "final_path": urlparse(page.url).path or "",
                    "final_url": page.url if getattr(page, "url", "") else "",
                    "status": "blocked",
                    "attempted": True,
                    "safe_mode": probe.get("safe_mode") or "standard",
                    "fallback_used": bool(probe.get("fallback_used")),
                    "evidence": f"Probe could not complete: {exc}",
                    "signals_before": before,
                    "signals_after": after,
                    "interaction": {
                        "attempted": bool(interaction.get("attempted")),
                        "clicked": bool(interaction.get("clicked")),
                        "navigated": bool(interaction.get("navigated")),
                        "action_id": interaction.get("action_id") or "",
                        "error": str(exc),
                    },
                }
            )
    return results, total_steps


def _execute_strategy_probe_step(
    *,
    step_id: str,
    label: str,
    page: Any,
    source_url: str,
    page_actions: List[Dict[str, Any]],
    static_html: str,
    run_id: str,
    session_id: str,
    phase: str,
    events: List[OperatorEvent],
    activation_log: List[Dict[str, Any]],
    activated_ids: Set[str],
    aria_matched_ids: Set[str],
    total_steps_ref: List[int],
) -> Dict[str, Any]:
    interaction: Dict[str, Any] = {"attempted": False, "clicked": False, "navigated": False}
    if step_id in {"homepage", "product_page", "collection_search"}:
        interaction["total_steps"] = total_steps_ref[0]
        return interaction

    live_nodes = candidates_from_aria_snapshot(aria_snapshot_for_page(page))
    if step_id == "variant_selection":
        candidate = _probe_candidate(step_id, page_actions, live_nodes)
        if candidate:
            return _click_probe_candidate(
                page=page,
                candidate=candidate,
                page_actions=page_actions,
                static_html=static_html,
                run_id=run_id,
                session_id=session_id,
                phase=phase,
                step_id=step_id,
                events=events,
                activation_log=activation_log,
                activated_ids=activated_ids,
                aria_matched_ids=aria_matched_ids,
                total_steps_ref=total_steps_ref,
            )
        interaction["total_steps"] = total_steps_ref[0]
        return interaction

    if step_id in {"add_to_cart", "cart", "checkout_handoff"}:
        sequence = _probe_sequence_for_step(step_id)
        for action_kind in sequence:
            live_nodes = candidates_from_aria_snapshot(aria_snapshot_for_page(page))
            signals = _probe_signal_snapshot(page_url=page.url, static_html=static_html, live_nodes=live_nodes)
            if step_id == "cart" and signals["cart_visible"]["hydrated"]:
                break
            if step_id == "checkout_handoff" and signals["checkout_visible"]["hydrated"]:
                action_kind = "checkout_handoff"
            candidate = _probe_candidate(action_kind, page_actions, live_nodes)
            if not candidate:
                continue
            interaction = _click_probe_candidate(
                page=page,
                candidate=candidate,
                page_actions=page_actions,
                static_html=static_html,
                run_id=run_id,
                session_id=session_id,
                phase=phase,
                step_id=step_id,
                events=events,
                activation_log=activation_log,
                activated_ids=activated_ids,
                aria_matched_ids=aria_matched_ids,
                total_steps_ref=total_steps_ref,
            )
            if interaction.get("clicked"):
                break
        interaction["total_steps"] = total_steps_ref[0]
        return interaction

    interaction["total_steps"] = total_steps_ref[0]
    return interaction


def _probe_outcome(
    *,
    step_id: str,
    source_url: str,
    before: Dict[str, Any],
    after: Dict[str, Any],
    interaction: Dict[str, Any],
    final_url: str,
) -> Tuple[str, str]:
    if step_id == "homepage":
        if after.get("page_path") == "/":
            return "pass", "Probe opened the homepage and captured hydrated navigation signals."
        return "partial", "Probe ran, but the final path was not the homepage."
    if step_id == "collection_search":
        if after.get("page_type") in {"collection", "search"}:
            return "pass", "Probe opened a collection/search surface and captured hydrated DOM evidence."
        if before.get("page_type") in {"collection", "search"}:
            return "partial", "Probe started from a collection/search surface, but product discovery signals stayed weak."
        return "blocked", "Probe did not find a collection/search surface to validate."
    if step_id == "product_page":
        if after.get("page_type") == "product" or after["add_to_cart_visible"]["hydrated"] or after["variant_controls"]["hydrated"]:
            return "pass", "Probe opened a product page and captured hydrated purchase controls."
        return "blocked", "Probe did not reach a product page with visible purchase controls."
    if step_id == "variant_selection":
        if interaction.get("clicked"):
            return "pass", "Probe found hydrated variant controls and activated one."
        if after["variant_controls"]["hydrated"] or before["variant_controls"]["hydrated"]:
            return "partial", "Probe found variant controls, but selected state was not confirmed."
        return "blocked", "Probe did not find a hydrated variant control to validate."
    if step_id == "add_to_cart":
        if interaction.get("clicked") and (after["cart_visible"]["hydrated"] or after["checkout_visible"]["hydrated"]):
            return "pass", "Probe clicked add-to-cart and observed cart/checkout state in the hydrated DOM."
        if interaction.get("clicked"):
            return "partial", "Probe clicked add-to-cart, but cart confirmation was not clearly visible."
        if after["add_to_cart_visible"]["hydrated"] or before["add_to_cart_visible"]["hydrated"]:
            return "blocked", "Probe saw an add-to-cart control but could not activate it."
        return "blocked", "Probe did not find an add-to-cart control to validate."
    if step_id == "cart":
        if after["cart_visible"]["hydrated"] and (after["checkout_visible"]["hydrated"] or after["line_item_visible"]["hydrated"]):
            return "pass", "Probe validated cart visibility and found checkout or line-item state."
        if after["cart_visible"]["hydrated"]:
            return "partial", "Probe found cart state, but checkout/line-item confirmation stayed weak."
        if interaction.get("clicked"):
            return "blocked", "Probe attempted cart activation, but cart state never became visible."
        return "blocked", "Probe did not find a cart surface to validate."
    if step_id == "checkout_handoff":
        if interaction.get("clicked") and _is_checkout_like_url(source_url, final_url):
            return "pass", "Probe clicked checkout and validated a safe checkout handoff."
        if after["checkout_visible"]["hydrated"] or before["checkout_visible"]["hydrated"]:
            return "partial", "Probe found checkout visibility, but handoff was not validated end-to-end."
        return "blocked", "Probe did not find a checkout handoff control to validate."
    return "partial", "Probe completed with limited evidence."


def _probe_sequence_for_step(step_id: str) -> List[str]:
    if step_id == "add_to_cart":
        return ["add_to_cart"]
    if step_id == "cart":
        return ["cart", "add_to_cart"]
    if step_id == "checkout_handoff":
        return ["checkout_handoff", "cart", "add_to_cart", "checkout_handoff"]
    return [step_id]


def _probe_candidate(
    step_id: str,
    page_actions: List[Dict[str, Any]],
    live_nodes: List[Dict[str, str]],
) -> Optional[Dict[str, Any]]:
    for action in _probe_actions_for_step(step_id, page_actions):
        if not _probe_action_allowed(step_id, action):
            continue
        match = _match_action_to_aria(action, live_nodes)
        if match:
            return {
                "action": action,
                "action_id": str(action.get("id") or ""),
                "role": str(action.get("role") or match.get("role") or "button"),
                "name": str(match.get("name") or catalog_accessible_name(action) or ""),
            }
    node = _first_probe_node(step_id, live_nodes, _probe_tokens_for_step(step_id))
    if node:
        return {
            "action": None,
            "action_id": "",
            "role": str(node.get("role") or "button"),
            "name": str(node.get("name") or ""),
        }
    return None


def _click_probe_candidate(
    *,
    page: Any,
    candidate: Dict[str, Any],
    page_actions: List[Dict[str, Any]],
    static_html: str,
    run_id: str,
    session_id: str,
    phase: str,
    step_id: str,
    events: List[OperatorEvent],
    activation_log: List[Dict[str, Any]],
    activated_ids: Set[str],
    aria_matched_ids: Set[str],
    total_steps_ref: List[int],
) -> Dict[str, Any]:
    role = str(candidate.get("role") or "button")
    name = str(candidate.get("name") or "")
    action = candidate.get("action") or {}
    action_id = str(candidate.get("action_id") or "")
    activation_id = action_id or f"llm_{role}_{name[:24]}"
    in_static = action_in_static_html(action, static_html) if action else _text_has_any(static_html, (name,))
    if action_id:
        aria_matched_ids.add(action_id)
    interaction = {"attempted": True, "clicked": False, "navigated": False, "action_id": activation_id}
    try:
        before_url = page.url
        _role_locator(page, role, name, action_id, page_actions).first.click(timeout=4000)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        _wait_after_dom(page)
        navigated = _url_key(before_url) != _url_key(page.url)
        total_steps_ref[0] += 1
        activated_ids.add(activation_id)
        activation_log.append(
            _activation_log_row(
                action,
                page.url,
                step_index=total_steps_ref[0],
                in_static_html=in_static,
                in_hydrated_tree=True,
                activation_attempted=True,
                activation_result="clicked",
            )
        )
        events.append(
            _explore_event(
                run_id,
                session_id,
                phase,
                total_steps_ref[0],
                page.url,
                OperatorActionType.CLICK.value,
                element_role=role,
                element_name=name,
                success=True,
                metadata={
                    "strategy_probe": step_id,
                    "action_id": activation_id,
                    "navigated": navigated,
                },
            )
        )
        interaction.update({"clicked": True, "navigated": navigated, "total_steps": total_steps_ref[0]})
        return interaction
    except Exception as exc:
        activation_log.append(
            _activation_log_row(
                action,
                page.url,
                step_index=total_steps_ref[0],
                in_static_html=in_static,
                in_hydrated_tree=True,
                activation_attempted=True,
                activation_result="timeout",
            )
        )
        events.append(
            _explore_event(
                run_id,
                session_id,
                phase,
                total_steps_ref[0],
                page.url,
                OperatorActionType.CLICK.value,
                element_role=role,
                element_name=name,
                success=False,
                metadata={
                    "strategy_probe": step_id,
                    "action_id": activation_id,
                    "error": str(exc),
                },
            )
        )
        interaction.update({"error": str(exc), "total_steps": total_steps_ref[0]})
        return interaction


def _probe_actions_for_step(step_id: str, page_actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    roles = set(_PROBE_ACTION_ROLES.get(step_id) or ())
    rows: List[Dict[str, Any]] = []
    for action in page_actions:
        action_role = str(action.get("action_role") or "")
        buyer_step = str(action.get("buyer_step") or "")
        if action_role in roles or buyer_step == step_id:
            rows.append(action)
    return rows


def _probe_action_allowed(step_id: str, action: Dict[str, Any]) -> bool:
    label = str(action.get("element_text") or action.get("label") or "").lower()
    target = str(action.get("target_path") or action.get("raw_target") or "").lower()
    action_role = str(action.get("action_role") or "")
    if step_id == "variant_selection" and _text_has_any(label, _VARIANT_DECOY_TOKENS):
        return False
    if step_id == "checkout_handoff":
        if action_role != "checkout_link" and not (target.startswith("/checkout") or "/checkouts" in target):
            return False
        if _text_has_any(label, _CHECKOUT_DECOY_TOKENS):
            return False
    return True


def _probe_tokens_for_step(step_id: str) -> Tuple[str, ...]:
    if step_id == "variant_selection":
        return _VARIANT_TOKENS
    if step_id == "add_to_cart":
        return _ADD_TO_CART_TOKENS
    if step_id == "cart":
        return _CART_TOKENS + _CART_STATE_TOKENS
    if step_id == "checkout_handoff":
        return _CHECKOUT_TOKENS
    if step_id == "collection_search":
        return ("shop", "collection", "search")
    return ()


def _first_probe_node(
    step_id: str,
    live_nodes: List[Dict[str, str]],
    tokens: Tuple[str, ...],
) -> Optional[Dict[str, str]]:
    for node in live_nodes:
        role = str(node.get("role") or "").lower()
        name = str(node.get("name") or "").strip()
        lower = name.lower()
        if role not in {"button", "link", "radio", "option", "checkbox"}:
            continue
        if any(token in lower for token in tokens):
            if step_id == "variant_selection" and _text_has_any(lower, _VARIANT_DECOY_TOKENS):
                continue
            if step_id == "checkout_handoff" and _text_has_any(lower, _CHECKOUT_DECOY_TOKENS):
                continue
            return node
    return None


def _probe_signal_snapshot(
    *,
    page_url: str,
    static_html: str,
    live_nodes: List[Dict[str, str]],
    expected_page_type: str = "",
) -> Dict[str, Any]:
    cart_nodes = _cart_signal_nodes(live_nodes)
    checkout_nodes = _checkout_signal_nodes(live_nodes)
    add_to_cart_nodes = _nodes_matching_tokens(live_nodes, _ADD_TO_CART_TOKENS)
    variant_nodes = _nodes_matching_tokens(live_nodes, _VARIANT_TOKENS)
    line_item_nodes = _nodes_matching_tokens(live_nodes, _LINE_ITEM_TOKENS)
    path = urlparse(page_url).path or "/"
    return {
        "page_path": path,
        "page_type": expected_page_type or _probe_page_type(path),
        "primary_ctas": [str(node.get("name") or "")[:80] for node in (add_to_cart_nodes + checkout_nodes)[:4]],
        "variant_controls": {
            "static": _text_has_any(static_html, _VARIANT_TOKENS),
            "hydrated": bool(variant_nodes),
            "names": [str(node.get("name") or "")[:60] for node in variant_nodes[:4]],
        },
        "add_to_cart_visible": {
            "static": _text_has_any(static_html, _ADD_TO_CART_TOKENS),
            "hydrated": bool(add_to_cart_nodes),
        },
        "cart_visible": {
            "static": _text_has_any(static_html, _CART_STATE_TOKENS),
            "hydrated": bool(cart_nodes),
        },
        "checkout_visible": {
            "static": _text_has_any(static_html, _CHECKOUT_TOKENS),
            "hydrated": bool(checkout_nodes),
        },
        "line_item_visible": {
            "static": _text_has_any(static_html, _LINE_ITEM_TOKENS),
            "hydrated": bool(line_item_nodes),
        },
    }


def _nodes_matching_tokens(live_nodes: List[Dict[str, str]], tokens: Tuple[str, ...]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for node in live_nodes:
        name = str(node.get("name") or "").lower()
        if any(token in name for token in tokens):
            rows.append(node)
    return rows


def _cart_signal_nodes(live_nodes: List[Dict[str, str]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for node in live_nodes:
        role = str(node.get("role") or "").lower()
        name = str(node.get("name") or "").lower()
        if role not in {"button", "link", "dialog", "region"}:
            continue
        if _text_has_any(name, _ADD_TO_CART_TOKENS):
            continue
        if _text_has_any(name, _CART_STATE_TOKENS) or _text_has_any(name, _CART_CONTROL_TOKENS):
            rows.append(node)
    return rows


def _checkout_signal_nodes(live_nodes: List[Dict[str, str]]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for node in live_nodes:
        role = str(node.get("role") or "").lower()
        name = str(node.get("name") or "").lower()
        if role not in {"button", "link"}:
            continue
        if _text_has_any(name, _CHECKOUT_DECOY_TOKENS):
            continue
        if _text_has_any(name, _CHECKOUT_TOKENS):
            rows.append(node)
    return rows


def _text_has_any(text: str, tokens: Tuple[str, ...]) -> bool:
    lower = str(text or "").lower()
    return any(token.lower() in lower for token in tokens if token)


def _probe_page_type(path: str) -> str:
    norm = (path or "/").lower()
    if norm == "/":
        return "homepage"
    if norm.startswith("/products") or norm.startswith("/product"):
        return "product"
    if norm.startswith("/collections") or norm.startswith("/collection"):
        return "collection"
    if norm.startswith("/cart"):
        return "cart"
    if norm.startswith("/checkout") or "/checkouts" in norm:
        return "checkout_handoff"
    if norm.startswith("/search"):
        return "search"
    return ""


def _strategy_page_type_for_path(universe: Dict[str, Any], path: str) -> str:
    norm = urlparse(path).path if path.startswith("http") else path
    norm = norm or "/"
    for page in universe.get("pages") or []:
        if str(page.get("path") or "/") != norm:
            continue
        strategy = page.get("strategy") or {}
        page_type = str(strategy.get("page_type") or "")
        if page_type:
            return page_type
    return _probe_page_type(norm)


def _actions_by_page(actions: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    rows: Dict[str, List[Dict[str, Any]]] = {}
    for action in actions:
        page_id = str(action.get("page_id") or "")
        if not page_id:
            continue
        rows.setdefault(page_id, []).append(action)
    return rows


def _probe_step_budget(probe_plan: List[Dict[str, Any]]) -> int:
    if not probe_plan:
        return 0
    return min(18, max(6, len(probe_plan) * 3))


def _is_checkout_like_url(source_url: str, url: str) -> bool:
    parsed = urlparse(urljoin(source_url, url))
    path = parsed.path or "/"
    host = (parsed.hostname or "").lower()
    return path.startswith("/checkout") or "/checkouts" in path or ".checkout." in host or host.startswith("checkout.")


def _crawler_quality_metrics(
    universe: Dict[str, Any],
    page_results: List[Dict[str, Any]],
    probe_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    strategy_pages = universe.get("pages") or []
    visited_types = {
        str(result.get("strategy_page_type") or "") for result in page_results if result.get("strategy_page_type")
    }
    total_product_pages = sum(1 for page in strategy_pages if str((page.get("strategy") or {}).get("page_type") or "") == "product")
    total_collection_pages = sum(1 for page in strategy_pages if str((page.get("strategy") or {}).get("page_type") or "") in {"collection", "search"})
    product_hits = sum(1 for result in page_results if result.get("strategy_page_type") == "product")
    collection_hits = sum(1 for result in page_results if result.get("strategy_page_type") in {"collection", "search"})
    probe_by_step = {str(row.get("step_id") or ""): row for row in probe_results}
    top_steps = ("product_page", "add_to_cart", "checkout_handoff")
    top_steps_with_evidence = sum(
        1
        for step in top_steps
        if str((probe_by_step.get(step) or {}).get("status") or "") in {"pass", "partial", "blocked"}
    )

    return {
        "product_page_hit_rate": round(100.0 * product_hits / max(total_product_pages, 1), 1) if total_product_pages else 0.0,
        "collection_page_hit_rate": round(100.0 * collection_hits / max(total_collection_pages, 1), 1) if total_collection_pages else 0.0,
        "add_to_cart_probe_success_rate": _probe_step_rate(probe_results, "add_to_cart", passing={"pass"}),
        "cart_visibility_rate": _probe_visibility_rate(probe_results, "cart", "cart_visible"),
        "checkout_handoff_validation_rate": _probe_step_rate(probe_results, "checkout_handoff", passing={"pass"}),
        "top_funnel_evidence_rate": round(100.0 * top_steps_with_evidence / len(top_steps), 1),
        "visited_strategy_page_types": sorted(visited_types),
    }


def _probe_step_rate(probe_results: List[Dict[str, Any]], step_id: str, *, passing: Set[str]) -> float:
    attempted = [row for row in probe_results if str(row.get("step_id") or "") == step_id]
    if not attempted:
        return 0.0
    success = sum(1 for row in attempted if str(row.get("status") or "") in passing)
    return round(100.0 * success / len(attempted), 1)


def _probe_visibility_rate(probe_results: List[Dict[str, Any]], step_id: str, signal_key: str) -> float:
    attempted = [row for row in probe_results if str(row.get("step_id") or "") == step_id]
    if not attempted:
        return 0.0
    visible = sum(
        1
        for row in attempted
        if bool(((row.get("signals_after") or {}).get(signal_key) or {}).get("hydrated"))
        or bool(((row.get("signals_before") or {}).get(signal_key) or {}).get("hydrated"))
    )
    return round(100.0 * visible / len(attempted), 1)


def _page_html_by_id(snapshot: SiteSnapshot) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for page in snapshot.pages or []:
        pid = str(getattr(page, "id", "") or "")
        html = str(getattr(page, "html", "") or "")
        if pid:
            out[pid] = html
    return out


def _wait_after_dom(page: Any) -> None:
    try:
        page.wait_for_timeout(500)
    except Exception:
        time.sleep(0.5)


def _aria_after_hydration(page: Any, static_html: str) -> Tuple[str, bool]:
    aria_text = aria_snapshot_for_page(page)
    hydrated = False
    if page_html_has_csr_bailout(static_html) or static_html_missing_main_nav(static_html):
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        _wait_after_dom(page)
        aria_text = aria_snapshot_for_page(page)
        hydrated = True
    return aria_text, hydrated


def _role_locator(
    page: Any,
    role: str,
    name: str,
    action_id: str = "",
    expected: Optional[List[Dict[str, Any]]] = None,
) -> Any:
    action = _action_for_id(expected or [], action_id) if expected else None
    if action:
        aria = catalog_accessible_name(action)
        if aria and aria.lower() != name.strip().lower():
            if "back" in aria.lower() or "back" in name.lower():
                return page.get_by_role(role, name=re.compile(r"back", re.I))
            if len(aria) <= 80:
                return page.get_by_role(role, name=re.compile(re.escape(aria[:60]), re.I))
    nav_exact = {"home", "work", "writing", "about", "contact", "blog", "pricing"}
    if role.lower() == "link" and name.strip().lower() in nav_exact:
        return page.get_by_role(role, name=re.compile(rf"^{re.escape(name.strip())}$", re.I))
    if "back" in name.lower() and role.lower() == "link":
        return page.get_by_role(role, name=re.compile(r"back", re.I))
    if role.lower() == "link" and len(name) > 80:
        fragment = re.escape(name.strip()[:40])
        return page.get_by_role(role, name=re.compile(fragment, re.I))
    return page.get_by_role(role, name=name, exact=False)


def _activation_log_row(
    action: Optional[Dict[str, Any]],
    page_url: str,
    *,
    step_index: int,
    in_static_html: bool,
    in_hydrated_tree: bool,
    activation_attempted: bool,
    activation_result: str,
) -> Dict[str, Any]:
    action = action or {}
    return {
        "action_id": action.get("id"),
        "page_url": page_url,
        "role": action.get("role") or "link",
        "accessible_name": action.get("label") or action.get("name") or "",
        "href": action.get("target_path") or action.get("path") or "",
        "in_static_html": in_static_html,
        "in_hydrated_tree": in_hydrated_tree,
        "activation_attempted": activation_attempted,
        "activation_result": activation_result,
        "step_index": step_index,
    }


def _action_for_id(expected: List[Dict[str, Any]], action_id: str) -> Optional[Dict[str, Any]]:
    for action in expected:
        if str(action.get("id")) == action_id:
            return action
    return None


def _build_visit_queue(source_url: str, universe: Dict[str, Any], max_pages: int) -> deque:
    queue: deque = deque()
    seen: Set[str] = set()
    for url in [source_url, *(universe.get("discovered_internal_urls") or [])]:
        key = _url_key(url)
        if key not in seen:
            seen.add(key)
            queue.append(url)
        if len(queue) >= max_pages:
            break
    return queue


def _actions_by_path(actions: List[Dict[str, Any]], source_url: str) -> Dict[str, List[Dict[str, Any]]]:
    by_path: Dict[str, List[Dict[str, Any]]] = {}
    for action in actions:
        path = str(action.get("target_path") or "")
        if not path.startswith("/"):
            target = str(action.get("target_url") or "")
            if target.startswith(source_url):
                path = urlparse(target).path or "/"
            else:
                continue
        by_path.setdefault(path, []).append(action)
    return by_path


def _page_id_for_path(path: str, universe: Dict[str, Any]) -> str:
    for entry in universe.get("pages") or []:
        if str(entry.get("path") or "") == path:
            return str(entry.get("page_id") or path)
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", path.strip("/")) or "home"
    return safe[:40]


def _url_key(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{(parsed.path or '/').rstrip('/') or '/'}"


def _enqueue_same_origin(
    current_url: str,
    queue: deque,
    visited: Set[str],
    source_url: str,
) -> None:
    parsed = urlparse(current_url)
    base = urlparse(source_url)
    if parsed.netloc != base.netloc:
        return
    key = _url_key(current_url)
    if key not in visited:
        queue.append(current_url)


def _match_action_to_aria(action: Dict[str, Any], live_nodes: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    role = str(action.get("role") or "link").lower()
    catalog_names = [_norm_label(n) for n in match_names_for_action(action) if n]
    if not catalog_names:
        return None
    for node in live_nodes:
        if str(node.get("role") or "").lower() != role:
            continue
        live_name = str(node.get("name") or "")
        if any(names_compatible(catalog_name, live_name) for catalog_name in catalog_names):
            return node
    return None


def _norm_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _resolve_action_id(
    expected: List[Dict[str, Any]],
    role: str,
    name: str,
    activated_ids: Set[str],
) -> str:
    for action in expected:
        aid = str(action.get("id") or "")
        if aid in activated_ids:
            continue
        if _match_action_to_aria(action, [{"role": role, "name": name}]):
            return aid
    return f"llm_{role}_{name[:24]}"


def _save_screenshot(page: Any, directory: str, page_id: str, step: int) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_-]+", "_", page_id)[:40]
    path = os.path.join(directory, f"{safe_id}_step{step}.png")
    page.screenshot(path=path, full_page=False)
    return path


def _shot_ref(run_id: str, path: str) -> Dict[str, str]:
    name = os.path.basename(path)
    return {"url": f"/api/ingress/runs/{run_id}/screenshots/{name}", "label": name}


def _explore_event(
    run_id: str,
    session_id: str,
    phase: str,
    step: int,
    url: str,
    action: str,
    *,
    element_role: str = "",
    element_name: str = "",
    success: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> OperatorEvent:
    return OperatorEvent(
        run_id=run_id,
        session_id=session_id,
        task_id="cursor_explore",
        snapshot_phase=phase,
        step=step,
        action=action,
        url=url,
        element_role=element_role,
        element_name=element_name,
        success=success,
        metadata=metadata or {},
    )
