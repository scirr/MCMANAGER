#!/bin/bash
cd "$(dirname "$0")" || exit 1
if [ ! -f mc_config.py ] && [ -f build_release.py ]; then
    echo "[ERROR] This is the source folder. Build the package first:"
    echo "        python3 build_release.py && unzip ../dist/MCManager-macOS.zip -d ~"
    echo "        then run: cd ~/MCManager && ./install.sh"
    exit 1
fi
echo "========================================"
echo "  MC Manager (macOS) — Setup"
echo "========================================"
echo ""

if [ "$(id -u)" -eq 0 ]; then
    echo "[ERROR] Do not run this script with sudo: the service is a per-user LaunchAgent."
    echo "Re-run: ./install.sh"
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERROR] Python 3 is not installed."
    echo "Install it: xcode-select --install   or   brew install python"
    exit 1
fi

if ! command -v java >/dev/null 2>&1 || ! java -version >/dev/null 2>&1; then
    echo "[WARNING] Java was not detected."
    echo "MC Manager will work, but you won't be able to start a server without Java 21+."
    echo "Install it: brew install --cask temurin@21   or run 'mc java install 21' later."
    echo ""
else
    echo "[OK] Java detected."
    echo ""
fi

APP_DIR="$(pwd)"
VENV="$APP_DIR/venv"

echo "[1/5] Creating the Python environment ($VENV)..."
if ! python3 -m venv --system-site-packages "$VENV" || [ ! -x "$VENV/bin/python" ]; then
    echo "[ERROR] Could not create the Python environment."
    echo "Install a full Python 3 (brew install python), then re-run this script."
    exit 1
fi
PY="$VENV/bin/python"
echo "[OK] $("$PY" --version)"
echo ""

echo "[2/5] Installing Pillow (optional, used by 'mc image')..."
if "$PY" -m pip install --quiet --disable-pip-version-check --require-hashes -r requirements.txt; then
    echo "[OK] Pillow installed."
else
    echo "[WARNING] Pillow could not be installed: 'mc image' will be unavailable."
    echo "          Everything else works. Retry later with: ./install.sh"
fi
echo ""

xattr -dr com.apple.quarantine "$APP_DIR" >/dev/null 2>&1

echo "[3/5] Installing the 'mc' command..."
"$PY" mc_config.py --install-only || exit 1
echo ""

echo "[4/5] Installing the daemon (LaunchAgent)..."
"$PY" mc_config.py --install-daemon || exit 1
echo ""

echo "[5/5] Done."
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
echo "Type 'mc deploy' in a NEW terminal to create your first server."
echo "If 'mc' is not found, add ~/bin to your PATH:  echo 'export PATH=\"\$HOME/bin:\$PATH\"' >> ~/.zshrc"
echo ""
