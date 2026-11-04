# Direct demo workflow cutover

New real uploads run through the configured n8n workflow. re-ink has no embedded provider SDK, provider key input, model selector, legacy result converter, or fixture fallback. Existing agent endpoints return 503 after normal authentication/permission checks. WorkOS and human local approval stay in place.

This is a separately hosted simulated customer environment using synthetic documents. External AI providers receive the originals. Deterministic fixtures do not establish provider quality or live deployment readiness. PDF supports available evidence highlighting; DOCX uses original download and available text evidence. Missing evidence requires manual checking. Approval records local contracts/parties, without a field-verification audit or Core publication.

## Before enabling uploads

1. Prepare the additive migration, release, private R2 bucket, restricted database roles, scoped service credentials, restartable dispatcher, n8n state and reference workflows. Follow storage-access and lifecycle runbooks. Keep `WORKFLOW_UPLOADS_ENABLED=false`.
2. Validate deterministic contract/security/lifecycle gates with disposable PostgreSQL. Validate real service connectivity and synthetic jobs. Run both selected providers through the same release and record all six-case outcomes, including failures and missing evidence.
3. Pause uploads on the old deployment. Allow existing tasks to finish where practical; preservation of old demo history is not required.
4. Stop **all old backend/background-task processes before starting new workers or enabling new uploads**. Old tasks write by job ID without attempt fencing. Deployment CI applies migrations before releasing the backend, so the maintenance pause and old-process shutdown must begin before triggering that deployment. Never allow old writers to coexist with workflow jobs.
5. Apply migrations and release the new backend/frontend. Only explicitly marked workflow jobs with their durable attempts belong to new history/dispatch. Legacy rows are excluded and unsupported operations are rejected; do not silently convert, resume, or resend them.
6. Re-upload synthetic originals, and smoke test upload → dispatch → atomic claim → authenticated original fetch → callback → review/correction → permission-gated local approval. Check failure, timeout, Retry, deletion/cleanup and terminal polling. Resume uploads only after capability flags and every required gate agree.

The browser receives only workflow-extraction/retry booleans and disabled agent capabilities. It never receives internal workflow/storage URLs, secrets, or provider configuration. Retry is shown only for failed/timed-out jobs when public capability and `document:upload` allow it; the backend enforces job eligibility and concurrency.

## Reset and retention

A reset is a deliberate organization-scoped operation identifying exact extraction jobs, attempts, receipts, dispatch rows, storage objects and retained workflow payloads. Inspect the selection before execution; no blanket SQL deletion is prescribed. Revoke job access/dispatch before object cleanup. Verify actual R2 deletion and pending-cleanup retries. Do not describe queued cleanup as physical removal. Approved contracts/parties, WorkOS configuration, unrelated jobs and other tenants are outside a demo extraction reset. Backup and external-provider retention are separate boundaries; document their actual policies.

## Rollback

Pause uploads and stop writers first. Prefer fixing forward using additive migrations and release history. An older binary must never process workflow attempts; do not roll back by falling back to an embedded provider or model. If a pre-cutover demo snapshot is restored, do so deliberately in isolation, with its matching release and scoped storage state. Old releases are not promised to understand the new lifecycle schema. No historical backfill or compatibility adapter is required.
