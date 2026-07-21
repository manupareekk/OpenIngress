"""LLM policy that chooses browser actions from the accessibility tree (Cursor-style)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..config import Config
from .aria_tree import format_candidates_for_llm


SYSTEM_PROMPT = """You simulate a Cursor-style browser agent completing specific user jobs on a site.

You ONLY choose actions from the numbered accessibility tree list provided.

Rules:
- Work through the user jobs listed in the prompt — prioritize the current focus job.
- Prefer actions that advance the active job (e.g. Work, Writing, View project, Contact).
- Avoid external links (names containing http, www, or very long marketing sentences).
- Use candidate_index to refer to a line in the list. Do not invent roles or names.
- Return action "done" when the current page/job step is complete or no useful on-site action remains.
- Return action "stop" only if the page failed to load or the tree is empty.

Respond with JSON only:
{
  "action": "click" | "done" | "stop",
  "candidate_index": <number or null>,
  "reason": "<one short sentence>"
}"""


def llm_explorer_enabled(explicit: Optional[bool] = None) -> bool:
    if explicit is False:
        return False
    return Config.llm_available()


def decide_next_browser_action(
    *,
    page_url: str,
    page_path: str,
    aria_snapshot: str,
    candidates: List[Dict[str, str]],
    step: int,
    max_steps: int,
    history: List[Dict[str, Any]],
    universe_totals: Dict[str, Any],
    pages_remaining: int,
    explore_job_context: str = "",
    active_nav_keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not candidates:
        return {"action": "stop", "candidate_index": None, "reason": "No interactive nodes in accessibility tree.", "policy": "heuristic"}

    if not llm_explorer_enabled():
        raise RuntimeError(
            "LLM_API_KEY is required. OpenIngress exploration uses your own model key (BYOK)."
        )

    try:
        return _decide_with_llm(
            page_url=page_url,
            page_path=page_path,
            aria_snapshot=aria_snapshot,
            candidates=candidates,
            step=step,
            max_steps=max_steps,
            history=history,
            universe_totals=universe_totals,
            pages_remaining=pages_remaining,
            explore_job_context=explore_job_context,
            active_nav_keywords=active_nav_keywords,
        )
    except Exception as exc:
        # Keep a single-step salvage so a transient API blip does not abort the whole run mid-page.
        fallback = _decide_with_heuristic(candidates, history, active_nav_keywords=active_nav_keywords)
        fallback["policy"] = "heuristic_fallback"
        fallback["llm_error"] = str(exc)
        return fallback


def _decide_with_llm(
    *,
    page_url: str,
    page_path: str,
    aria_snapshot: str,
    candidates: List[Dict[str, str]],
    step: int,
    max_steps: int,
    history: List[Dict[str, Any]],
    universe_totals: Dict[str, Any],
    pages_remaining: int,
    explore_job_context: str = "",
    active_nav_keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    from ..utils.llm_client import LLMClient

    job_section = explore_job_context.strip()
    if job_section:
        job_section = f"\n{job_section}\n"

    history_lines = []
    for item in history[-8:]:
        history_lines.append(
            f"- step {item.get('step')}: {item.get('action')} "
            f"{item.get('role', '')} \"{item.get('name', '')}\" @ {item.get('url', '')}"
        )

    user_prompt = f"""Current URL: {page_url}
Path: {page_path}
Exploration step: {step} / {max_steps}
Pages remaining in queue: {pages_remaining}

Site catalog (from crawl):
- total actions: {universe_totals.get('actions', 0)}
- on-site actions: {universe_totals.get('on_site_actions', 0)}
- info nodes: {universe_totals.get('info_nodes', 0)}

{job_section}
Recent history:
{chr(10).join(history_lines) if history_lines else "(none)"}

Accessibility tree candidates (pick by candidate_index):
{format_candidates_for_llm(candidates)}

Aria snapshot excerpt:
{(aria_snapshot or '')[:3500]}
"""

    client = LLMClient()
    result = client.chat_json(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.15,
        max_tokens=512,
    )
    action = str(result.get("action") or "done").lower()
    if action not in {"click", "done", "stop"}:
        action = "done"

    index = result.get("candidate_index")
    choice = None
    if action == "click" and index is not None:
        try:
            idx = int(index)
            if 0 <= idx < len(candidates):
                choice = dict(candidates[idx])
        except (TypeError, ValueError):
            choice = None

    if action == "click" and choice is None:
        fallback = _decide_with_heuristic(candidates, history, active_nav_keywords=active_nav_keywords)
        return {
            "action": "click",
            "candidate_index": fallback.get("candidate_index"),
            "role": fallback.get("role"),
            "name": fallback.get("name"),
            "reason": f"LLM pick invalid; heuristic fallback. {result.get('reason', '')}",
            "policy": "llm_invalid_fallback",
        }

    payload = {
        "action": action,
        "candidate_index": index,
        "reason": str(result.get("reason") or ""),
        "policy": "llm",
    }
    if choice:
        payload["role"] = choice["role"]
        payload["name"] = choice["name"]
    return payload


def _decide_with_heuristic(
    candidates: List[Dict[str, str]],
    history: List[Dict[str, Any]],
    active_nav_keywords: Optional[List[str]] = None,
) -> Dict[str, Any]:
    clicked = {
        (item.get("role"), item.get("name"))
        for item in history
        if item.get("action") == "click"
    }
    keywords = [k.lower() for k in (active_nav_keywords or []) if k]

    def score(item: Dict[str, str]) -> int:
        name = str(item.get("name") or "").lower()
        value = 0
        if (item.get("role"), item.get("name")) in clicked:
            return -100
        if item.get("role") == "link":
            value += 3
        if len(name) <= 24:
            value += 2
        if name in {"home", "work", "writing", "about", "blog", "contact"}:
            value += 5
        if keywords and any(kw in name for kw in keywords):
            value += 8
        if any(skip in name for skip in ("http://", "https://", "www.")):
            value -= 10
        if len(name) > 60:
            value -= 4
        return value

    ranked = sorted(enumerate(candidates), key=lambda pair: score(pair[1]), reverse=True)
    for index, item in ranked:
        if score(item) < 0:
            continue
        return {
            "action": "click",
            "candidate_index": index,
            "role": item["role"],
            "name": item["name"],
            "reason": "Heuristic: short on-site link prefered.",
        }
    return {"action": "done", "candidate_index": None, "reason": "No remaining useful candidates.", "policy": "heuristic"}
