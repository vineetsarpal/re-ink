SHELL := /bin/bash

BACKEND_DIR := backend
FRONTEND_DIR := frontend

.PHONY: setup backend-install backend-dev frontend-install frontend-dev dev

setup: backend-install frontend-install ## Install backend and frontend dependencies

backend-install: ## Install backend Python dependencies via uv
	cd $(BACKEND_DIR) && uv sync --group dev

frontend-install: ## Install frontend npm dependencies
	cd $(FRONTEND_DIR) && npm install

backend-dev: ## Run the FastAPI dev server with auto-reload
	cd $(BACKEND_DIR) && uv run uvicorn app.main:app --reload

frontend-dev: ## Run the Vite dev server
	cd $(FRONTEND_DIR) && npm run dev -- --host

dev: ## Run backend and frontend dev servers concurrently
	@echo "Launching backend and frontend dev servers..."
	@trap 'kill 0' INT TERM EXIT; \
		$(MAKE) -s backend-dev & \
		$(MAKE) -s frontend-dev & \
		wait
