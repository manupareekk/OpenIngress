PYTHON := $(shell command -v python3.10 2>/dev/null || command -v python3)

.PHONY: install dev backend worker frontend test smoke

install:
	@if [ -z "$(PYTHON)" ]; then echo "Need python3.10 or python3 on PATH"; exit 1; fi
	cd backend && $(PYTHON) -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && playwright install chromium
	cd frontend && npm install

dev:
	@echo "Start backend: make backend"
	@echo "Start frontend: make frontend"

backend:
	cd backend && . .venv/bin/activate && python run.py

worker:
	cd backend && . .venv/bin/activate && python worker.py

frontend:
	cd frontend && npm run dev

test:
	cd backend && . .venv/bin/activate && python -m pytest

smoke:
	curl -s http://127.0.0.1:5055/api/ingress/runs | head -c 200
