# Production trial setup

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

Before deploying trial eligibility, set `TRIAL_IDENTITY_HASH_KEY` as a secret in
FastAPI Cloud. Generate a high-entropy value and retain it across deployments.
Migration 0017 needs no identity or WorkOS secrets. After migrating, run the
one-off backfill with the same identity key and migration-owner database URL
before expanding trial access; see [trial eligibility setup](trial-eligibility.md).

The owner chose the existing production environment for synthetic validation;
there were no live users at initial setup. A read-only check on 2026-11-11
confirmed protocol 2 deployed on the backend and Worker, queue delivery enabled
and a configured minute cron. Existing data must be preserved. Earlier dated
setup notes below describe historical state.

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
so a deployment without explicit limits cannot spend free-trial funding.

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

Before expanding customer access, finish readiness checks, confirm queue
delivery and successful maintenance execution, and verify storage, paid-call
fencing, limits, signup controls and synthetic extraction end to end. Queue
delivery and the cron configuration were confirmed in the linked snapshot;
recent maintenance execution outcomes were not checked. The customer-key
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
`deleted` immediately. Failed deletions retry after five minutes, doubling on consecutive failures
to a 24-hour cap. Success resets the failure counter; persistent failures
continue daily and need monitoring. Each scheduler call processes up to
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

### Protocol-2 changes (2026-11-11)

Migration `0016_cleanup_backoff` adds a consecutive cleanup failure counter and
replaces `reink_finish_expired_upload` with the same signature and ACL. Existing
cleanup role grants remain sufficient; provisioning must not be rerun. Its
downgrade restores the five-minute schedule and removes the counter. Lease,
fencing, live-reference checks, daily rescans and seven-day retirement remain.

The Cloudflare claim now authorizes preparation only. A separate one-shot
`provider-start` request counts the trial start after document and credential
fetches succeed, immediately before the provider probe. Existing machine role
grants cover this operation. Protocol 2 now rejects mismatched pairs before a
claim can spend a start. These changes were subsequently merged and deployed
(verified read-only on 2026-11-11). The coordinated procedure below records the
rollout sequence rather than a list of still-pending deployment steps.

Preparation failures settle without spending a global trial start. Failed
provider calls still count against the global monthly cap of 100. Provider-start
authorization is never retried: a lost acknowledgment can conservatively spend
a start without making a provider call. A process crash can still require
expiry; no exactly-once provider execution guarantee is made.

### Coordinated protocol-2 rollout

For a **separately authorized** production window; only local help/SQL checks
were performed during this review. Freeze other backend merges/deploys:
`.github/workflows/deploy.yml` runs **upgrade head → FastAPI deploy** on backend
pushes to `main`. Do not merge until step 4. Record the old backend SHA, Worker
version and intake settings; use linked, clean release checkouts. Preserve keys, grants
and quota counters. Commands start at repo root; keep shell tracing off.

Verified locally with Wrangler **4.160.1**:
`queues`, `pause-delivery`, `resume-delivery`, `info`, `triggers deploy`, `deploy`,
`tail`. Recheck help when changing versions.

**1. Block intake on the currently running backend release.** From its linked
checkout (not the candidate checkout), keep `CLOUDFLARE_TRIAL_ENABLED=true`,
`CLOUDFLARE_ENABLED=true`, `EXTRACTION_QUOTA_ENABLED=true` and existing keys/limits.
Set `EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT=0`, then deploy that same
backend release. Also enable the ingress maintenance gate described above to
block customer uploads/retries; leave machine and maintenance routes available.

```sh
cd backend
uv run fastapi cloud env set EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT 0
uv run fastapi deploy --app-id "$FASTAPI_CLOUD_APP_ID"
cd ..
```

Verify free uploads are rejected by the capacity policy and customer uploads and
retries are rejected by the ingress gate. Admitted requests can finish; status
and machine/maintenance routes stay enabled. Preserve the kill switch and
maintenance gate through CI. Trial=false permits legacy uploads;
Cloudflare=false blocks draining.

**2. Stop cron dispatch, drain the old matched pair, then pause delivery.** Make
a local, uncommitted config beside the original so its relative `main` stays
valid. This only changes schedules; it retains the consumer configuration:

```sh
python3 - <<'PYCONFIG'
from pathlib import Path
p = Path('workflows/cloudflare/wrangler.toml')
s = p.read_text()
assert s.count('crons = ["* * * * *"]') == 1
p.with_name('wrangler.rollout.toml').write_text(s.replace('crons = ["* * * * *"]', 'crons = []'))
PYCONFIG
npx wrangler triggers deploy --config workflows/cloudflare/wrangler.rollout.toml
```

Confirm **no Cron Triggers** in the Worker dashboard (`triggers deploy` is
experimental). Empty crons stops dispatch; leaving cron on would enqueue work.
It also stops expiry/cleanup: invoke them manually with existing dedicated
tokens. Let scheduled invocations already running finish; keep old Worker code.

Create this helper: use scheduler tokens for maintenance and a synthetic user's
access token for document routes. Hidden prompts keep credentials out of history:

```sh
cat > /tmp/reink-rollout-http.py <<'PYHTTP'
import getpass, sys
import httpx
method, path = sys.argv[1:3]
headers = {"Authorization": "Bearer " + getpass.getpass("Bearer credential for " + path + ": ")}
with httpx.Client(base_url="https://re-ink.fastapicloud.dev", timeout=60, follow_redirects=False) as c:
    if len(sys.argv) == 4:
        with open(sys.argv[3], "rb") as f:
            r = c.request(method, path, headers=headers, files={"file": ("synthetic.pdf", f, "application/pdf")})
    else:
        r = c.request(method, path, headers=headers)
    print("HTTP", r.status_code)
    r.raise_for_status()
    data = r.json()
    print({k: data[k] for k in ("job_id", "status", "processed", "attempted", "error_code") if k in data})
PYHTTP
cd backend
uv run python /tmp/reink-rollout-http.py POST /api/maintenance/cloudflare-dispatch
uv run python /tmp/reink-rollout-http.py POST /api/maintenance/expiry
uv run python /tmp/reink-rollout-http.py POST /api/maintenance/cleanup
cd ..
```

Repeat bounded dispatch/expiry as needed with the **old** consumer still running;
maintain cleanup periodically. When SQL active counts and backlog are zero:

```sh
npx wrangler queues pause-delivery reink-extraction --config workflows/cloudflare/wrangler.rollout.toml
npx wrangler queues info reink-extraction --config workflows/cloudflare/wrangler.rollout.toml
npx wrangler queues info reink-extraction-dlq --config workflows/cloudflare/wrangler.rollout.toml
```

`info` checks identity/wiring only. **Wrangler has no backlog command or pause
status output** (confirmed in its bundled `src/queues/cli/commands/info.ts`).
In Queues dashboard, confirm `reink-extraction` is paused and backlog is zero;
check the DLQ too. Require fresh, stable metrics. If work remains, resume the
old consumer (step-6 command), drain, then pause again. Never purge/pull/ack/replay
messages to fake a drain; investigate DLQ entries separately.

**3. Confirm database and invocation drain.** Save this read-only check locally;
the owner wrapper hides the URL and requires confirmation of the production
endpoint. Do not substitute the tenant app role: RLS would hide other orgs.

```sh
cat > /tmp/reink-rollout-check.py <<'PYSQL'
import os, sys
import psycopg
from psycopg.rows import dict_row
queries = [
    "SELECT version_num FROM public.alembic_version",
    """SELECT count(*) AS pending_outbox_total,
       count(*) FILTER (WHERE a.status IN ('queued','processing') AND j.deleted_at IS NULL
         AND j.selected_attempt_id=a.attempt_id) AS pending_outbox_active,
       count(*) FILTER (WHERE o.lease_until > clock_timestamp()) AS live_dispatch_leases
       FROM public.workflow_outbox o JOIN public.extraction_attempts a USING(attempt_id)
       JOIN public.extraction_jobs j ON j.job_id=a.job_id WHERE o.acknowledged_at IS NULL""",
    """SELECT count(*) FILTER (WHERE a.status='queued') AS queued,
       count(*) FILTER (WHERE a.status='processing') AS processing
       FROM public.extraction_attempts a JOIN public.extraction_jobs j ON j.job_id=a.job_id
       WHERE j.deleted_at IS NULL AND j.selected_attempt_id=a.attempt_id""",
    "SELECT month,trial_starts,trial_successes,trial_pending FROM public.extraction_quota_global WHERE id=1",
    """SELECT (SELECT count(*) FROM public.storage_cleanup WHERE lease_until > clock_timestamp()) AS cleanup_leases,
       (SELECT count(*) FROM public.upload_intents WHERE cleanup_lease_until > clock_timestamp()) AS upload_cleanup_leases""",
]
with psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row) as c:
    c.read_only = True
    for q in queries:
        print(c.execute(q).fetchall())
    if len(sys.argv) == 2:
        print(c.execute("""SELECT a.status, r.status AS reservation, r.provider_started,
            x.terminal_event->>'status' AS checkpoint,
            EXISTS (SELECT 1 FROM public.workflow_receipts w WHERE w.attempt_id=a.attempt_id AND w.event_id='terminal') AS delivered
            FROM public.extraction_jobs j JOIN public.extraction_attempts a ON a.attempt_id=j.selected_attempt_id
            LEFT JOIN public.extraction_quota_reservations r ON r.org_id=a.org_id AND r.attempt_id=a.attempt_id
            LEFT JOIN public.cloudflare_executions x ON x.attempt_id=a.attempt_id WHERE j.job_id=%s""", (sys.argv[1],)).fetchall())
    c.rollback()
PYSQL
cd backend
uv run python ../deploy/storage/run_as_owner.py --target production uv run python /tmp/reink-rollout-check.py
uv run python ../deploy/storage/run_as_owner.py --target production uv run python ../deploy/storage/check_trial_schema.py
cd ..
```

Require active outbox, live dispatch leases, queued, processing and queue
backlog all zero. Total pending outbox can contain terminal/expired rows;
reconcile rather than delete them. After pausing, allow the full 15-minute
invocation window since last delivery plus any abandoned backend request.
Confirm zero active Worker/backend requests in monitoring and repeat all checks.
Expire ambiguous attempts; do not replay their provider calls. Stop if unproven.

**4. Merge and verify the backend while everything stays paused.** Merge the
approved backend PR into `main` through the normal review process. Wait for the
`Deploy to FastAPI Cloud` workflow for that exact merge SHA to pass **both**
`Run database migrations` and `Deploy`. Do not launch a competing manual deploy.
Rerun step 3: require revision `0016_cleanup_backoff`, unchanged schema counts,
no definer-function access for `reink_app`, and `search_path=pg_catalog, pg_temp`.
Reconfirm the ingress gate rejects intake and the global trial call cap remains zero.

Probe protocol 2 without claiming or reserving a job (the route validates the
signed capability but does not access the DB). Supply existing secrets only at
the hidden prompts; never print/store the capability:

```sh
cd backend
uv run python - <<'PYPROBE'
import base64, getpass
import httpx
from app.services.dispatch_capability import issue_capability
key = base64.b64decode(getpass.getpass('CLOUDFLARE_CAPABILITY_KEY: '), altchars=b'-_', validate=True)
token = getpass.getpass('CLOUDFLARE_MACHINE_TOKEN: ')
cap = issue_capability(key, 'rollout-probe', 'rollout-probe', 'rollout-probe', ttl_seconds=300)
with httpx.Client(follow_redirects=False, timeout=20) as c:
    r = c.get('https://re-ink.fastapicloud.dev/api/cloudflare/jobs/rollout-probe/attempts/rollout-probe/protocol',
              headers={'Authorization': 'Bearer ' + token, 'X-Dispatch-Capability': cap})
    assert r.status_code == 200, r.status_code
    assert r.json() == {'protocol_version': '2'}
print('Backend protocol 2 verified; no claim sent')
PYPROBE
cd ..
```

**5. Deploy the new Worker with cron still off.** From the approved new Worker
checkout, regenerate the step-2 paused config from its `wrangler.toml`, then:

```sh
npx wrangler deploy --config workflows/cloudflare/wrangler.rollout.toml
npx wrangler queues pause-delivery reink-extraction --config workflows/cloudflare/wrangler.rollout.toml
npx wrangler queues info reink-extraction --config workflows/cloudflare/wrangler.rollout.toml
```

Recheck pause state and absent cron. The final `wrangler.toml` would restart
cron dispatch; do not deploy it yet. The consumer remains configured but paused.

**6. Controlled canary, then general resume.** With cron off/backlog empty,
keep the trial call cap at zero. Configure the ingress maintenance gate to
admit only the operator's synthetic canary request, using a stored customer key.
Keep trial/Cloudflare/quotas true and verify other intake is still blocked.
Canary delivery
requires a controlled queue resume before general intake:

```sh
cd backend
uv run python /tmp/reink-rollout-http.py POST /api/provider-credentials/landingai/acknowledgment
uv run python /tmp/reink-rollout-http.py POST /api/documents/upload /absolute/path/to/synthetic.pdf
# Record job_id from the upload response, and supply the dispatch scheduler token:
uv run python /tmp/reink-rollout-http.py POST /api/maintenance/cloudflare-dispatch
cd ..
npx wrangler queues resume-delivery reink-extraction --config workflows/cloudflare/wrangler.rollout.toml
# Poll using the synthetic user's token (replace JOB_ID with the recorded ID):
cd backend
uv run python /tmp/reink-rollout-http.py GET /api/documents/status/JOB_ID
cd ..
```

Poll to completion; inspect synthetic results/guided review in the authenticated
UI. Rerun the step-3 check with the job ID (command below): require a completed
checkpoint and delivered receipt, succeeded reservation and provider_started.
For this customer-funded canary, global trial starts/successes stay unchanged,
with no pending quota left. When separately verifying free funding after restoring
the trial call cap, one successful extraction increases both trial counters by one. Check
protocol/maintenance errors. On failure pause again and roll back, not retry.

```sh
cd backend
uv run python ../deploy/storage/run_as_owner.py --target production uv run python /tmp/reink-rollout-check.py JOB_ID
cd ..
```

After successful verification, restore the final Worker configuration and cron:

```sh
npx wrangler deploy --config workflows/cloudflare/wrangler.toml
npx wrangler queues resume-delivery reink-extraction --config workflows/cloudflare/wrangler.toml
npx wrangler queues info reink-extraction --config workflows/cloudflare/wrangler.toml
```

Verify the minute cron, intended consumer and live expiry/cleanup. Restore the
approved global trial call cap in FastAPI Cloud, remove the ingress gate, and redeploy the **same**
verified backend release. Observe queue age, starts and errors before ending the
window. Remove the temporary config/helpers; never commit them or credentials.

**Rollback if verification fails.** Set the trial call cap to zero, close the ingress gate, and apply on the
current backend, stop cron with step 2, pause delivery, then wait for the same
invocation/SQL drain. Manually run expiry/cleanup as needed. If failed-canary
messages remain, first let their attempts become terminal, briefly resume the
current matched pair to acknowledge closed/terminal deliveries, then confirm
zero backlog and pause again before switching versions. Preserve ambiguous
attempts and consumed starts; never replay provider work or reset accounting.

Prefer a rollback app/Worker pair that **retains migration 0016 and its revision
file**. Its added counter and same-signature function are compatible with prior
application code. Prepare an approved rollback PR reverting application changes
while keeping migration history; merging it still runs `upgrade head`. Never
merge an old tree missing 0016 while the DB records that revision. Deploy the
matching Worker through the cron-off config, reprobe the pair's expected protocol
(an older matched pair may predate protocol 2), and repeat the canary before
restoring the final config, delivery and intake. Do not mix old Worker/new
backend or new Worker/old backend; mismatch refuses work.

A schema downgrade is optional, **not** the default rollback. If explicitly
chosen, keep intake, cron and delivery paused and all CI backend deployments
held; verify no active cleanup leases/requests as well as extraction drain:

```sh
cd backend
uv run python ../deploy/storage/run_as_owner.py --target production uv run python -m alembic downgrade 0015_trial_hardening
uv run python ../deploy/storage/run_as_owner.py --target production uv run python ../deploy/storage/check_trial_schema.py
cd ..
```

0016 downgrade restores the verbatim 0015 function (same ACL and hardened
search_path), restores five-minute cleanup scheduling and drops only
`upload_intents.cleanup_failures`; its failure-count history is lost. Verify
revision/function/ACL before deploying compatible code. The next ordinary CI
`upgrade head` will reapply 0016 if its file remains, so do not release the CI
hold until the intended schema target is agreed. Neither path changes roles or
grants; stop for approval if production privileges prove insufficient.

## Orphan organization reconciliation (weekly)

Crash-safe provisioning makes duplicates unlikely but not impossible, so run the
read-only orphan report weekly (append a calendar reminder if monitoring has not
replaced it yet). The report lists users with more than one organization,
organizations with zero members, and provisioning intents not `completed` after
one hour. It only reads WorkOS and the database and never creates, updates or
deletes anything.

```sh
cd backend
WORKOS_API_KEY=... DATABASE_URL=postgresql+psycopg://reink_app:...@.../reink \
    uv run python ../deploy/report_orphan_orgs.py
```

Supply the production WorkOS secret and the application database URL at runtime;
do not commit credentials or the report output (it contains user identifiers).

Resolve findings by hand, in this order:

1. **Stale provisioning intents** (`pending`/`org_created`, not updated for an
   hour). `pending` with no org: ask the user to retry sign-in, which resumes
   with the same idempotency key. `org_created` with an organization: have the
   user retry sign-in so the membership is created and the intent completes.
   Only mark an intent `completed` manually (migration-owner SQL on
   `provisioning_intents`) if the user already has their organization and a
   retry cannot help; record what you changed.
2. **Organizations with zero members.** Usually a crash between creating the
   WorkOS organization and creating the membership. First check the database
   for tenant data under that `org_id` (extraction jobs, contracts, parties,
   quota row). If any exists, do not delete the WorkOS organization; restore a
   membership or use organization closure so the purge removes the data. If
   there is none and a later attempt gave the user a different organization,
   delete the empty organization in the WorkOS dashboard. If the user should
   have that organization, create the missing membership there instead.
3. **Users with more than one organization.** Identify the organization in real
   use (has documents, quota usage, recent sign-ins) and confirm with the user
   which one to keep. Remove the extra membership (and, if it is an orphan
   duplicate, the organization) via the WorkOS dashboard or API. Removing the
   wrong membership can lock a user out of their data, so do not guess.

Re-run the report after reconciling; it should come back all clear. Escalate a
finding you cannot explain rather than deleting anything destructive.
