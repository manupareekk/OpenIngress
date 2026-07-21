#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from playwright.sync_api import sync_playwright


@dataclass(frozen=True)
class LogLine:
    at_frame: int
    level: str
    source: str
    run: str
    text: str


def _safe_text(text: str, limit: int = 240) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) > limit:
        return s[: limit - 1] + "…"
    return s


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            rows.append({"text": line})
    return rows


def _iter_run_dirs(recordings_root: Path) -> Iterable[Path]:
    # recordings_root/<timestamp>/<case>/<strategy>/
    for ts in sorted([p for p in recordings_root.iterdir() if p.is_dir()]):
        for case in sorted([p for p in ts.iterdir() if p.is_dir()]):
            for strat in sorted([p for p in case.iterdir() if p.is_dir()]):
                yield strat


def _collect_lines(
    recordings_root: Path,
    fps: int,
    duration_sec: int,
    lines_per_sec: float,
    seed: int,
    max_runs: int,
) -> List[LogLine]:
    rng = random.Random(seed)
    run_dirs = list(_iter_run_dirs(recordings_root))
    if not run_dirs:
        raise SystemExit(f"No runs found under {recordings_root}")

    rng.shuffle(run_dirs)
    run_dirs = run_dirs[: max_runs]

    total_frames = fps * duration_sec
    total_lines_target = max(1, int(lines_per_sec * duration_sec))
    stride = max(1, total_frames // total_lines_target)

    lines: List[LogLine] = []
    frame = 0

    for run_dir in run_dirs:
        run_name = run_dir.relative_to(recordings_root).as_posix()

        summary = _read_json(run_dir / "summary.json") or {}
        ok = bool(summary.get("ok", False))
        header_level = "ok" if ok else "err"
        lines.append(
            LogLine(
                at_frame=frame,
                level=header_level,
                source="run",
                run=run_name,
                text=f"RUN {run_name} — ok={ok}",
            )
        )
        frame += stride

        # High-signal: step failures from summary.json
        for step in (summary.get("steps") or [])[:12]:
            if not isinstance(step, dict):
                continue
            if step.get("ok", True):
                continue
            err = (step.get("details") or {}).get("error") if isinstance(step.get("details"), dict) else None
            lines.append(
                LogLine(
                    at_frame=frame,
                    level="err",
                    source="step",
                    run=run_name,
                    text=f"{step.get('name', 'step')} failed: {_safe_text(err or step)}",
                )
            )
            frame += stride

        # Browser console
        for row in _read_jsonl(run_dir / "console.jsonl")[:120]:
            lines.append(
                LogLine(
                    at_frame=frame,
                    level=str(row.get("type") or "log"),
                    source="console",
                    run=run_name,
                    text=_safe_text(row.get("text") or row),
                )
            )
            frame += stride
            if frame >= total_frames:
                break
        if frame >= total_frames:
            break

        # Uncaught JS errors
        for row in _read_jsonl(run_dir / "pageerror.jsonl")[:60]:
            lines.append(
                LogLine(
                    at_frame=frame,
                    level="error",
                    source="pageerror",
                    run=run_name,
                    text=_safe_text(row.get("error") or row),
                )
            )
            frame += stride
            if frame >= total_frames:
                break
        if frame >= total_frames:
            break

        # Network failures
        for row in _read_jsonl(run_dir / "requestfailed.jsonl")[:120]:
            msg = f"{row.get('method', 'GET')} {row.get('url', '')} — {row.get('failure', '')}"
            lines.append(
                LogLine(
                    at_frame=frame,
                    level="warn",
                    source="requestfailed",
                    run=run_name,
                    text=_safe_text(msg),
                )
            )
            frame += stride
            if frame >= total_frames:
                break
        if frame >= total_frames:
            break

    if not lines:
        raise SystemExit("No log lines collected.")

    # Clamp to duration; ensure ascending frames.
    lines = [ln for ln in lines if ln.at_frame < total_frames]
    lines.sort(key=lambda l: l.at_frame)
    return lines


def _html_payload(
    title: str,
    fps: int,
    width: int,
    height: int,
    lines: List[LogLine],
) -> str:
    # Keep payload small and deterministic.
    payload = [
        {
            "at": ln.at_frame,
            "lvl": ln.level,
            "src": ln.source,
            "run": ln.run,
            "txt": ln.text,
        }
        for ln in lines
    ]

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>{title}</title>
    <style>
      :root {{
        --bg: #07080a;
        --panel: rgba(255,255,255,0.03);
        --line: rgba(255,255,255,0.08);
        --muted: rgba(255,255,255,0.55);
        --ink: rgba(255,255,255,0.92);
        --ok: #53d18b;
        --warn: #f7c15a;
        --err: #ff5d5d;
        --cyan: #76d5ff;
        --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      }}
      html, body {{
        width: 100%;
        height: 100%;
        margin: 0;
        background: var(--bg);
        color: var(--ink);
        font-family: var(--mono);
        overflow: hidden;
      }}
      .frame {{
        position: relative;
        width: {width}px;
        height: {height}px;
        margin: 0;
        background:
          radial-gradient(900px circle at 20% -10%, rgba(118,213,255,0.08), transparent 65%),
          radial-gradient(980px circle at 85% 110%, rgba(255,93,93,0.06), transparent 58%),
          linear-gradient(to right, rgba(255,255,255,0.04) 1px, transparent 1px),
          linear-gradient(to bottom, rgba(255,255,255,0.04) 1px, transparent 1px);
        background-size: auto, auto, 64px 64px, 64px 64px;
        background-position: 0 0, 0 0, 0 0, 0 0;
      }}
      .topbar {{
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 56px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 22px;
        border-bottom: 1px solid var(--line);
        background: linear-gradient(to bottom, rgba(0,0,0,0.65), rgba(0,0,0,0.2));
        box-sizing: border-box;
      }}
      .title {{
        letter-spacing: 0.12em;
        text-transform: uppercase;
        font-size: 12px;
        color: var(--muted);
      }}
      .meta {{
        font-size: 12px;
        color: var(--muted);
      }}
      .stack {{
        position: absolute;
        top: 56px;
        left: 0;
        right: 0;
        bottom: 0;
        padding: 18px 22px 22px;
        box-sizing: border-box;
      }}
      .panel {{
        height: 100%;
        width: 100%;
        border: 1px solid var(--line);
        background: var(--panel);
        box-sizing: border-box;
        overflow: hidden;
      }}
      .lines {{
        height: 100%;
        padding: 14px 14px 18px;
        overflow: hidden;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }}
      .line {{
        display: grid;
        grid-template-columns: 92px 110px 1fr;
        gap: 12px;
        align-items: baseline;
        font-size: 14px;
        line-height: 1.35;
        white-space: nowrap;
      }}
      .ts {{
        color: rgba(255,255,255,0.35);
      }}
      .tag {{
        color: rgba(255,255,255,0.45);
      }}
      .msg {{
        color: var(--ink);
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .lvl-ok .tag {{ color: var(--ok); }}
      .lvl-warn .tag {{ color: var(--warn); }}
      .lvl-err .tag, .lvl-error .tag {{ color: var(--err); }}
      .lvl-info .tag {{ color: var(--cyan); }}

      .scan {{
        position: absolute;
        inset: 0;
        pointer-events: none;
        background-image: repeating-linear-gradient(
          to bottom,
          rgba(255,255,255,0.035) 0px,
          rgba(255,255,255,0.035) 1px,
          transparent 1px,
          transparent 7px
        );
        opacity: 0.15;
        mix-blend-mode: overlay;
        animation: scan 12s linear infinite;
      }}
      @keyframes scan {{
        from {{ transform: translateY(0); }}
        to {{ transform: translateY(7px); }}
      }}
    </style>
  </head>
  <body>
    <div class="frame">
      <div class="topbar">
        <div class="title">{title}</div>
        <div class="meta">{fps} fps · {width}×{height}</div>
      </div>
      <div class="stack">
        <div class="panel">
          <div id="lines" class="lines"></div>
        </div>
      </div>
      <div class="scan"></div>
    </div>

    <script>
      const FPS = {fps};
      const payload = {json.dumps(payload)};
      const linesEl = document.getElementById('lines');
      const maxLines = 44;

      function pad(n, w=2) {{
        const s = String(n);
        return s.length >= w ? s : '0'.repeat(w - s.length) + s;
      }}

      function formatTs(frame) {{
        const totalSec = Math.floor(frame / FPS);
        const m = Math.floor(totalSec / 60);
        const s = totalSec % 60;
        const f = frame % FPS;
        return `${{pad(m)}}:${{pad(s)}}.${{pad(f, 2)}}`;
      }}

      function addLine(item) {{
        const lvl = String(item.lvl || 'log').toLowerCase();
        const tag = `[${{item.src}}]`;
        const run = item.run ? ` ${{item.run}}` : '';
        const msg = String(item.txt || '');

        const row = document.createElement('div');
        row.className = `line lvl-${{lvl}}`;
        row.innerHTML = `
          <div class="ts">${{formatTs(item.at)}}</div>
          <div class="tag">${{tag}}</div>
          <div class="msg">${{msg}}<span style="color: rgba(255,255,255,0.25)">${{run}}</span></div>
        `;
        linesEl.appendChild(row);
        while (linesEl.children.length > maxLines) {{
          linesEl.removeChild(linesEl.firstChild);
        }}
      }}

      let frame = 0;
      let idx = 0;
      const totalFrames = Math.max(...payload.map(p => p.at)) + 1;

      function tick() {{
        while (idx < payload.length && payload[idx].at <= frame) {{
          addLine(payload[idx]);
          idx++;
        }}
        frame++;
        if (frame <= totalFrames + FPS) {{
          requestAnimationFrame(tick);
        }}
      }}

      requestAnimationFrame(tick);
    </script>
  </body>
</html>"""


def _rename_single_video(video_dir: Path, dest: Path) -> None:
    candidates = [p for p in video_dir.glob("*") if p.is_file()]
    if not candidates:
        raise SystemExit(f"No video produced in {video_dir}")
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(newest), str(dest))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render a terminal-style 'error storm' video from Playwright artifacts.")
    parser.add_argument(
        "--recordings-root",
        default=str(Path("backend/uploads/recordings-7-examples").resolve()),
        help="Root with <timestamp>/<case>/<strategy>/ outputs from record_playwright_agents.py",
    )
    parser.add_argument("--out-dir", default=str(Path("backend/uploads/error-storm").resolve()), help="Output directory.")
    parser.add_argument("--duration-sec", type=int, default=60, help="Video duration in seconds.")
    parser.add_argument("--fps", type=int, default=30, help="Frames per second.")
    parser.add_argument("--lines-per-sec", type=float, default=14.0, help="How fast logs stream.")
    parser.add_argument("--width", type=int, default=1920, help="Viewport width.")
    parser.add_argument("--height", type=int, default=1080, help="Viewport height.")
    parser.add_argument("--seed", type=int, default=7, help="Shuffle seed for choosing runs.")
    parser.add_argument("--max-runs", type=int, default=7, help="Max number of runs to include.")
    parser.add_argument("--headful", action="store_true", help="Show the browser while recording.")
    parser.add_argument("--slowmo-ms", type=int, default=0, help="Slow down while recording (usually 0).")
    args = parser.parse_args(argv)

    recordings_root = Path(args.recordings_root)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    lines = _collect_lines(
        recordings_root=recordings_root,
        fps=int(args.fps),
        duration_sec=int(args.duration_sec),
        lines_per_sec=float(args.lines_per_sec),
        seed=int(args.seed),
        max_runs=int(args.max_runs),
    )

    title = "error storm — agents vs dom"
    html = _html_payload(title=title, fps=int(args.fps), width=int(args.width), height=int(args.height), lines=lines)

    ts = time.strftime("%Y%m%d-%H%M%S")
    run_dir = out_dir / ts
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "payload.json").write_text(
        json.dumps([ln.__dict__ for ln in lines], indent=2, sort_keys=True), encoding="utf-8"
    )
    (run_dir / "page.html").write_text(html, encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=p.chromium.executable_path, headless=not args.headful, slow_mo=args.slowmo_ms)
        ctx = browser.new_context(
            viewport={"width": int(args.width), "height": int(args.height)},
            record_video_dir=str(run_dir / "video_raw"),
            record_video_size={"width": int(args.width), "height": int(args.height)},
        )
        page = ctx.new_page()
        page.set_content(html, wait_until="load")
        # Record long enough to play the full animation.
        page.wait_for_timeout(int(args.duration_sec * 1000) + 1200)
        page.screenshot(path=str(run_dir / "frame.png"))
        ctx.close()
        browser.close()

    _rename_single_video(run_dir / "video_raw", run_dir / "video.webm")
    shutil.rmtree(run_dir / "video_raw", ignore_errors=True)

    print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

