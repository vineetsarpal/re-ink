# Production trial setup

The owner chose the existing production environment for synthetic validation;
there are no live users. The trial remains disabled until the full setup and
validation are complete. Existing data must be preserved.

The approved initial limits are five successful free extractions per organization
(lifetime), 50 successful extractions per organization per UTC month, and 100
free extraction starts across all organizations per UTC month. A free start
counts even if processing fails; customer-key starts do not count against it.
Configure these non-secret settings when enabling the production trial:

```text
EXTRACTION_FREE_LIMIT=5
EXTRACTION_MONTHLY_LIMIT=50
EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT=100
EXTRACTION_GLOBAL_TRIAL_MONTHLY_LIMIT=100
```

The second global setting limits successful or pending free reservations to
100 as a complementary admission safeguard; the starts limit above is the
controlling cap on funded provider attempts. Leave both code defaults at zero,
so a deployment without explicit limits cannot enable the trial.

Follow the agreed order: inspect existing resources and confirm the database
target, prepare restricted database roles and validate migrations, configure
Cloudflare, configure protected backend settings, then validate with synthetic
documents. Never paste credentials into deployment notes or the chat.

The owner selected `reink_db` on the `production` branch of the Neon `re-ink`
project as the intended target. FastAPI Cloud's masked connection has not been
verified against it; deliberately configure the application to use this target
before treating it as the active database. Run schema migrations over a direct
owner connection and use separate restricted identities at runtime.

On 2026-11-10, migrations 0008–0014 succeeded on the separate
`trial-migration-validation` branch copied from production, and then on the
selected production `reink_db`. Contract, party and extraction-job counts
matched before and after in both cases. The trial remains disabled.
The copied branch's existing `reink_app` role had effective access to the new
tables through the owner's default privileges; verify the production role and
the dedicated machine identities before enabling the trial.
The five machine and maintenance provisioning scripts also completed on that
branch using dedicated non-login `reink_check_*` roles. The updated cleanup
role has the required function access without direct upload-intent read access.
These checks do not provision or verify the production runtime identities.

Before enabling customer access, finish readiness checks, turn on the queue
consumer and maintenance schedule, and verify storage, paid-call fencing,
limits, signup controls and synthetic extraction end to end. The customer-key
feature is intentionally disabled in the code until that work is complete.
Account deletion remains disabled pending separate closure safeguards.

Public signup controls must be checked in the actual WorkOS environment. The
global start limit bounds trial calls, but per-organization limits alone do not
prevent repeated signups. Organization provisioning serializes concurrent
requests for the same user, but a crash or ambiguous WorkOS failure after an
organization is created can still leave an orphan or duplicate; establish a
reconciliation procedure before public launch.

Expired uploads keep tombstones that are revisited for late storage writes
every 24 hours. Once a successful rescan happens at least 7 days after the
upload lease deadline, the row is marked `deleted` and never rescanned (rows
are retained, not removed). Uploads deleted in the request itself are marked
`deleted` immediately. Failed deletions retry after five minutes without a
limit, so monitor failing rows. Each scheduler call processes up to
`CLEANUP_BATCH_LIMIT` (default 25) items, alternating fairly between upload
tombstones and revoked originals, and starts no new item after
`CLEANUP_TIME_BUDGET_SECONDS` (default 10; the Cloudflare caller aborts at 45s).

Over-quota uploads are rejected before any storage write. Those rejections
count toward `EXTRACTION_ATTEMPTS_PER_MINUTE`, so retry loops get 429 with
`Retry-After`.

### Migration 0015 (`0015_trial_hardening`)

Apply over the direct owner connection after 0014: `uv run alembic upgrade head`.
It runs plain `CREATE INDEX` (short write locks, with a 10s `lock_timeout`;
the tables are small), adds the `deleted` upload-intent status, sets
`search_path = pg_catalog, pg_temp` on every `reink_*` SECURITY DEFINER
function, and revokes EXECUTE on them (and all access to `cleanup_turn`) from
`reink_app` if that role exists. No function signature changes, so existing
maintenance roles keep their grants and the provisioning scripts need not be
rerun. Afterwards confirm that this returns no rows:

```sql
SELECT p.oid::regprocedure FROM pg_proc p
WHERE p.prosecdef AND p.proname LIKE 'reink\_%'
  AND has_function_privilege('reink_app', p.oid, 'EXECUTE');
```

The migration does not change owner default privileges. A SECURITY DEFINER
function added by a later migration must revoke access from `reink_app`
explicitly, or the owner's default privileges should be adjusted separately.

### Production state (2026-11-10)

`0015_trial_hardening` was applied first to `trial-migration-validation`, then
to production `reink_db`; counts were unchanged and `reink_app` can execute no
definer function. Login roles `reink_cf_machine`, `reink_cf_dispatch`,
`reink_cf_expiry` and `reink_cf_cleanup` were created on production with
`deploy/storage/create_service_roles.py` (passwords in the operator's macOS
Keychain, service `re-ink neon production reink_db`) and granted with the
matching `provision_*.py` scripts via `deploy/storage/run_as_owner.py --target
production`. `deploy/storage/check_role_grants.py` lists their effective
privileges. `reink_cf_auditor` was not created: nothing calls it yet.

### Service-role connection strings

Each `CLOUDFLARE_*_DATABASE_URL` must use its own role and
`sslmode=verify-full`, against the same endpoint and database as
`DATABASE_URL`. If no `sslrootcert` is given, the backend pins the bundled
`certifi` CA file, because the libpq bundled with `psycopg[binary]` may not
find the host certificate store (observed on macOS with `sslrootcert=system`).
An explicit `sslrootcert` in the URL is respected.
