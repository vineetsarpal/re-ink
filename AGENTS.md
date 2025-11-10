# Repository Guidelines

## Project Structure & Module Organization
`backend/` hosts the FastAPI service with domain modules under `app/` (`api`, `models`, `schemas`, `services`) and migration config in `alembic.ini`. Persisted uploads land in `backend/uploads/`, and tests live in `backend/tests/`. `frontend/` is a Vite + React workspace; business logic sits in `src/services/`, views in `src/pages/`, and reusable UI in `src/components/`. Shared TypeScript types are centralized in `src/types/`.

## Build, Test, and Development Commands
Backend: `python -m venv venv && source venv/bin/activate`, `pip install -r requirements.txt`, `alembic upgrade head`, and `uvicorn app.main:app --reload` for live reload. Run `pytest` from `backend/` to execute FastAPI and service tests. Frontend: `npm install`, `npm run dev` for local development, `npm run build` for production bundles, and `npm run preview` to sanity-check the build. Run `npm run lint` to enforce ESLint rules before opening a PR.

## Coding Style & Naming Conventions
Follow PEP 8 in Python modules: four-space indentation, snake_case for functions, and PascalCase for Pydantic schemas and SQLAlchemy models. Keep route modules scoped by feature (e.g., `app/api/contracts.py`) and prefer dependency-injected services over direct DB access. In TypeScript, rely on strict mode defaults, keep components PascalCase in `src/components`, hooks prefixed with `use`, and favor the `@/*` path alias over relative imports. Use ESLint to catch deviations; auto-fix where possible.

## Testing Guidelines
Backend tests should mirror module layout in `backend/tests`, using descriptive filenames like `test_documents.py` and `pytest.mark.asyncio` for async endpoints. Cover new endpoints with FastAPI test clients and exercise service-layer edge cases. While no frontend test runner is bundled, lint must remain clean; when adding UI logic, consider lightweight Vitest or React Testing Library specs and document manual verification steps in the PR description.

## Commit & Pull Request Guidelines
Commit messages in this repo favor concise, Title Case subjects (e.g., `Update Extraction Schema`). Keep subjects under ~70 characters and write in the imperative or descriptive present tense. For pull requests, include a short summary, link related issues, list setup or migration steps, and paste relevant screenshots or console output for UI or API changes. Confirm backend `pytest`, frontend `npm run lint`, and any new commands succeed before requesting review.

## Configuration & Secrets
Copy `backend/.env.example` and `frontend/.env.example` to configure API keys and service URLs; never commit populated `.env` files. PostgreSQL connectivity is controlled through the backend `.env`, and the frontend expects a `VITE_API_URL`. Store LandingAI credentials in your local `.env` only and coordinate rotation with maintainers.
