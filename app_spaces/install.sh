#!/usr/bin/env bash

set -euo pipefail

# aaPanel runs this from an extracted app_spaces plugin directory.

PLUGIN=/www/server/panel/plugin/app_spaces

case "${1:-install}" in

  install|update)

    [ "$(id -u)" -eq 0 ] || { echo 'Run the aaPanel installer as root'; exit 1; }

    [ -f "$PLUGIN/app_spaces_main.py" ] || { echo 'Extract app_spaces into the panel plugin directory first'; exit 1; }

    mkdir -p "$PLUGIN/data"

    chmod 700 "$PLUGIN/data"

    chmod 755 "$PLUGIN/install.sh"

    /www/server/panel/pyenv/bin/python3 "$PLUGIN/panel_integration.py"

    echo 'App Spaces files ready. No workloads, proxies, or system services were changed.'

    ;;

  uninstall)
    /www/server/panel/pyenv/bin/python3 "$PLUGIN/panel_integration.py" uninstall

    # Intentionally retain files/data; no recursive deletion or workload shutdown.

    echo 'App Spaces requires no daemon removal. Workloads and plugin data are preserved.'

    ;;

  *) echo 'Usage: install.sh install|update|uninstall'; exit 1 ;;

esac

