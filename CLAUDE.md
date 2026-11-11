# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**re-ink** is a multi-tenant B2B web app for reinsurance contract and party management. Users upload PDF/DOCX reinsurance documents. LandingAI's Agentic Document Extraction extracts the data, which is reviewed (with per-field source grounding) and approved into structured Contract and Party records. A LangChain/LangGraph agent layer adds guided intake and automated contract review.

**Stack**: FastAPI + SQLAlchemy + PostgreSQL (Neon) + Alembic · React 18 + TypeScript + Vite + React Query · WorkOS (AuthKit, organizations, RBAC) · Cloudflare (Worker + Queues for extraction, R2 for documents, Pages for the frontend) · LandingAI ADE

## Development Commands

```bash
make setup          # Install backend + frontend deps (runs sync-version)
make dev            # Both dev servers (backend :8000, frontend :3000)
make bump-version V=1.2.3  # VERSION, backend/VERSION, frontend/package.json
```

Backend (from `backend/`, Python 3.13+, managed by uv):

```bash
uv sync
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
uv run pytest
```

Frontend (from `frontend/`): `npm run dev`, `npm run build`, `npm run lint`. There is no frontend test runner; verify with `npm run build` and document manual checks in PRs.

Worker (repo root): `node --test workflows/cloudflare/*.test.mjs`. Pass the file glob, not the directory.

API docs are at `http://localhost:8000/docs`; read the endpoint list there rather than from this file.

## Architecture

### Tenancy and auth

- **Tenant = WorkOS organization.** The SPA uses AuthKit (Bearer access token held in memory). `get_current_user` validates the WorkOS JWT and requires an `org_id`. `get_authenticated_user` allows orgless users, and is used only by onboarding.
- **RBAC.** Endpoints gate on WorkOS permission slugs via `require_permission("<resource>:<action>")`, e.g. `document:upload`, `contract:write`, `member:manage`, `sso:manage`, `organization:close`. A new permission must also be added to the WorkOS dashboard roles.
- **Isolation is Postgres RLS.** The app connects as the restricted, non-BYPASSRLS role `reink_app`. `get_tenant_db` binds `app.current_org` on every transaction, and an unbound query sees zero rows. Tenant tables carry `org_id NOT NULL` and RLS policies. Use `get_tenant_db` for tenant data; `get_db` is for non-tenant tables.
- **Organization lifecycle.** Every org-scoped router is registered with `_auth = [get_current_user, require_active_organization]` in `api/__init__.py`. A closing org gets 423 `ORGANIZATION_CLOSING` everywhere except the routes in `EXEMPT_ROUTES` (`core/organization_lifecycle.py`). A route-enumeration test fails if a new org-scoped route skips this.
- **Onboarding.** `POST /api/onboarding/provision-organization` gives a zero-org user a dedicated org. It is crash-safe through a durable `provisioning_intents` row plus a WorkOS idempotency key, and assigns free-trial eligibility once.

### Extraction pipeline

With `CLOUDFLARE_TRIAL_ENABLED` (production), uploads never call LandingAI from the API process:

1. `POST /api/documents/upload` stores the original in R2 under the org's tenant prefix, creates an `ExtractionJob` + `ExtractionAttempt` + outbox row, and reserves quota.
2. The Worker cron calls `/api/maintenance/cloudflare-dispatch`, which leases outbox rows onto the Cloudflare queue.
3. The Worker (`workflows/cloudflare/worker.mjs`) consumes each message. It calls the machine routes in `api/endpoints/cloudflare.py` (protocol, claim, document, credential, provider-start, checkpoint, deliver) and runs LandingAI.
4. The SPA polls `GET /api/documents/status/{job_id}`, then reviews `results` with `field_sources` overlaid on the PDF by `DocumentPreview`.

Without the flag, the legacy in-process path calls `landingai_service` directly.

The cron also calls `/api/maintenance/expiry`, `/cleanup` and `/purge`. Each maintenance and machine route has its own bearer token and its own least-privilege DB role (`reink_cf_machine`, `_dispatch`, `_expiry`, `_cleanup`, `_purge`).

### Quotas and the free trial

- **Funding.** Each extraction is either `customer` (the org stored its own LandingAI key, AES-GCM encrypted in `provider_credentials`) or `trial` (the platform key).
- **Trial eligibility.** It is decided at provisioning and stored on `extraction_quota_org.trial_eligible`, which fails closed. The creating user (HMAC via `TRIAL_IDENTITY_HASH_KEY`) and, for non-webmail emails, the domain may each claim one trial (`trial_users`, `trial_domains`). Never change or lose that key.
- **Caps.** Trial: 5 free per org, plus 50/month successes and 200/month attempts. Customer: `EXTRACTION_CUSTOMER_MONTHLY_LIMIT` and `EXTRACTION_CUSTOMER_MONTHLY_ATTEMPT_LIMIT`. The per-minute limit and the global trial caps always apply. Setting `EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT=0` stops free extractions only. `EXTRACTION_UNCAPPED_ORGANIZATION_IDS` (the owner's test org) skips the monthly caps for customer funding only.

### Account lifecycle

- **Leaving.** `POST /api/members/me/leave` removes the caller's membership. If it is their only one, it deletes the WorkOS user instead. The last admin gets 409.
- **Closing.** `POST /api/organization/close` requires `organization:close`. It cancels active attempts, settles their quota, and starts a 30-day grace period during which `cancel-closure` restores access.
- **Purge.** `purge_worker.py` runs after the grace period. It deletes R2 objects (verified empty), then tenant rows, then the WorkOS org, then marks the org `purged`. Quota and trial rows are retained.

### Code layout

- **Backend (`backend/app/`).**
  - `api/endpoints/` holds thin handlers.
  - `services/` holds business logic: `workflow_service.py` (attempts, outbox, settlement), `extraction_quota.py`, `trial_eligibility.py`, `storage_service.py` / `private_document_service.py` (R2), `landingai_service.py`, `party_matching.py`, `agent_service.py`.
  - `agents/` holds the LangChain agents.
  - `core/` holds config, auth, tenancy, lifecycle and Cloudflare runtime factories.
  - `*_worker.py` holds the maintenance job logic.
- **Frontend (`frontend/src/`).** `pages/` and `components/`, plus `AuthGuards.tsx` and `RequirePermission.tsx` for auth. `services/api.ts` is the single Axios client, and `types/` mirrors the backend schemas. Import with the `@/*` alias.
- **Tooling.** `deploy/` holds one-off operator scripts (role provisioning in `deploy/storage/`, the trial backfill, the orphan-org report). `docs/` holds runbooks (`trial-production-setup.md`, `trial-eligibility.md`, `organization-closure.md`) and the user guide.

## Conventions and gotchas

- **Migrations.**
  - Alembic is the only schema source; nothing calls `create_all()`. Revision ids are at most 32 chars (`00NN_short_name`).
  - Grant privileges in the migration with a `DO $$ ... IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '<role>') ...` block, least privilege. New service roles come from `deploy/storage/create_service_roles.py`. Neon console-created roles get BYPASSRLS, so create roles with SQL.
- **New tenant tables** need `org_id`, RLS policies and `reink_app` grants. They must also be classified in `DELETE_TABLES` or `RETAIN_TABLES` in `purge_worker.py`; the purge fails closed on an unclassified `org_id` table.
- **Settings validation is strict.** With `CLOUDFLARE_ENABLED`, `core/config.py` requires every Cloudflare DB URL and token, all distinct, and refuses to start otherwise. Set new production secrets in FastAPI Cloud **before** merging code that requires them.
- **Deploys.**
  - A push to `main` touching `backend/**` runs `alembic upgrade head` (owner URL) and deploys the backend to FastAPI Cloud through CI. Merging is releasing.
  - The frontend deploys to Cloudflare Pages.
  - The Worker deploys manually with `npx wrangler deploy --config workflows/cloudflare/wrangler.toml`, and only after its secrets exist; a missing scheduler token stops all maintenance.
- **Tests.**
  - Backend tests run against real Postgres (`reink_test`, overridable with `TEST_DATABASE_URL`) as the restricted role.
  - CI runs in UTC with no `.env`. Also run `PGTZ=UTC uv run pytest`, and set any WorkOS key or token a test needs inside the test.
  - Use a fresh `TEST_DATABASE_URL` database when switching between branches with different migrations.
- **Domain spelling.** The party role is spelled "cedant".
- **Versioning.** The root `VERSION` is the source of truth. CI copies it to `backend/VERSION`; run `make sync-version` locally.

## Agent skills

### Issue tracker

Issues and PRDs live as GitHub issues in `vineetsarpal/re-ink`; use the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, default names (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
