#!/bin/bash
cd "$(dirname "$0")" || exit 1
LABEL="io.github.scirr.mcmanager"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
echo "========================================"
echo "  MC Manager (macOS) — Uninstall"
echo "========================================"
echo ""
echo "This script removes system integrations:"
echo "  - $LABEL LaunchAgent"
echo "  - The 'mc' command (/usr/local/bin/mc or ~/bin/mc)"
echo "  - Generated files (logs, run, previous, venv, mc, __pycache__)"
echo ""
echo "The .py scripts in this folder will NOT be removed."
echo ""

read -r -p "Continue uninstallation? (Y/N): " CONFIRM
case "$CONFIRM" in
    [yY]*) ;;
    *) echo "Cancelled." ; exit 0 ;;
esac
echo ""

echo "[1/4] Stopping active Minecraft servers..."
python3 -c "import mc_servers; mc_servers.stop_all_running()" 2>/dev/null
sleep 5
echo ""

echo "[2/4] Removing the LaunchAgent..."
if [ -f "$PLIST" ]; then
    launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1
    rm -f "$PLIST"
    echo "[OK] LaunchAgent removed."
else
    echo "[OK] No LaunchAgent installed."
fi
echo ""

echo "[3/4] Removing the 'mc' command..."
for target in /usr/local/bin/mc "$HOME/bin/mc"; do
    if [ -f "$target" ] && grep -q "mc_cli.py" "$target" 2>/dev/null; then
        rm -f "$target" 2>/dev/null && echo "[OK] $target removed." \
            || echo "[!] Could not remove $target: run  sudo rm $target"
    fi
done
echo ""

echo "[4/4] Cleaning generated files..."
rm -rf logs run previous venv __pycache__
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
echo "Uninstallation complete."
echo ""
