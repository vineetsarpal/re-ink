# Cloudflare extraction prototype

`worker.mjs` adapts a Cloudflare queue invocation to the backend machine endpoints and LandingAI. `queue.mjs` contains the delivery boundary and `landingai.mjs` performs provider requests. Run the local mocked checks with `node --test workflows/cloudflare/*.test.mjs`.

This is not deployment-ready: the example queue and cron triggers are disabled, and the backend Cloudflare routes and trial are off by default. Mocked worker tests and simulated backend trials do not establish live provider behavior. Validate the configured environment with synthetic documents before accepting real customer documents.

The worker requests the same flat provider schema as the production FastAPI LandingAI integration, then maps the response into the review-result envelope. `provider-schema.json` is generated from `get_extraction_schema()` and must stay synchronized with that function. The worker does not transmit raw provider responses: guided intake reads the normalized `parsed_results`, which the backend must persist. Extraction quality and guided intake behavior still need synthetic end-to-end validation before enabling the worker.

The runtime expects `REINK_API_ORIGIN`, `REINK_WORKER_TOKEN`, `LANDINGAI_PARSE_MODEL`, and `LANDINGAI_EXTRACT_MODEL`. Its scheduled handler also expects distinct `REINK_DISPATCH_SCHEDULER_TOKEN`, `REINK_EXPIRY_SCHEDULER_TOKEN`, and `REINK_CLEANUP_SCHEDULER_TOKEN` secrets. The scheduled handler tries dispatch, expiry and cleanup independently and reports only a generic failure if either fails. All tokens must be stored as Worker secrets. Queue messages carry a short-lived signed capability, which is also sensitive and must not be logged; they never contain the provider key or document. The backend supplies both only after authenticating the attempt. `business-schema.json` is a pinned copy of the backend machine result schema and must be regenerated when that contract changes.

## Required coordinator contract

`consumeBatch(batch, services)` accepts Cloudflare-shaped queue messages containing the versioned job and attempt identifiers and signed capability. The injected services require an authenticated backend which enforces the following rules:

- `claim(dispatch)` durably and atomically returns `start` and a secret `checkpoint_token` for preparation to at most one consumer for each attempt. Once granted, `start` must **never** be granted again for that attempt, even after a process crash, a timeout or the same queue message being redelivered. It can instead return `in_progress`, `closed`, or `terminal` with the exact previously stored event. The Cloudflare coordinator implements this fence; the legacy workflow claim uses a different contract.
- `extract(dispatch)` retrieves a tenant-authorized document and key, requests one-shot `provider-start` authorization, calls the provider only after an explicit authorization acknowledgment, and normalizes the response. It must not log credentials or document contents. Its result must satisfy the backend result schema; this prototype does not validate it. The key is never put into a queue message or returned in an event.
- `checkpoint(dispatch, checkpoint_token, event)` durably stores the exact terminal event and returns `true` only after it is committed. Duplicate checkpoint requests must be idempotent and reject conflicting event bodies. A subsequent claim must return this exact event as `terminal`.
- `deliver(event)` returns `true` only after an identity-matching backend acknowledgment. It must permit idempotent redelivery of the same event and reject mismatched acknowledgments.

These rules prevent this consumer from deliberately repeating a provider call on ordinary redelivery; they do not promise exactly-once provider execution. If the process stops after a provider request starts but before a terminal event is checkpointed, the attempt remains `in_progress` until the backend expires or reconciles it. Retrying that attempt requires a deliberate policy because the provider may already have charged for it. Queue retention, dead-letter handling, deadline expiry and quota release must be coordinated with that policy.

The worker buffers documents and responses. It currently rejects documents larger than 5 MiB, and caps provider responses at 8 MiB, as conservative prototype limits; these do not establish that it is safe under Cloudflare's 128 MiB per-isolate limit with concurrent messages. Runtime testing and a concurrency limit are required before deployment. When the Cloudflare trial gate is enabled, the API and upload UI also enforce a 5 MiB document limit.

An oversized terminal result is checkpointed as a generic failure. A result rejected by the backend contract, or an ambiguous checkpoint transport failure, can still leave the claimed attempt in progress until expiry; neither condition should trigger another provider call for that attempt.

## Retries and timeouts

Every queue-path request has an `AbortSignal.timeout`: 15 s for backend JSON calls (matching the backend statement timeout), 30 s for the document download, 180 s for LandingAI parse and 120 s for extract. These keep the worst case after a claim (about 500 s including retries) inside the backend's default 600 s `WORKFLOW_PROCESSING_TIMEOUT_SECONDS` and Cloudflare's 15-minute queue consumer wall-clock limit. Raise them only together with that deadline.

- Checkpoint and deliver are retried in the same invocation (4 attempts, 250 ms / 1 s / 3 s backoff) with the same token and event, because both are idempotent. Only after that does the message fall back to `retry()`; a redelivery can then deliver a stored checkpoint, but an unstored one stays `in_progress` until expiry.
- Credential and document fetches are retried in the same invocation (3 attempts, 250 ms / 1 s) on network errors, timeouts, 429 and 5xx. Other statuses, such as 409 for an inactive attempt, are not retried.
- The claim has spent the one-shot preparation token, but does not count a trial start. A redelivery cannot start this attempt again. A persistent failure before the provider call is therefore checkpointed as `PREPARATION_FAILED` (with `retryable: true` when it was transient) instead of using `retry()`, which would only leave the attempt stuck until expiry.
- After preparation succeeds, `provider-start` atomically counts a start and denies repeat authorizations. It is never retried. A 429 cap denial is a pre-provider `TRIAL_CAPACITY_UNAVAILABLE` failure with a clear add-key/try-later message and no counted start; retry availability still depends on current backend quota policy. Other denied, malformed or ambiguous responses prevent provider execution and are checkpointed as `EXTRACTION_FAILED`. A lost acknowledgment may conservatively count an unused start. Existing machine-role grants suffice.
- LandingAI calls are never retried; any failure after the provider request starts is checkpointed as `EXTRACTION_FAILED`.
- Every request uses `redirect: 'manual'` and accepts only status 200, so redirects are never followed. Workers does not implement the Fetch `error` redirect mode: it throws a `TypeError` before sending, which Node does not reproduce.
- Scheduled failures log one JSON line per failed route (`route` plus HTTP `status` or error type), never tokens or response bodies. View them with `wrangler tail reink-extraction`.

The backend sizes the machine-route database pool per process with `CLOUDFLARE_MACHINE_POOL_SIZE` (default 2), `CLOUDFLARE_MACHINE_POOL_MAX_OVERFLOW` (default 1) and `CLOUDFLARE_MACHINE_POOL_TIMEOUT_SECONDS` (default 5). The defaults suit `max_concurrency = 1`, with room for a retry that overlaps a request the Worker abandoned on timeout. Raise them in step with `max_concurrency`, within the database's connection limit. Validate the live provider response against the backend contract before enabling the trial.

## Deployment preparation

[`wrangler.example.toml`](./wrangler.example.toml) is a review-only template. Its queue consumer is commented out and its cron list is empty; copying it alone will not process work. The backend components have default-off gates; their dedicated roles and settings must be provisioned and verified. Validate with synthetic documents, including failure and restart cases. The owner has chosen production resources for the initial trial because the app has no live users.

When the integration is ready for an authorized test deployment:

1. Copy the template to a local Wrangler configuration, choose a unique Worker name and trusted HTTPS API origin, and set explicitly tested LandingAI parse and extract model versions. The backend and Worker must agree on the business schema and model settings; `.invalid` and `REPLACE_...` are placeholders.
2. Create separate test queues for extraction and dead letters. In the copied config, replace both names and uncomment the consumer section. Start with `max_batch_size = 1`, `max_concurrency = 1`, `max_retries = 50` and `retry_delay = 30` seconds. These are cautious test settings, **not** verified production limits. A single slow document can delay others until their backend deadlines expire. The dead-letter queue contains signed capabilities: restrict access, set appropriate retention, and investigate expired/ambiguous attempts before any manual replay. See [Cloudflare queue consumer settings](https://developers.cloudflare.com/workers/wrangler/configuration/).
3. Configure a dedicated Cloudflare API token with only the queue permissions needed by the backend producer, plus the Cloudflare account ID and extraction queue ID. These are backend-side settings; the example Worker config does not grant access or provision them. The backend routes and database-role wiring require explicit configuration and live verification.
4. Supply `REINK_WORKER_TOKEN`, `REINK_DISPATCH_SCHEDULER_TOKEN`, `REINK_EXPIRY_SCHEDULER_TOKEN`, and `REINK_CLEANUP_SCHEDULER_TOKEN` as four independent Worker secrets, each at least 32 characters. Match each to the corresponding backend machine identity. Never put these values, customer keys, encryption keys or signed capabilities in the TOML, source control, logs, or queue payload beyond the required signed capability. Use Wrangler's interactive `secret put` command for each secret; do not paste the values into command history. The backend also requires a protected credential-encryption key, operator LandingAI trial key, restricted database credentials, provider and queue configuration, and explicitly chosen global trial limits.
5. After validating the worker, enable the example cron `* * * * *` in the copied config. It runs dispatch, expiry and cleanup once per minute. Each dispatch request starts at most five messages and stops starting more after a 15-second budget; a slow in-flight operation can run beyond that budget. Track queue age and backend deadlines, and review changes to [Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/). Enabling cron or queue triggers changes live infrastructure and must happen only after the integration is ready and deployment is authorized.

The existing scheduled request timeout is 45 seconds. Dispatch's budget is checked between synchronous operations and its HTTP timeout limits inactivity, not total request duration, so neither guarantees completion within 45 seconds; monitor and test slow backend processing. A scheduler timeout does not cancel backend work. Queue delivery is at-least-once; the checkpoint and one-shot claim prevent deliberate repeat of paid calls on ordinary redelivery, but a crash during a provider request can leave an ambiguous outcome. Do not claim exactly-once billing. The global trial-start limit counts started extraction jobs, not dollars or individual LandingAI API calls.

### Coordinated rollout (protocol 2)

Use **pause → drain → deploy backend + Worker → verify → resume** for upgrades
and rollbacks. Do not deploy one side while work is running.

1. Pause public upload/retry admission, dispatch scheduling and queue consumption;
   leave expiry/cleanup available and terminal delivery enabled.
2. Drain all existing Worker invocations and backend requests, allowing the full
   15-minute invocation window. Confirm zero active invocations. Resolve queued
   and ambiguous attempts through expiry; never manually replay a provider call.
3. Deploy migration 0016, the backend and matching Worker while paused. Existing
   role grants suffice. `claim_preparation` is preparation only. The Worker first
   GETs the authenticated attempt `/protocol`, requires `protocol_version: "2"`,
   then sends `X-Extraction-Protocol: 2` with claim. A missing/older probe stops
   before claim; a missing/wrong claim version returns 409 before starting work.
   Watch `extraction_protocol_mismatch` Worker logs and backend
   `EXTRACTION_PROTOCOL_MISMATCH` errors. No mismatch consumes starts or calls ADE.
4. Verify the probe and negative claim checks with unchanged counters, then run
   an isolated synthetic canary: prepare without a start, authorize exactly once,
   checkpoint and settle. Also verify cap denial and non-retryable/quota-denied
   retry UI. Keep public admission closed until these checks pass.
5. Resume dispatch/consumption for the canary, observe delivery and settlement,
   then reopen admission and monitor counters, protocol errors and queue age.

See [the production procedure](../../docs/trial-production-setup.md#coordinated-protocol-2-rollout)
for the full checklist. A failed verification keeps rollout paused; restore both
artifacts together before resuming.
