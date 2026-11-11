# Preparation failure UI verification (2026-11-11)

The Worker checkpoints `PREPARATION_FAILED` as a terminal failed event before
provider execution. Delivery through `workflow_service.ingest_event` saves the
error code and message on the selected attempt and job. The documents status API
now returns `error_code` and `can_retry`; `documentApi.getStatus` carries those
fields through its `DocumentExtractionStatus` response type.

`ExtractionStatus` displays a specific preparation-failure message and offers
retry only when both its caller permits retry and the status API reports
`can_retry: true`. `UploadPage` permits it for real trial jobs. The API flag
requires a selected failed/timed-out attempt, trial access, upload permission,
the current processing acknowledgment, a stored retryable flag that is not false,
and read-only quota/rate eligibility. The retry endpoint uses the same service
policy and atomic reservation at click time. A retry creates a new
attempt on the same job. The durable Cloudflare terminal checkpoint retains the event's `retryable` flag;
a false flag suppresses the button and rejects POST retry. Legacy jobs have no retry path and return false.

Verification used local Chrome with a temporary Vite component harness. Status
and retry calls were replaced with local fixtures, and all non-local browser
requests were blocked. This was a script-driven browser check followed by manual
visual inspection of the rendered screenshot, not an authenticated full-page
or provider integration check:

- A failed status with `error_code: PREPARATION_FAILED`, `can_retry: true`, and
  `allowRetry` rendered “We could not prepare your document for extraction.
  Please try again later.” and a “Retry extraction” button. The screenshot
  showed the error icon, complete message and unobstructed button.
- Clicking retry switched the fixture to queued and resumed the polling
  indicator.
- Loading the same failure with `can_retry: false` rendered the message with
  zero retry buttons.

The temporary harness was deleted and its server stopped. No frontend test
runner or permanent browser-test dependency was added. The backend regression
file `tests/test_preparation_failure_status.py` first failed three cases for
missing API fields, then passed all three. It checks both retryable hints,
actual retry acceptance and a new attempt, queued-state retry rejection, and
legacy retry exclusion. The isolated local database was
`reink_followups_ui_20261111`. Frontend build and changed-file ESLint passed;
Vite retains its existing large-chunk warning.

Review follow-up: the component also displays `TRIAL_CAPACITY_UNAVAILABLE` as
“Free extractions are temporarily unavailable. Add a LandingAI key or try again
later.” The server's `can_retry` is authoritative; the redundant client status
recheck was removed. The earlier browser observations above predate these
policy corrections and do not constitute a browser check of the capacity text.
Current backend tests cover both retryable values and six quota/rate denials,
including unchanged counters across repeated status reads.
