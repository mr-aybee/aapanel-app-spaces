# Architecture and compatibility record

## Boundaries

The plugin includes `appspaces_core/creation.py` and `creation_ui.js`. Creation specifications are validated, rendered as native unit/Compose source, held in private session-bound tickets, and committed with exclusive file creation. Schema version 2 adds creation tickets and managed-workload ownership records. Existing schema-1 tables are retained through additive initialization. Managed Docker Start routes through the owned Compose source; definition-only workloads are shown as Defined while their daemon is available. No existing workload is adopted implicitly. See `CREATION.md` for options and failure behavior.

The installed UI is a scoped HTML fragment with inline CSS/JS to match aaPanel plugin loading. `ui.*` are editable source; `index.html` is assembled. A separate preview contains explicit fixtures; it is never packaged as a live backend. Namespaces change plugin metadata only.

`app_spaces_main.api` authenticates every request, checks method/CSRF, gates the primary interactive administrator, parses JSON and dispatches to application services. It does not expose a generic command execution route. Mutations require fresh random request IDs, stored for 24 hours to reject accidental replays. Lifecycle and apply operations are protected by per-registration flock files across panel workers. Audit stores actor/session hash, operation, target and outcome without config payloads or raw secrets.

SQLite stores namespaces, registrations, audit, request IDs and expiring config-preview tickets. An apply ticket includes proposed configuration, is session-bound and consumed before mutation. Data is server-private. Tickets are cleaned on future preview requests; expired records can remain in a quiet installation and must be treated as sensitive data in backups.

Systemd discovery obtains unit properties from systemctl. Registered inventory resolves cgroup PIDs and their TCP listeners where accessible. Docker discovery uses inspect and stable Compose labels, grouping replicas. Standalone Docker workload identity is its name; deleted/replaced names may resolve a new container, which is appropriate only when the admin intentionally retains that logical name. UI lifecycle actions apply to all current instances of a logical workload and return per-instance results.

The proxy adapter tokenizes a conservative subset of Nginx syntax. It reads vhost server_name/location/proxy_pass and inline upstreams, normalizes addresses and matches only local target ports. It reports inferred/ambiguous results rather than claiming exact project ownership. Include expansion, Unix sockets, DNS/variable targets and authoritative aaPanel reverse-proxy metadata remain unsupported.

## What was inspected on the existing server

- aaPanel plugins live in `/www/server/panel/plugin/` with `<name>_main.py`, matching class, `index.html`, `info.json` and install script conventions.
- The installed Supervisor frontend uses POST `/plugin?action=a&name=<plugin>&s=<method>` through panel jQuery.
- Installed `BTPanel.check_csrf()` checks `x-http-token` against the panel session token.
- Installed user login sets `session['login']`, `session['username']` and `session['uid']`; temporary login links also set `tmp_login_id`.
- Existing Nginx files use inline proxy_pass routes for Orbyn's frontend/API split.
- Exact panel version has not been established: the expected legacy `data/version.pl` path was absent. No claim of full installed-version compatibility is made.

No live plugin installation, lifecycle action, unit edit, Docker modification or proxy edit was performed during source implementation.

## Remaining compatibility/pilot work

Test the actual panel plugin upload/registration flow, modal size and scoped CSS, primary-admin identity on the target installation, auth expiry, CSRF refresh, Linux file ownership/permissions/flock, real systemd validation error behavior, Docker daemon availability and Nginx project metadata. Windows tests fake subprocess/runtime adapters and mock ownership/locking for config fixtures; they are not live Linux integration tests.

Before extending capabilities, add managed Compose adoption with explicit source ownership, structured environment editing/managed drop-ins, authoritative proxy metadata, dependency/readiness declarations, export import and finer role policy. These are deliberately not simulated as working production features in the UI.

## References

- https://www.aapanel.com/pkg/aaPanel_Linux_Panel_Plug-in_development_documentation_v1.1.pdf
- https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
- https://docs.docker.com/reference/cli/docker/container/inspect/
- https://docs.docker.com/reference/compose-file/services/

The implementation uses the existing aaPanel conventions observed on this server; runtime behavior still requires a disposable deployment pilot.
