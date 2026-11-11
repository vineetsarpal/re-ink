# Organization closure

Migration `0020_organization_lifecycle` adds a non-tenant lifecycle record, with
purge progress reserved for #65. No purge or physical deletion runs in this
slice. The requesting user is retained as an HMAC made with
`TRIAL_IDENTITY_HASH_KEY`; configure that secret before enabling closure.

WorkOS must include `organization:close` in the authorized admin's token (#60).
`POST /api/organization/close` requires `{ "confirm": "CLOSE" }`. Closure returns
a UTC purge date 30 days after the request. Repeated close requests preserve that
date. Cancel with `POST /api/organization/cancel-closure` before the purge date;
a request at or after the deadline returns 409. Any member can read
`GET /api/organization/lifecycle`.

The router-level gate rejects closing organizations with 423 and
`detail.code=ORGANIZATION_CLOSING`, plus `purge_after`. Lifecycle operations,
self-leave, and system config are the only org-scoped exceptions. Machine and
scheduler routes retain their separate authentication. Normal requests share an
advisory lock; closing/cancelling takes its exclusive counterpart. Closure locks
jobs before attempts and settles reservations as failures in its transaction.
Cancelled attempts stop dispatching, reject Worker access/start/checkpoints,
and remain cancelled after reopening. Documents, contracts, parties, credentials
and original storage objects are retained. Provider requests already sent
cannot be recalled; provider-side copies remain governed by LandingAI's terms.

## Manual UI verification before release

- With `organization:close`, visit Organization settings and type `CLOSE` in the
  danger zone. Verify other values cannot submit and the exact purge date is
  shown after closing.
- As a member without that permission, confirm the closing screen replaces all
  app routes, shows the purge date and provider-retention note, and offers no
  cancel action. A second active tab should switch on its next API request or
  lifecycle poll/focus check.
- As the authorized admin, cancel during the grace period. Verify normal access
  and saved data return; cancelled extraction jobs remain cancelled.
- Verify close-only admins can reach Organization settings without SSO-management
  permission. SSO and key controls still require their own permissions.

HTTP tests exercise the lifecycle and route lock against real Postgres; the
frontend production build is checked. Live WorkOS/browser verification remains
a release check and has not been performed by the local automated suite.

## Scheduled purge after the grace period

Migration `0021_purge_role` installs conditional grants for `reink_cf_purge`.
`POST /api/maintenance/purge` uses its own scheduler bearer token and database
identity. Set all new backend secrets **before deploying the new backend**;
Cloudflare configuration validation requires a distinct role/URL and token.
Keep the existing production deployment gates in the trial runbook.

Manual production setup (operator terminal; never paste credentials into chat):

1. Create only the new login, without overwriting existing service roles:

   ```sh
   cd backend
   uv run python ../deploy/storage/create_service_roles.py --role reink_cf_purge
   ```

   The script prompts for the direct owner URL and production endpoint, generates
   a password, and stores it in the macOS Keychain. The role has no BYPASSRLS,
   superuser rights, memberships or table ownership. Apply migration 0021 via the
   normal release workflow. If creating the role after the migration, use the
   owner-run helper on that fresh role:

   ```sh
   uv run python ../deploy/storage/run_as_owner.py --target production uv run python ../deploy/storage/provision_purge.py reink_cf_purge
   ```

   Do not rerun the fresh-role helper against a role that already has grants.
   `SELECT(org_id)` and `DELETE` are granted on the explicitly enumerated tenant
   tables; lifecycle SELECT and only its progress/status UPDATE columns are
   granted. Tenant RLS stays enabled, with `app.current_org` bound per transaction.
   No read of encrypted keys or deletion/update of accounting is granted.

2. Generate a new independent printable random secret (at least 32 characters).
   Set `CLOUDFLARE_PURGE_TOKEN` and `CLOUDFLARE_PURGE_DATABASE_URL` as secrets in
   FastAPI Cloud. The URL must use `reink_cf_purge`, target the same production
   database as the other roles, and use `sslmode=verify-full`. The new token must
   differ from machine, dispatch, expiry and cleanup tokens. The bootstrap
   `deploy/set_cloud_env_from_keychain.py` recognizes both new names; it refuses
   existing variables, so use FastAPI Cloud secret settings for this incremental
   update. Confirm `WORKOS_API_KEY` and `WORKOS_CLIENT_ID` remain configured.

3. Store that same purge token in the Worker using its hidden prompt, from the
   repository root:

   ```sh
   npx wrangler secret put REINK_PURGE_SCHEDULER_TOKEN --config workflows/cloudflare/wrangler.toml
   ```

   Deploy the backend with the migration, then deploy the Worker with all four
   distinct scheduler tokens configured:

   ```sh
   npx wrangler deploy --config workflows/cloudflare/wrangler.toml
   ```

4. Verify authenticated maintenance outcomes and lifecycle progress. A missing,
   incorrect or oversized bearer token returns 401 when configured. Defaults are
   `PURGE_BATCH_LIMIT=5` organizations and `PURGE_TIME_BUDGET_SECONDS=10` (at most
   12). `processed` counts organizations attempted, including recorded failures;
   inspect `purge_step`, `purge_attempts` and `last_purge_error` for completion.

Each run skips active/cancelled closures and future deadlines. A per-organization
lifecycle advisory lock serializes each checkpoint with close/cancel and other
purge workers. Cancellation is rejected after the deadline, including between
purge checkpoints. Progress is `started` → `storage_done` → `data_done` →
`workos_done` → `done`/`purged`. Failures retry the unfinished step next run;
finished steps are not repeated. An ambiguous WorkOS response can cause its
DELETE to be retried; a 404 is success. Exactly-once external deletion cannot be
guaranteed across a crash, so that operation is idempotent.

Storage is deleted only under the hashed tenant prefix and verified by an empty
listing before deleting any tenant rows. An unclassified table with `org_id`
stops data deletion and WorkOS deletion until its retain/delete policy and
privileges are updated. Contracts, parties, links, documents, attempts,
executions, outbox/receipts, upload intents, storage cleanup, credentials,
acknowledgments and provisioning intents are deleted. Lifecycle, organization
quota, reservation/rate accounting, global quota and trial user/domain claims
survive. WorkOS deletion occurs only after storage verification and committed
tenant deletion. #65 does not delete data held by LandingAI.
