#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  Deploiement de MC Manager (Linux)"
echo "========================================"
echo ""

# Verifie que ce script est lance en root (necessaire pour installer
# la commande globale dans /usr/local/bin et le service systemd)
if [ "$(id -u)" -ne 0 ]; then
    echo "[ERREUR] Ce script doit etre execute avec sudo."
    echo "Relancez : sudo ./install.sh"
    exit 1
fi
echo "[OK] Droits root confirmes."
echo ""

# Verifie que Python est installe
if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERREUR] Python 3 n'est pas installe."
    echo "Installez-le : sudo dnf install python3   (Fedora)"
    exit 1
fi

# Java n'est requis que pour demarrer un serveur (mc start), pas pour
# l'installation elle-meme - simple avertissement, jamais bloquant. Une
# detection plus large (hors PATH) est faite par MC Manager lui-meme au
# moment de mc start (mc_core.find_java).
if ! command -v java >/dev/null 2>&1; then
    echo "[ATTENTION] Java n'a pas ete detecte dans le PATH."
    echo "MC Manager fonctionnera, mais vous ne pourrez pas demarrer de serveur sans Java 21+."
    echo "Installez-le : sudo dnf install java-21-openjdk-headless (ou https://adoptium.net/)"
    echo ""
else
    echo "[OK] Java detecte."
    echo ""
fi

echo "[1/4] Installation des dependances Python (Pillow, optionnel)..."
python3 -m pip install --quiet Pillow 2>/dev/null \
    || dnf install -y -q python3-pillow 2>/dev/null \
    || echo "[!] Pillow non installe (optionnel, requis uniquement pour 'mc image')."
echo ""

echo "[2/4] Installation de la commande globale 'mc'..."
python3 mc_config.py --install-only
echo ""

echo "[3/4] Installation du daemon (service systemd)..."
python3 mc_config.py --install-daemon
echo ""

echo "[4/4] Termine."
echo "========================================"
echo "  Installation terminee !"
echo "========================================"
echo ""
echo "Tapez 'mc deploy' dans un NOUVEAU terminal pour creer votre premier serveur."
echo ""
