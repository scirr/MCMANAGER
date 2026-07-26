@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo   MC Manager (Windows) — Uninstall
echo ========================================
echo.
echo This script removes the system integrations:
echo   - MCManagerDaemon Windows service (NSSM)
echo   - Residual scheduled task (if any)
echo   - Global 'mc' command (C:\Windows\System32\mc.bat)
echo   - Generated files (logs, server.pid, nssm\, __pycache__)
echo.
echo The .py scripts in this folder will NOT be deleted.
echo.

set /p CONFIRM="Continue with uninstall? (Y/N) : "
if /i not "%CONFIRM%"=="Y" (
    echo Cancelled.
    pause
    exit /b 0
)
echo.

echo [1/5] Stopping running Minecraft servers...
python -c "import mc_servers; mc_servers.stop_all_running()"
timeout /t 5 /nobreak >nul
echo.

echo [2/5] Removing MCManagerDaemon Windows service...
if exist "nssm\nssm.exe" (
    "nssm\nssm.exe" stop MCManagerDaemon >nul 2>&1
    "nssm\nssm.exe" remove MCManagerDaemon confirm >nul 2>&1
)
sc query MCManagerDaemon >nul 2>&1
if not errorlevel 1 (
    sc stop MCManagerDaemon >nul 2>&1
    sc delete MCManagerDaemon >nul 2>&1
    echo [OK] MCManagerDaemon service removed.
) else (
    echo [OK] No MCManagerDaemon service found.
)
echo.

echo [3/5] Cleaning up any residual scheduled task...
schtasks /query /tn "MCManagerDaemon" >nul 2>&1
if not errorlevel 1 (
    schtasks /delete /tn "MCManagerDaemon" /f >nul 2>&1
    echo [OK] Scheduled task removed.
) else (
    echo [OK] No residual scheduled task found.
)
echo.

echo [4/5] Removing global 'mc' command...
if exist "C:\Windows\System32\mc.bat" (
    del /f /q "C:\Windows\System32\mc.bat" >nul 2>&1
    if exist "C:\Windows\System32\mc.bat" (
        echo [!] Admin rights required to delete C:\Windows\System32\mc.bat
        echo     Re-run this script as administrator, or delete it manually.
    ) else (
        echo [OK] Global 'mc' command removed.
    )
) else (
    echo [OK] Global 'mc' command not found.
)
echo.

echo [5/5] Cleaning generated files...
if exist "logs" rmdir /s /q "logs" >nul 2>&1
del /f /q "daemon.log" >nul 2>&1
del /f /q "daemon_error*.log" >nul 2>&1
del /f /q "server.pid" >nul 2>&1
del /f /q "mc.bat" >nul 2>&1
if exist "nssm" rmdir /s /q "nssm" >nul 2>&1
if exist "__pycache__" rmdir /s /q "__pycache__" >nul 2>&1
echo [OK] Generated files cleaned.
echo.

if exist "config.json" (
    set /p DELCONF="Also delete config.json and webhooks.json (RCON/Discord tokens)? (Y/N) : "
    if /i "%DELCONF%"=="Y" (
        del /f /q "config.json" >nul 2>&1
        del /f /q "webhooks.json" >nul 2>&1
        echo [OK] Configuration deleted.
    ) else (
        echo [OK] Configuration kept.
    )
    echo.
)

echo ========================================
echo   IMPORTANT: your Minecraft server files are NOT deleted
echo ========================================
echo.
echo This script never touches your server files (worlds, mods, backups).
echo If you want to fully delete everything, remove these folders manually:
python -c "import mc_servers; mc_servers.print_data_locations()" 2>nul
echo.

echo ========================================
echo   Uninstall complete.
echo ========================================
echo.
echo MC Manager is no longer integrated into the system (service, command, task).
echo The files in this folder remain available if you want to reinstall later
echo using install.bat.
echo.
pause
