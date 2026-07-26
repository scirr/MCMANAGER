@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   Deploiement de MC Manager (Windows)
echo ========================================
echo.

REM Verifie que ce terminal est lance en administrateur (necessaire pour copier
REM la commande globale dans System32 et installer le service Windows)
net session >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Ce script doit etre execute en tant qu'administrateur.
    echo Clic droit sur install.bat, puis "Executer en tant qu'administrateur".
    pause
    exit /b 1
)
echo [OK] Droits administrateur confirmes.
echo.

REM Verifie que Python est installe
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    echo Telechargez Python 3.11+ sur https://python.org
    pause
    exit /b 1
)

REM Java n'est requis que pour demarrer un serveur (mc start), pas pour
REM l'installation elle-meme - simple avertissement, jamais bloquant. Une
REM detection plus large (hors PATH) est faite par MC Manager lui-meme au
REM moment de mc start (mc_core.find_java).
java -version >nul 2>&1
if errorlevel 1 (
    echo [ATTENTION] Java n'a pas ete detecte dans le PATH.
    echo MC Manager fonctionnera, mais vous ne pourrez pas demarrer de serveur sans Java 21+.
    echo Telechargez-le sur https://adoptium.net/
    echo.
) else (
    echo [OK] Java detecte.
    echo.
)

echo [1/4] Installation des dependances Python (Pillow)...
python -m pip install --quiet Pillow
echo.

echo [2/4] Installation de la commande globale 'mc'...
python mc_config.py --install-only
echo.

echo [3/4] Installation du daemon (service Windows via NSSM)...
echo       Telechargement de NSSM si necessaire, puis creation du service.
python -c "import mc_config; mc_config.install_daemon_task()"
echo.

echo [4/4] Termine.
echo ========================================
echo   Installation terminee !
echo ========================================
echo.
echo Tapez 'mc deploy' dans un NOUVEAU terminal pour creer votre premier serveur.
echo.
pause
