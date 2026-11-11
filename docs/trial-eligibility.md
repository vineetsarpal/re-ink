# Trial eligibility

## Deploy prerequisites

**Set `TRIAL_IDENTITY_HASH_KEY` in FastAPI Cloud before deploying this change.**
Generate a high-entropy secret (for example, `openssl rand -hex 32`). Retain and
back it up: changing it would make retained user claims unrecognizable. It is
independent of WorkOS API credentials and provider credential encryption keys.
Provisioning new organizations requires it; migration 0017 does not.

Migration `0017_trial_eligibility` is schema-only and needs no WorkOS or identity
hash secrets. Existing quota rows become eligible without changing counters;
subsequent rows default to ineligible. Only provisioning grants new eligibility.

## One-off backfill

Run the idempotent backfill after migration 0017 and before expanding trial
access. Use the same `TRIAL_IDENTITY_HASH_KEY` configured in FastAPI Cloud, plus
`WORKOS_API_KEY`, `WORKOS_CLIENT_ID`, and the migration-owner `DATABASE_URL`.
The owner connection must be able to read every organization's quota and provider
acknowledgment rows (the application role is restricted by tenant RLS).
Load these secrets into the process environment using your secret manager, then
run from the repository root:

```bash
cd backend
uv run python ../deploy/backfill_trial_eligibility.py
```

The script resolves the email of the LandingAI acknowledgment's user through
WorkOS for every organization with free successes or pending free reservations.
It inserts HMAC user claims and normalized non-webmail domain claims, preserving
existing records on conflict. It commits all records together; a missing
acknowledgment or failed lookup rolls back the run. Resolve the missing identity
and rerun. Repeated successful runs do not create duplicate claims or change
quota counters. The script reads runtime settings; CI migration runs need only
their normal database configuration.

Trial-user hashes and normalized work-domain claims have no tenant foreign keys
and must survive future tenant deletion. Webmail exceptions are reviewed in
`backend/app/services/webmail_domains.txt`. Joining a verified-domain organization
does not claim a new trial. The organization allowlist is removed; leftover `TRIAL_ALLOWED_ORGANIZATION_IDS`
in production is ignored (`extra='ignore'`). Access follows the Cloudflare trial
switch, permissions and acknowledgment. Customer funding uses a 500-success /
2,000-attempt monthly default; approved uncapped organizations bypass those two
caps only with a stored customer key. Trial eligibility and per-minute limits
are unaffected. Set `EXTRACTION_GLOBAL_TRIAL_CALL_MONTHLY_LIMIT=0` to stop free
funding while customer funding continues. See [production setup](trial-production-setup.md)
for the settings and deployment gate: **#60 and follow-up checks 1–3 must be
complete before production deployment**.


Before production release, manually verify the organization settings page shows
key management to an admin with `member:manage` in an organization that was never
listed, and that usage shows “unlimited” only when that organization has a stored
key and is configured as uncapped. The local verification covers API behavior and
the frontend build; signed-in browser checks remain part of the deployment gate.
