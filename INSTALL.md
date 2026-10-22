# Installing App Spaces in aaPanel

This guide installs the App Spaces plugin on a Linux server running aaPanel. Installing it doesn't change any of your existing services, containers or proxy projects.

## 1. Prerequisites

- A Linux server with aaPanel installed. You need root SSH access and the aaPanel **primary administrator** account.
- Python 3.9 or later in aaPanel's runtime (`/www/server/panel/pyenv/bin/python3 --version`).
- systemd tools: `systemctl`, `journalctl`, `systemd-analyze`, `ss`, `ip`. These come preinstalled on most distributions.
- Optional: Docker with the Compose v2 plugin (`docker compose version`) for the Docker features.
- Make a backup of the panel first. aaPanel → Settings → Backup, or a server snapshot.

## 2. Get the package

**Option A: download** `app_spaces-<version>.zip` from the [GitHub Releases](https://github.com/mr-aybee/aapanel-app-spaces/releases) page.

**Option B: build it yourself** (any OS with Python 3.9 or later):

```bash
git clone https://github.com/mr-aybee/aapanel-app-spaces.git app-spaces && cd app-spaces
python tools/assemble_ui.py
python -m unittest discover -s tests
python tools/build.py          # -> dist/app_spaces-<version>.zip
```

The zip contains a single `app_spaces/` folder.

## 3. Install

### Option A: aaPanel plugin import (UI)

1. In aaPanel, open **App Store** and choose **Import plugin** (the label varies by version, for example *Third-party → Import*).
2. Upload `app_spaces-<version>.zip`.
3. Your panel version may not run the installer on import. If so, run step 3 of option B over SSH.

### Option B: manual install (SSH, as root)

```bash
# 1. upload the zip, e.g.
scp dist/app_spaces-0.0.1.zip root@your-server:/tmp/

# 2. extract into the aaPanel plugin directory
cd /tmp && unzip -o app_spaces-0.0.1.zip -d /www/server/panel/plugin/

# 3. run the installer
bash /www/server/panel/plugin/app_spaces/install.sh install
```

The installer:
- creates private plugin storage at `/www/server/panel/plugin/app_spaces/data` (mode 700)
- publishes the workspace shell to `BTPanel/static/app_spaces/`
- adds one marked script tag for the **App Spaces** shortcut beside Supervisor in Proxy Project
- adds one marked startup loader for the `/app-spaces` route

It **does not** create, stop or restart any service.

### 4. Reload the panel

```bash
bt restart        # or: /etc/init.d/bt restart
```

Then hard-refresh aaPanel in your browser (Ctrl+F5).

## 5. Verify

- **App Store → Installed** lists **App Spaces**.
- **Website → Proxy Project** shows an **App Spaces** button next to Supervisor.
- `https://<your-panel>/app-spaces` opens the workspace in its own tab while you're logged in as the primary admin.

## 6. First run

1. Click **+ Namespace** and create one, such as `myapp-production`.
2. Click **Discover services** and register the systemd units and containers that belong to it.
3. Start with a **disposable test service**. Open it, turn on its lifecycle and config permissions (off by default), and try restarting it and editing its configuration.
4. When you're happy with how it behaves, register your production workloads.

## Updating

```bash
unzip -o app_spaces-<new-version>.zip -d /www/server/panel/plugin/
bash /www/server/panel/plugin/app_spaces/install.sh update
bt restart
```

Updating keeps the `data/` directory and your namespaces. aaPanel updates can replace the panel template. If the Proxy Project shortcut disappears, run `install.sh update` again.

## Uninstalling

```bash
bash /www/server/panel/plugin/app_spaces/install.sh uninstall
```

This removes only the marked template hook, the startup loader and the two static files. Your workloads and the plugin's `data/` are **kept**. Then remove the plugin from aaPanel's plugin management. If you are sure you don't need its data any more, also delete `/www/server/panel/plugin/app_spaces/data/`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Plugin not listed | Check that `/www/server/panel/plugin/app_spaces/app_spaces_main.py` and `info.json` exist, then restart the panel. |
| `Run the aaPanel installer as root` | Run `install.sh` with `sudo` or as root. |
| `Extract app_spaces into the panel plugin directory first` | The zip went to the wrong place. It should create `/www/server/panel/plugin/app_spaces/`. |
| Shortcut missing after an aaPanel update | `bash .../app_spaces/install.sh update` |
| "Forbidden" or "authentication" errors | Log in as the **primary** administrator. Temporary login links and API keys are rejected. |
| CPU/RAM show *unavailable* | The server needs cgroup v2 (`stat -fc %T /sys/fs/cgroup` should print `cgroup2fs`). |
| No Docker services | Check that `docker ps` and `docker compose version` work for root. |

For deeper operational details (config editing, backups, rollback, metrics), see [docs/INSTALL.md](docs/INSTALL.md).
