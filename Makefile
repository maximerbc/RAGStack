.PHONY: setup dev backend frontend test lint build model browser e2e perf clean

setup:
	python3 -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/pip install -e '.[dev]'
	cd frontend && npm ci --cache ../.npm-cache

dev:
	./scripts/dev.sh

backend:
	.venv/bin/uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload

frontend:
	cd frontend && npm run dev

test:
	.venv/bin/pytest
	cd frontend && npm test -- --run

lint:
	.venv/bin/ruff check backend
	cd frontend && npm run lint

build:
	cd frontend && npm run build

model:
	.venv/bin/rag-2026-download-model

browser:
	cd frontend && PLAYWRIGHT_BROWSERS_PATH=../.models/playwright npx playwright install chromium

e2e:
	cd frontend && PLAYWRIGHT_BROWSERS_PATH=../.models/playwright npx playwright test

perf:
	.venv/bin/python -m app.perf

clean:
	find backend -type d -name __pycache__ -prune -exec rm -r {} +
