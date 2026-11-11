# Cloudflare extraction prototype

## Open access deployment gate

Do not deploy open access to production until **#60 is complete** and follow-up
checks **1–3** pass: signed-in UI extraction, the `TRIAL_CAPACITY_UNAVAILABLE`
message, and confirmed scheduled maintenance outcomes. Merging is permitted.

The organization allowlist has been removed. A leftover
`TRIAL_ALLOWED_ORGANIZATION_IDS` environment variable is harmless because
settings use `extra='ignore'`; it has no effect and can be removed. All
organizations can manage keys and extract when `CLOUDFLARE_TRIAL_ENABLED=true`,
subject to permissions, processing acknowledgment, eligibility, and quotas.

Backend settings (not Worker variables):

```text
EXTRACTION_MONTHLY_LIMIT=50
EXTRACTION_MONTHLY_ATTEMPT_LIMIT=200
EXTRACTION_CUSTOMER_MONTHLY_LIMIT=500
EXTRACTION_CUSTOMER_MONTHLY_ATTEMPT_LIMIT=2000
EXTRACTION_UNCAPPED_ORGANIZATION_IDS=[]
```

The customer attempt default preserves the trial defaults' 4:1 ratio. Configure
`EXTRACTION_UNCAPPED_ORGANIZATION_IDS` as a JSON array of approved organization
IDs. Listed organizations skip only monthly success and attempt caps, and only
while using their own stored key. Trial eligibility, free limits, global trial
caps, and per-minute rate limiting remain enforced. Usage reports the applicable
monthly limit, or `null` (displayed as “unlimited”) for an uncapped customer.

**Free-trial kill switch:** set `EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT=0`
in FastAPI Cloud and redeploy the same backend release. This blocks new free
admissions and provider starts while customer-funded work continues. Keep trial,
Cloudflare and quotas enabled; setting trial=false permits the legacy upload
path. Restoring the approved call cap reopens free funding. The complementary
`EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT` still bounds free successes plus pending
reservations. Neither global trial cap limits customer-funded work.

For a full intake pause during a coordinated rollout, additionally use an
operator-managed ingress maintenance rule to reject upload/retry requests while
leaving machine, status and maintenance routes reachable. Verify rejection for
customer-funded organizations too before draining; a zero trial cap alone does
not pause customer traffic. If that ingress gate is unavailable, do not begin
the drain procedure.

`worker.mjs` adapts a Cloudflare queue invocation to the backend machine endpoints and LandingAI. `queue.mjs` contains the delivery boundary and `landingai.mjs` performs provider requests. Run the local mocked checks with `node --test workflows/cloudflare/*.test.mjs`.

The example queue and cron triggers are disabled, and the backend Cloudflare routes and trial are off by default. The production configuration is separate: a read-only check on 2026-11-11 confirmed protocol 2 deployed, queue delivery enabled and a configured minute cron. Mocked worker tests alone do not establish live provider behavior.

The worker requests the same flat provider schema as the production FastAPI LandingAI integration, then maps the response into the review-result envelope. `provider-schema.json` is generated from `get_extraction_schema()` and must stay synchronized with that function. The worker does not transmit raw provider responses: guided intake reads the normalized `parsed_results`, which the backend must persist. The rollout audit confirmed completed extraction metadata; extraction quality and guided intake behavior still require authenticated UI verification before expanding access.

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

The backend sizes the machine-route database pool per process with `CLOUDFLARE_MACHINE_POOL_SIZE` (default 2), `CLOUDFLARE_MACHINE_POOL_MAX_OVERFLOW` (default 1) and `CLOUDFLARE_MACHINE_POOL_TIMEOUT_SECONDS` (default 5). The defaults suit `max_concurrency = 1`, with room for a retry that overlaps a request the Worker abandoned on timeout. Raise them in step with `max_concurrency`, within the database's connection limit. Validate the live provider response against the backend contract before expanding trial access.

## Deployment preparation

[`wrangler.example.toml`](./wrangler.example.toml) is a review-only template. Its queue consumer is commented out and its cron list is empty; copying it alone will not process work. The backend components have default-off gates; their dedicated roles and settings must be provisioned and verified. Validate with synthetic documents, including failure and restart cases. The owner chose production resources for the initial trial when the app had no live users.

The following steps prepare a separate test deployment from the example template.
They do not describe pending changes to the already configured production Worker:

1. Copy the template to a local Wrangler configuration, choose a unique Worker name and trusted HTTPS API origin, and set explicitly tested LandingAI parse and extract model versions. The backend and Worker must agree on the business schema and model settings; `.invalid` and `REPLACE_...` are placeholders.
2. Create separate test queues for extraction and dead letters. In the copied config, replace both names and uncomment the consumer section. Start with `max_batch_size = 1`, `max_concurrency = 1`, `max_retries = 50` and `retry_delay = 30` seconds. These are cautious test settings, **not** verified production limits. A single slow document can delay others until their backend deadlines expire. The dead-letter queue contains signed capabilities: restrict access, set appropriate retention, and investigate expired/ambiguous attempts before any manual replay. See [Cloudflare queue consumer settings](https://developers.cloudflare.com/workers/wrangler/configuration/).
3. Configure a dedicated Cloudflare API token with only the queue permissions needed by the backend producer, plus the Cloudflare account ID and extraction queue ID. These are backend-side settings; the example Worker config does not grant access or provision them. The backend routes and database-role wiring require explicit configuration and live verification.
4. Supply `REINK_WORKER_TOKEN`, `REINK_DISPATCH_SCHEDULER_TOKEN`, `REINK_EXPIRY_SCHEDULER_TOKEN`, and `REINK_CLEANUP_SCHEDULER_TOKEN` as four independent Worker secrets, each at least 32 characters. Match each to the corresponding backend machine identity. Never put these values, customer keys, encryption keys or signed capabilities in the TOML, source control, logs, or queue payload beyond the required signed capability. Use Wrangler's interactive `secret put` command for each secret; do not paste the values into command history. The backend also requires a protected credential-encryption key, operator LandingAI trial key, restricted database credentials, provider and queue configuration, and explicitly chosen global trial limits.
5. After validating the worker, enable the example cron `* * * * *` in the copied config. It runs dispatch, expiry and cleanup once per minute. Each dispatch request starts at most five messages and stops starting more after a 15-second budget; a slow in-flight operation can run beyond that budget. Track queue age and backend deadlines, and review changes to [Cloudflare Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/). Enabling cron or queue triggers changes live infrastructure and must happen only after the integration is ready and deployment is authorized.

The existing scheduled request timeout is 45 seconds. Dispatch's budget is checked between synchronous operations and its HTTP timeout limits inactivity, not total request duration, so neither guarantees completion within 45 seconds; monitor and test slow backend processing. A scheduler timeout does not cancel backend work. Queue delivery is at-least-once; the checkpoint and one-shot claim prevent deliberate repeat of paid calls on ordinary redelivery, but a crash during a provider request can leave an ambiguous outcome. Do not claim exactly-once billing. The global trial-start limit counts started extraction jobs, not dollars or individual LandingAI API calls.

### Coordinated rollout (protocol 2)

Follow the [ordered production runbook](../../docs/trial-production-setup.md#coordinated-protocol-2-rollout)
for the full commands, hidden credential prompts, read-only SQL, protocol probe,
canary and rollback. This is the completed rollout procedure, not a pending-task
checklist. CLI syntax was checked against Wrangler **4.160.1**; recheck help when
changing versions.

1. On the current backend release, keep trial/Cloudflare/quotas enabled, set
   `EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT=0` in FastAPI Cloud and redeploy the same
   release. Enable the ingress maintenance gate for customer uploads/retries and
   verify it rejects intake. Setting trial=false permits legacy uploads;
   setting Cloudflare=false prevents in-flight delivery and maintenance.
2. Generate `wrangler.rollout.toml` beside the production config by replacing
   `crons = ["* * * * *"]` with `crons = []` (runbook step 2). Stop cron:

   ```sh
   npx wrangler triggers deploy --config workflows/cloudflare/wrangler.rollout.toml
   ```

   Keep the old matched consumer running while manually invoking bounded
   dispatch/expiry/cleanup as documented. Require zero active pending outbox,
   queued/processing attempts and queue backlog before pausing delivery:

   ```sh
   npx wrangler queues pause-delivery reink-extraction --config workflows/cloudflare/wrangler.rollout.toml
   npx wrangler queues info reink-extraction --config workflows/cloudflare/wrangler.rollout.toml
   ```

   `info` verifies identity/wiring, **not backlog or pause state**; this Wrangler
   has no backlog command. Confirm those in Queues dashboard metrics/settings,
   including DLQ, and repeat the read-only SQL after all invocations drain.
3. Only then merge backend changes to `main`: CI automatically applies 0016
   and deploys FastAPI. Require both steps for the exact merge SHA to pass,
   revision `0016_cleanup_backoff` and the authenticated `/api/cloudflare/jobs/
   {job_id}/attempts/{attempt_id}/protocol` probe returning version `2`.
4. Deploy the new Worker with the **cron-off** config and reaffirm queue pause:

   ```sh
   npx wrangler deploy --config workflows/cloudflare/wrangler.rollout.toml
   npx wrangler queues pause-delivery reink-extraction --config workflows/cloudflare/wrangler.rollout.toml
   ```

5. Admit only the operator canary through the ingress gate, using its stored
   customer key and a synthetic PDF; manually dispatch it,
   then use `queues resume-delivery` with the paused config for controlled canary
   delivery. Cron stays off. Verify completion/results, checkpoint/settlement,
   zero trial starts for the customer-funded canary and no pending reservation before general resume.
6. After the canary passes, deploy the **final** config, enable delivery, verify
   the restored cron and maintenance, then restore the approved trial call cap and remove the ingress maintenance gate:

   ```sh
   npx wrangler deploy --config workflows/cloudflare/wrangler.toml
   npx wrangler queues resume-delivery reink-extraction --config workflows/cloudflare/wrangler.toml
   ```

A plain deploy of the final config earlier would re-enable the minute cron and
consumer configuration. Queue pause alone cannot drain an existing backlog.
On failure, set the trial call cap to zero and close the ingress gate, stop cron, pause/drain and restore a **matching** pair.
Prefer keeping 0016 and its revision file in the rollback PR; dropping the
revision file breaks CI against an already-upgraded DB. The runbook gives the
optional owner-run downgrade to 0015, ACL/search_path checks and CI hold needed
to prevent automatic re-upgrade. No provisioning or grant changes are required.

## Organization purge scheduler

The scheduled handler independently calls `/api/maintenance/purge` alongside
 dispatch, expiry and cleanup. Configure the new, distinct
`REINK_PURGE_SCHEDULER_TOKEN` with `wrangler secret put` before deploying the
Worker; one maintenance endpoint failing does not prevent the others running.
All four scheduler tokens must be distinct, and none belongs in wrangler vars.

Manual production preparation is required before the backend release:

1. Create the dedicated `reink_cf_purge` login using
   `cd backend && uv run python ../deploy/storage/create_service_roles.py --role reink_cf_purge`.
2. Apply migration `0021_purge_role` through the normal release workflow. If the
   role is created afterward, grant its rights with the owner-run
   `deploy/storage/provision_purge.py reink_cf_purge` helper. RLS remains enabled;
   the purge binds `app.current_org` instead of using BYPASSRLS.
3. Set `CLOUDFLARE_PURGE_DATABASE_URL` (same database, distinct role,
   `sslmode=verify-full`) and `CLOUDFLARE_PURGE_TOKEN` as FastAPI Cloud secrets
   **before deploying the new backend**. Keep WorkOS API credentials configured.
4. From the repository root, run
   `npx wrangler secret put REINK_PURGE_SCHEDULER_TOKEN --config workflows/cloudflare/wrangler.toml`
   and enter the same new token, then deploy the matched Worker with
   `npx wrangler deploy --config workflows/cloudflare/wrangler.toml`.

See [organization closure](../../docs/organization-closure.md#scheduled-purge-after-the-grace-period)
for exact operator commands, least-privilege grants, progress/failure monitoring,
and the retained accounting tables. Defaults process at most 5 organizations
within a 10-second start budget per call. The grace deadline is enforced in
Postgres; active or cancelled closures are never selected. Purge is destructive
and deployment remains subject to the existing production release gates.
