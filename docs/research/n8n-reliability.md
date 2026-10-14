# n8n acceptance, deduplication, and callback constraints

Research for [Research n8n acceptance, deduplication, and callback constraints](https://github.com/vineetsarpal/re-ink/issues/45), accessed 2026-10-14. This is decision-enabling evidence, not an implementation or a deployment choice. Scope: synthetic-document demo, approved external AI, with a path to customer deployment; existing WorkOS and local human approval remain outside the workflow replacement.

## Evidence boundary

Official documentation is rolling and was read on the access date. Source observations below are pinned to n8n commit `50c4ced2241430e13fa7042e976ed33f07bf5009`, whose CLI package reports `2.44.0`; this is an inspected master revision, not a claim about the installed or recommended release. No running n8n deployment was supplied or fault-tested. Pin and verify the chosen release before treating source observations as deployment guarantees. [Version metadata](https://github.com/n8n-io/n8n/blob/50c4ced2241430e13fa7042e976ed33f07bf5009/packages/cli/package.json)

The local re-ink baseline is `cf52e5bb5e1e4ae96cafe092718a0d7cff5f70e6`: upload commits an `ExtractionJob` and schedules an in-process FastAPI background task. The model persists job/result state but has no separate workflow attempt or callback inbox. Thus persistence of the record alone does not establish replay of interrupted work. This is a source inference, not a tested restart result. [Upload and background task](https://github.com/vineetsarpal/re-ink/blob/cf52e5bb5e1e4ae96cafe092718a0d7cff5f70e6/backend/app/api/endpoints/documents.py), [job model](https://github.com/vineetsarpal/re-ink/blob/cf52e5bb5e1e4ae96cafe092718a0d7cff5f70e6/backend/app/models/extraction_job.py)

## Authenticated asynchronous acceptance

Native Webhook support includes Basic, Header, and JWT authentication, configurable HTTP status/body, and production URLs registered by publishing a workflow. Test URLs require listening/execution. The default maximum payload is 16 MB (self-hosting can change it). Immediate response confirms workflow start; it is not a documented promise of completed extraction or callback delivery. [Webhook documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/)

At the pinned source revision, the immediate-response branch awaits `WorkflowRunner.run` before constructing the response and exposes the execution ID to response expressions. The v1 runner registers the execution through `activeExecutions.add`, then awaits local startup or queue addition. Queue addition calls Bull with retention/priority options; the inspected path does not derive its job identity from a caller's idempotency key. These are narrow code observations, not a cross-version exactly-once or disk-durability contract. [Webhook handler](https://github.com/n8n-io/n8n/blob/50c4ced2241430e13fa7042e976ed33f07bf5009/packages/cli/src/webhooks/webhook-helpers.ts#L1181), [runner](https://github.com/n8n-io/n8n/blob/50c4ced2241430e13fa7042e976ed33f07bf5009/packages/cli/src/workflow-runner.ts#L443), [queue addition](https://github.com/n8n-io/n8n/blob/50c4ced2241430e13fa7042e976ed33f07bf5009/packages/cli/src/scaling/scaling.service.ts#L427)

Respond to Webhook allows a custom JSON/status response after validation or a persistence step. A workflow ending without that node can return a default 200; errors before its first response return 500, and subsequent response nodes are ignored. Therefore re-ink must validate an acceptance envelope, not interpret every 2xx as the intended acceptance. [Respond to Webhook behavior](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.respondtowebhook/)

Inference for the later contract decision: define precisely what “accepted” commits, return an explicit identity-bearing envelope, and account for a lost response after successful submission. If acceptance means an application-owned durable deduplication record exists, the reference workflow must create that record before its explicit acceptance response. Whether this is necessary for the demo remains a human decision.

## Attempt identity and duplicate deliveries

No end-to-end duplicate-safe extraction guarantee was established by the reviewed webhook/queue sources. A second HTTP submission must be treated as potentially starting another execution. An n8n execution ID is useful telemetry; it is insufficient by itself to identify a business attempt across transport retries and deliberate reruns. This is an inference from the acceptance and queue paths above, not a claim that every n8n node lacks duplicate filtering.

Workflow static data is explicitly experimental, saved on successful execution, unavailable for normal test persistence, and potentially unreliable under frequent executions. It does not establish an atomic concurrent attempt claim. Documentation suggests data tables for persistence but does not, on this page, promise an atomic uniqueness/lease primitive. [Static-data limitations](https://docs.n8n.io/code/cookbook/builtin/get-workflow-static-data/)

The specification must decide an application attempt identity, retry-versus-new-attempt semantics, atomic claim/storage ownership, duplicate acceptance response, and stale callback rejection. A database uniqueness constraint or equivalent atomic primitive is a candidate to investigate; a read-then-write marker is not evidence of concurrency safety. Provider calls may also need provider-specific idempotency; n8n cannot retroactively undo a side effect whose response was lost.

## Progress and result callbacks

HTTP Request can POST JSON with generic credential authentication and configurable timeout. It normally treats only 2xx responses as success; “Never Error” changes that. These mechanisms support callbacks, but neither a callback schema nor reliable redelivery is supplied for this integration. [HTTP Request documentation](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.httprequest/)

An error workflow can react to execution failures, but trigger failures may lack an execution ID and retry metadata is conditional. It is useful failure handling, not evidence that all machine/process/network failures produce a business terminal callback. [Error handling](https://docs.n8n.io/flow-logic/error-handling/)

Inference: re-ink/reference-workflow responsibilities include authenticating the callback separately from the incoming webhook, binding it to tenant/job/attempt, validating payloads, handling duplicates and ordering, and deciding redelivery/reconciliation when the receiver is unavailable. Progress must not overwrite a terminal result; a late result from an obsolete attempt must not silently replace the selected attempt. Exact fields, state transitions, timeouts, and retry limits remain decisions, not research conclusions.

## Recovery and deployment limits

Queue mode separates main/webhook reception from workers through Redis and a shared database. Distributed SQLite is unsupported; shared credential encryption keys are required. Filesystem binary persistence is unsupported in queue mode, and S3 external storage is documented for binary persistence. Graceful worker shutdown has a configurable timeout. This topology does not itself specify Redis persistence, backups, or a transaction spanning Redis and the application database. [Queue deployment](https://docs.n8n.io/hosting/scaling/queue-mode/)

Pinned source distinguishes recovering regular-mode enqueued executions from reconstructing crashed execution information. Queue recovery marks database executions missing from the queue as crashed. “Recovery” therefore must not be read as “automatically resume every interrupted node and deliver its callback.” [Enqueued recovery](https://github.com/n8n-io/n8n/blob/50c4ced2241430e13fa7042e976ed33f07bf5009/packages/cli/src/executions/enqueued-execution-recovery.service.ts), [execution recovery](https://github.com/n8n-io/n8n/blob/50c4ced2241430e13fa7042e976ed33f07bf5009/packages/cli/src/executions/execution-recovery.service.ts), [queue recovery](https://github.com/n8n-io/n8n/blob/50c4ced2241430e13fa7042e976ed33f07bf5009/packages/cli/src/scaling/scaling.service.ts#L872)

Execution data settings independently control success/error/progress persistence; progress saving defaults off. Execution pruning is enabled by default and deletes finished execution and binary data; default age/count thresholds are 14 days/10,000. Thus n8n execution history cannot be assumed to be the permanent re-ink evidence ledger. [Execution settings](https://docs.n8n.io/hosting/configuration/environment-variables/executions/), [pruning](https://docs.n8n.io/hosting/scaling/execution-data/)

Before a customer deployment claim, verify the pinned release under lost acceptance response, repeated concurrent submission, worker kill during a provider call, Redis/database interruption, callback receiver outage, and stale attempt completion. These are proposed acceptance experiments, not tests completed by this investigation.

## Safe reference-workflow export

Workflow JSON exports contain credential names/IDs and can contain authentication headers imported from cURL. Official guidance explicitly requires removing/anonymizing sensitive details before sharing. A downloadable workflow is not automatically a sanitized artifact. [Export guidance](https://docs.n8n.io/workflows/export-import/)

Inference for export review: use placeholder credential references and endpoints; inspect node parameters, Code content, pinned/sample data, headers, signed URLs, tokens, and document text before committing. Keep credentials separately provisioned. The exact import/bootstrap flow and retention policy remain later decisions. This research creates no workflow export or production credential.

## Decision-enabling conclusion

n8n supplies authenticated triggers, explicit responses, HTTP callbacks, persistent execution infrastructure, and failure/recovery tools. The reviewed evidence does not establish business-level exactly-once acceptance, atomic attempt deduplication, guaranteed callback delivery, or automatic continuation of arbitrary interrupted provider work. The extraction contract and demo topology must state which of these are workflow/application responsibilities and which failure cases the demo proves. Source observations above are version-scoped; unknowns are explicit and do not require choosing customer policy during research.
