#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from playwright.sync_api import sync_playwright


@dataclass(frozen=True)
class Beat:
    at_s: float
    kind: str
    text: str


def _make_events(duration_sec: int, seed: int) -> List[Beat]:
    # Deterministic high-signal "Codex run" style timeline:
    # - initial command
    # - recurring permission prompts
    # - dense stream of warnings/errors
    import random

    rng = random.Random(seed)
    beats: List[Beat] = []
    t = 0.6

    def add(dt: float, kind: str, text: str) -> None:
        nonlocal t
        t += dt
        beats.append(Beat(at_s=round(t, 3), kind=kind, text=text))

    beats.append(Beat(at_s=0.25, kind="info", text="Codex · run session"))
    beats.append(Beat(at_s=0.9, kind="type", text='Try to book a demo on https://acme-saas.com (agent mode)'))

    add(3.4, "info", "Launching browser (Playwright)…")
    add(1.1, "perm", "Allow browser automation (navigate / click / type)?")
    add(0.9, "info", "Collecting accessibility tree…")
    add(1.2, "perm", "Allow reading the accessibility tree + screenshots?")

    error_pool = [
        ("warn", "aria snapshot: duplicate name → “Get started” (3 matches)"),
        ("warn", "locator: getByRole('button', name='Book a demo') resolved 0 elements"),
        ("warn", "click: element visible but not actionable (no role/name)"),
        ("warn", "modal: focus trapped; no dismiss control in tree"),
        ("warn", "navigation: SPA route changed but content not stable"),
        ("warn", "timeout: waiting for networkidle"),
        ("warn", "timeout: locator('text=Continue')"),
        ("warn", "a11y: link has no accessible name"),
        ("warn", "a11y: button is icon-only; name=\"\""),
        ("warn", "DOM drift: ids regenerated on re-render"),
        ("warn", "scroll: content virtualized; elements detach"),
        ("warn", "iframe: target inside cross-origin frame"),
        ("warn", "requestfailed: 403 (bot check / rate limit)"),
        ("warn", "requestfailed: 429 (too many requests)"),
        ("warn", "requestfailed: net::ERR_BLOCKED_BY_CLIENT"),
        ("warn", "console: React hydration mismatch"),
        ("warn", "console: Uncaught TypeError (reading 'focus')"),
        ("warn", "console: Failed to load resource (404)"),
        ("warn", "cookie banner: accept button unlabeled"),
        ("warn", "captcha / interstitial: cannot proceed without human solve"),
    ]

    # Dense middle section: more errors, occasional permission prompt.
    while t < max(10.0, duration_sec - 12.0):
        dt = rng.uniform(0.22, 0.55)
        kind, msg = rng.choice(error_pool)
        add(dt, kind, msg)
        # every ~6-10 events: add a permission prompt (the "spiral")
        if rng.random() < 0.12:
            add(rng.uniform(0.4, 0.9), "perm", rng.choice(
                [
                    "Allow fallback to coordinate click (less reliable)?",
                    "Allow retries (up to 3) with alternative selectors?",
                    "Allow downloading additional browser dependencies?",
                    "Allow interacting with a potentially destructive action?",
                ]
            ))
            add(rng.uniform(0.2, 0.6), "info", rng.choice(["Retrying…", "Recomputing plan…", "Re-scanning page…"]))

        if t >= duration_sec:
            break

    # Hard stop.
    beats.append(Beat(at_s=round(duration_sec - 7.0, 3), kind="err", text="BLOCKED: escalation required"))
    beats.append(Beat(at_s=round(duration_sec - 5.2, 3), kind="err", text="reason: permissions + bot checks + missing semantics"))
    beats.append(Beat(at_s=round(duration_sec - 3.3, 3), kind="err", text="result: no reliable delegated path"))
    beats.append(Beat(at_s=round(duration_sec - 1.2, 3), kind="info", text="(session ended)"))

    # Ensure sorted and within duration.
    beats = [b for b in beats if 0 <= b.at_s <= duration_sec]
    beats.sort(key=lambda b: b.at_s)
    return beats


def _html(title: str, width: int, height: int, fps: int, beats: List[Beat], speed: float) -> str:
    payload = [{"at": b.at_s, "k": b.kind, "t": b.text} for b in beats]
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>{title}</title>
    <style>
      :root {{
        /* Codex-ish white terminal */
        --bg: #f6f6f4;
        --panel: rgba(255,255,255,0.92);
        --line: rgba(17,17,17,0.12);
        --muted: rgba(17,17,17,0.56);
        --ink: rgba(17,17,17,0.92);
        --ok: #16794c;
        --warn: #b45309;
        --err: #b42318;
        --cyan: #0b5fff;
        --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
        --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
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
        background: var(--bg);
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
        background: rgba(255,255,255,0.92);
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
      .shell {{
        width: 100%;
        height: 100%;
        display: grid;
        grid-template-columns: 260px 1.25fr 0.9fr;
        gap: 14px;
      }}

      .sidebar {{
        border: 1px solid var(--line);
        background: rgba(255,255,255,0.84);
        box-shadow: 0 16px 44px rgba(0,0,0,0.06);
        display: flex;
        flex-direction: column;
        overflow: hidden;
      }}

      .sidehdr {{
        padding: 14px 14px 10px;
        border-bottom: 1px solid var(--line);
        display: flex;
        flex-direction: column;
        gap: 6px;
      }}
      .brand {{
        font-family: var(--sans);
        font-size: 13px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: rgba(17,17,17,0.72);
      }}
      .sub {{
        font-family: var(--mono);
        font-size: 12px;
        color: rgba(17,17,17,0.50);
      }}
      .nav {{
        padding: 10px 10px 12px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }}
      .navitem {{
        border: 1px solid rgba(17,17,17,0.10);
        background: rgba(17,17,17,0.02);
        padding: 10px 10px;
        font-family: var(--sans);
        font-size: 13px;
        color: rgba(17,17,17,0.78);
        display: flex;
        align-items: center;
        justify-content: space-between;
      }}
      .pill {{
        font-family: var(--mono);
        font-size: 11px;
        color: rgba(17,17,17,0.55);
      }}

      .panel {{
        height: 100%;
        width: 100%;
        border: 1px solid var(--line);
        background: var(--panel);
        box-sizing: border-box;
        overflow: hidden;
        box-shadow: 0 16px 44px rgba(0,0,0,0.08);
      }}

      .panelhdr {{
        height: 42px;
        border-bottom: 1px solid var(--line);
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 0 12px;
        font-family: var(--sans);
        font-size: 12px;
        letter-spacing: 0.10em;
        text-transform: uppercase;
        color: rgba(17,17,17,0.62);
        background: rgba(255,255,255,0.76);
      }}

      .panelbody {{
        height: calc(100% - 42px);
      }}

      .browser {{
        height: 100%;
        display: grid;
        grid-template-rows: 38px 1fr;
      }}
      .browserbar {{
        border-bottom: 1px solid var(--line);
        background: rgba(17,17,17,0.02);
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 0 12px;
        font-family: var(--mono);
        font-size: 12px;
        color: rgba(17,17,17,0.62);
      }}
      .dot {{
        width: 10px;
        height: 10px;
        border-radius: 999px;
        background: rgba(17,17,17,0.12);
      }}
      .url {{
        flex: 1;
        border: 1px solid rgba(17,17,17,0.12);
        background: rgba(255,255,255,0.84);
        padding: 6px 10px;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }}
      .browsermain {{
        position: relative;
        background:
          linear-gradient(180deg, rgba(17,17,17,0.02), rgba(17,17,17,0)),
          repeating-linear-gradient(to bottom, rgba(17,17,17,0.04) 0, rgba(17,17,17,0.04) 1px, transparent 1px, transparent 28px);
        overflow: hidden;
      }}
      .ghostsite {{
        position: absolute;
        inset: 0;
        padding: 38px 34px;
        font-family: var(--sans);
      }}
      .ghostsite h1 {{
        margin: 0 0 12px;
        font-size: 34px;
        font-weight: 600;
        letter-spacing: -0.02em;
        color: rgba(17,17,17,0.84);
      }}
      .ghostsite p {{
        margin: 0 0 10px;
        max-width: 46ch;
        color: rgba(17,17,17,0.62);
        line-height: 1.5;
      }}
      .ctaRow {{
        margin-top: 18px;
        display: flex;
        gap: 10px;
        align-items: center;
      }}
      .cta {{
        border: 1px solid rgba(17,17,17,0.16);
        background: rgba(17,17,17,0.06);
        padding: 10px 12px;
        font-size: 12px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: rgba(17,17,17,0.78);
      }}

      .terminal {{
        height: 100%;
        padding: 14px 16px 18px;
        box-sizing: border-box;
        display: flex;
        flex-direction: column;
        gap: 10px;
        overflow-y: auto;
        scrollbar-gutter: stable;
      }}
      .terminal::-webkit-scrollbar {{
        width: 10px;
      }}
      .terminal::-webkit-scrollbar-thumb {{
        background: rgba(17,17,17,0.16);
        border-radius: 10px;
        border: 3px solid rgba(255,255,255,0.70);
      }}
      .terminal::-webkit-scrollbar-track {{
        background: transparent;
      }}
      .line {{
        display: flex;
        gap: 12px;
        align-items: baseline;
        font-size: 15px;
        line-height: 1.35;
        white-space: pre-wrap;
        animation: pop 180ms ease-out;
      }}
      @keyframes pop {{
        from {{ transform: translateY(6px); opacity: 0; }}
        to {{ transform: translateY(0); opacity: 1; }}
      }}
      .prompt {{
        color: rgba(17,17,17,0.45);
        min-width: 88px;
      }}
      .msg {{
        color: var(--ink);
        flex: 1;
      }}
      .lvl-ok .msg {{ color: var(--ok); }}
      .lvl-warn .msg {{ color: var(--warn); }}
      .lvl-err .msg {{ color: var(--err); font-weight: 600; }}
      .lvl-info .msg {{ color: var(--cyan); }}

      .cursor {{
        display: inline-block;
        width: 10px;
        height: 18px;
        margin-left: 2px;
        background: rgba(17,17,17,0.65);
        transform: translateY(2px);
        animation: blink 0.9s steps(1, end) infinite;
      }}
      @keyframes blink {{
        0%, 50% {{ opacity: 1; }}
        50.01%, 100% {{ opacity: 0; }}
      }}

      .permission {{
        border: 1px solid rgba(17,17,17,0.14);
        background: rgba(255,255,255,0.88);
        padding: 14px 14px 12px;
        margin: 6px 0 2px;
        animation: modalIn 220ms ease-out;
      }}
      @keyframes modalIn {{
        from {{ transform: translateY(10px); opacity: 0; }}
        to {{ transform: translateY(0); opacity: 1; }}
      }}
      .permission .hdr {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 10px;
        color: rgba(17,17,17,0.72);
        font-size: 13px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
      }}
      .permission .body {{
        color: rgba(17,17,17,0.70);
        font-size: 15px;
        line-height: 1.45;
      }}
      .permission .btnrow {{
        display: flex;
        gap: 10px;
        margin-top: 12px;
      }}
      .btn {{
        border: 1px solid rgba(17,17,17,0.16);
        background: rgba(17,17,17,0.03);
        color: rgba(17,17,17,0.78);
        padding: 8px 10px;
        font-size: 13px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }}
      .btn.primary {{
        border-color: rgba(17,17,17,0.35);
        background: rgba(17,17,17,0.06);
        color: rgba(17,17,17,0.92);
      }}

      .fade {{
        position: absolute;
        left: 0;
        right: 0;
        top: 56px;
        height: 56px;
        pointer-events: none;
        background: linear-gradient(to bottom, rgba(246,246,244,1), rgba(246,246,244,0));
      }}

      .overlay {{
        position: absolute;
        inset: 0;
        display: none;
        align-items: center;
        justify-content: center;
        background: rgba(0,0,0,0.12);
        backdrop-filter: blur(2px);
      }}
      .overlay.show {{ display: flex; }}
      .modal {{
        width: min(820px, 92%);
        border: 1px solid rgba(17,17,17,0.14);
        background: rgba(255,255,255,0.94);
        box-shadow: 0 24px 70px rgba(0,0,0,0.18);
      }}
      .modal .hdr {{
        height: 44px;
        padding: 0 14px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-bottom: 1px solid rgba(17,17,17,0.12);
        font-family: var(--sans);
        font-size: 12px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: rgba(17,17,17,0.62);
      }}
      .modal .body {{
        padding: 14px 14px 10px;
        font-family: var(--sans);
        font-size: 15px;
        color: rgba(17,17,17,0.74);
        line-height: 1.5;
      }}
      .modal .btnrow {{
        display: flex;
        justify-content: flex-end;
        gap: 10px;
        padding: 0 14px 14px;
      }}
      .mbtn {{
        border: 1px solid rgba(17,17,17,0.16);
        background: rgba(17,17,17,0.03);
        padding: 9px 12px;
        font-size: 12px;
        letter-spacing: 0.10em;
        text-transform: uppercase;
        font-family: var(--sans);
        color: rgba(17,17,17,0.78);
      }}
      .mbtn.primary {{
        background: rgba(17,17,17,0.08);
        border-color: rgba(17,17,17,0.22);
      }}
    </style>
  </head>
  <body>
    <div class="frame">
      <div class="topbar">
        <div class="title">{title}</div>
        <div class="meta">{fps} fps · {width}×{height} · speed {speed:.2f}×</div>
      </div>
      <div class="stack">
        <div class="shell">
          <div class="sidebar">
            <div class="sidehdr">
              <div class="brand">Codex</div>
              <div class="sub">agent run · browser tools</div>
            </div>
            <div class="nav">
              <div class="navitem"><span>Run</span><span class="pill">active</span></div>
              <div class="navitem"><span>Traces</span><span class="pill">zip</span></div>
              <div class="navitem"><span>Console</span><span class="pill">jsonl</span></div>
              <div class="navitem"><span>Requests</span><span class="pill">fail</span></div>
              <div class="navitem"><span>A11y tree</span><span class="pill">snapshot</span></div>
            </div>
          </div>

          <div class="panel">
            <div class="panelhdr"><span>Browser</span><span>chromium</span></div>
            <div class="panelbody browser">
              <div class="browserbar">
                <span class="dot"></span><span class="dot"></span><span class="dot"></span>
                <div class="url" id="url">https://acme-saas.com</div>
              </div>
              <div class="browsermain">
                <div class="ghostsite">
                  <h1>Book a demo</h1>
                  <p>Humans see the layout. Agents see roles, names, and actions.</p>
                  <p>When those semantics are missing, delegated work turns into retries.</p>
                  <div class="ctaRow">
                    <div class="cta">Get started</div>
                    <div class="cta">Request demo</div>
                    <div class="cta">Pricing</div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="panelhdr"><span>Run log</span><span id="status">running</span></div>
            <div class="panelbody">
              <div class="terminal" id="terminal"></div>
            </div>
          </div>
        </div>
      </div>
      <div class="fade"></div>
      <div class="overlay" id="overlay">
        <div class="modal">
          <div class="hdr"><span>Approval required</span><span>Y / N</span></div>
          <div class="body" id="modalText">Allow action?</div>
          <div class="btnrow">
            <button class="mbtn">Deny</button>
            <button class="mbtn primary">Allow</button>
          </div>
        </div>
      </div>
    </div>
    <script>
      const FPS = {fps};
      const SPEED = {speed};
      const beats = {json.dumps(payload)};
      const el = document.getElementById('terminal');
      const overlay = document.getElementById('overlay');
      const modalText = document.getElementById('modalText');
      const statusEl = document.getElementById('status');

      const maxLines = 120;
      const state = {{
        beatIndex: 0,
        typed: '',
        typingTarget: '',
        typingUntil: 0,
        now: 0,
      }};

      function keepBottom() {{
        // Make scrolling visible and smooth-ish.
        const target = Math.max(0, el.scrollHeight - el.clientHeight);
        const cur = el.scrollTop;
        el.scrollTop = cur + (target - cur) * 0.35;
      }}

      function addRow(kind, prompt, html) {{
        const row = document.createElement('div');
        row.className = `line lvl-${{kind}}`;
        row.innerHTML = `<div class="prompt">${{prompt}}</div><div class="msg">${{html}}</div>`;
        el.appendChild(row);
        keepBottom();
      }}

      function escapeHtml(s) {{
        return String(s).replace(/[&<>\"']/g, (c) => ({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#039;'}}[c]));
      }}

      function showPermission(text) {{
        modalText.textContent = String(text || '');
        overlay.classList.add('show');
      }}

      function startTyping(command, seconds) {{
        state.typed = '';
        state.typingTarget = command;
        state.typingUntil = state.now + seconds;
        addRow('info', 'user', `<span id="typed"></span><span class="cursor"></span>`);
      }}

      function updateTyping() {{
        if (!state.typingTarget) return;
        const typedEl = document.getElementById('typed');
        if (!typedEl) return;
        const total = state.typingTarget.length;
        const p = Math.min(1, (state.now - (state.typingUntil - 3.6)) / 3.6); // 3.6s default window
        const count = Math.max(0, Math.min(total, Math.floor(total * p)));
        state.typed = state.typingTarget.slice(0, count);
        typedEl.textContent = state.typed;
        if (count >= total && state.now >= state.typingUntil) {{
          // finalize command row
          typedEl.parentElement.innerHTML = escapeHtml(state.typingTarget);
          state.typingTarget = '';
        }}
      }}

      function tick() {{
        // deterministic-ish timebase
        const frame = Math.floor(state.now * FPS);

        while (state.beatIndex < beats.length && beats[state.beatIndex].at <= state.now) {{
          const b = beats[state.beatIndex];
          if (b.k === 'type') {{
            startTyping(b.t, 4.0);
          }} else if (b.k === 'perm') {{
            showPermission(b.t);
            addRow('warn', 'approval', escapeHtml('prompted: ' + String(b.t || '')));
          }} else {{
            overlay.classList.remove('show');
            addRow(b.k, b.k === 'info' ? 'agent' : b.k, escapeHtml(b.t));
            if (String(b.k) === 'err') {{
              statusEl.textContent = 'blocked';
            }}
          }}
          state.beatIndex++;
        }}

        updateTyping();
        keepBottom();
        state.now += (1 / FPS) * SPEED;
        if (state.now < beats[beats.length - 1].at + 6) {{
          requestAnimationFrame(tick);
        }} else {{
          overlay.classList.remove('show');
        }}
      }}

      requestAnimationFrame(tick);
	    </script>
	  </body>
	</html>"""


def _html_codex_desktop(title: str, width: int, height: int, fps: int, beats: List[Beat], speed: float) -> str:
    payload = [{"at": b.at_s, "k": b.kind, "t": b.text} for b in beats]
    end_s = max(8.0, float(beats[-1].at_s) + 6.5) if beats else 12.0
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>{title}</title>
    <style>
      :root {{
        --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
        --sans: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
        --ink: rgba(10, 10, 10, 0.92);
        --muted: rgba(10, 10, 10, 0.50);
        --muted2: rgba(10, 10, 10, 0.35);
        --line: rgba(10, 10, 10, 0.10);
        --card: rgba(255, 255, 255, 0.98);
        --card2: rgba(255, 255, 255, 0.94);
        --shadow: 0 30px 80px rgba(0,0,0,0.20);
        --shadow2: 0 16px 44px rgba(0,0,0,0.12);
        --danger: #b42318;
        --dangerSoft: rgba(180, 35, 24, 0.10);
      }}

      html, body {{
        width: 100%;
        height: 100%;
        margin: 0;
        overflow: hidden;
        background:
          radial-gradient(1200px 720px at 20% 40%, rgba(62, 110, 255, 0.10), transparent 60%),
          radial-gradient(900px 600px at 75% 10%, rgba(255, 140, 0, 0.06), transparent 55%),
          radial-gradient(900px 700px at 70% 80%, rgba(0, 180, 130, 0.08), transparent 60%),
          linear-gradient(180deg, #eef0f2, #e7eaee);
        color: var(--ink);
        font-family: var(--sans);
      }}

      .frame {{
        position: relative;
        width: {width}px;
        height: {height}px;
        display: flex;
        align-items: center;
        justify-content: center;
      }}

      .window {{
        width: min(1500px, 92%);
        height: min(980px, 92%);
        border-radius: 18px;
        background: var(--card);
        box-shadow: var(--shadow);
        overflow: hidden;
        position: relative;
      }}

      .macbar {{
        height: 56px;
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 0 18px;
        border-bottom: 1px solid var(--line);
        background: rgba(255,255,255,0.92);
        box-sizing: border-box;
      }}
      .macLeft {{
        display: flex;
        align-items: center;
        gap: 10px;
        min-width: 220px;
      }}
      .pillbtn {{
        width: 42px;
        height: 26px;
        border-radius: 999px;
        border: 1px solid rgba(10,10,10,0.10);
        background: rgba(10,10,10,0.04);
        position: relative;
      }}
      .pillbtn::after {{
        content: "";
        position: absolute;
        left: 7px;
        top: 6px;
        width: 14px;
        height: 14px;
        border-radius: 4px;
        border: 1px solid rgba(10,10,10,0.18);
        background: rgba(255,255,255,0.90);
      }}
      .navicons {{
        display: flex;
        gap: 10px;
        color: rgba(10,10,10,0.55);
        font-size: 16px;
        user-select: none;
      }}
      .navicons span {{
        width: 18px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }}
      .macTitle {{
        flex: 1;
        text-align: center;
        font-size: 16px;
        font-weight: 500;
        color: rgba(10,10,10,0.86);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .macRight {{
        min-width: 220px;
        display: flex;
        justify-content: flex-end;
        gap: 14px;
        color: rgba(10,10,10,0.50);
        user-select: none;
      }}
      .macRight span {{
        width: 18px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }}

      .threadWrap {{
        position: absolute;
        inset: 56px 0 0 0;
        overflow: hidden;
        background: rgba(255,255,255,0.98);
      }}
      .thread {{
        position: absolute;
        inset: 0;
        overflow-y: auto;
        padding: 22px 26px 220px;
        box-sizing: border-box;
        scrollbar-gutter: stable;
      }}
      .thread::-webkit-scrollbar {{
        width: 12px;
      }}
      .thread::-webkit-scrollbar-thumb {{
        background: rgba(10,10,10,0.14);
        border-radius: 999px;
        border: 4px solid rgba(255,255,255,0.90);
      }}
      .thread::-webkit-scrollbar-track {{
        background: transparent;
      }}

      .msg {{
        margin: 0 0 16px;
        animation: fadeUp 160ms ease-out;
      }}
      @keyframes fadeUp {{
        from {{ transform: translateY(6px); opacity: 0; }}
        to {{ transform: translateY(0); opacity: 1; }}
      }}
      .msg p {{
        margin: 0 0 10px;
        font-size: 18px;
        line-height: 1.45;
        color: rgba(10,10,10,0.90);
      }}
      .mutedLine {{
        font-size: 18px;
        line-height: 1.45;
        color: rgba(10,10,10,0.58);
      }}

      .toolRow {{
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 16px;
        color: rgba(10,10,10,0.58);
        margin: 4px 0 2px;
      }}
      .toolIcon {{
        width: 18px;
        height: 18px;
        border-radius: 4px;
        border: 1px solid rgba(10,10,10,0.14);
        background: rgba(10,10,10,0.03);
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        color: rgba(10,10,10,0.55);
        user-select: none;
      }}
      .toolText {{
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}

      .thinking {{
        margin-top: 6px;
        font-size: 16px;
        color: rgba(10,10,10,0.38);
      }}

      .outBlock {{
        border-radius: 12px;
        border: 1px solid rgba(10,10,10,0.10);
        background: rgba(10,10,10,0.03);
        padding: 12px 14px;
        margin-top: 10px;
      }}
      .outBlock pre {{
        margin: 0;
        font-family: var(--mono);
        font-size: 14px;
        line-height: 1.45;
        color: rgba(10,10,10,0.72);
        white-space: pre-wrap;
      }}
      .outBlock.danger {{
        border-color: rgba(180, 35, 24, 0.28);
        background: var(--dangerSoft);
      }}
      .outBlock.danger pre {{
        color: rgba(180, 35, 24, 0.92);
        font-weight: 600;
      }}

      .approvalWrap {{
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        pointer-events: none;
        padding: 0 18px 22px;
        display: flex;
        justify-content: center;
      }}
      .approval {{
        width: min(980px, 92%);
        border-radius: 16px;
        border: 1px solid rgba(10,10,10,0.10);
        background: var(--card2);
        box-shadow: var(--shadow2);
        pointer-events: auto;
        transform: translateY(18px);
        opacity: 0;
        transition: transform 180ms ease-out, opacity 180ms ease-out;
      }}
      .approval.show {{
        transform: translateY(0);
        opacity: 1;
      }}
      .approvalInner {{
        padding: 16px 18px 14px;
      }}
      .approvalQ {{
        font-size: 18px;
        line-height: 1.35;
        font-weight: 520;
        color: rgba(10,10,10,0.88);
        margin-bottom: 10px;
      }}
      .approvalCmd {{
        border-radius: 10px;
        border: 1px solid rgba(10,10,10,0.08);
        background: rgba(10,10,10,0.03);
        padding: 10px 12px;
        font-family: var(--mono);
        font-size: 13px;
        line-height: 1.45;
        color: rgba(10,10,10,0.55);
        white-space: pre-wrap;
        margin-bottom: 10px;
      }}
      .choices {{
        border-radius: 12px;
        border: 1px solid rgba(10,10,10,0.10);
        overflow: hidden;
        background: rgba(255,255,255,0.72);
      }}
      .choice {{
        display: flex;
        gap: 10px;
        padding: 10px 12px;
        border-top: 1px solid rgba(10,10,10,0.08);
        align-items: center;
        color: rgba(10,10,10,0.78);
        font-size: 15px;
      }}
      .choice:first-child {{
        border-top: none;
      }}
      .choice.dim {{
        color: rgba(10,10,10,0.42);
      }}
      .choice .n {{
        width: 24px;
        color: rgba(10,10,10,0.52);
      }}
      .choice .txt {{
        flex: 1;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }}
      .choice .arrows {{
        display: inline-flex;
        flex-direction: column;
        gap: 3px;
        color: rgba(10,10,10,0.35);
        font-size: 12px;
        margin-left: 8px;
      }}
      .approvalFoot {{
        display: flex;
        align-items: center;
        justify-content: flex-end;
        gap: 16px;
        padding-top: 10px;
        color: rgba(10,10,10,0.55);
        font-size: 14px;
      }}
      .submitBtn {{
        display: inline-flex;
        align-items: center;
        gap: 10px;
        padding: 8px 14px;
        border-radius: 999px;
        background: rgba(10,10,10,0.90);
        color: rgba(255,255,255,0.96);
        font-weight: 560;
        user-select: none;
      }}
      .submitBtn .kbd {{
        width: 18px;
        height: 18px;
        border-radius: 6px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: rgba(255,255,255,0.16);
        color: rgba(255,255,255,0.92);
        font-size: 12px;
        font-family: var(--mono);
      }}
    </style>
  </head>
  <body>
    <div class="frame">
      <div class="window">
        <div class="macbar">
          <div class="macLeft">
            <div class="pillbtn" aria-hidden="true"></div>
            <div class="navicons" aria-hidden="true"><span>←</span><span>→</span><span>✎</span></div>
          </div>
          <div class="macTitle">{title}</div>
          <div class="macRight" aria-hidden="true"><span>⋯</span><span>≡</span><span>▢</span></div>
        </div>
        <div class="threadWrap">
          <div class="thread" id="thread"></div>
        </div>
        <div class="approvalWrap">
          <div class="approval" id="approval">
            <div class="approvalInner">
              <div class="approvalQ" id="approvalQ">Allow action?</div>
              <div class="approvalCmd" id="approvalCmd"></div>
              <div class="choices" id="choices"></div>
              <div class="approvalFoot">
                <div id="skip">Skip</div>
                <div class="submitBtn" id="submitBtn">Submit <span class="kbd">↩</span></div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <script>
      const FPS = {fps};
      const SPEED = {speed};
      const beats = {json.dumps(payload)};
      const END_S = {end_s:.3f};

      const thread = document.getElementById('thread');
      const approval = document.getElementById('approval');
      const approvalQ = document.getElementById('approvalQ');
      const approvalCmd = document.getElementById('approvalCmd');
      const choices = document.getElementById('choices');
      const submitBtn = document.getElementById('submitBtn');

      const state = {{
        now: 0,
        beatIndex: 0,
        openOut: null,
        outLines: 0,
        approvalActive: false,
        approvalUntilWall: 0,
        scrollAnim: null,
        timer: null,
      }};

      function clamp(n, a, b) {{ return Math.max(a, Math.min(b, n)); }}

      function makeEl(tag, className) {{
        const el = document.createElement(tag);
        if (className) el.className = className;
        return el;
      }}

      function scrollToBottomSmooth(ms) {{
        const start = thread.scrollTop;
        const end = thread.scrollHeight;
        const startT = performance.now();
        const dur = Math.max(0, ms);
        if (state.scrollAnim) cancelAnimationFrame(state.scrollAnim);
        function step(t) {{
          const p = dur === 0 ? 1 : clamp((t - startT) / dur, 0, 1);
          const eased = 1 - Math.pow(1 - p, 3);
          thread.scrollTop = start + (end - start) * eased;
          if (p < 1) state.scrollAnim = requestAnimationFrame(step);
        }}
        state.scrollAnim = requestAnimationFrame(step);
      }}

      function appendMsg(node) {{
        thread.appendChild(node);
        if (thread.children.length > 240) {{
          for (let i = 0; i < 40; i++) {{
            if (thread.firstChild) thread.removeChild(thread.firstChild);
          }}
        }}
        scrollToBottomSmooth(140);
      }}

      function addParagraph(text) {{
        const m = makeEl('div', 'msg');
        const p = document.createElement('p');
        p.textContent = text;
        m.appendChild(p);
        appendMsg(m);
      }}

      function addMuted(text) {{
        const m = makeEl('div', 'msg');
        const d = makeEl('div', 'mutedLine');
        d.textContent = text;
        m.appendChild(d);
        appendMsg(m);
      }}

      function addToolRow(text) {{
        const m = makeEl('div', 'msg');
        const row = makeEl('div', 'toolRow');
        const ic = makeEl('span', 'toolIcon');
        ic.textContent = '⌁';
        const t = makeEl('div', 'toolText');
        t.textContent = text;
        row.appendChild(ic);
        row.appendChild(t);
        m.appendChild(row);
        appendMsg(m);
      }}

      function addThinking() {{
        const m = makeEl('div', 'msg');
        const t = makeEl('div', 'thinking');
        t.textContent = 'Thinking';
        m.appendChild(t);
        appendMsg(m);
      }}

      function ensureOutBlock(danger=false) {{
        if (state.openOut && state.outLines < 12 && !danger) return state.openOut;
        const m = makeEl('div', 'msg');
        const box = makeEl('div', 'outBlock' + (danger ? ' danger' : ''));
        const pre = document.createElement('pre');
        pre.textContent = '';
        box.appendChild(pre);
        m.appendChild(box);
        appendMsg(m);
        state.openOut = pre;
        state.outLines = 0;
        return pre;
      }}

      function outLine(text, danger=false) {{
        const pre = ensureOutBlock(danger);
        pre.textContent += (pre.textContent ? '\\n' : '') + text;
        state.outLines++;
      }}

      function showApproval(q, cmd, opts) {{
        approvalQ.textContent = q;
        approvalCmd.textContent = cmd;
        choices.innerHTML = '';

        for (let i = 0; i < opts.length; i++) {{
          const row = makeEl('div', 'choice' + (i === 0 ? '' : ' dim'));
          const n = makeEl('div', 'n');
          n.textContent = String(i + 1) + '.';
          const txt = makeEl('div', 'txt');
          txt.textContent = opts[i];
          row.appendChild(n);
          row.appendChild(txt);
          if (i === 0) {{
            const arrows = makeEl('div', 'arrows');
            const up = document.createElement('div'); up.textContent = '↑';
            const dn = document.createElement('div'); dn.textContent = '↓';
            arrows.appendChild(up); arrows.appendChild(dn);
            row.appendChild(arrows);
          }}
          choices.appendChild(row);
        }}
        approval.classList.add('show');
        state.approvalActive = true;
        state.approvalUntilWall = performance.now() + 1350;
      }}

      function hideApproval() {{
        approval.classList.remove('show');
        state.approvalActive = false;
      }}

      function cmdForPerm(text) {{
        const t = String(text || '').toLowerCase();
        if (t.includes('download')) {{
          return "node -e \\"fetch('https://registry.npmjs.org/',{{headers:{{'user-agent':'Mozilla/5.0'}}}}).then(r=>console.log(r.status)).catch(e=>{{console.error(e.message);process.exit(1)}})\\"";
        }}
        if (t.includes('accessibility') || t.includes('screenshot')) {{
          return "python -m agent.inspect --a11y --screenshots --url https://acme-saas.com";
        }}
        if (t.includes('coordinate')) {{
          return "python -m agent.click --fallback=coords --target \\"Request demo\\"";
        }}
        if (t.includes('retry')) {{
          return "python -m agent.run --retries 3 --selector-strategy hybrid";
        }}
        if (t.includes('destructive')) {{
          return "python -m agent.submit --confirm --form schedule_demo";
        }}
        return "curl -L https://acme-saas.com/demo -H 'user-agent: Mozilla/5.0'";
      }}

      function permQuestion(text) {{
        const t = String(text || '');
        if (t.toLowerCase().includes('browser automation')) {{
          return "Allow browser automation to inspect the site without submitting any data?";
        }}
        return t || "Allow action?";
      }}

      function permOptions(text) {{
        const cmd = cmdForPerm(text);
        return [
          "Yes",
          "Yes, and don't ask again for commands that start with " + cmd.slice(0, 28) + "…",
          "No, and tell Codex what to do differently",
        ];
      }}

      function handleBeat(b) {{
        const k = String(b.k || '');
        const t = String(b.t || '');

        if (k === 'type') {{
          addParagraph(t);
          return;
        }}
        if (k === 'perm') {{
          const cmd = cmdForPerm(t);
          addToolRow("Running " + cmd);
          addThinking();
          showApproval(permQuestion(t), cmd, permOptions(t));
          return;
        }}
        if (k === 'info') {{
          addMuted(t);
          return;
        }}
        if (k === 'warn') {{
          outLine("WARN  " + t, false);
          return;
        }}
        if (k === 'err') {{
          outLine("ERROR " + t, true);
          return;
        }}
      }}

      submitBtn.addEventListener('click', () => {{
        state.approvalUntilWall = performance.now();
      }});

      function step() {{
        if (state.approvalActive) {{
          if (performance.now() < state.approvalUntilWall) {{
            return;
          }}
          hideApproval();
          outLine("✓ approval granted", false);
        }}

        while (state.beatIndex < beats.length && beats[state.beatIndex].at <= state.now) {{
          handleBeat(beats[state.beatIndex]);
          state.beatIndex++;
        }}

        state.now += (1 / FPS) * SPEED;
        if (state.now >= END_S) {{
          hideApproval();
          clearInterval(state.timer);
        }}
      }}

      // Seed narrative to match Codex “narrative first” feel.
      addParagraph("I’m going to inspect the target surface structure first and surface any blockers before attempting interactive submission.");
      addToolRow("Running agent: open https://acme-saas.com (read-only)");
      addThinking();

      state.timer = setInterval(step, Math.round(1000 / FPS));
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


def _default_beats() -> List[Beat]:
    return _make_events(duration_sec=70, seed=7)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Render a 'permission spiral' terminal video.")
    parser.add_argument("--out-dir", default=str(Path("backend/uploads/permission-spiral").resolve()), help="Output directory.")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--duration-sec", type=int, default=70, help="Narrative length before the BLOCKED end.")
    parser.add_argument("--seed", type=int, default=7, help="Shuffle seed for message selection.")
    parser.add_argument("--speed", type=float, default=0.85, help="Playback speed multiplier (higher = faster).")
    parser.add_argument("--headful", action="store_true")
    parser.add_argument("--slowmo-ms", type=int, default=0)
    args = parser.parse_args(argv)

    beats = _make_events(duration_sec=int(args.duration_sec), seed=int(args.seed))
    title = "use an agent to submit a schedule demo form …"
    html = _html_codex_desktop(title=title, width=args.width, height=args.height, fps=args.fps, beats=beats, speed=args.speed)

    ts = time.strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out_dir) / ts
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "page.html").write_text(html, encoding="utf-8")
    (out_dir / "beats.json").write_text(json.dumps([b.__dict__ for b in beats], indent=2, sort_keys=True), encoding="utf-8")

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=p.chromium.executable_path, headless=not args.headful, slow_mo=args.slowmo_ms)
        ctx = browser.new_context(
            viewport={"width": int(args.width), "height": int(args.height)},
            record_video_dir=str(out_dir / "video_raw"),
            record_video_size={"width": int(args.width), "height": int(args.height)},
        )
        page = ctx.new_page()
        page.set_content(html, wait_until="load")
        duration_ms = int((beats[-1].at_s + 7.0) * 1000 / max(0.01, float(args.speed)))
        page.wait_for_timeout(duration_ms)
        page.screenshot(path=str(out_dir / "frame.png"))
        ctx.close()
        browser.close()

    _rename_single_video(out_dir / "video_raw", out_dir / "video.webm")
    shutil.rmtree(out_dir / "video_raw", ignore_errors=True)
    print(str(out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
