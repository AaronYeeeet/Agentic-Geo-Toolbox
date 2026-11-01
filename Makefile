# Agentic Geo-Toolbox: one-command local setup.
SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173

.PHONY: help install dev test test-backend test-frontend lint e2e-install e2e screenshots

help:
	@echo "make install      install backend (uv) and frontend (npm) dependencies"
	@echo "make dev          run backend (:$(BACKEND_PORT)) and frontend (:$(FRONTEND_PORT)); Ctrl-C stops both"
	@echo "make test         backend pytest, frontend typecheck and vitest"
	@echo "make lint         ruff and oxlint"
	@echo "make e2e-install  download Chromium for Playwright (once)"
	@echo "make e2e          Playwright smoke tests (starts both servers itself)"
	@echo "make screenshots  Playwright screenshots into frontend/screenshots/"

install: backend/.venv frontend/node_modules

backend/.venv: backend/pyproject.toml backend/uv.lock
	cd backend && uv sync
	@touch backend/.venv

frontend/node_modules: frontend/package.json frontend/package-lock.json
	cd frontend && npm ci --no-fund --no-audit
	@touch frontend/node_modules

dev: install
	@echo "Backend  http://localhost:$(BACKEND_PORT)/api/health"
	@echo "Frontend http://localhost:$(FRONTEND_PORT)"
	@set -a; [ -f .env ] && . ./.env; set +a; \
	trap 'kill 0' INT TERM EXIT; \
	(cd backend && uv run uvicorn app.main:app --reload --host 127.0.0.1 --port $(BACKEND_PORT)) & \
	(cd frontend && BACKEND_URL=http://127.0.0.1:$(BACKEND_PORT) npm run dev -- --host 127.0.0.1 --port $(FRONTEND_PORT)) & \
	wait

test: install test-backend test-frontend

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm run typecheck && npm test

lint: install
	cd backend && uv run ruff check .
	cd frontend && npm run lint

e2e-install: install
	cd frontend && npx playwright install chromium

e2e: install
	cd frontend && npx playwright test --project=e2e

screenshots: install
	cd frontend && npx playwright test --project=screenshots
