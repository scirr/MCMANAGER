#!/bin/bash
cd "$(dirname "$0")" || exit 1
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
    echo "Install it: sudo apt install python3   (Debian/Ubuntu)"
    echo "            sudo dnf install python3   (Fedora)"
    exit 1
fi

# Java is only required to start a server (mc start), not for the
# installation itself - simple warning, never blocking. A broader
# detection (outside PATH) is done by MC Manager itself at mc start
# time (mc_core.find_java).
if ! command -v java >/dev/null 2>&1; then
    echo "[WARNING] Java was not detected in PATH."
    echo "MC Manager will work, but you won't be able to start a server without Java 21+."
    echo "Install it: sudo apt install openjdk-21-jre-headless   (Debian/Ubuntu)"
    echo "            sudo dnf install java-21-openjdk-headless  (Fedora)"
    echo ""
else
    echo "[OK] Java detected."
    echo ""
fi

APP_DIR="$(pwd)"
VENV="$APP_DIR/venv"

echo "[1/5] Creating the Python environment ($VENV)..."
# --system-site-packages: a distribution-packaged Pillow (fallback below) stays visible.
if ! python3 -m venv --system-site-packages "$VENV"; then
    if command -v apt-get >/dev/null 2>&1; then
        echo "[i] Installing python3-venv..."
        apt-get install -y python3-venv && python3 -m venv --system-site-packages "$VENV"
    fi
fi
if [ ! -x "$VENV/bin/python" ]; then
    echo "[ERROR] Could not create the Python environment."
    echo "Install the venv module, then re-run this script:"
    echo "  sudo apt install python3-venv   (Debian/Ubuntu)"
    echo "  sudo dnf install python3        (Fedora)"
    exit 1
fi
PY="$VENV/bin/python"
echo "[OK] $("$PY" --version)"
echo ""

echo "[2/5] Installing Pillow (optional, used by 'mc image')..."
if "$PY" -m pip install --quiet --disable-pip-version-check --require-hashes -r requirements.txt; then
    echo "[OK] Pillow installed (version and hashes pinned in requirements.txt)."
elif command -v apt-get >/dev/null 2>&1 && apt-get install -y python3-pil; then
    echo "[OK] Pillow installed from the distribution (python3-pil)."
elif command -v dnf >/dev/null 2>&1 && dnf install -y python3-pillow; then
    echo "[OK] Pillow installed from the distribution (python3-pillow)."
else
    echo "[WARNING] Pillow could not be installed: 'mc image' will be unavailable."
    echo "          Everything else works. Retry later with: sudo ./install.sh"
fi
echo ""

echo "[3/5] Installing global 'mc' command..."
"$PY" mc_config.py --install-only || exit 1
echo ""

echo "[4/5] Installing daemon (systemd service)..."
"$PY" mc_config.py --install-daemon || exit 1
echo ""

# This root install created files (logs/, venv/, __pycache__, ...) as root:root,
# but the service runs as $SUDO_USER. Hand the app directory back to that user
# so the daemon can write logs/daemon.log (otherwise it loops in 'activating'
# with PermissionError). ':' after the name uses the user's login group.
chown -R "${SUDO_USER:-root}:" "$APP_DIR"

echo "[5/5] Done."
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "Type 'mc deploy' in a NEW terminal to create your first server."
echo ""
