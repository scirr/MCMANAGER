#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  MC Manager (Linux) — Setup"
echo "========================================"
echo ""

# Check this script is run as root (required to install the global
# command in /usr/local/bin and the systemd service)
if [ "$(id -u)" -ne 0 ]; then
    echo "[ERROR] This script must be run with sudo."
    echo "Re-run: sudo ./install.sh"
    exit 1
fi
echo "[OK] Root rights confirmed."
echo ""

# Check Python is installed
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] Python 3 is not installed."
    echo "Install it: sudo dnf install python3   (Fedora)"
    exit 1
fi

# Java is only required to start a server (mc start), not for the
# installation itself - simple warning, never blocking. A broader
# detection (outside PATH) is done by MC Manager itself at mc start
# time (mc_core.find_java).
if ! command -v java >/dev/null 2>&1; then
    echo "[WARNING] Java was not detected in PATH."
    echo "MC Manager will work, but you won't be able to start a server without Java 21+."
    echo "Install it: sudo dnf install java-21-openjdk-headless (or https://adoptium.net/)"
    echo ""
else
    echo "[OK] Java detected."
    echo ""
fi

echo "[1/4] Installing Python dependencies (Pillow, optional)..."
python3 -m pip install --quiet Pillow 2>/dev/null \
    || dnf install -y -q python3-pillow 2>/dev/null \
    || echo "[!] Pillow not installed (optional, only required for 'mc image')."
echo ""

echo "[2/4] Installing global 'mc' command..."
python3 mc_config.py --install-only
echo ""

echo "[3/4] Installing daemon (systemd service)..."
python3 mc_config.py --install-daemon
echo ""

# This root install created files (logs/, __pycache__, ...) as root:root, but
# the service runs as $SUDO_USER. Hand the app directory back to that user so
# the daemon can write logs/daemon.log (otherwise it loops in 'activating' with
# PermissionError). ':' after the name uses the user's login group.
APP_DIR="$(pwd)"
chown -R "${SUDO_USER:-root}:" "$APP_DIR"

echo "[4/4] Done."
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "Type 'mc deploy' in a NEW terminal to create your first server."
echo ""
