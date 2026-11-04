# Provider and acceptance evidence

The implementation has deterministic local evidence. **The live demo is not accepted or ready:** actual deployment, both-provider interoperability, human-confirmed ground truth and measured provider quality/citations remain unperformed. Fixtures cannot satisfy those gates. This report separates the evidence so local passes cannot imply a deployed/live result.

## Deterministic contract lifecycle and security

The focused #52 suite runs against real disposable PostgreSQL at port 55432 with migrations and restricted non-owner/non-BYPASSRLS application sessions:

```sh
cd backend
UV_CACHE_DIR=/tmp/reink-uv-cache TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/reink_acceptance_test uv run --no-sync pytest -q -p no:logging tests/test_workflow_acceptance.py tests/test_permission_enforcement.py tests/test_extraction_isolation.py tests/test_corpus_evaluation.py
```

Observed: **51 passed**, 6 dependency/deprecation warnings. Complete final output: `/tmp/reink-52-tests-final.log`. Earlier failed fixture attempts are preserved in `/tmp/reink-52-tests.log`, `/tmp/reink-52-tests-2.log`, `/tmp/reink-52-tests-3.log`; they identified a missing claim schema_version and outdated removed-route/disabled-agent expectations. The final changes fix fixture expectations rather than relaxing application boundaries.

The orchestrator ran the final integrated backend suite on disposable `reink_final_test`: **253 passed**, 20 dependency/deprecation warnings, `/tmp/reink-integrated-tests.log`. The database was created fresh and upgraded through migration 0007; the final run includes the additional endpoint concurrency, ambiguous-commit and corpus scorer cases. Local PostgreSQL is **14.17**; the repository CI config selects PostgreSQL 17, but CI was not run here. Dedicated worker provisioning/access checks are recorded in `/tmp/reink-worker-probe.log`, `/tmp/reink-worker-scope-tests.log` and `backend/tests/test_worker_scope.py`. The script-backed test checks the actual dedicated restricted role, literal customer RLS despite malicious session-org settings, and denial of approved contract/party writes. These local checks do not establish Neon/VPS access.

The generated n8n artifacts passed **18 deterministic Node tests**, including canonical backend result validation: `node --test workflows/n8n/tests/*.test.cjs`. Sanitized Compose configuration validation and a local dispatcher image build passed; no n8n import was performed.

After moving synchronous original-document storage I/O into FastAPI's request thread pool, the focused acceptance suite passed again: **10 passed**, `/tmp/reink-final-document-threadpool-tests.log`. The database authorization snapshot and post-fetch deletion/deadline fences remain intact.

| Gate | Deterministic evidence and limitation |
| --- | --- |
| Upload/dispatch/result/review | Actual PDF and DOCX multipart uploads; fake private object store; real committed job/attempt/outbox; `dispatch_once` with explicit fake n8n HTTP; actual service claim, original fetch and callback routes; status/result; correction and permission-gated local approval |
| No network transaction | Worker HTTP and machine original fetch assert no tracked database session holds a transaction at network/storage I/O; outbox is committed before dispatch |
| Storage/DB atomicity | Failed storage creates no runnable work. Precommit DB failure removes orphan when possible; cleanup outage leaves object for reconciliation without runnable rows. Lost commit response preserves original if commit succeeded. If absence cannot be proved, original is retained |
| Service identity/tenant | Missing/wrong/dispatch credentials rejected for claim/document/event with no mutation; cross-org document/job/callback hidden; malformed result rejected; service credential cannot authorize human approval |
| Claim/retry concurrency | Competing actual endpoint requests use independent committed restricted sessions: exactly one extraction claim owner; concurrent manual Retry yields one replacement and one conflict |
| Callback/lifecycle | Existing `test_workflow_lifecycle.py` covers committed leases, restart fencing, same-attempt transport retry, owner/lost acknowledgement, replay/conflicting IDs, early completion, stale/terminal fences, deadline races and durable deletion/cleanup retry |
| Terminal polling/retry | Status endpoint expires deadlines to visible timed_out; Retry requires document permission; stale callback cannot replace new work; deletion revokes polling/callback access |
| Human review | Corrections persist on approval; service extraction and Retry create no approved parties/contracts. Missing explicit currency, identity/dates and canonical party roles yield validation errors; malformed party collections fail validation |
| Legacy/capabilities | Legacy rows excluded from human workflow status/result/file routes. Removed mock-job route rejects POST. Disabled AI agents retain permission enforcement; no provider fixture fallback |
| Contract/normalizers | Separate contract and provider fixture suites cover type/version/size/evidence/party alignment, missing facts, unreadable/empty output and provider-specific normalization. Their local assertions establish deterministic validation only |
| Corpus | Six checked-in originals, independent expected fixture manifest, genuine image-only scan and valid blank PDF; offline scoring mechanics tested. Human ground-truth signoff pending |

Existing rollback-session tenancy tests remain useful for authorization but are not cited as concurrency/restart evidence. Actual service-auth credential binding, WorkOS login, S3 semantics and provider execution are not replaced by injected identity/session/storage fixtures.

## Live interoperability and deployment access

Every item below is **UNPERFORMED**, with no live credential use or public deployment claimed:

- Actual VPS runtime and restricted Neon DNS/TLS/login/lease tests.
- Actual private R2 immutable put/get/delete and cleanup/reconciliation access.
- DNS/HTTPS, administrator authentication and service credential binding/rotation.
- Persistent n8n workflow state, pinned runtime import and restart recovery in the selected deployment.
- Live LandingAI branch over all six originals, with release/model/API/workflow/execution/attempt identifiers and every outcome/rerun recorded.
- Live OpenAI branch over the same originals and re-ink release, with the same records.
- Agreed upload pause, old-worker shutdown, cutover and rollback rehearsal.

No selected provider key is required by re-ink. Provider billing/model access belongs to trusted workflow configuration. Missing actual access is an unperformed gate, not evidence of successful deployment.

## Provider quality and manual corrections

No live provider predictions have been measured. **LandingAI: 0 executions; OpenAI: 0 executions.** Correctness denominators are unavailable, not zero-error scores. The synthetic expected manifest is independently drafted by the implementation agent and needs human review/signoff before provider execution; human authorship/review is not invented.

Use `backend/tests/corpus/expected.json` and `scripts/evaluate_corpus.py` to report every normalized run. Keep missing, incorrect, unexpected and unsupported facts distinct; separate party name/role results, ambiguous/missing facts, failures and manual corrections. The evaluator is offline, never calls providers and does not certify a `mode=live` declaration. It retains reruns individually rather than selecting the best result. A small synthetic corpus does not establish production accuracy or a numerical release threshold.

Record case ID, frozen original hash, provider/model/API/workflow version, re-ink release, run/job/attempt/workflow execution IDs, outcome/error, fields assessed/correct/missing/incorrect/unexpected, party outcomes, corrections and final human action. Preserve failures and configuration changes. Failed cases have explicit case outcomes and no invented scalar prediction denominator. Long descriptions and unexpected-but-source-supported values require manual review.

## Evidence and citation correctness

**Live ADE citation audit: UNPERFORMED. OpenAI live evidence coverage: UNPERFORMED.** Mechanical literal quote checks are not semantic/box verification. For each ADE source verify quoted text, page, field support and rectangle on the original. Record supplied evidence coverage separately from incorrect citations and absent evidence. Do not infer truthful citations from valid coordinates alone.

OpenAI must omit unvalidated grounding/confidence. DOCX uses original download and omits converted-page coordinates unless a separately reviewable rendition is deliberately supplied; none is part of this milestone. Deterministic source/normalizer tests and UI fixture demonstrations cannot establish genuine provider citation fidelity. A completed fixture without field_sources establishes absence handling only.

## Browser and presentation checks

Final `npm run build` and `npm run lint` both passed, with complete output in `/tmp/reink-frontend-final-build.log` and `/tmp/reink-frontend-final-lint.log`. Vite retains the existing large-chunk advisory; lint has no errors or warnings.

The real frontend components were exercised in Chromium through Playwright using the isolated `frontend/tests/workflow-ui` fixture entry. The explicit yellow banner identifies mocked identity/API/extraction/approval. Checks passed for canonical synthetic PDF rendering and an active source highlight, absent evidence, unset currency/party role, manual corrections and simulated approval, DOCX download without inline preview, stopped terminal polling, explicit Retry and hidden viewer upload controls. The final `window.fixtureUiChecksPassed === true` assertion confirmed every asynchronous check completed. Logs: `/tmp/reink-ui-final-checks.log`; inspected PDF review screenshot: `/tmp/output/playwright/reink-pdf-review.png`. The final browser reported no console errors and two existing React Router future-flag advisories. An interrupted fixture-server connection failure is preserved in `/tmp/reink-ui-final-firstfailure.log`; restarting that loopback server resolved it.

The authored rectangle demonstrates UI overlay behavior only, not ADE citation fidelity. This harness cannot establish genuine WorkOS/provider/deployment behavior. No frontend test framework or production fixture fallback was added; instructions and the repeatable CLI check are in `frontend/tests/workflow-ui/README.md`.

The final presentation must identify the separately hosted simulated customer environment and external AI flows. A provider defect should be recorded and corrected visibly; invented facts, empty success on unreadable input and fabricated evidence are defects to fix before acceptance. Backup/provider retention and deletion boundaries remain those in the storage/cutover runbooks. Do not claim deletion of unrelated approved contracts, parties or tenants.

## Provider response reference

Checked against official documentation on October 15, 2026. This is the implementation handoff for #46, scoped to the LandingAI/OpenAI decision in [#51](https://github.com/vineetsarpal/re-ink/issues/51#issuecomment-6206615705) and the existing result contract in [#48](https://github.com/vineetsarpal/re-ink/issues/48#issuecomment-6181857239). It does not replace the backend schema or claim live validation. Provider adapters belong in the versioned n8n workflow.

## LandingAI ADE REST

Use authenticated multipart `POST https://api.va.landing.ai/v1/ade/parse` with the original in `document` and an explicitly configured `model`. Retain the returned `markdown`, `chunks`, `grounding`, and response model version while normalizing. [Parse API](https://docs.landing.ai/api-reference/tools/ade-parse).

Then multipart `POST https://api.va.landing.ai/v1/ade/extract`, supplying `markdown` as a file, `schema` as a JSON string, configured `model`, and `strict=true`. The schema is provider input derived from the approved business fields, not an independent app contract. [Extract API](https://docs.landing.ai/api-reference/tools/ade-extract).

Pass Parse Markdown unchanged so its element IDs survive. A 206 response is partial content, not ordinary success; schema violations can still produce 206 with strict mode. Check `metadata.schema_violation_error`, warnings, and Parse failed pages explicitly. A safe initial workflow may fail these cases instead of silently presenting a complete extraction. [Extraction behavior](https://docs.landing.ai/ade/ade-extract).

Map `extraction` business values; traverse matching nested `extraction_metadata` for each field's `references` and `value`. References may name UUID chunks, table cells such as `0-u`, or other HTML IDs. Capture requested/resolved versions and any `metadata.fallback_model_version`; an unexpected provider model fallback needs explicit handling. This is the REST reference-ID format, not a universal SDK range/tree contract. [Extraction response](https://docs.landing.ai/ade/ade-extract-response).

Evidence mapping:

- Resolve reference IDs in global `grounding`; table cells have their own boxes and `position.chunk_id`. Chunk-only lookup loses cell evidence.
- Obtain text from `chunks[].markdown` or the referenced HTML element within Parse Markdown. Do not relabel extracted `value` as a quotation.
- Convert zero-based `page` to one-based `page_number`. Boxes already use normalized `{left,top,right,bottom}`, with top-left origin.
- Global grounding confidence measures parsed text, ranges 0..1, and is not a calibrated correctness probability. It is not extraction confidence; omit it initially.

These response facts come from [Parse JSON and grounding](https://docs.landing.ai/ade/ade-json-response). Adapter policy: select the first resolvable genuine text reference in provider order, preserving its matching location; omit unresolved evidence rather than inferring a page from an ID. Reject invalid rectangles under #48. Do not use generated figure descriptions as literal document quotations. Keep party values and their source maps together through filtering to preserve indices. One representative citation deliberately loses other provider references.

PDF and DOCX are documented API inputs. DOCX is converted to PDF and pagination/layout may change. Consequently, retain available source text for DOCX but omit converted page/box locations in the unchanged original-document review. [Supported types and conversion](https://docs.landing.ai/ade/ade-file-types). Synchronous Parse supports up to 100 PDF pages; Parse Jobs is a distinct interface. Enforce the chosen path's limits and fail explicitly rather than switching APIs implicitly. [Rate and page limits](https://docs.landing.ai/ade/ade-rate-limits). No synchronous PDF/DOCX byte ceiling was established by these pages; do not invent one or equate the app's 50 MiB ceiling with provider acceptance.

## Direct OpenAI Responses

Use `POST https://api.openai.com/v1/responses`, Bearer authentication, and JSON. Request shape:

```json
{
  "model": "<operator-configured compatible model>",
  "store": false,
  "input": [{"role": "user", "content": [
    {"type": "input_file", "filename": "synthetic.pdf", "file_data": "data:application/pdf;base64,<bytes>"},
    {"type": "input_text", "text": "Extract only stated contract facts; unknown values are null."}
  ]}],
  "text": {"format": {"type": "json_schema", "name": "reinsurance_contract", "strict": true, "schema": {}}}
}
```

Replace the empty illustrative schema with a supported generated schema. For DOCX use its original filename and MIME type. Responses supports DOCX text extraction without embedded images/charts; PDF-capable models receive text and page images. Each file must be under 50 MB; combined files are limited to 50 MB. This is not 50 MiB. Base64 enlarges the HTTP body; transport/proxy limits and model context remain additional constraints. Prefer small synthetic inputs. [File inputs](https://developers.openai.com/api/docs/guides/file-inputs).

Structured Outputs needs a root object, all declared properties required, nullable types for unknown values, and `additionalProperties:false` on every object. The documented schema ceiling is 5,000 properties, 10 nesting levels, and 120,000 total schema-name/enum/const characters. Use only supported keywords. Inspect response status before parsing: incomplete (including token exhaustion/content filter), failed, refusal content, missing output, or invalid JSON must not become empty success. Traverse `output` message items and `content` entries for `output_text`; do not assume `output[0]` is the final message. Then run canonical business validation and reject no-useful-facts output. JSON conformance alone proves neither correctness nor evidence. [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs).

The approved minimal branch omits `field_sources`, per-field confidence, and global confidence. Model-supplied quotations/pages/boxes are not validated citations. Keep unknown currency and role unset; do not fabricate defaults. Metadata may identify exact model/configuration versions and bounded missing-evidence warnings, without raw responses or prompts.

## Remaining acceptance evidence

No provider calls, account inspection, or accuracy measurement were performed for this document. Both branches still require credentials, accessible models/endpoints, sanitized captures from actual synthetic requests, and pinned n8n/node/API/parser/model versions in the tested release manifest. Documentation examples and deterministic normalizer fixtures are not captured live responses.

The two-live-provider gate remains open until the same labeled PDF/DOCX corpus runs through both branches on one re-ink build. Measure business correctness separately from ADE quote/location correctness, disclose OpenAI's evidence gap, and exercise ambiguous/missing facts and unreadable inputs. Check actual DOCX inline file behavior with the selected OpenAI model and actual nested/array ADE metadata with the selected schema; do not promote these documentation-derived mappings to tested compatibility. External provider processing/retention remains separate from n8n's seven-day pruning policy.
