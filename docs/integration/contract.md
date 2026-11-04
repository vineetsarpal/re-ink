# Extraction workflow contract, version 1

The authoritative machine models are [`backend/app/schemas/workflow.py`](../../backend/app/schemas/workflow.py). The integration validates provider-normalized facts and then projects them into the existing `ExtractionResult` review shape. Providers and normalization run in n8n; backend reads must not invoke provider parsers. This document describes the boundary, not deployment readiness or provider accuracy.

## Transport and identity

Every envelope requires the string `schema_version: "1"`. IDs are nonblank strings of at most 128 characters without control characters. Job identity also identifies its uploaded original; there is no separate document ID. The backend issues attempt IDs. A workflow execution key identifies one claimant, and an event ID remains stable on redelivery. Execution IDs are optional telemetry, not authorization.

Dispatch to the trusted configured n8n endpoint:

```json
{"schema_version":"1","operation":"extract_reinsurance_contract","job_id":"job-example","attempt_id":"attempt-example"}
```

Only HTTP **202** with the following validated, identity-matching body acknowledges acceptance. Other successful HTTP statuses and a mismatched job/attempt do not acknowledge work. Acceptance means delivery was accepted, not that extraction completed.

```json
{"schema_version":"1","job_id":"job-example","attempt_id":"attempt-example","status":"accepted","workflow_execution_id":null}
```

Before document retrieval or provider calls, n8n posts to `POST /api/workflows/extraction/jobs/{job_id}/attempts/{attempt_id}/claim`:

```json
{"schema_version":"1","execution_key":"stable-n8n-execution-key"}
```

A successful claim response exposes the backend's active deadline:

```json
{"schema_version":"1","job_id":"job-example","attempt_id":"attempt-example","decision":"run","deadline_at":"2026-10-16T01:00:00Z"}
```

`decision: "already_claimed"` means exit before document/provider work and without submitting a failure for the owner. The same owner may repeat its claim while active. A transport lease can be reclaimed after restart; the extraction claim is never automatically reassigned to another execution. Backend authorization/deadlines govern the actual permission to run.

Fetch the original with `GET /api/workflows/extraction/jobs/{job_id}/document?attempt_id=...` using the scoped workflow credential. Document access checks customer/job/current-attempt authorization. Service errors must not reveal another customer's job. Response content type and filename must reflect the original; no storage paths, bucket credentials, or user-selected remote URLs are exposed.

## Events

Post authenticated events to `POST /api/workflows/extraction/events`:

```json
{"schema_version":"1","job_id":"job-example","attempt_id":"attempt-example","event_id":"progress-1","status":"processing"}
```

A useful partial completion:

```json
{
  "schema_version": "1",
  "job_id": "job-example",
  "attempt_id": "attempt-example",
  "event_id": "result-1",
  "status": "completed",
  "result": {
    "contract_data": {"contract_name": "Synthetic Example Treaty"},
    "parties_data": [{"name": "Synthetic Insurer", "role": "cedant"}],
    "field_sources": {
      "contract": {"contract_name": {"source_text": "Synthetic Example Treaty", "page_number": 1}},
      "parties": [{"name": {"source_text": "Synthetic Insurer", "page_number": 1}}]
    },
    "extraction_metadata": {"workflow_version": "demo-v1"}
  }
}
```

This illustrates a reviewable partial draft, not an approvable contract or measured extraction success. Unreadable/no-useful-output documents send failure:

```json
{"schema_version":"1","job_id":"job-example","attempt_id":"attempt-example","event_id":"failure-1","status":"failed","error":{"code":"NO_CONTRACT_DATA","message":"No useful contract data was found.","retryable":false}}
```

Error codes match `[A-Z][A-Z0-9_]{0,63}`; messages are nonblank safe strings up to 1,000 characters. Retryability is advisory. Operators/workflows must omit secrets, provider traces, and document excerpts from errors. Errors are plain text, not raw provider error objects.

Ingestion and identical replay return HTTP 200:

```json
{"schema_version":"1","event_id":"result-1","status":"acknowledged"}
```

Validation precedes persistence; a rejected request cannot partly update a result. Authentication failures use 401/403; inaccessible jobs use 404; malformed/unsupported schemas use 422; excessive payloads use 413; stale attempts/conflicting event identities use 409. Lifecycle handling additionally fences terminal/deleted work and canonical-payload replay. The event schema alone does not implement those fences or prove tenant isolation.

## Normalized result and evidence

`contract_data` and `parties_data` are required. Unknown business fields and nested objects where scalar facts are expected are rejected. Fields may be omitted/null when unknown. Dates are real calendar dates as `YYYY-MM-DD` strings. Financial amounts and rates are finite JSON numbers; strings, booleans, NaN, and infinities are invalid. Commission uses percentage points: `12.5` means 12.5%. Currency uses an uppercase ISO 4217 code; no default currency is inserted.

Supported contract fields:

- Identity/categories: `contract_number`, `contract_name`, `contract_type`, `contract_sub_type`, `contract_nature`.
- Dates: `effective_date`, `expiration_date`, `inception_date`.
- Financial terms: `premium_description`, `premium_amount`, `currency`, `limit_description`, `limit_amount`, `retention_description`, `retention_amount`, `commission_description`, `commission_rate`.
- Coverage/wording: `line_of_business`, `coverage_territory`, `coverage_description`, `terms_and_conditions`, `special_provisions`.

Category values match the current application: contract type `treaty`, `facultative`, `proportional`, `non-proportional`; subtype `quota_share`, `surplus`, `xol`, `facultative_obligatory`, `facultative_optional`; nature `proportional`, `non-proportional`. Normalize provider labels before sending. If normalization is uncertain, preserve the original financial wording in its `*_description` field and leave the uncertain scalar absent/null. Do not add `*_text` aliases, invented numbers, lifecycle/approval fields, actors, database IDs, or active flags.

Each party requires a nonblank `name`. Optional `role` is `cedant`, `reinsurer`, or `broker`; missing role stays unset for reviewer selection. Other supported party fields are `email`, `phone`, `address_line1`, `address_line2`, `city`, `state`, `postal_code`, `country`, `registration_number`, `license_number`, `notes`, with string/null values. The ordered party array can be empty and contains at most 100 entries. Do not reorder parties separately from evidence.

`field_sources` is optional. When supplied, `parties` is required with exactly one map per party, including empty maps. `contract` maps contract field names to one source each. A citation may reference only a supplied non-null fact on its corresponding contract/party. Unknown or dangling references fail validation.

Each source permits `value` (scalar/null), `source_text`, `page_number`, `chunk_id`, `bbox`, `confidence`. A supplied citation requires a nonblank source quotation of at most 8,000 characters; absent evidence is omitted, never an empty citation. Pages are strict one-based integers. Boxes contain exactly finite `left`, `top`, `right`, `bottom`, with `0 <= left < right <= 1`, `0 <= top < bottom <= 1`; a box requires a page. Source text must be a real quotation. Structural validation cannot prove that a quotation or coordinate is actually supported by the original; provider grounding and manual evidence checks remain necessary.

Optional per-source/global confidence must be finite in `[0,1]`. Include it only when its provider documents the scale, and record semantics where useful. Validation of range does not establish provider calibration or cross-provider comparability. OpenAI extraction without independently validated grounding must omit invented citations/coordinates/confidence. DOCX uses text evidence/original download; no invented converted-page coordinates or inline-preview promise. One representative citation per field is a compatibility limitation, not preservation of every provider citation.

`extraction_metadata` supports optional string keys `workflow_version`, `provider`, `provider_version`, `model`, `model_version`, `api_version` (each at most 256 characters), optional `confidence_semantics` (1,000 characters), and `warnings` (up to 100 strings of at most 1,000 characters). Its UTF-8 JSON size is at most 16 KiB. Raw responses, prompts, arbitrary nested metadata, credentials and full document copies are outside this boundary. Workflows/operators are responsible for ensuring otherwise valid provenance/warning strings contain no secrets/document copies.

A completed result must contain at least one useful contract fact or named party. Empty/null/blank-only contract facts with no parties fail. Ordinary review permits missing evidence and corrections; approval still requires the existing permissions/mandatory fields. This boundary adds no field verification audit, stable draft-party IDs, or approval revision protocol.

## Request bounds and implementation helpers

Callback JSON is at most 5 MiB of UTF-8 with at most 20 nested containers, no compressed bodies, duplicate keys, or non-finite numeric tokens. Oversize output is rejected, not truncated. Ordinary fact strings are bounded at 100,000 characters. Deployment/workflow configuration must coordinate any changes to these release-owned limits.

Routes should bound streaming reads at `MAX_CALLBACK_BYTES + 1`, then call `parse_workflow_event(body, content_encoding)`. The helper returns the discriminated `ProcessingEvent`, `CompletedEvent`, or `FailedEvent`; `WorkflowPayloadError` exposes safe `detail` and `status_code` without echoing provider values. `parse_workflow_json` provides the raw checks for other machine bodies, then `WorkflowClaimRequest.model_validate` validates a claim. `validate_acceptance(payload, job_id, attempt_id)` checks the contracted acceptance identity; its caller separately enforces HTTP 202.

Store validated completion using `event.result.model_dump(exclude_unset=True)` or project it through `event.result.to_extraction_result()`. Omissions remain omissions, so unknown currency/role never acquire application defaults. `WorkflowEventAck` and `WorkflowClaimResponse` describe typed responses. Generate JSON Schema from the Python models/`EVENT_ADAPTER` if an external consumer needs a schema; do not maintain an independent hand-edited provider schema as application authority.

Focused tests: `cd backend && uv run pytest -q -p no:logging tests/test_workflow_contract.py`. Deterministic fixtures prove structural rules, not live extraction quality, provider-switch readiness, storage access, concurrency guarantees, or deployed connectivity.
