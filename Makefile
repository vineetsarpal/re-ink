SHELL := /bin/bash

BACKEND_DIR := backend
FRONTEND_DIR := frontend

.PHONY: setup backend-install backend-dev frontend-install frontend-dev dev sync-version bump-version seed-parties

setup: backend-install frontend-install sync-version ## Install backend + frontend dependencies

backend-install: ## Install backend Python dependencies via uv
	cd $(BACKEND_DIR) && uv sync --group dev

frontend-install: ## Install frontend npm dependencies
	cd $(FRONTEND_DIR) && npm install

backend-dev: ## Run the FastAPI dev server with auto-reload
	cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload

frontend-dev: ## Run the Vite dev server
	cd $(FRONTEND_DIR) && npm run dev -- --host

sync-version: ## Copy root VERSION into backend/ for local dev
	cp VERSION backend/VERSION

bump-version: ## Set a new version: make bump-version V=1.2.3
	@test -n "$(V)" || (echo "Usage: make bump-version V=x.y.z" && exit 1)
	@echo "$(V)" > VERSION
	@cp VERSION backend/VERSION
	@cd frontend && npm version $(V) --no-git-tag-version --allow-same-version > /dev/null
	@echo "Version set to $(V)"

seed-parties: ## Seed the parties table with reinsurance market participants
	cd $(BACKEND_DIR) && uv run python scripts/seed_parties.py

dev: ## Run backend and frontend dev servers concurrently
	@echo "Launching backend and frontend dev servers..."
	@trap 'kill 0' INT TERM EXIT; \
		$(MAKE) -s backend-dev & \
		$(MAKE) -s frontend-dev & \
		wait
