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

Expired uploads retain permanent tombstones and are revisited for late storage
writes every 24 hours. Failed deletions retry after five minutes. This relies
on the cleanup scheduler continuing to run and creates ongoing database and
storage-operation costs; monitor backlog and capacity. A finite cleanup time
is not guaranteed if storage writes can remain pending indefinitely.
