# n8n reference reliability contract

Reviewed 2026-10-15 against the accepted resolutions for issues [49](https://github.com/vineetsarpal/re-ink/issues/49#issuecomment-6201724519), [51](https://github.com/vineetsarpal/re-ink/issues/51#issuecomment-6206615705), and [52](https://github.com/vineetsarpal/re-ink/issues/52#issuecomment-6206878564). This is implementation guidance and source review; no installed n8n runtime, restart test, provider call, or live deployment is certified here.

## Pin and source boundary

Use `docker.n8n.io/n8nio/n8n:2.43.4` for the first reference deployment. Record its resolved image digest and actual `n8n --version` in the tested-release manifest before activation. The official [2.43.4 release](https://github.com/n8n-io/n8n/releases/tag/n8n%402.43.4) is dated October 12, 2026, commit `69d73b9`. The earlier ticket #45 research inspected CLI metadata 2.44.0; [2.44.0 is a pre-release](https://github.com/n8n-io/n8n/releases/tag/n8n%402.44.0), so that inspection is not this deployment's version evidence. Do not deploy a moving `latest`, `stable`, or `beta` tag.

Pin exported node `typeVersion` values as well as the image. At 2.43.4 the inspected core nodes support Webhook **2.2**, Respond to Webhook **1.5**, HTTP Request **4.5**, and Wait **1.1**. The export must record the remaining nodes' actual versions; these numbers alone do not certify an import. Version-specific sources: [Webhook](https://github.com/n8n-io/n8n/blob/n8n%402.43.4/packages/nodes-base/nodes/Webhook/Webhook.node.ts), [Respond](https://github.com/n8n-io/n8n/blob/n8n%402.43.4/packages/nodes-base/nodes/RespondToWebhook/RespondToWebhook.node.ts), [HTTP Request](https://github.com/n8n-io/n8n/blob/n8n%402.43.4/packages/nodes-base/nodes/HttpRequest/HttpRequest.node.ts), [Wait](https://github.com/n8n-io/n8n/blob/n8n%402.43.4/packages/nodes-base/nodes/Wait/Wait.node.ts).

## Common path and acceptance

Use one production POST Webhook with Header Auth credentials, `responseMode: responseNode`, and a stable versioned path. Publish only after credential binding and synthetic validation. The test webhook is temporary and is not a dispatcher endpoint. Authentication and separate production/test registration are documented in [Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/).

The common path is authenticate → validate dispatch → freeze trusted branch/version/model configuration → explicit JSON acceptance → claim → retrieve original → selected provider branch → normalize → freeze terminal event → deliver callback. Validation failures explicitly respond with a safe 4xx and stop. Respond to Webhook uses `respondWith: json`, `options.responseCode: 202`, `options.enableStreaming: false`, and the application-defined acceptance envelope with matching job/attempt/schema identity. Continue through its input output to the claim node. Do not echo arbitrary request fields or secrets.

The dispatcher must validate status and the complete acceptance envelope, not merely any 2xx. A workflow finishing without its response node can return n8n's default 200; errors before that node return 500, and a second response node is ignored. Acceptance confirms the common path reached its response node; it cannot guarantee completion, a durable callback, or exactly-once provider work. [Respond to Webhook behavior](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.respondtowebhook/).

## Claim and lifecycle audit

Before document retrieval or any provider request call the authenticated application endpoint:

```text
POST /api/workflows/extraction/jobs/{job_id}/attempts/{attempt_id}/claim
{"schema_version":"1","execution_key":"<stable execution identity>"}
```

Use `$execution.id`, optionally prefixed by a non-secret stable instance namespace. n8n documents it as the [current execution's unique ID](https://docs.n8n.io/code/cookbook/builtin/execution/). Capture it once. A transport retry of this claim uses the same key. Another webhook execution has a different key and cannot take ownership. Do not implement claims in workflow static data or an n8n data table; the backend's atomic current-attempt fence is authoritative.

Require a matching job/attempt/schema response and `decision: run` with valid `deadline_at` before continuing. `already_claimed` exits without retrieval, provider work, or a terminal callback for the owner. Terminal/stale/deleted/expired rejection exits. Unknown decisions and malformed responses fail closed. A same-owner repeated claim may recover a lost response while active; it is not permission to rerun a provider node after an ambiguous provider response.

| Race or failure | Required application behavior |
| --- | --- |
| Lost webhook acknowledgement | Retry delivery with the same job/attempt; distinct executions compete at the claim gate. |
| Claim or callback arrives before dispatch acknowledgement | Establish progress/terminal state atomically; later acknowledgement never regresses it. |
| Owner dies after claim | Keep its claim; backend expires the attempt. Only manual Retry creates a new attempt. |
| Deadline and terminal callback race | Serialize under the same job/attempt fence using database time. Late new events cannot complete it. |
| Duplicate event | Same ID and canonical payload returns prior receipt; changed payload conflicts. |
| Manual Retry or deletion races old work | Current-attempt/tenant/deletion fences reject old access and callbacks. |

Queued work initially has a ten-minute creation deadline; first valid acceptance/claim establishes processing and its initial ten-minute deadline. Neither repeated acknowledgements nor repeated claims extend it. The backend returns the active deadline to the winning workflow; n8n must not calculate a competing business deadline. Backend status reads and worker sweeps enforce expiry even after process restarts. Timeout does not cancel an already-running provider request.

## Callback delivery and provider ambiguity

Create each callback event once after normalization. Store its complete envelope, `event_id`, timestamp, and result/error in a dedicated item field. Prefer a deterministic event identity derived from attempt/execution/terminal event kind, or generate once upstream; never generate IDs/timestamps in the HTTP Request expression on each pass. Preserve the exact payload across retries, including telemetry. Success and failure paths converge on the same delivery loop. Do not turn callback delivery failure into a new extraction-failure event after a completion event may already have committed.

Use HTTP Request with Header Auth credential, fixed trusted backend origin, redirects disabled, TLS verification enabled, bounded timeout, and full response status/headers. Set `Never Error` for HTTP status classification; separately route network/timeout errors through the node error output. Disable generic Retry On Fail and implement an explicit status-aware loop. Native [HTTP Request options](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/) expose these controls; `Never Error` is not a guarantee that network exceptions become ordinary response items.

On valid application acknowledgement stop. Retry connection errors, lost/invalid acknowledgements, 429 and 5xx with the frozen event, bounded exponential backoff and jitter (initial five seconds, cap sixty seconds), respecting bounded Retry-After and the remaining `deadline_at`. Do not begin a request after the deadline; bound request duration by remaining time. Terminal 4xx, including replay conflict/stale 409 and deleted 410/404, stop. Alert with safe metadata for configuration/authentication/schema rejection. Invalid 2xx responses are ambiguous, not proof that a result failed to commit.

Use Code/IF/Wait nodes to carry `retry_count`, frozen event, next delay, and deadline separately from HTTP output. HTTP Request replaces ordinary input with its response, so restore the delivery context explicitly from the upstream item; do not accidentally resend response JSON. Preserve single-item pairing and binary references through the provider path.

Wait is useful for bounded retry pacing, but [waits shorter than 65 seconds remain in process](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.wait/). Thus the five-to-sixty-second loop is not a durable callback outbox across a crash. This accepted design exposes lost execution/results through backend timeout and manual Retry. Do not claim arbitrary interrupted-node recovery, or use execution/node reruns to bypass ownership. Provider POSTs have Retry On Fail disabled: an ambiguous response may have incurred processing/charges, and repeating it requires a verified provider idempotency facility or a deliberate new application attempt.

## Runtime and retention settings

Start with one VPS n8n process in regular mode and persistent n8n state/binary volume. This does not require queue mode, Redis, direct application DB credentials, or a distributed scheduler. Keep n8n's own state separate from the restricted application worker connection. Preserve the credential encryption key securely across restart/restore; record secret injection and rotation in the operator runbook, never the export.

Recommended non-secret baseline (hostnames below are examples to replace):

```dotenv
EXECUTIONS_MODE=regular
N8N_WEBHOOK_URL=https://n8n.example.invalid/
N8N_PROXY_HOPS=1
N8N_DEFAULT_BINARY_DATA_MODE=filesystem
EXECUTIONS_DATA_PRUNE=true
EXECUTIONS_DATA_MAX_AGE=168
EXECUTIONS_DATA_SAVE_ON_SUCCESS=none
EXECUTIONS_DATA_SAVE_ON_ERROR=all
EXECUTIONS_DATA_SAVE_ON_PROGRESS=false
EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=false
N8N_BLOCK_ENV_ACCESS_IN_NODE=true
N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true
```

`N8N_WEBHOOK_URL` replaces deprecated `WEBHOOK_URL` from 2.35 onward; set proxy hops to the actual trusted proxy chain and forward original host/protocol/IP correctly. [Reverse proxy configuration](https://docs.n8n.io/hosting/configuration/configuration-examples/webhook-url/). Credentials belong in n8n credential storage; non-secret branch/model settings belong in a documented configuration node rather than `$env`. [Security settings](https://docs.n8n.io/hosting/configuration/environment-variables/security/).

Filesystem binary mode reduces document memory pressure and needs a persistent writable volume; queue mode does not support that mode. A future queue topology requires separate storage/recovery validation. Pruning only operates on the active binary mode, so changing modes needs explicit cleanup of old files. [Binary data](https://docs.n8n.io/hosting/scaling/binary-data/).

The 168-hour setting is rolling eligibility, not exact seven-day physical deletion: pruning is asynchronous, has a hard-delete buffer, excludes new/running/waiting executions, and excludes annotated executions. Operator reset must cover stranded executions, pinned editor data, binary files, exports and backups. Never pin customer documents. Saving successful payloads is unnecessary for metadata-based evaluation; error payloads can contain originals/provider data and require the same reset policy. [Pruning rules](https://docs.n8n.io/hosting/scaling/execution-data/).

Configure bounded HTTP timeouts and a finite n8n execution safety timeout appropriate to the deployed backend deadline window; it is only a resource guard. `EXECUTIONS_TIMEOUT` is in seconds, while native AI timeout settings use milliseconds. Per-workflow overrides can change the n8n guard, so inspect the export at import. Keep the returned backend deadline authoritative, including when its configured duration changes. [Execution settings](https://docs.n8n.io/hosting/configuration/environment-variables/executions/).

## Import and required evidence

Import inactive; remove credential names/IDs, secrets/custom headers, pinned data, customer URLs and actual execution payloads from committed exports. Bind fresh local credentials and documented non-secret overrides, validate both normalizers against application fixtures, then publish. Preserve a sanitized previous export and version manifest for rollback; change branch/config only between jobs. [Export/import guidance](https://docs.n8n.io/workflows/export-import/).

Before calling the demo ready, prove on the pinned runtime: malformed dispatch never reaches provider work; authenticated competing deliveries yield one claim owner; loss before/after acceptance and owner crash end visibly; callback replay/conflict/status retry/deadline behavior; early completion before acknowledgement; deleted/stale attempts cannot fetch or overwrite results; restart persists credentials/state; cleanup removes retained binary/workflow data. Record exact image/node/API/model versions. Two live provider branches and all six synthetic cases remain independent acceptance gates; deterministic tests do not satisfy them.

## Application lifecycle and workers

The API commits the uploaded original's metadata, queued job, selected attempt and outbox dispatch together. Historical jobs without a selected workflow attempt never enter dispatch. Each manually requested Retry creates a new attempt; transport redelivery keeps the existing identity. Retry never publishes or approves business records.

Run the dispatcher with the backend release:

```sh
cd backend
uv run python -m app.worker
```

Run a separate storage cleanup process with its own storage credentials:

```sh
uv run python -m app.worker --cleanup
```

Both accept `--once` for bounded operator runs. Configure the customer organization, trusted webhook URL and dispatch token. The dispatcher does not require the callback service token or object-storage credentials. `WORKFLOW_WORKER_DATABASE_URL` is mandatory and must use a restricted PostgreSQL identity and `sslmode=verify-full`; migration credentials are separate. Each worker transaction rebinds the configured organization. The engine limits its pool to two connections with no overflow.

Dispatch claims use `FOR UPDATE SKIP LOCKED`, commit a bounded token lease, perform webhook HTTP outside the transaction and fence acknowledgement/retry updates by the token and lease expiry. The HTTP timeout must be shorter than the lease. Only HTTP 202 with a matching versioned acceptance counts. Temporary errors and invalid/lost acceptance retry the same attempt with capped backoff; permanent HTTP configuration/authentication rejection fails it safely. A winning claim or valid callback acknowledges transport independently, so a later delivery outcome cannot undo progress.

The claim endpoint assigns one immutable workflow execution owner per active attempt. Another execution receives `already_claimed` and must stop before fetching the document or calling providers. Retrying the owner's claim returns `run` without resetting the deadline. Both decisions include the backend deadline. The document route requires an existing claim, releases its authorization transaction before storage I/O, and checks the lifecycle again before returning bytes.

Queue and processing deadlines default to 600 seconds. The first acceptance, claim or processing event starts the processing deadline. Reads, callbacks, claims and the worker enforce deadlines using PostgreSQL time under the same job/attempt locks. New callbacks cannot alter terminal attempts; exact current-attempt event replays return their stored acknowledgement, while canonical payload conflicts and stale attempts return 409.

Delete revokes eligibility and purges normalized data, dispatch rows, attempt history and callback receipts in one transaction. A minimal deletion marker and durable cleanup reference remain. Cleanup uses a separate leased transaction, performs storage deletion outside database transactions and commits a token-fenced result. Failures reschedule cleanup. Until physical cleanup succeeds, authenticated machine requests return 410; after marker purge they return 404. These responses never recreate work. Deletion cannot undo provider processing that already received document bytes.

Deterministic coverage is in `backend/tests/test_workflow_lifecycle.py` and uses real PostgreSQL, independent connections and concurrent claim/retry/deadline tests. Provider idempotency and accuracy are separate live acceptance checks.
