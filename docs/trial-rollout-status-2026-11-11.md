# Trial rollout status (2026-11-11)

Read-only production checks at approximately **18:37 UTC** confirmed that the
protocol-2 trial is deployed and restricted to one allowlisted organization.
This snapshot supersedes earlier statements that the trial is disabled or the
protocol-2 changes are local only. It is not approval for public launch.

## Confirmed state

| Check | Observation | Evidence |
| --- | --- | --- |
| Backend CI | Current `main`, `ea0bb6ddaf1e40572d10260cffdcd9989dd1b9d7`, passed migrations and deployment at 17:09 UTC. | [GitHub Actions run](https://github.com/vineetsarpal/re-ink/actions/runs/43065353201), including both successful job steps. |
| Public health | HTTP 200, `healthy`; app version is `dev`. | `GET https://re-ink.fastapicloud.dev/health`. The reported version does not identify the deployed commit. |
| Backend protocol | HTTP 200, `protocol_version: "2"`. | Authenticated GET to the documented protocol probe using a short-lived synthetic capability. No claim or provider-start request was sent. |
| Worker | Version `d0e0bd0e-85f5-402b-b812-37b093d3e442` receives 100% of traffic; deployed at 17:28:09 UTC. | Cloudflare deployment API. Downloaded active source contains protocol version `2`, the compatibility probe, and `provider-start` authorization. |
| Cron | `* * * * *`, configured at 17:28:11 UTC. | Cloudflare Worker schedules API. This confirms configuration, not successful execution of each maintenance route. |
| Extraction queue | Delivery is not paused. One `reink-extraction` Worker consumer, batch size 1, concurrency 1, DLQ `reink-extraction-dlq`. | Cloudflare queue detail API. |
| Backlogs | Extraction queue and DLQ each report zero messages and zero bytes. | Read-only [queue metrics API](https://developers.cloudflare.com/api/resources/queues/methods/get_metrics/). No messages were pulled, acknowledged or replayed. |
| Trial settings | Cloudflare routing, trial and quota enabled; one organization in the allowlist. Limits: 5 free successes per organization, 50 monthly successes per organization, 100 global monthly starts, 100 global successful/pending reservations. | FastAPI Cloud environment read, restricted to non-secret settings. Organization identifiers omitted. |

## Existing extraction evidence

The existing restricted `reink_cf_machine` database login was used with
`transaction_read_only=on`, verified TLS, and tenant scope set to the allowlisted
organization. Only lifecycle/accounting metadata was queried; document contents,
provider keys and encrypted credential snapshots were not read.

- Three attempts are completed in that organization; no other attempt statuses
  were returned.
- One attempt was created after the latest CI backend deployment, at
  **17:13:22 UTC**, and completed at **17:22:23 UTC**. It has trial funding,
  `provider_started=true`, a succeeded reservation, a completed terminal
  checkpoint and a delivered terminal receipt, with no attempt error code.
- Global November accounting shows **3 starts, 3 successes, 0 pending**.
- Active unacknowledged outbox work and live dispatch leases for the allowlisted
  organization are both zero.

This corroborates a completed extraction after the backend update, before the
17:28 final Worker deployment. No new extraction was started during this audit.
There is no before/after counter snapshot here to independently prove the
canary's exact accounting delta. Tenant-scoped outbox observations do not prove
that every other organization's database work is drained.

## Remaining checks

- Inspect extraction quality, source evidence and guided review in the
  authenticated UI; this audit inspected lifecycle metadata only.
- Browser-check the current `TRIAL_CAPACITY_UNAVAILABLE` message and retry
  eligibility. The earlier [UI verification](trial-followup-ui-verification.md)
  used fixtures and predates the capacity-message change.
- Verify recent dispatch, expiry and cleanup execution outcomes and monitoring.
  An enabled cron and empty queues do not establish all maintenance paths work.
- Confirm the live Alembic revision and schema/role invariants with a suitable
  read-only owner audit. CI migration success is confirmed, but the restricted
  role audit here did not query migration history or audit every role grant.
- Before expanding access, verify actual WorkOS signup controls and establish
  organization-provisioning reconciliation as described in the
  [production setup](trial-production-setup.md).
- Finish the doc cleanup recorded in commit `a954be8`: extract embedded runbook
  helpers into `deploy/`, deduplicate the README, remove the captured Wrangler
  help, document `VERSION` copying for manual deploys, and clarify the CI
  `backend/**` path filter. The global Wrangler executable used for this audit
  reports 4.24.3; the original runbook help capture refers to 4.160.1.

No production settings, database records, quota counters, deployments or queue
messages were changed by this audit. No browser verification was performed.
