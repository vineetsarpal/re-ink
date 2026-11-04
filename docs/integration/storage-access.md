# Private originals and operator access

The backend validates original PDF/DOCX bytes (50 MiB maximum), persists size/SHA-256, and uses authenticated HTTPS S3 operations against a private R2 Standard bucket. Keys contain a hash of the authenticated organization and a fresh server UUID. The immutable original is retained until explicit deletion/reset. Public bucket routes and signed public document URLs are unnecessary. n8n receives only scoped application document access; never R2 or database credentials.

Configure `STORAGE_BACKEND=r2`, `R2_ENDPOINT_URL` (account HTTPS endpoint without a path), `R2_BUCKET`, `R2_REGION=auto`, `WORKFLOW_CUSTOMER_ORG_ID`. Inject `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` into backend/cleanup runtime through protected server configuration. Use a bucket-restricted R2 Object Read & Write token; do not grant account administrator access. No resource names or credentials are supplied by the repository. R2 Standard allowances are subject to billing overages; verify current account usage/pricing before deployment.

From `backend/`, run `uv run python ../deploy/storage/check_r2.py` in the actual backend/cleanup runtime. It writes a disposable synthetic object, compares its bytes and deletes it. A successful local fake-storage test is not deployment evidence. Record actual R2 public-access-disabled configuration and operation results without secrets. Rotate the bucket token through protected runtime injection, restart consumers, verify this check, then revoke the old token.

## Failed uploads and deletion

Storage failures return safe 503 errors. Uploaded originals become runnable only after job/attempt/outbox commit. If database commit fails, the upload endpoint attempts immediate deletion. If that also fails, R2 itself is the durable orphan inventory. Schedule the operator reconciliation command daily using a runtime with scoped database reads and bucket access:

```
cd backend
uv run python ../deploy/storage/reconcile_orphans.py
```

The default is dry run. Only the configured customer's namespace is listed; objects younger than 24 hours and objects referenced by jobs or cleanup records are excluded. Database unavailability stops reconciliation and never counts as evidence of an orphan. Review candidates, pause uploads and drain in-flight upload requests before `--delete` to exclude commit races. A grace interval longer than any operational upload interruption is required. Run again after recovery; do not delete the entire bucket. Durable lifecycle cleanup retries storage errors after logical deletion; physical removal must be confirmed separately. Explicit legacy reset requires a reviewed organization-scoped operation; these tools deliberately do not traverse/delete local legacy files.

## Dedicated Neon worker identity

Use a separately created LOGIN role without superuser, BYPASSRLS, CREATEROLE, CREATEDB, relation ownership or role memberships. Protect its login secret outside shell history. With owner/migration credentials, run `uv run python ../deploy/storage/provision_worker.py <dedicated-role>` after migration. The script grants only lifecycle table SELECT/UPDATE/DELETE and installs role-specific restrictive policies with the literal configured organization. Ordinary transaction-scoped `app.current_org` policies still apply. A malicious worker changing that GUC cannot gain another tenant. Do not use the application or owner role as worker. Verify no inherited PUBLIC grants or SECURITY DEFINER functions expose extra writes; revoke such deployment-specific grants before acceptance.

The VPS worker uses `WORKFLOW_WORKER_DATABASE_URL` with `sslmode=verify-full` and suitable runtime CA trust. Keep migration `DATABASE_URL` out of the VPS. Bound its pool, use short transactions and rebind the trusted organization on every transaction. Worker HTTP/storage calls run outside database transactions. The dispatcher needs no R2 secret unless the same process runs cleanup.

Run `uv run python ../deploy/storage/check_worker_access.py --other-org <deliberately-different-org>` inside the actual VPS container. It requires verify-full TLS, rejects privileged roles or approval-table writes, verifies restrictive tenant policies/forced RLS, rolls back a lease-style update, then substitutes the other tenant GUC and requires zero visible/mutable rows. `--local-test` only skips the TLS requirement for disposable local PostgreSQL; it cannot satisfy actual deployment acceptance. Actual VPS acceptance requires DNS/TCP/TLS/login from its container, certificate/hostname verification, and a rolled-back lease transaction. Record the login role and flags, confirm expected organization job visibility, then deliberately `SET LOCAL app.current_org` to a different tenant and prove SELECT returns no foreign rows and UPDATE/INSERT cannot touch them. Attempt rolled-back writes to contracts/parties and require permission denial. Confirm the role cannot alter policies, assume another role or bypass RLS. Never disable TLS or substitute owner credentials to pass. Runtime access remains unperformed until the operator supplies and verifies the real endpoint/role.

The optional Compose `cleanup` profile runs a separate cleanup worker with `cleanup.env` copied securely from `cleanup.env.example`. Enable it with `docker compose --profile cleanup up -d cleanup`; inject only the restricted database scope and R2 credential.

## Runtime, retention and handoff gates

The operator supplies VPS administrative access, chosen subdomain/DNS, outbound Neon/R2/provider connectivity, protected service secrets, and n8n provider billing access. n8n editor requires administrator login over valid HTTPS; persist state and encryption key through container restart. Keep database/container-management ports private. Distinct dispatch and callback/document tokens must be independently rotatable. The existing WorkOS frontend origin remains unchanged.

Originals/results remain until explicit deletion/reset; n8n execution payloads expire after seven days and metadata-only logs after thirty days. Reset covers selected extraction data and retained workflow payloads, without deleting unrelated contracts/parties or tenants. Record actual Neon restore/backup expiry and any manual backup owner/expiry; R2 durability is not an independent backup, and R2 S3 versioning must not be assumed. No live access, restore window or provider outcome is established by source or deterministic tests.
