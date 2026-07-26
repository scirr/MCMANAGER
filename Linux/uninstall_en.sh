#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  MC Manager (Linux) — Uninstall"
echo "========================================"
echo ""
echo "This script removes system integrations:"
echo "  - mc_manager systemd service"
echo "  - Global 'mc' command (/usr/local/bin/mc)"
echo "  - Generated files (logs, mc, __pycache__)"
echo ""
echo "The .py scripts in this folder will NOT be removed."
echo ""

read -r -p "Continue uninstallation? (Y/N): " CONFIRM
case "$CONFIRM" in
    [yY]*) ;;
    *) echo "Cancelled." ; exit 0 ;;
esac
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] Root rights required to remove the service and /usr/local/bin/mc."
    echo "    Re-run: sudo ./uninstall.sh"
    exit 1
fi

echo "[1/4] Stopping active Minecraft servers..."
python3 -c "import mc_servers; mc_servers.stop_all_running()" 2>/dev/null
sleep 5
echo ""

echo "[2/4] Removing mc_manager systemd service..."
if systemctl list-unit-files mc_manager.service >/dev/null 2>&1 \
   && [ -f /etc/systemd/system/mc_manager.service ]; then
    systemctl stop mc_manager.service >/dev/null 2>&1
    systemctl disable mc_manager.service >/dev/null 2>&1
    rm -f /etc/systemd/system/mc_manager.service
    systemctl daemon-reload
    echo "[OK] mc_manager service removed."
else
    echo "[OK] No mc_manager service installed."
fi
echo ""

echo "[3/4] Removing global 'mc' command..."
if [ -f /usr/local/bin/mc ]; then
    rm -f /usr/local/bin/mc
    echo "[OK] Global 'mc' command removed."
else
    echo "[OK] Global 'mc' command already absent."
fi
echo ""

echo "[4/4] Cleaning generated files..."
rm -rf logs __pycache__
rm -f daemon.log daemon_error*.log server.pid mc
echo "[OK] Generated files cleaned."
echo ""

if [ -f "servers.json" ]; then
    read -r -p "Also delete servers.json (server registry)? (Y/N): " DELCONF
    case "$DELCONF" in
        [yY]*)
            rm -f servers.json
            echo "[OK] Registry deleted."
            ;;
        *) echo "[OK] Registry kept." ;;
    esac
    echo ""
fi

echo "========================================"
echo "  IMPORTANT: your Minecraft servers are NOT deleted"
echo "========================================"
echo ""
echo "This script never touches your server files (worlds, mods, backups)."
echo "If you really want to erase everything, delete these yourself:"
python3 -c "import mc_servers; mc_servers.print_data_locations()" 2>/dev/null
echo ""

echo "========================================"
echo "  Uninstallation complete."
echo "========================================"
echo ""
echo "MC Manager is no longer integrated with the system (service, command)."
echo "The files in this folder remain available if you want to reinstall"
echo "later with install.sh."
echo ""
