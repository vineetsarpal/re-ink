# Authentication and Access

re-ink protects contract and party data by requiring authenticated, organization-scoped access.

## How access works

- Users sign in through WorkOS AuthKit.
- API requests include an access token.
- Data access is scoped to the user's active organization.
- Users without an organization are provisioned into one before using protected app areas.

## Administrator responsibilities

Administrators should confirm:

- The WorkOS client ID is configured for the frontend and backend.
- Redirect URIs match the deployed application URL.
- Server-side WorkOS API configuration is available for account widgets and organization provisioning.
- Users are invited or otherwise allowed to sign in under the intended authentication policy.

## Access troubleshooting

If a user can sign in but cannot access app data, confirm the user has an organization-scoped session and is using the expected account.

