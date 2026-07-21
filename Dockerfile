FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

ARG CODEX_CLI_VERSION=0.136.0

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install chromium
RUN if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1 || [ "$(node -p "process.versions.node.split('.')[0]")" -lt 16 ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
        && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
        && apt-get install -y --no-install-recommends nodejs \
        && rm -rf /var/lib/apt/lists/*; \
    fi \
    && npm install -g @openai/codex@${CODEX_CLI_VERSION} \
    && codex --version

COPY backend/ .

ENV PORT=5055
EXPOSE 5055

CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 --threads 4 --timeout 300 wsgi:app
