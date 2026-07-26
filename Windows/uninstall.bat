@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   Desinstallation de MC Manager (Windows)
echo ========================================
echo.
echo Ce script supprime les integrations systeme :
echo   - Service Windows MCManagerDaemon (NSSM)
echo   - Tache planifiee residuelle (si presente)
echo   - Commande globale 'mc' (C:\Windows\System32\mc.bat)
echo   - Fichiers generes (logs, server.pid, nssm\, __pycache__)
echo.
echo Les scripts .py de ce dossier ne seront PAS supprimes.
echo.

set /p CONFIRM="Continuer la desinstallation ? (O/N) : "
if /i not "%CONFIRM%"=="O" (
    echo Annule.
    pause
    exit /b 0
)
echo.

echo [1/5] Arret des serveurs Minecraft actifs...
python -c "import mc_servers; mc_servers.stop_all_running()"
timeout /t 5 /nobreak >nul
echo.

echo [2/5] Suppression du service Windows MCManagerDaemon...
if exist "nssm\nssm.exe" (
    "nssm\nssm.exe" stop MCManagerDaemon >nul 2>&1
    "nssm\nssm.exe" remove MCManagerDaemon confirm >nul 2>&1
)
sc query MCManagerDaemon >nul 2>&1
if not errorlevel 1 (
    sc stop MCManagerDaemon >nul 2>&1
    sc delete MCManagerDaemon >nul 2>&1
    echo [OK] Service MCManagerDaemon supprime.
) else (
    echo [OK] Aucun service MCManagerDaemon installe.
)
echo.

echo [3/5] Nettoyage d'une eventuelle tache planifiee residuelle...
schtasks /query /tn "MCManagerDaemon" >nul 2>&1
if not errorlevel 1 (
    schtasks /delete /tn "MCManagerDaemon" /f >nul 2>&1
    echo [OK] Tache planifiee supprimee.
) else (
    echo [OK] Aucune tache planifiee residuelle.
)
echo.

echo [4/5] Suppression de la commande globale 'mc'...
if exist "C:\Windows\System32\mc.bat" (
    del /f /q "C:\Windows\System32\mc.bat" >nul 2>&1
    if exist "C:\Windows\System32\mc.bat" (
        echo [!] Droits admin requis pour supprimer C:\Windows\System32\mc.bat
        echo     Relancez ce script en tant qu'administrateur, ou supprimez-le manuellement.
    ) else (
        echo [OK] Commande 'mc' globale supprimee.
    )
) else (
    echo [OK] Commande 'mc' globale deja absente.
)
echo.

echo [5/5] Nettoyage des fichiers generes...
if exist "logs" rmdir /s /q "logs" >nul 2>&1
del /f /q "daemon.log" >nul 2>&1
del /f /q "daemon_error*.log" >nul 2>&1
del /f /q "server.pid" >nul 2>&1
del /f /q "mc.bat" >nul 2>&1
if exist "nssm" rmdir /s /q "nssm" >nul 2>&1
if exist "__pycache__" rmdir /s /q "__pycache__" >nul 2>&1
echo [OK] Fichiers generes nettoyes.
echo.

if exist "config.json" (
    set /p DELCONF="Supprimer aussi config.json et webhooks.json (tokens RCON/Discord) ? (O/N) : "
    if /i "%DELCONF%"=="O" (
        del /f /q "config.json" >nul 2>&1
        del /f /q "webhooks.json" >nul 2>&1
        echo [OK] Configuration supprimee.
    ) else (
        echo [OK] Configuration conservee.
    )
    echo.
)

echo ========================================
echo   IMPORTANT : vos serveurs Minecraft ne sont PAS supprimes
echo ========================================
echo.
echo Ce script ne touche jamais aux fichiers de vos serveurs (mondes, mods,
echo backups). Si vous voulez vraiment tout effacer, supprimez vous-meme :
python -c "import mc_servers; mc_servers.print_data_locations()" 2>nul
echo.

echo ========================================
echo   Desinstallation terminee.
echo ========================================
echo.
echo MC Manager n'est plus integre au systeme (service, commande, tache).
echo Les fichiers du dossier restent disponibles si vous souhaitez reinstaller
echo plus tard avec install.bat.
echo.
pause
