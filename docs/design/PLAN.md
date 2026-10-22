# App Spaces — aaPanel plugin plan

Status: design proposal, not an implementation authorization. Created 21 October 2026.

## Workspace and scope

The canonical project folder is `D:\Repos\aaPanel`. Future plugin work starts there. This deliverable contains a standalone HTML prototype (`index.html`), this plan, and a README. No server installations, service changes, Docker operations, proxy changes, or GitHub changes are part of this design phase.

Working name: **App Spaces**. The supplied Rancher screenshot informs dense table layout, namespace section bands, compact status indicators, linked workload names, and row actions. The design is an aaPanel plugin concept, not a Kubernetes integration or exact Rancher clone. Its aaPanel shell is illustrative; production must use installed aaPanel UI conventions.

## Outcome

Provide one aaPanel screen for app namespaces containing multiple systemd services and Docker workloads. Show status, source identity, listening/published ports, linked aaPanel reverse proxy projects and domains, resource metrics when available, and logs. Preserve the operating system and Docker as the process managers. Preserve aaPanel as the proxy/SSL manager. Keep existing GitHub runners and release automation operational.

## Organizing model

- Server → namespace (app/environment grouping) → registered services.
- Examples: `orbyn-production`, `shared-infrastructure`, `genie-staging`.
- Each workload has one primary namespace; shared infrastructure can have optional consumer references later. Moving between namespaces changes plugin metadata only.
- Namespaces are organizational records, not Kubernetes namespaces, Docker networks, filesystem paths, security boundaries, or systemd slices.
- The first version targets the local aaPanel server only. Remote and multi-server management is deferred.
- Register existing workloads first. New service creation is a later, separately reviewed feature.

## Interface

### Namespace listing

Dense, collapsible namespace sections. Search by workload, unit, image, namespace or domain. Filter namespace, runtime, and status. Columns: select, normalized state, service/source, runtime, host listener or Docker port mapping, proxy project/domain, CPU/memory, uptime, actions.

Display truthful states: Running, Starting, Stopped, Failed, Restarting, Unknown, and Unavailable. A running process is not automatically healthy. Show health separately when a health check is configured. Docker health may be absent. Never display invented resource readings; use unavailable when accounting/permissions do not support them.

Row details contain Overview, Environment, Configuration, Logs, and Proxy tabs. Surface native IDs and commands. Support context-appropriate Start/Stop/Restart actions, and bulk operations with confirmation and per-service outcomes. Namespace action order and dependencies are not implied by table order.

### Environment and readable configuration

The user's main preference is readable configuration within the plugin, not a long Supervisor environment line or an externally edited JSON wrapper.

- systemd: show raw source and supported drop-ins/EnvironmentFile references; optionally expose variable rows backed by a narrowly scoped managed drop-in. Do not flatten an existing unit or destroy comments. Distinguish configured, inherited and effective values, including reset semantics. Never claim arbitrary systemd syntax is editable through a simple parser.
- Docker: show inspect-derived effective configuration as read-only. For explicitly adopted Compose workloads, edit the authoritative Compose/environment source, validate, show a diff, then recreate the affected service. `docker restart` does not apply new environment variables.
- Externally managed containers: inspection, logs and allowed lifecycle actions first. Configuration adoption requires an explicit procedure; do not silently replace a deployment owned by another tool.
- Mask secrets by default; preserve unchanged values without sending them back in cleartext. Do not infer every secret solely from its variable name; allow explicit secret markings.
- Apply: validate → show diff with secrets redacted → confirm → backup → write atomically → daemon-reload for systemd where needed → restart/recreate → verify → report. Restoration of config does not reverse database migrations or other app side effects.

## Runtime adapters

### systemd

Discover via structured systemctl/D-Bus properties: unit ID, load/active/substate, enabled status, fragment path, drop-ins, main PID, restart count, start timestamp, and accounting metrics. Read journal entries scoped to unit. Resolve process listening sockets without treating inherited or shared sockets as unique proof of ownership. Missing fragment or transient/generated units must be clearly labeled; do not edit unsupported sources. Register only selected services and require explicit permission for lifecycle actions.

### Docker

Discover daemon availability, containers, state/health, image and digest, stable Compose project/service labels, published address/port/protocol, mounts, restart policy and stats. Use Compose project/service identity when available because container IDs change on redeployment. Handle multiple replicas as one logical workload with expandable instances; standalone containers use recorded identity with reconciliation on replacement. Keep container internal ports separate from host-published ports. Logs must identify the selected instance.

Do not assume a container image can be rebuilt locally or that every container belongs to a Compose project. Detect unavailable Docker without breaking systemd screens. Scope container API access through the plugin backend; never expose the Docker socket to the browser.

## Proxy project associations

Read aaPanel's reverse proxy project records and relevant effective Nginx server/location/upstream configuration. Verify the installed version's metadata/API and file layouts before implementation. Domain config filenames alone are not sufficient to reconstruct every proxy project.

Normalize target scheme, hostname/IP, port, protocol and path. Match systemd listeners and Docker host port mappings with local-address awareness, IPv4/IPv6, named upstreams, default HTTP/HTTPS ports, and DNS resolution confidence. Do not match a remote host to a local workload solely because its port number is equal.

Associations are many-to-many: one domain can route `/` to a frontend and `/api/`, `/hubs/`, `/files/` to the API; a service can have multiple domains and proxy projects. Show all matches in details, summarize compactly in the table, and mark exact, inferred, ambiguous, stale, unsupported or manually confirmed mappings. A reachable port does not prove a particular route works.

No mapping is normal for private databases, Redis, workers and internal-only containers. Never label these as broken solely because they have no proxy. Initial proxy features are read-only with a link/deep-link to aaPanel when supported. Routing and certificate editing remain outside the initial plugin scope.

## Backend and persistence

Inventory adapters return a common service DTO with native identity, namespace, runtime, capabilities, normalized/native state, timestamps, endpoints, metrics and errors. Separate inventory, mutation, proxy discovery, configuration, logs and audit modules. Initial polling uses bounded requests; refresh intervals and journal/container log tails have explicit limits. Avoid whole-host process/log dumps on each page load.

Persist namespace records, registrations, ownership/capability flags, explicit proxy overrides, and an audit history in a plugin-owned local SQLite database or aaPanel-supported equivalent after verifying platform conventions. Do not duplicate runtime configuration or store live secrets in namespace metadata. Schema versioning and backup/export are required. Discovery caching is not authoritative runtime state.

Expose conceptual operations: list namespaces/workloads, register/unregister, assign namespace, get details/ports/proxies, get bounded logs, lifecycle action, read/validate/apply supported configuration, audit history. Unregister means remove plugin registration, not delete a unit or container. Namespace deletion never deletes workloads.

## Permissions and mutation safety

Use aaPanel authentication, authorization and request validation conventions verified on the installed version. Viewing logs, revealing secrets, editing config, lifecycle actions and bulk actions are separate capabilities. Restrict edits to registered workload sources and explicitly managed drop-ins; resolve paths and reject symlink/path traversal escapes. Use argv-based subprocess calls or structured APIs, never shell-concatenated user input. Protect mutation endpoints against CSRF and duplicate/replayed operations.

Use per-workload operation locks, bounded command execution, config revision hashes to reject concurrent overwrite, atomic writes, restrictive file permissions and secret-redacted audit events. Do not write whole configuration bodies or environment values into ordinary request logs. Account for aaPanel root-level backend execution: frontend visibility alone is not authorization.

Uninstalling the plugin removes its UI/metadata only by default. It must not stop services, delete apps, remove Docker volumes, or rewrite aaPanel proxies.

## CI/CD compatibility

Existing Orbyn GitHub Actions and systemd lifecycle commands remain valid. Plugin refresh reconciles changes made outside the UI. Never introduce Supervisor or new launch wrappers. Preserve the systemd unit files, runtime user, environment, ports, paths and restart semantics unless a separately reviewed change requests otherwise.

For future Docker deployments, choose the authoritative Compose files and container registry workflow before enabling UI writes. Avoid UI edits to build-generated files that the next pipeline overwrites. Record configuration ownership and show externally changed revisions.

## Delivery phases and acceptance

1. **Design review (now):** review the HTML prototype, navigation, namespace model, runtime distinctions, proxy detail and readable configuration experience. Demo data and actions are labeled; no external API calls.
2. **Platform discovery:** inspect aaPanel version and plugin development conventions, authentication and permissions, native UI assets, proxy API/schema, systemd and Docker versions, and repository instructions. Produce a compatibility matrix. Read-only; do not modify live workloads.
3. **Read-only plugin:** installable plugin shell; namespace registration/grouping; systemd and Docker inventory; status, ports, bounded logs, proxy mapping and unavailable-state handling. Namespace persistence survives plugin restart; no workload changes.
4. **Lifecycle controls:** scoped start/stop/restart; audit, permissions, locks, confirmation and per-item batch results. Validate on disposable test services/containers first. Never start two managers for the same workload.
5. **Configuration workflow:** systemd managed drop-ins/raw editor with source restrictions; explicitly managed Compose changes; validation/diff/backup/apply and truthful restart/recreate outcomes. Secret-preservation and conflict tests are required.
6. **Packaging and pilot:** documented installation/update/uninstall, schema migration and backup/restore; keyboard/responsive UI verification; one selected app pilot after explicit implementation authorization. Preserve the server's existing deployment route.

## Verification plan

Use fixtures for many-to-many proxy routes, local vs remote hosts sharing ports, wildcard/IPv6 listeners, named upstreams and ambiguous matches. Test namespace moves without runtime mutation, missing service definitions, Docker absence, replaced containers/replicas, partial failures and external config changes. Validate secret masking/preservation, command injection/path traversal rejection, concurrency, permissions, and backend request guards. Exercise real lifecycle/config operations only against disposable workloads. Check responsive layouts, keyboard navigation, empty states, loading/error states, dialog focus and sample interactions.

## Prototype boundaries

`index.html` is a dependency-free visual prototype with simulated namespace creation, search/filtering, collapsing, selection, detail tabs, namespace reassignment and lifecycle controls. Data resets on reload. Save/apply does not save input. Discovery lists illustrative candidates; real registration is not implemented. Metrics, images, uptime and staging names are sample data, not a live inventory. The 3 Orbyn services/domains are grounded in prior inspection but their displayed state/metrics are illustrative. The other rows are examples, not deployment recommendations. Unsupported lifecycle/config permissions are design work for the next phase.

## Decisions still needed before implementation

- Final plugin name, allowed administrators and whether service creation belongs in v1.
- Whether a namespace always means app + environment or needs separate app/environment fields.
- Raw editor only initially versus structured environment editing as well.
- Which Compose projects can be explicitly adopted and who owns their configuration.
- Whether the main screen needs multi-instance expansion in v1.
- How app group restart ordering and readiness should be declared, if requested.

## References to verify during implementation

- aaPanel plugin development: https://www.aapanel.com/pkg/aaPanel_Linux_Panel_Plug-in_development_documentation_v1.1.pdf
- systemd unit configuration: https://www.freedesktop.org/software/systemd/man/latest/systemd.service.html
- systemd environment configuration: https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html
- Docker Compose service model: https://docs.docker.com/reference/compose-file/services/

These are research starting points, not a claim that compatibility has already been tested against the installed aaPanel version.
