# Deploy OpenIngress

This repo is a **self-hosted** crawl + agent break-point engine.

For local setup, env vars, and Docker, see **[SELF_HOST.md](SELF_HOST.md)**.

## Production sketch

1. Run the Flask API (`backend/`, or the root `Dockerfile`) on any host (VPS, Render, Fly.io, etc.).
2. Build the Vue app: `cd frontend && npm run build`, then serve `frontend/dist` (or any static host) with `VITE_API_URL` pointing at your API.
3. Set `LLM_API_KEY` on the API host. Keep `AUTH_DISABLED=1` / `BILLING_DISABLED=1` unless you intentionally wire optional auth.

Do not put LLM keys or backend secrets in the frontend build.
