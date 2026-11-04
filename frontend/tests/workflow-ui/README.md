# Explicit workflow UI fixtures

This isolated Vite entry renders the actual upload, status, review and PDF preview components with deliberately simulated identity and API responses. It never calls WorkOS, providers, R2 or the database, and is not part of the production build. The yellow banner labels its limits. Backend acceptance tests separately exercise committed database operations and permissions.

From `frontend/`, start the loopback-only harness:

```sh
npm exec vite -- --config tests/workflow-ui/vite.config.mjs
```

Open `http://127.0.0.1:4174/` with Playwright CLI. Run `checks.cjs` through `playwright-cli run-code --filename <absolute-path-to-checks.cjs>`. Use a temporary working directory for CLI snapshots/downloads. The final browser flag `window.fixtureUiChecksPassed === true` confirms all asynchronous checks completed; the CLI may initially return while the simulated approval alert is being accepted.

The checks cover synthetic PDF rendering/highlight, visible absence of evidence, no implicit currency/party role, corrections and simulated approval, DOCX original download without preview, terminal polling stopping, explicit Retry, and a viewer's hidden upload control. `/original.pdf` and `/original.docx` serve the canonical checked-in corpus directly, without separate copies. The highlighted PDF rectangle is a deterministic authored fixture, not measured ADE grounding.

Query parameters select `?case=pdf`, `?case=missing`, `?case=docx`, `?case=timeout` or `?viewer=1` for manual inspection. Provider quality, real sign-in and deployment interoperability remain separate live gates. Never point this fixture entry at a production service.
