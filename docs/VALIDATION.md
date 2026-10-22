# Validation record — 22 October 2026

## Executed locally

- 43 Python unittest fixtures passed on Windows/Python 3.12: existing inventory/config/auth tests plus creation rendering, command/environment literal handling, path and identity validation, hidden preview secrets, session-bound one-use creation, explicit boot/start, exclusive collision protection, retained definitions on startup failure, Docker options, defined-only Docker workloads, local Dockerfile build flags, invalid ports/volumes, listening-port conflicts, healthcheck constraints and missing namespaces.
- Playwright/system Edge checks passed: previous inventory and configuration flows plus systemd Create, Dockerfile Create & Start, hidden creation-preview environment values, advanced fields, and the 390px creation dialog overflow check.
- Desktop, configuration-dialog and mobile screenshots captured and visually reviewed. Windows UTF-8 assembly issue was found and corrected before packaging.
- aaPanel archive generated with deterministic timestamps and file modes. Preview/demo, mutable plugin data and Python caches are excluded from the plugin ZIP.

## Important limits of this evidence

Backend adapters in tests use command fixtures. Ownership and advisory locks are mocked for cross-platform apply tests. No real systemctl action, real Docker lifecycle/config operation, Linux lock contention test, live aaPanel plugin installation or real production configuration edit was executed. Browser tests use the explicitly labeled fixture preview, not an authenticated live panel. Logs can contain sensitive content not recognized by generic redaction.

The source is prepared for a disposable Linux/aaPanel integration pilot; local test success is not a claim of production certification.
