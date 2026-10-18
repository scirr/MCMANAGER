@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist mc_config.py if exist build_release.py (
    echo [ERROR] This is the source folder. Build the package first:
    echo         python build_release.py
    echo         then unzip ..\dist\MCManager.zip, open the MCManager folder and run install.bat there.
    pause
    exit /b 1
)
echo ========================================
echo   MC Manager (Windows) — Setup
echo ========================================
echo.

REM Requires administrator rights to copy the global command to System32
REM and install the Windows service.
net session >nul 2>&1
if errorlevel 1 (
    echo [ERROR] This script must be run as administrator.
    echo Right-click install.bat and select "Run as administrator".
    pause
    exit /b 1
)
echo [OK] Administrator rights confirmed.
echo.

REM Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Download Python 3.11+ from https://python.org
    pause
    exit /b 1
)

REM Java is only required to start a server (mc start), not for the installer itself.
REM MC Manager performs a broader Java search (outside PATH) at mc start time (mc_core.find_java).
java -version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] Java was not detected in PATH.
    echo MC Manager will work, but you won't be able to start a server without Java 21+.
    echo Download it from https://adoptium.net/
    echo.
) else (
    echo [OK] Java detected.
    echo.
)

echo [1/5] Installing Python dependencies (Pillow)...
python -m pip install --quiet Pillow
echo.

echo [2/5] Installing global 'mc' command...
python mc_config.py --install-only
echo.

echo [3/5] Installing daemon (Windows service via NSSM)...
echo       Downloading NSSM if needed, then creating the service.
echo       The service never stops running servers when it restarts (AppKillProcessTree 0).
python mc_config.py --install-daemon
echo.

echo [4/5] Checking Windows Firewall...
python -c "import mc_firewall; print('Firewall:', mc_firewall.detect() or 'not detected - game ports will have to be opened by hand')"
echo       Game-port rules ("MCManager - Port N") are added by 'mc deploy' and 'mc add'.
echo.

echo [5/5] Done.
echo ========================================
echo   Setup complete!
echo ========================================
echo.
echo Open a NEW terminal and type 'mc deploy' to create your first server.
echo.
pause
