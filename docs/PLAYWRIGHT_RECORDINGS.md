# Playwright screen recordings (agent strategies)

This repo already uses **Python Playwright**. The script below records:

- `video.webm` (screen recording)
- `trace.zip` (Playwright trace)
- `console.jsonl`, `pageerror.jsonl`, `requestfailed.jsonl`
- `a11y.json` + `dom.html` snapshots (before/after)

## Run

From the repo root:

```bash
python3 backend/scripts/record_playwright_agents.py \
  --cases backend/scripts/recording_cases.sample.json \
  --out backend/uploads/recordings \
  --slowmo-ms 120
```

Single URL:

```bash
python3 backend/scripts/record_playwright_agents.py \
  --url "https://example.com" \
  --goal "Book a demo" \
  --out backend/uploads/recordings
```

## “Agents” (strategies)

The script runs multiple strategies per case:

- `a11y_role` — `get_by_role()` selection (accessibility-tree-first)
- `text` — `get_by_text()` selection
- `dom_heuristic` — DOM + coordinate click heuristic

Limit strategies:

```bash
python3 backend/scripts/record_playwright_agents.py \
  --url "https://example.com" \
  --goal "Book a demo" \
  --strategies a11y_role,dom_heuristic
```

## Output layout

Artifacts are written under:

`backend/uploads/recordings/<timestamp>/<case>/<strategy>/`

## Error-storm video (visual log wall)

To generate a single **terminal-style “errors after errors”** video from your recorded runs:

```bash
python3 backend/scripts/render_error_storm_video.py \
  --recordings-root backend/uploads/recordings-7-examples \
  --out-dir backend/uploads/error-storm \
  --duration-sec 60
```

Output: `backend/uploads/error-storm/<timestamp>/video.webm` plus `payload.json` + `frame.png`.

## Permission-spiral video (terminal → prompts → blocked)

This creates a clean “agent terminal” clip: slow command entry, repeated permission prompts, and a final red **BLOCKED**.

```bash
python3 backend/scripts/render_permission_spiral_video.py \
  --out-dir backend/uploads/permission-spiral \
  --speed 0.7
```

Output: `backend/uploads/permission-spiral/<timestamp>/video.webm`
