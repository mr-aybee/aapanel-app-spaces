# App Spaces — aaPanel plugin source

Version 0.0.1. App Spaces opens in its own authenticated tab, with a shortcut beside Supervisor in Proxy Project. Namespaces group systemd and Docker workloads; Extra remains last and collapsed. CPU/RAM update independently every five seconds while the tab is visible.

## What is implemented

- Namespace creation/deletion, workload registration/unregistration and reassignment, persisted in SQLite.
- Discovery of existing systemd services and Docker containers; Compose replicas grouped by project/service labels.
- Live native process state, host TCP listeners/published Docker ports, systemd and Docker cgroup CPU/RAM, and available uptime. Unsupported metrics are displayed as unavailable, never fabricated.
- Read-only Nginx proxy route association, multiple routes/domains per workload, and local-address-aware matching.
- Opt-in start/stop/restart controls, per-service operation locks, confirmations, request replay protection and activity history.
- Bounded journal/container log tails and environment inspection with explicit value reveal.
- Registered local systemd unit editor: hidden initial view, explicit reveal/edit, syntax validation, redacted diff, revision conflict detection, five-minute session-bound apply token, original-file backup, atomic write, daemon reload/restart and recovery attempt on failure.
- Installable plugin layout, deterministic ZIP packaging, standalone fixture preview, and backend/browser tests.
- Create-service wizard with .NET, Node, registry-image and local Dockerfile presets. Configure paths, argv, per-line environment, restart/boot behavior, Docker ports/mounts/network, resource limits, health check and process options. Validate first, then Create or Create & Start.
- Exclusive creation of prefixed systemd units or plugin-owned Compose projects; no existing definition is overwritten. Docker definitions can be saved without pulling/building/creating containers and later started from the listing.

## Layout

```
app_spaces/
  app_spaces_main.py     aaPanel API entry, primary-admin authorization and CSRF
  appspaces_core/core.py           inventory adapters, proxy parser, storage and config editing
  index.html            generated small aaPanel launcher
  workspace.html        generated standalone live shell, published to panel static assets
  panel_shortcut.js / panel_integration.py  Proxy Project button installation
  ui.html / ui.css / ui.js / creation_ui.js  editable UI sources
  info.json / icon.png / install.sh
preview/
  index.html            standalone generated preview; safe to open locally
  demo.js               explicit in-memory fixtures, excluded from installed plugin
tests/                  Python fixtures and Playwright browser checks
tools/assemble_ui.py    rebuild index.html and preview after UI changes
tools/build.py          create dist/app_spaces-0.0.1.zip
docs/                   architecture, compatibility, installation and limitations
```

## Local development

Python 3.9+; deployment target is Linux. No third-party Python packages required.

```bash
python tools/assemble_ui.py
python -m unittest discover -s tests -v
python tools/build.py
```

Open `preview/index.html` to inspect the functional UI with fixtures. Actions there affect only memory and reset on reload. It does not contact the server. The original design mockup is preserved in `docs/design/`.

For UI checks install Playwright in a development environment and run `node tests/ui.spec.cjs`. Set `BROWSER_CHANNEL=msedge` or `chrome` to use a system browser; `PLAYWRIGHT_MODULE` can point to an existing Playwright package. Screenshots are written to `test-results/`.

## Current release boundaries

Existing Docker environment/configuration is read-only: this source does not adopt or rewrite externally owned Compose files or migrate deployments. Lifecycle controls work on registered containers/replicas. Newly created Docker definitions are plugin-owned; Start runs Compose up and builds local Dockerfile sources when configured. Editing their Compose source through the UI is still deferred. There is no remote server management, secret store, auto dependency orchestration or proxy editing.

See `docs/CREATION.md` for supported creation options, definition ownership, startup behavior and validation limits. Existing private registry authentication must already be configured on the server for the account running Docker; no registry credentials are stored by this form.

The Nginx parser reads top-level aaPanel vhost files, inline locations and inline named upstreams. It does not expand includes or resolve dynamic upstreams, and it does not claim that a vhost filename is the authoritative aaPanel proxy-project ID. The UI labels associations as inferred and reports incomplete configurations. Exact proxy-project metadata integration is a compatibility task.

Systemd editing supports regular service fragments beneath `/etc/systemd/system`; vendor, transient, generated and symlinked units are not edited. Drop-ins and EnvironmentFile references are not rewritten. Environment inspection uses systemd's configured Environment property, not a guaranteed complete process-effective environment. Config apply verifies process state, not app/database readiness.

Only the primary aaPanel administrator (`uid=1`, normal interactive session) can use this version. No new network listener is created. Plugin data/backup files can contain secrets and require protected server backups.

Read `docs/INSTALL.md` before an explicitly authorized installation.
