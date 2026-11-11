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
