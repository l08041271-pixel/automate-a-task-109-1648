# MassageVIP Riyadh — common tasks.  Run `make` to see this list.
.DEFAULT_GOAL := help
PY := .venv/bin/python
PIP := .venv/bin/pip

help: ## Show available commands
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

venv: ## Create the virtual environment
	python3 -m venv .venv

install: venv ## Install runtime dependencies
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

install-dev: install ## Install runtime + dev dependencies
	$(PIP) install -r requirements-dev.txt

test: ## Run the test suite
	$(PY) -m pytest -q

lint: ## Lint with ruff
	.venv/bin/ruff check app tests scripts

fmt: ## Auto-fix lint issues
	.venv/bin/ruff check --fix app tests scripts

run: ## Run the API locally
	$(PY) -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

env: ## Generate .env with real secrets
	$(PY) scripts/generate_env.py

owner: ## Create the first owner account
	$(PY) scripts/create_owner.py --email owner@massagevip.sa --name "Owner"

migrate: ## Apply SQL migrations to DATABASE_URL
	$(PY) scripts/apply_migrations.py

migrate-check: ## Show which migrations would run
	$(PY) scripts/apply_migrations.py --dry-run

schema: ## Regenerate migrations/001_init.sql from the models
	$(PY) scripts/generate_schema_sql.py

followups: ## Process due follow-ups (drafts only)
	$(PY) scripts/run_followups.py

growth: ## Run the growth agent (recommendation only)
	$(PY) scripts/run_growth_agent.py --days 7

clean: ## Remove caches and the local dev database
	rm -rf .pytest_cache .ruff_cache __pycache__ */__pycache__ */*/__pycache__
	rm -f massagevip_dev.db massagevip_dev.db-wal massagevip_dev.db-shm

.PHONY: help venv install install-dev test lint fmt run env owner migrate migrate-check schema followups growth clean
