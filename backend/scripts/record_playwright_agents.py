#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


@dataclass(frozen=True)
class Case:
    name: str
    url: str
    goal: str


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    started_at_ms: int
    ended_at_ms: int
    details: Dict[str, Any]


@dataclass(frozen=True)
class RunSummary:
    case: Case
    strategy: str
    ok: bool
    started_at_ms: int
    ended_at_ms: int
    steps: List[StepResult]
    artifacts_dir: str


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-").lower()
    return slug or "run"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _rename_single_video(video_dir: Path, dest: Path) -> Optional[str]:
    if not video_dir.exists():
        return None
    candidates = [p for p in video_dir.glob("*") if p.is_file()]
    if not candidates:
        return None
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(newest), str(dest))
    return dest.name


def _dump_dom(page, out_dir: Path) -> None:
    try:
        html = page.content()
    except Exception:
        return
    (out_dir / "dom.html").write_text(html, encoding="utf-8")


def _dump_a11y(page, out_dir: Path) -> None:
    try:
        snapshot = page.accessibility.snapshot(interesting_only=False)
    except Exception:
        snapshot = None
    _write_json(out_dir / "a11y.json", snapshot)


def _dump_url(page, out_dir: Path) -> None:
    try:
        _write_json(out_dir / "location.json", {"url": page.url})
    except Exception:
        pass


def _request_failure_text(req) -> Optional[str]:
    """
    Playwright exposes request failure details differently across versions.
    Normalize to a string and never raise inside event handlers.
    """
    try:
        failure = getattr(req, "failure", None)
        failure = failure() if callable(failure) else failure
        if isinstance(failure, str):
            return failure
        if isinstance(failure, dict):
            return (
                failure.get("errorText")
                or failure.get("error_text")
                or failure.get("message")
                or failure.get("name")
                or json.dumps(failure)
            )
        return None
    except Exception as e:
        return f"failure_parse_error: {e!r}"


def _step(name: str, steps: List[StepResult], fn: Callable[[], Dict[str, Any]]) -> bool:
    started = _now_ms()
    try:
        details = fn() or {}
        ok = True
    except Exception as e:
        ok = False
        details = {"error": repr(e)}
    ended = _now_ms()
    steps.append(StepResult(name=name, ok=ok, started_at_ms=started, ended_at_ms=ended, details=details))
    return ok


def _click_by_accessibility(page, goal: str, timeout_ms: int) -> Dict[str, Any]:
    patterns = [
        ("button", goal),
        ("link", goal),
        ("textbox", goal),
    ]
    last_error: Optional[str] = None
    for role, name in patterns:
        try:
            locator = page.get_by_role(role, name=re.compile(re.escape(name), re.IGNORECASE))
            locator.first.click(timeout=timeout_ms)
            return {"clicked_role": role, "name": name}
        except Exception as e:
            last_error = repr(e)
            continue
    raise RuntimeError(last_error or "no matching role element found")


def _click_by_text(page, goal: str, timeout_ms: int) -> Dict[str, Any]:
    locator = page.get_by_text(re.compile(re.escape(goal), re.IGNORECASE))
    locator.first.click(timeout=timeout_ms)
    return {"clicked_text": goal}


def _click_by_best_effort_dom(page, goal: str, timeout_ms: int) -> Dict[str, Any]:
    # Evaluate on-page to pick a "best" candidate based on text similarity.
    result = page.evaluate(
        """(goal) => {
  function norm(s) {
    return String(s || '').toLowerCase().replace(/\\s+/g,' ').trim();
  }
  const g = norm(goal);
  const els = Array.from(document.querySelectorAll('button, a, [role="button"], input[type="submit"], input[type="button"]'));
  const scored = els.map((el, idx) => {
    const text = norm(el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '');
    const contains = text.includes(g);
    const score = (contains ? 1000 : 0) + Math.min(text.length, 120) + (el.tagName === 'BUTTON' ? 10 : 0);
    return {idx, text, score};
  }).sort((a,b) => b.score - a.score);
  const best = scored.find(s => s.text.length > 0) || scored[0];
  if (!best) return {ok:false, reason:'no candidates'};
  const el = els[best.idx];
  el.scrollIntoView({block:'center', inline:'center'});
  const rect = el.getBoundingClientRect();
  return {
    ok: true,
    selectorHint: el.tagName.toLowerCase(),
    text: best.text,
    x: Math.round(rect.left + rect.width/2),
    y: Math.round(rect.top + rect.height/2),
  };
}""",
        goal,
    )
    if not result or not result.get("ok"):
        raise RuntimeError(f"dom_heuristic_failed: {result}")
    page.mouse.click(result["x"], result["y"], timeout=timeout_ms)
    return {"clicked_xy": {"x": result["x"], "y": result["y"]}, "picked_text": result.get("text")}


STRATEGIES: Dict[str, Callable[..., Dict[str, Any]]] = {
    "a11y_role": _click_by_accessibility,
    "text": _click_by_text,
    "dom_heuristic": _click_by_best_effort_dom,
}


def _load_cases(cases_path: Optional[str], url: Optional[str], goal: Optional[str]) -> List[Case]:
    if cases_path:
        raw = json.loads(Path(cases_path).read_text(encoding="utf-8"))
        cases = []
        for item in raw:
            cases.append(Case(name=str(item["name"]), url=str(item["url"]), goal=str(item["goal"])))
        return cases

    if not url or not goal:
        raise SystemExit("Provide either --cases cases.json OR both --url and --goal.")

    return [Case(name=_safe_slug(url), url=url, goal=goal)]


def run_case(
    case: Case,
    strategy_name: str,
    out_root: Path,
    headful: bool,
    viewport: Tuple[int, int],
    timeout_ms: int,
    slow_mo_ms: int,
) -> RunSummary:
    started = _now_ms()
    ts_slug = time.strftime("%Y%m%d-%H%M%S")
    run_dir = out_root / ts_slug / _safe_slug(case.name) / strategy_name
    run_dir.mkdir(parents=True, exist_ok=True)

    steps: List[StepResult] = []
    ok = True

    console_path = run_dir / "console.jsonl"
    pageerror_path = run_dir / "pageerror.jsonl"
    requestfail_path = run_dir / "requestfailed.jsonl"

    with sync_playwright() as p:
        # In some sandboxed environments Playwright's "headless shell" binary can fail to launch.
        # Prefer the full Chromium for Testing binary.
        browser = p.chromium.launch(
            executable_path=p.chromium.executable_path,
            headless=not headful,
            slow_mo=slow_mo_ms or 0,
        )
        ctx = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            record_video_dir=str(run_dir / "video_raw"),
            record_video_size={"width": viewport[0], "height": viewport[1]},
        )
        ctx.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = ctx.new_page()

        page.on("console", lambda msg: _append_jsonl(console_path, {"ts_ms": _now_ms(), "type": msg.type, "text": msg.text}))
        page.on("pageerror", lambda err: _append_jsonl(pageerror_path, {"ts_ms": _now_ms(), "error": str(err)}))
        page.on(
            "requestfailed",
            lambda req: _append_jsonl(
                requestfail_path,
                {
                    "ts_ms": _now_ms(),
                    "url": req.url,
                    "method": req.method,
                    "failure": _request_failure_text(req),
                },
            ),
        )

        def nav() -> Dict[str, Any]:
            page.goto(case.url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            return {"url": page.url}

        ok = ok and _step("navigate", steps, nav)

        def capture_baseline() -> Dict[str, Any]:
            page.screenshot(path=str(run_dir / "screen.png"), full_page=True)
            _dump_url(page, run_dir)
            _dump_a11y(page, run_dir)
            _dump_dom(page, run_dir)
            return {}

        _step("baseline_dump", steps, capture_baseline)

        click_fn = STRATEGIES.get(strategy_name)
        if not click_fn:
            raise SystemExit(f"Unknown strategy: {strategy_name}. Choose from: {', '.join(sorted(STRATEGIES))}")

        def attempt_click() -> Dict[str, Any]:
            return click_fn(page, case.goal, timeout_ms)

        ok = ok and _step("attempt_click", steps, attempt_click)

        def post_click() -> Dict[str, Any]:
            # Let the page react; dump another snapshot for diffing.
            page.wait_for_timeout(750)
            page.screenshot(path=str(run_dir / "screen_after.png"), full_page=True)
            _dump_url(page, run_dir / "after")
            _dump_a11y(page, run_dir / "after")
            return {"url": page.url}

        _step("post_click_dump", steps, post_click)

        trace_path = run_dir / "trace.zip"
        ctx.tracing.stop(path=str(trace_path))
        ctx.close()

        # Rename the produced video to a stable filename (per run).
        _rename_single_video(run_dir / "video_raw", run_dir / "video.webm")
        try:
            shutil.rmtree(run_dir / "video_raw")
        except Exception:
            pass

        try:
            browser.close()
        except Exception:
            pass

    ended = _now_ms()
    summary = RunSummary(
        case=case,
        strategy=strategy_name,
        ok=bool(ok),
        started_at_ms=started,
        ended_at_ms=ended,
        steps=steps,
        artifacts_dir=str(run_dir),
    )
    _write_json(run_dir / "summary.json", asdict(summary))
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Record Playwright runs (video + trace + errors) for multiple strategies.")
    parser.add_argument("--cases", help="Path to JSON array of {name,url,goal}.")
    parser.add_argument("--url", help="Single URL (if not using --cases).")
    parser.add_argument("--goal", help="Goal text to click (if not using --cases).")
    parser.add_argument(
        "--strategies",
        default="a11y_role,text,dom_heuristic",
        help=f"Comma-separated strategies. Options: {', '.join(sorted(STRATEGIES))}",
    )
    parser.add_argument("--out", default=str(Path("backend/uploads/recordings").resolve()), help="Output root directory.")
    parser.add_argument("--headful", action="store_true", help="Run headful (shows the browser while recording).")
    parser.add_argument("--width", type=int, default=1280, help="Viewport width.")
    parser.add_argument("--height", type=int, default=720, help="Viewport height.")
    parser.add_argument("--timeout-ms", type=int, default=25000, help="Timeout per navigation/action.")
    parser.add_argument("--slowmo-ms", type=int, default=0, help="Slow down actions for readability.")

    args = parser.parse_args(argv)

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    cases = _load_cases(args.cases, args.url, args.goal)
    strategies = [s.strip() for s in str(args.strategies).split(",") if s.strip()]

    all_summaries: List[RunSummary] = []
    for case in cases:
        for strategy in strategies:
            summary = run_case(
                case=case,
                strategy_name=strategy,
                out_root=out_root,
                headful=bool(args.headful),
                viewport=(int(args.width), int(args.height)),
                timeout_ms=int(args.timeout_ms),
                slow_mo_ms=int(args.slowmo_ms),
            )
            all_summaries.append(summary)
            print(f"[{summary.strategy}] ok={summary.ok} → {summary.artifacts_dir}")

    _write_json(out_root / "index.json", [asdict(s) for s in all_summaries])
    return 0 if all(s.ok for s in all_summaries) else 2


if __name__ == "__main__":
    raise SystemExit(main())
