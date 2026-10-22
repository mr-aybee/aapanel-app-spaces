# Installation and operations

Version 0.0.1 uses the existing aaPanel session and primary-admin API. Installation prepares private plugin storage, publishes a static UI shell, and adds one marked script tag to the modern panel template. Existing workloads and proxy configuration remain unchanged.

## Build and pilot

1. Run the backend and browser checks, then `python tools/assemble_ui.py` and `python tools/build.py`.
2. Back up the panel and selected service configuration. Use aaPanel's local plugin import if the installed version accepts the package layout; otherwise extract the `app_spaces/` folder into `/www/server/panel/plugin/` as a primary administrator after reviewing it. Do not run an unreviewed archive as root.
3. Invoke `bash /www/server/panel/plugin/app_spaces/install.sh install`. This prepares plugin storage, the static workspace and the navigation shortcut. It does not create services or touch existing workloads.
4. Verify that aaPanel lists the plugin. Open it in a normal primary-administrator session. It uses aaPanel's `/plugin?action=a&name=app_spaces&s=api` POST endpoint and native fetch with the existing panel CSRF header. The small launcher transfers that token to the same-origin child tab; it never appears in the URL. If it is not listed, check version-specific plugin registration/import requirements; do not modify unrelated panel files to bypass validation.
5. Create a namespace and discover/register a disposable workload. Lifecycle/config capabilities are opt-in and default off.
6. Check inventory, logs, proxy associations and restart controls on the disposable workload. Validate unit edits and recovery there before registering a production app.

No production migrations or restarts are part of source creation. Existing GitHub runners, CI/CD and systemd service files remain unchanged.

## Runtime requirements

- Linux with Python >=3.9 in aaPanel's runtime; only standard-library Python modules are used.
- systemctl, systemd-analyze, journalctl and ss for systemd features; ip for detecting local interface addresses.
- Docker CLI/daemon for Docker features, with the Compose v2 plugin for creation and plugin-owned lifecycle operations. Docker failure does not prevent use of systemd features.
- Nginx vhosts at `/www/server/panel/vhost/nginx` for the current proxy adapter.
- Existing panel authentication, primary admin session (`uid=1`), and valid `x-http-token`. Temporary login links and API-only credentials are rejected.

## Editing configuration

Register a regular local systemd unit with both lifecycle and config permission. Open Configuration, explicitly reveal it, edit the readable unit, then Validate & preview. A valid preview expires after five minutes and is tied to your session and the current file revision. Apply backs up the original under the plugin data directory, writes atomically, reloads systemd and restarts the unit. If startup fails, it restores the file and attempts recovery. Inspect application logs afterward; process success is not an application readiness test.

No long Supervisor environment lines, launch wrappers or JSON environment files are introduced. Original comments and unit sections are preserved unless the administrator edits them. Existing drop-ins can override the edited source and are listed for awareness. Referenced EnvironmentFiles are outside this release's editor.

## Backups and rollback

Back up `/www/server/panel/plugin/app_spaces/data/` securely. It includes registrations, audit, short-lived preview content and unit backups, potentially with credentials. Do not commit it to Git. Export registrations from the UI for a secret-free metadata snapshot. The export format is documented JSON; automated import is not implemented.

To recover a manually identified unit backup, inspect and restore that one file, run `systemctl daemon-reload` and restart only that unit. An app restart or restored unit cannot undo database migrations or application side effects.

## Updating and uninstalling

Keep the `data/` directory when updating source. Rebuild generated UI before packaging. `install.sh uninstall` removes only the marked template hook and the two owned static files, leaving data and workloads in place. Remove the plugin through the installed panel's plugin-management flow after preserving data; unit files, containers, volumes, databases, proxy projects and CI/CD are not owned by this plugin and must remain intact.

## Separate tab and Proxy Project shortcut

The installer copies workspace.html to /www/server/panel/BTPanel/static/app_spaces/index.html and panel_shortcut.js beside it. Only the shell is public; every data operation still requires the primary panel session plus CSRF. A marked script tag in BTPanel/templates/default/index_new.html mounts App Spaces beside the native Supervisor toolbar button. Native compiled bundles are unchanged. Refresh aaPanel after updates. A panel update may replace this template; rerun install.sh update to restore the hook. The original template is retained privately in plugin data for reference; uninstall removes the marked tag without reverting unrelated panel changes.

## Live resource usage

Metrics use one batched systemctl query, one Docker ID list and one batched inspect for this server. They read cgroup-v2 CPU/memory counters directly; systemd falls back to its accounting properties when available. Docker metrics require cgroup v2. CPU is a delta over samples: 100% means one fully used core and the first sample shows Sampling. Unavailable counters are never fabricated. Stopped, existing workloads report zero. Registrations whose instances no longer exist remain unavailable. RAM is total cgroup memory, including cache.

The metrics API bypasses proxy/discovery inventory. A private four-second shared cache and nonblocking lock prevent duplicate collectors across tabs. The UI uses one in-flight request, pauses hidden tabs, retries errors after ten seconds, suppresses stale values, and gives slow successful requests at least one second of breathing room. Normal cadence is five seconds; inventory remains thirty seconds. No daemon is installed.

## Workspace route

The workspace URL is /app-spaces and has no release query parameter. The installer adds one marked startup loader to BTPanel/__init__.py; the plugin itself registers only the exact workspace and legacy shell URLs. The view returns the public shell with explicit UTF-8, no-store caching and nosniff; data access remains in the existing primary-admin/CSRF API. Refreshing the workspace does not invoke the dashboard router. The previous startup source is backed up privately before the first change. Uninstall removes only the marked loader; reload aaPanel to activate startup changes. Legacy /static/app_spaces/index.html links still work and switch to the canonical URL.
