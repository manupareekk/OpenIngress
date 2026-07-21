# Self-hosting OpenIngress

Run the crawl + break-point engine and dashboard locally. Bring your own LLM API key (required).
OSS scope: **live public sites** (paste a URL). Authenticated / internal tools are enterprise.

## Quick start

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# Required — add your key in backend/.env:
# LLM_API_KEY=sk-...

make install   # creates venv, pip install, Playwright Chromium, npm install
make backend   # terminal 1 → http://127.0.0.1:5055
make frontend  # terminal 2 → http://localhost:5175
```

Open `http://localhost:5175` → **New** → enter a public site URL → review coverage and break points.

### Prerequisites

- **Python 3.10+** (Makefile prefers `python3.10`, falls back to `python3`)
- **Node 18+** for the Vite UI
- Network access once for `playwright install chromium` (included in `make install`)

If Chromium is missing later: `cd backend && . .venv/bin/activate && python -m playwright install chromium`

On Linux you may also need: `python -m playwright install-deps chromium`

## Required env

| Variable | Where | Notes |
|----------|-------|-------|
| `LLM_API_KEY` | `backend/.env` | Required for run create + exploration |
| `AUTH_DISABLED=1` | `backend/.env` | Default on — local auth off |
| `BILLING_DISABLED=1` | `backend/.env` | Default on — billing routes inert |
| `VITE_AUTH_DISABLED=1` | `frontend/.env` | Must match backend for local OSS |
| `VITE_API_URL` | `frontend/.env` | Points at local API |

Optional: `LLM_BASE_URL`, `LLM_MODEL_NAME`, Azure OpenAI vars.

## Crawl defaults

- Max depth: **3**
- Max pages: **100**

Tune via run payload `max_pages` if needed.

## Docker

See root `Dockerfile` for a containerized backend (Playwright image + Gunicorn). Frontend: `cd frontend && npm run build`. Default job mode is `inline` (`JOB_EXECUTION_MODE`).
