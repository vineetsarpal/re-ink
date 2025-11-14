SHELL := /bin/bash

PYTHON ?= python3
BACKEND_DIR := backend
FRONTEND_DIR := frontend
VENV := $(BACKEND_DIR)/venv
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn

.PHONY: setup backend-venv backend-install backend-dev frontend-install frontend-dev dev

setup: backend-install frontend-install ## Install backend and frontend dependencies

backend-venv: ## Create the backend virtual environment if missing
	@if [ ! -d "$(VENV)" ]; then \
		cd $(BACKEND_DIR) && $(PYTHON) -m venv venv; \
	fi

backend-install: backend-venv ## Install backend Python dependencies
	cd $(BACKEND_DIR) && $(PIP) install -r requirements.txt

frontend-install: ## Install frontend npm dependencies
	cd $(FRONTEND_DIR) && npm install

backend-dev: ## Run the FastAPI dev server with auto-reload
	cd $(BACKEND_DIR) && $(UVICORN) app.main:app --reload

frontend-dev: ## Run the Vite dev server
	cd $(FRONTEND_DIR) && npm run dev -- --host

dev: ## Run backend and frontend dev servers concurrently
	@echo "Launching backend and frontend dev servers..."
	@trap 'kill 0' INT TERM EXIT; \
		$(MAKE) -s backend-dev & \
		$(MAKE) -s frontend-dev & \
		wait
