# Creating services — v0.0.1

Use **Create service**, select a namespace, choose systemd or Docker, and fill in the definition. **Validate & preview** performs checks without starting a workload. **Create** saves/registers the definition; **Create & Start** also issues its start command. These features are source implementation, not a claim that live creation has already been piloted.

## Supported systemd options

- Existing Linux user, absolute executable, existing working directory, explicit argument array.
- Environment as readable KEY=value lines. Optional matching single/double quotes are interpreted by the browser; no shell or variable interpolation is performed. Newline/NUL values are rejected in this initial form.
- Restart policy, restart delay, explicit boot enablement, CPU cores converted to CPUQuota and optional memory limit.
- Generates a normal readable `/etc/systemd/system/appspaces-NAMESPACE-NAME.service`. Environment values are separate `Environment=` lines; no wrappers or Supervisor are introduced.
- Literal argument handling disables systemd dollar expansion and escapes percent specifiers. No shell is implied. Select an executable and arguments, rather than pasting a shell command into one field.
- Before creation: namespace exists, generated unit name is unused across systemd and the local filesystem, user/paths exist, user can traverse the workdir/execute the binary, and systemd-analyze validates the generated source.
- File creation is exclusive with mode 0600. systemd can read it as the service manager; the app runs as the selected user. No vendor/system unit is overwritten.

Boot enablement is separate from immediate start. Checking Enable at boot and choosing Create means the service can start on the next boot even though it is not started now. Working directory existence and executable checks do not prove that DLLs/scripts/config files are complete or that application startup will succeed.

## Supported Docker options

- Use an existing registry/local image, or build a local Dockerfile with an absolute context and relative Dockerfile path. An image tag is required in both modes.
- Optional command and entrypoint arrays, in-container working directory, container user/UID:GID.
- Published host/container ports with IPv4/IPv6 bind addresses and TCP/UDP. Form defaults to loopback for use with aaPanel proxies. A listener check catches already-bound requested host ports but cannot eliminate races or guarantee Docker will accept a bind.
- Bind mounts with existing server sources, project-scoped named volumes, read-only/read-write flags. Missing bind paths are not silently created. Volumes are not deleted as failure cleanup.
- Default project bridge or an explicitly named existing external network. No host-networking switch is exposed.
- Restart policy, CPU/memory/PID limits, init process, no-new-privileges, optional read-only root filesystem with writable /tmp.
- Optional exec-form healthcheck starting with CMD, with 30-second interval, 5-second timeout, three retries and a 15-second start period. The image must contain the healthcheck executable.
- Rotating json-file logs: 10 MB, three files. No arbitrary Compose passthrough, privileged switch, registry-password store, remote builds, multi-service Compose import or Swarm/Kubernetes orchestration is implemented.

Generated `compose.yaml` files live under the plugin's private `data/projects/PROJECT/` folder. Projects use an appspaces- prefix and namespace/service-derived identity, with a stable hash when names need shortening. New workloads are automatically registered with lifecycle control. No existing Compose project or directory is adopted/overwritten.

Docker Create saves only the definition and returns Defined. It does not pull images, build, create containers or allocate named volumes. Start later runs `docker compose up -d`; local-build definitions add `--build`. Create & Start performs the same startup immediately. Stop/Restart use Compose for plugin-owned Docker workloads; externally registered workloads retain their original lifecycle adapter. Up may recreate a container if the owned source was changed manually; do not hand this source to another deployment tool without resolving ownership.

Environment dollars are escaped for Compose so entered values are literal. Form creation does not add an external `.env` file. Raw Compose editing from the UI remains a later feature; existing Docker environment views show effective container values after startup.

## Creation workflow and failure behavior

The primary-aaPanel-administrator and CSRF checks cover creation. Preview stores a private, five-minute, session-bound specification and returns a generated source preview with all environment values hidden. A fresh request ID and explicit confirmation are required to create. Creation takes an identity lock and revalidates namespace, identity, filesystem paths, syntax and relevant host listeners before consuming the ticket. No image is pulled during preview.

If definition creation succeeds but enabling/startup fails, the UI reports Created, needs attention. The registered definition stays available for logs and retries. It is not falsely reported as a successful running app. Docker volumes/images or application/database side effects are not deleted as rollback. A successful start command still requires checking inventory/health/application readiness.

Unregister removes metadata, not the definition, container or volumes. Managed project paths remain reserved until an administrator deliberately reviews and removes or adopts their source. Moving namespaces changes grouping only and does not rename unit/project identities.

## Options explored but deferred

Editing/adopting arbitrary Compose stacks, app dependency graphs, replicated creation/scaling, build arguments and build-secret management, registry credential UI, GPU/device mappings, extra capabilities, scheduled jobs, proxy creation and multi-server deployment require separate ownership and permission design. The current create form covers a single app/worker/container definition and can be used repeatedly within a namespace.

References: [Docker Compose service options](https://docs.docker.com/reference/compose-file/services/) and [systemd execution settings](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).
