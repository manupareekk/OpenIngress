"""Live Playwright operator using the accessibility tree."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from ..models import AgentTask, OperatorActionType, OperatorEvent, SiteSnapshot
from .url_page_importer import normalize_url


from .aria_tree import aria_snapshot_for_page, candidates_from_aria_snapshot as _candidates_from_aria_snapshot


class LiveOperatorRunner:
    def run_tasks(
        self,
        *,
        run_id: str,
        snapshot: SiteSnapshot,
        tasks: List[AgentTask],
        operators_per_task: int = 3,
        max_steps: int = 20,
        device: str = "desktop",
    ) -> List[OperatorEvent]:
        from playwright.sync_api import sync_playwright

        if not snapshot.pages:
            return []
        start_url = _resolve_start_url(snapshot.source_url)
        viewport = {"width": 390, "height": 844} if device == "mobile" else {"width": 1440, "height": 900}
        events: List[OperatorEvent] = []

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for task in tasks:
                for attempt in range(max(1, operators_per_task)):
                    session_id = f"{task.id}_{attempt + 1}_{uuid.uuid4().hex[:6]}"
                    context = browser.new_context(viewport=viewport)
                    page = context.new_page()
                    try:
                        page.goto(start_url, wait_until="domcontentloaded", timeout=30_000)
                    except Exception:
                        events.append(
                            OperatorEvent(
                                run_id=run_id,
                                session_id=session_id,
                                task_id=task.id,
                                snapshot_phase=snapshot.phase,
                                step=0,
                                action=OperatorActionType.EXIT.value,
                                url=start_url,
                                element_name="navigation_failed",
                                metadata={"error": "Could not load start URL"},
                            )
                        )
                        context.close()
                        continue

                    success = False
                    for step in range(1, max_steps + 1):
                        started = time.perf_counter()
                        if self._task_satisfied(page, task):
                            success = True
                            events.append(
                                OperatorEvent(
                                    run_id=run_id,
                                    session_id=session_id,
                                    task_id=task.id,
                                    snapshot_phase=snapshot.phase,
                                    step=step,
                                    action=OperatorActionType.TASK_SUCCESS.value,
                                    url=page.url,
                                    duration_ms=int((time.perf_counter() - started) * 1000),
                                    success=True,
                                )
                            )
                            break

                        aria_text = aria_snapshot_for_page(page)
                        candidates = _candidates_from_aria_snapshot(aria_text)
                        choice = self._pick_candidate(candidates, task)
                        if not choice:
                            events.append(
                                OperatorEvent(
                                    run_id=run_id,
                                    session_id=session_id,
                                    task_id=task.id,
                                    snapshot_phase=snapshot.phase,
                                    step=step,
                                    action=OperatorActionType.EXIT.value,
                                    url=page.url,
                                    element_name="no_actionable_node",
                                    duration_ms=int((time.perf_counter() - started) * 1000),
                                    metadata={"candidates": len(candidates)},
                                )
                            )
                            break

                        try:
                            locator = page.get_by_role(choice["role"], name=choice["name"], exact=False)
                            locator.first.click(timeout=5000)
                            action = OperatorActionType.CLICK.value
                        except Exception as exc:
                            events.append(
                                OperatorEvent(
                                    run_id=run_id,
                                    session_id=session_id,
                                    task_id=task.id,
                                    snapshot_phase=snapshot.phase,
                                    step=step,
                                    action=OperatorActionType.EXIT.value,
                                    url=page.url,
                                    element_role=choice["role"],
                                    element_name=choice["name"],
                                    duration_ms=int((time.perf_counter() - started) * 1000),
                                    metadata={"error": str(exc)},
                                )
                            )
                            break

                        events.append(
                            OperatorEvent(
                                run_id=run_id,
                                session_id=session_id,
                                task_id=task.id,
                                snapshot_phase=snapshot.phase,
                                step=step,
                                action=action,
                                url=page.url,
                                element_role=choice["role"],
                                element_name=choice["name"],
                                duration_ms=int((time.perf_counter() - started) * 1000),
                            )
                        )
                    if not success and not any(
                        event.session_id == session_id and event.action == OperatorActionType.TASK_SUCCESS.value
                        for event in events
                    ):
                        events.append(
                            OperatorEvent(
                                run_id=run_id,
                                session_id=session_id,
                                task_id=task.id,
                                snapshot_phase=snapshot.phase,
                                step=max_steps,
                                action=OperatorActionType.EXIT.value,
                                url=page.url,
                                element_name="max_steps",
                                metadata={"reason": "step_budget_exhausted"},
                            )
                        )
                    context.close()
            browser.close()
        return events

    def _task_satisfied(self, page: Any, task: AgentTask) -> bool:
        url = page.url or ""
        if task.success_url_contains and task.success_url_contains in url:
            return True
        if task.success_text:
            try:
                body = page.inner_text("body", timeout=3000)
                if task.success_text.lower() in body.lower():
                    return True
            except Exception:
                pass
        if task.success_selector:
            try:
                return page.locator(task.success_selector).count() > 0
            except Exception:
                return False
        return False

    def _pick_candidate(self, candidates: List[Dict[str, str]], task: AgentTask) -> Optional[Dict[str, str]]:
        if not candidates:
            return None
        instruction = (task.instruction or "").lower()
        terms = [token for token in re.split(r"\W+", instruction) if len(token) >= 4]
        success_hint = (task.success_text or "").lower()

        def score(item: Dict[str, str]) -> int:
            name = item.get("name", "").lower()
            value = sum(2 for term in terms if term in name)
            if success_hint and success_hint in name:
                value += 8
            if item.get("role") == "link":
                value += 2
            if item.get("role") == "button":
                value += 1
            # Cursor-style browser agents favor short, labeled nav controls over long body copy.
            if len(name) <= 24:
                value += 2
            if any(skip in name for skip in ("http://", "https://", "www.")):
                value -= 6
            if "accessibility" in instruction or "speed" in instruction or "explore" in instruction:
                if name in {"home", "work", "writing", "about", "blog", "contact"}:
                    value += 4
            return value

        ranked = sorted(candidates, key=score, reverse=True)
        return ranked[0] if ranked else None


def _resolve_start_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return value
    try:
        return normalize_url(value)
    except ValueError:
        return value
