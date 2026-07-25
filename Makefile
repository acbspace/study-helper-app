# Study League — developer entry points.
# Windows users without make: each target's commands work verbatim in a shell;
# see README.md for the per-platform equivalents.

PY ?= python
API_DIR = services/api
WORKER_DIR = services/worker

.PHONY: help infra-up infra-down api-install api-run migrate seed test lint typecheck \
        mobile-install mobile-start mobile-test mobile-typecheck check \
        worker-test worker-lint worker-typecheck coverage openapi lint-js format check-js

help:
	@echo "infra-up / infra-down   Start/stop PostgreSQL + Redis"
	@echo "api-install             Create venv + install API deps"
	@echo "migrate                 Run Alembic migrations"
	@echo "seed                    Seed development data"
	@echo "api-run                 Start FastAPI with reload"
	@echo "test / lint / typecheck Backend checks"
	@echo "worker-*                Worker checks"
	@echo "coverage                Backend tests with a coverage report"
	@echo "openapi                 Refresh docs/api/openapi.json + generated TS types"
	@echo "lint-js / format        ESLint / Prettier across the JS workspaces"
	@echo "mobile-*                Mobile equivalents"
	@echo "check                   Everything CI runs"

infra-up:
	docker compose up -d postgres redis

infra-down:
	docker compose down

api-install:
	cd $(API_DIR) && $(PY) -m venv .venv && .venv/bin/pip install -e ".[dev]"

migrate:
	cd $(API_DIR) && .venv/bin/alembic upgrade head

seed:
	cd $(API_DIR) && .venv/bin/python -m app.seed

api-run:
	cd $(API_DIR) && .venv/bin/uvicorn app.main:app --reload --port 8000

test:
	cd $(API_DIR) && .venv/bin/pytest -q

lint:
	cd $(API_DIR) && .venv/bin/ruff check . && .venv/bin/ruff format --check .

typecheck:
	cd $(API_DIR) && .venv/bin/mypy app

coverage:
	cd $(API_DIR) && .venv/bin/pytest -q --cov=app --cov-report=term-missing:skip-covered

# Regenerate the API contract and everything derived from it, in dependency order.
openapi:
	cd $(API_DIR) && .venv/bin/python -m scripts.openapi_snapshot --write
	npm run generate:api

worker-test:
	cd $(WORKER_DIR) && ../api/.venv/bin/pytest -q

worker-lint:
	cd $(WORKER_DIR) && ../api/.venv/bin/ruff check . && ../api/.venv/bin/ruff format --check .

worker-typecheck:
	cd $(WORKER_DIR) && ../api/.venv/bin/mypy worker

lint-js:
	npm run lint

format:
	npm run format

check-js:
	npm run lint && npm run format:check

mobile-install:
	npm install

mobile-start:
	npm run --workspace apps/mobile start

mobile-test:
	npm run --workspace apps/mobile test

mobile-typecheck:
	npm run --workspace apps/mobile typecheck

check: lint typecheck test worker-lint worker-typecheck worker-test check-js \
       mobile-typecheck mobile-test
