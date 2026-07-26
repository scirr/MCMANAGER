#!/bin/bash
cd "$(dirname "$0")"
echo "========================================"
echo "  Desinstallation de MC Manager (Linux)"
echo "========================================"
echo ""
echo "Ce script supprime les integrations systeme :"
echo "  - Service systemd mc_manager"
echo "  - Commande globale 'mc' (/usr/local/bin/mc)"
echo "  - Fichiers generes (logs, mc, __pycache__)"
echo ""
echo "Les scripts .py de ce dossier ne seront PAS supprimes."
echo ""

read -r -p "Continuer la desinstallation ? (O/N) : " CONFIRM
case "$CONFIRM" in
    [oO]*) ;;
    *) echo "Annule." ; exit 0 ;;
esac
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] Droits root requis pour supprimer le service et /usr/local/bin/mc."
    echo "    Relancez : sudo ./uninstall.sh"
    exit 1
fi

echo "[1/4] Arret des serveurs Minecraft actifs..."
python3 -c "import mc_servers; mc_servers.stop_all_running()" 2>/dev/null
sleep 5
echo ""

echo "[2/4] Suppression du service systemd mc_manager..."
if systemctl list-unit-files mc_manager.service >/dev/null 2>&1 \
   && [ -f /etc/systemd/system/mc_manager.service ]; then
    systemctl stop mc_manager.service >/dev/null 2>&1
    systemctl disable mc_manager.service >/dev/null 2>&1
    rm -f /etc/systemd/system/mc_manager.service
    systemctl daemon-reload
    echo "[OK] Service mc_manager supprime."
else
    echo "[OK] Aucun service mc_manager installe."
fi
echo ""

echo "[3/4] Suppression de la commande globale 'mc'..."
if [ -f /usr/local/bin/mc ]; then
    rm -f /usr/local/bin/mc
    echo "[OK] Commande 'mc' globale supprimee."
else
    echo "[OK] Commande 'mc' globale deja absente."
fi
echo ""

echo "[4/4] Nettoyage des fichiers generes..."
rm -rf logs __pycache__
rm -f daemon.log daemon_error*.log server.pid mc
echo "[OK] Fichiers generes nettoyes."
echo ""

if [ -f "servers.json" ]; then
    read -r -p "Supprimer aussi servers.json (registre des serveurs) ? (O/N) : " DELCONF
    case "$DELCONF" in
        [oO]*)
            rm -f servers.json
            echo "[OK] Registre supprime."
            ;;
        *) echo "[OK] Registre conserve." ;;
    esac
    echo ""
fi

echo "========================================"
echo "  IMPORTANT : vos serveurs Minecraft ne sont PAS supprimes"
echo "========================================"
echo ""
echo "Ce script ne touche jamais aux fichiers de vos serveurs (mondes, mods,"
echo "backups). Si vous voulez vraiment tout effacer, supprimez vous-meme :"
python3 -c "import mc_servers; mc_servers.print_data_locations()" 2>/dev/null
echo ""

echo "========================================"
echo "  Desinstallation terminee."
echo "========================================"
echo ""
echo "MC Manager n'est plus integre au systeme (service, commande)."
echo "Les fichiers du dossier restent disponibles si vous souhaitez reinstaller"
echo "plus tard avec install.sh."
echo ""
