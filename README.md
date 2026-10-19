# 🎮 MC Manager

**MC Manager** is a lightweight, cross-platform Minecraft server management tool built in Python. It automates server scheduling, backups, Discord notifications, and provides a simple `mc` CLI — available on both **Linux** and **Windows**.

> Designed for personal or small community Minecraft servers running Fabric, Paper, Forge or any JAR-based server.

## 📖 Full documentation

This README is a high-level overview only. For installation steps and the complete, up-to-date command reference for your platform, see:

- 🪟 **[Windows guide](Windows/README_Windows.md)** — multi-server management, `mc deploy`/`mc add`/`mc configure`, full command reference
- 🐧 **[Linux guide](Linux/README_Linux.md)** — installation, configuration, command reference

---

## ✨ Features

- **Automatic scheduling** — Opens and closes the server at configured hours every day
- **Automatic backups** — Mid-session, nightly and manual ZIP backups with `save-off` / `save-on` safety
- **Discord webhooks** — Notifies players on server open, close, and shutdown events
- **Maintenance mode** — Instantly pauses the daemon without stopping it
- **Sleep mode** — Frees the server's memory when nobody plays; the server stays listed and wakes when a known player joins, optionally keeping them connected (hold) or freezing the JVM (Linux)
- **Router** — Several servers behind one port, chosen by hostname, with per-IP limits and CIDR lists (Linux)
- **Every server type** — Vanilla, Paper, Folia, Purpur, Fabric, Quilt, Forge, NeoForge, Spigot, and the Velocity/Waterfall/BungeeCord proxies; `mc upgrade` moves a server to a newer Minecraft version (Linux)
- **Modpacks, mods and plugins by name** — Modrinth, CurseForge and FTB modpacks; mods and plugins from Modrinth, CurseForge and Hangar with their dependencies; a managed Java runtime per server (Linux)
- **Custom domain** — Show players a friendly domain/link (from any DNS provider) instead of a bare IP
- **AutoModpack integration** — Sends the connection key directly in the Discord embed
- **CPU affinity** — Pins the server process to specific CPU cores
- **Shared registry (dual-boot)** — Point Windows and Linux at one shared disk (`MCMANAGER_DATA_DIR`) and the same servers appear on both, no re-registering
- **Bilingual (FR/EN)** — A single build; the language is chosen on first launch and switchable anytime with `mc language`
- **Scriptable** — Documented exit codes, `--json` output with a versioned schema, and commands (`mc active`, `mc players`, `mc rcon`, `mc config`, `mc freeze`) so tools never have to parse MC Manager's files (Linux)
- **Signed updates** — `mc update` installs only packages whose Ed25519 signature and hashes check out, keeps the previous version for `mc update --rollback`; releases are built, signed and attested by CI
- **Hardened** — polkit instead of sudo, sandboxed systemd service, secrets readable by their owner only, RCON exposure checks (Linux); see [SECURITY.md](SECURITY.md)
- **Cross-platform** — Same logic, adapted natively for Linux and Windows

---

## 📁 Project Structure

Both platforms share the same module set and command surface. They are fully independent — no code is shared between the two directories.

```
MC_Manager/
├── core/               # modules shared by every platform (Linux and Windows)
│   ├── mc_cli.py       # entry point, dashboard, command dispatch
│   ├── mc_core.py      # lifecycle, native RCON, backups, webhooks
│   ├── mc_config.py    # config.json/webhooks.json, systemd install
│   ├── mc_servers.py   # multi-server registry (servers.json)
│   ├── mc_deploy.py    # deploy / add / configure wizards
│   ├── mc_daemon.py    # background scheduler (30s tick)
│   ├── mc_doctor.py    # non-destructive diagnostics
│   ├── mc_firewall.py  # ufw / firewalld rule automation
│   ├── mc_sig.py       # Ed25519 verification of signed updates
│   ├── mc_image.py     # server-icon.png handling
│   ├── mc_lang.py      # bilingual FR/EN strings
│   ├── mc_validate.py  # pure validators
│   ├── mc_api.py       # operations layer: states, start/stop/switch, sleep, freeze
│   ├── mc_content.py   # datapacks and mods
│   ├── mc_software.py  # server software installers (every loader and proxy)
│   ├── mc_java.py      # Temurin runtimes per server
│   ├── mc_modsources.py# mods/plugins by name (Modrinth, CurseForge, Hangar)
│   ├── mc_modpack.py   # modpacks (Modrinth, CurseForge, FTB)
│   ├── mc_http.py      # https downloads with hash checks
│   ├── mc_crash.py     # crash-loop detection
│   ├── mc_players.py   # whitelist, ops, bans, kick, connection history
│   ├── mc_world.py     # dimensions, world export/import/reset, Chunky pregeneration
│   ├── mc_task.py      # cron evaluator and scheduled tasks
│   ├── mc_s3.py        # S3 client (AWS Signature V4, stdlib)
│   ├── mc_backup.py    # backup list, retention, restore, sftp/s3/restic destinations
│   ├── mc_alert.py     # alert channels (e-mail, Telegram, ntfy, webhook, Discord)
│   ├── mc_metrics.py   # Prometheus exporter and server sampling
│   ├── mc_statuspage.py# static public status page
│   ├── mc_httpapi.py   # local HTTP API server (Unix socket / loopback + token)
│   ├── mc_apiops.py    # one handler per operation of the API contract
│   ├── mc_jobs.py      # in-memory registry of long API operations
│   ├── mc_remote.py    # remote access state: TLS certificate, devices, pairing, roles, audit
│   ├── mc_remoteserver.py # TLS 1.3 listener of the remote API
│   ├── mc_remoteclient.py # client side: profiles, pinned fingerprint, `mc --remote`
│   ├── mc_proxy.py     # TCP relay, connection limits, CIDR and banned IP filters
│   ├── mc_router.py    # hostname routing and private router configuration
│   ├── mc_protocol.py  # Minecraft network protocol (VarInt, handshake, status, login)
│   ├── mc_sleep.py     # sleep listener (status/login answered while the server sleeps)
│   ├── mc_ipc.py       # request channel CLI -> daemon
│   ├── mc_setup.py     # Java check
│   ├── mc_platform.py  # platform contract: the `plat` object every system call goes through
│   ├── platform_linux.py # Linux implementation (/proc, systemd, ufw/firewalld, termios)
│   ├── platform_macos.py # macOS implementation (ps/lsof, launchd, Application Firewall)
│   ├── plat_posix.py   # POSIX functions shared by the Linux and macOS implementations
│   ├── platform_windows.py, plat_win_*.py # Windows implementation
│   ├── webhook_templates.json
│   └── tests/
│
├── packaging/linux/    # .deb and .rpm builder (build_packages.py)
├── apps/linux/         # Desktop app (GTK 4 + libadwaita), Flatpak manifest
├── apps/macos/         # Desktop app (SwiftUI), Swift package
│
├── Linux/              # Linux packaging (systemd service)
│   ├── build_release.py
│   ├── install.sh / uninstall.sh
│   └── README_Linux.md
│
└── Windows/            # Windows packaging (NSSM service)
    ├── build_release.py
    ├── install.bat / uninstall.bat
    ├── webhook_templates.json
    └── README_Windows.md
```

---

## 🚀 Quick Start

### Linux

```bash
cd Linux/
python3 build_release.py
unzip ../dist/MCManager-Linux.zip -d ~
cd ~/MCManager && sudo ./install.sh
mc deploy
```

Or download `MCManager-Linux.zip` from the latest release and run `sudo ./install.sh` inside it.

### Install from a package (Debian, Ubuntu, Fedora)

Build the package with `python3 packaging/linux/build_packages.py` (output in `dist/`). The application goes to `/opt/mcmanager`, the command to `/usr/bin/mc`.

```bash
# Debian / Ubuntu
sudo apt install ./mcmanager_<version>_all.deb

# Fedora
sudo dnf install ./mcmanager-<version>-1.noarch.rpm

sudo mcmanager-setup        # installs the service for your user
mc deploy
```

Java is not a dependency: MC Manager installs one per server. Update with `sudo apt install ./<new>.deb` or `sudo dnf upgrade ./<new>.rpm` (`mc update` refuses on a package install). Removing the package never deletes your servers or worlds.

### Windows

Right-click `install.bat` → **Run as administrator**, then open a new terminal:

```
mc deploy
```

> Both platforms share the same multi-server workflow (`mc deploy`/`mc add`/`mc configure`, dashboard, modes...). See the **[Linux guide](Linux/README_Linux.md)** or **[Windows guide](Windows/README_Windows.md)** for the full walkthrough.

---

### Desktop app (Linux)

`apps/linux/` holds a native GTK 4 + libadwaita app (Python and PyGObject). It never reads MC Manager files: everything goes through the `/v1` API, either by the daemon's local socket (`run/api.sock`) or by a paired remote server (pinned certificate, device token). It shows the server dashboard (state, players, RAM), start/stop/restart/wake, the live console, the online players and the settings (read only). Texts follow the system language (English or French).

```
sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1   # libadwaita 1.5+
cd apps/linux && python3 -m mcmanager_app
```

On first launch, choose **This machine** or **A remote server** (address, fingerprint check, 8-digit code from `mc remote pair`). Tests: `cd apps/linux && python3 -m unittest discover tests` (the view tests run only where GTK is installed). A Flatpak manifest is in `apps/linux/flatpak/`; it opens only the daemon's `run/` folder.

### Desktop app (Windows)

<<<<<<< HEAD
`apps/windows/` holds a WinUI 3 app (C#, .NET 8, Windows App SDK 1.6, unpackaged, no MSIX). It never reads MC Manager files: it reads the port and the token the daemon writes to `run/api.token` and talks to the local `/v1` API on `127.0.0.1`. It shows the server list (state, players, RAM), start/stop/restart/resume, the live console, the player lists (whitelist, ops, bans, kick), backups, mods, datapacks, worlds (sizes, pre-generation, dimension reset), scheduled tasks and the server settings (mode, hours, Java, configuration keys; secret values are write-only), plus a wizard to create a server. Texts follow the system language (English or French).
=======
`apps/windows/` holds a WinUI 3 app (C#, .NET 8, Windows App SDK 1.6, unpackaged, no MSIX). It never reads MC Manager files: it reads the port and the token the daemon writes to `run/api.token` and talks to the local `/v1` API on `127.0.0.1`. It shows the server list (state, players, RAM), start/stop/restart/resume, the live console, the player lists (whitelist, ops, bans, kick), backups, mods, datapacks, world, scheduled tasks, settings and a server creation wizard. A paired remote MC Manager can be used too: the certificate fingerprint is pinned and compared in constant time, and the device token is kept in the macOS keychain. Texts follow the system language (English or French).
>>>>>>> feat/3.0-app-macos-onglets

| Project | Role |
|---|---|
| `MCManager.Client` | Typed API client, local API discovery, `ApiException` (net8.0, no UI) |
| `MCManager.ViewModels` | MVVM view models (CommunityToolkit.Mvvm), testable without Windows |
| `MCManager.App` | WinUI 3 windows and views, FR/EN `.resw` strings |
| `MCManager.Client.Tests`, `MCManager.ViewModels.Tests` | xunit tests, run on Linux |

```
cd apps/windows
dotnet test MCManager.Client.Tests
dotnet test MCManager.ViewModels.Tests
dotnet build MCManager.App -c Release -p:Platform=x64   # Windows only
```

### Desktop app (macOS)

`apps/macos/` holds a SwiftUI app (Swift 5.10, macOS 14+) built with SwiftPM, no Xcode project. It never reads MC Manager files: it talks to the local `/v1` API through the Unix socket `run/api.sock`, found by `MCMANAGER_RUN_DIR` or by the `WorkingDirectory` of the `io.github.scirr.mcmanager` LaunchAgent. It shows the server list (state, RAM), start/stop/restart/resume, the live console, the player lists (whitelist, ops, bans, kick), backups, mods, datapacks, world, scheduled tasks, settings and a server creation wizard. A paired remote MC Manager can be used too: the certificate fingerprint is pinned and compared in constant time, and the device token is kept in the macOS keychain. Texts follow the system language (English or French).

| Target | Role |
|---|---|
| `MCManagerKit` | Socket client, models, `ApiError`, observable view models (no UI) |
| `MCManagerApp` | SwiftUI window, FR/EN `Localizable.xcstrings` |
| `MCManagerKitTests` | XCTest on a fake transport |

```
cd apps/macos
swift build
swift test
swift run MCManagerApp
```

---

## 🖥️ CLI Commands

> Linux and Windows now share the same command surface. Every command accepts an optional target (a server name, a registry number, or nothing to use the active server). See the platform guides for the authoritative, up-to-date reference.

| Command | Description |
|---|---|
| `mc deploy` | Download a JAR and auto-configure a new server |
| `mc add` | Register an existing server folder |
| `mc configure` | Reconfigure an existing server |
| `mc` *(no args)* | Show the multi-server dashboard |
| `mc use <target>` | Set the active server |
| `mc remove <target>` | Unregister a server |
| `mc start` / `mc stop [--force]` | Start / stop the server (`--force` kills the process if RCON is unavailable) |
| `mc stop --reason <r> [--quiet]` | Stop for a stated reason (`sleep`, `update`, `maintenance`, `switch`) — Linux |
| `mc status [--json]` | Show server status (explicit state, RAM, uptime, players) — `--json` on Linux |
| `mc active` / `mc players` / `mc rcon "<cmd>"` | Scripting helpers: active server, players online, one RCON command — Linux |
| `mc config get\|set <key> [value]` | Read / change a setting everywhere it lives — Linux |
| `mc freeze` / `mc thaw` | Freeze the world for an external backup — Linux |
| `mc switch <target>` | Hand the active server's place (ports included) to another server — Linux |
| `mc sleep enable\|disable\|status` | Sleep when nobody plays, wake when a known player joins — Linux |
| `mc metrics serve` | Prometheus metrics of every server on `127.0.0.1:9225` — Linux |
| `mc status-page enable\|disable` | Static public status page regenerated by the service — Linux |
| `mc router enable\|disable\|status\|route\|default\|allow\|deny` | Several servers behind one port, routed by hostname — Linux |
| `mc datapack` / `mc mod` | Manage datapacks and mods (AutoModpack copy, quarantine) — Linux |
| `mc console` | Attach to the interactive RCON console |
| `mc logs` | Show recent server logs |
| `mc backup` | Manual ZIP backup |
| `mc backup list\|restore\|remote` | List, restore (server stopped) and send backups to sftp / S3 / restic — Linux |
| `mc alert add\|list\|remove\|test` | Alerts by e-mail, Telegram, ntfy, webhook or Discord, filtered per event — Linux |
| `mc open` / `mc resume` | Open the server folder / resume from maintenance |
| `mc announce` | Send the startup Discord webhook manually |
| `mc mode <schedule\|always\|maintenance>` | Switch the daemon operating mode |
| `mc schedule H M H M` | Set opening and closing time |
| `mc doctor` | Run non-destructive diagnostics |
| `mc language [fr\|en]` | Show or change the interface language |
| `mc update [--check\|--to X\|--rollback]` | Signed self-update, specific version, or rollback |
| `mc edit` | Edit `config.json` in `$EDITOR` |
| `mc image add\|rm` | Set or remove the server icon |
| `mc daemon <run\|start\|stop\|restart>` | Control the background service |

---

## ⚙️ How It Works

A background **daemon** runs continuously and checks the current time every 30 seconds:

```
┌─────────────────────────────────────────────────┐
│                  MC Manager Daemon               │
│                                                  │
│  Every 30s:                                      │
│  ┌──────────────┐     ┌──────────────────────┐   │
│  │ Scheduled?   │─YES─▶ Start server         │   │
│  └──────────────┘     │ Send Discord webhook  │   │
│         │             │                       │   │
│         NO            └──────────────────────┘   │
│         │                                         │
│  ┌──────▼───────┐     ┌──────────────────────┐   │
│  │ Closing time?│─YES─▶ Warn players (RCON)   │   │
│  └──────────────┘     │ Save & stop server    │   │
│                       │ Run backup            │   │
│                       │ Send Discord webhook  │   │
│                       └──────────────────────┘   │
└─────────────────────────────────────────────────┘
```

---

## 💬 Discord Webhooks

MC Manager sends rich Discord embeds on four events:

| Event | Trigger |
|---|---|
| 🟢 `start_automod` | Server opens with AutoModpack enabled |
| 🟢 `start_normal` | Server opens normally |
| 🔴 `stop` | Manual stop via `mc stop` |
| 🔴 `fermeture_nuit` | Automatic nightly shutdown |

All webhook content lives in `webhook_templates.json` — **no hardcoded text in Python**.  
Webhooks are silenced during maintenance mode by design (no players connected).

---

## 🔧 Platform Differences

| Feature | Linux | Windows |
|---|---|---|
| Background process | `subprocess` + PID file | `subprocess` + PID file |
| CPU affinity | `os.sched_setaffinity` | `SetProcessAffinityMask` (WinAPI) |
| Process detection | PID file + `/proc` | `tasklist` + PID file |
| Force kill | `os.killpg` (SIGKILL) | `taskkill /F /PID` |
| File backup | `shutil` + `zipfile` | `shutil` + `zipfile` |
| HTTP requests | `urllib` (built-in) | `urllib` (built-in) |
| RCON | native Python socket | native Python socket |
| Daemon | systemd service | NSSM Windows service |
| Firewall | `ufw` or `firewalld` | `netsh advfirewall` |
| Global command | `mc` in `/usr/local/bin/` | `mc.bat` in `System32` |
| Server console | interactive RCON (termios) | interactive RCON |
| Icon file picker | zenity / kdialog | `tkinter` |

---

## 📋 Requirements

### Linux
- [Python 3.10+](https://www.python.org/downloads/)
- [Java 21](https://adoptium.net/temurin/releases/?version=21) (Temurin recommended)
- systemd (standard on Fedora and most distributions)
- Optional: `ufw` or `firewalld` for automatic port rules, `Pillow` for server-icon resizing, `zenity`/`kdialog` for the graphical icon picker
- No external runtime dependencies — RCON, HTTP and backups use the Python standard library

### Windows
- [Python 3.10+](https://www.python.org/downloads/) (check **"Add Python to PATH"** during install)
- [Java 21](https://adoptium.net/temurin/releases/?version=21) (Temurin recommended)
- NSSM (downloaded automatically by `install.bat`)

---

## 📄 License

Mozilla Public License 2.0 (MPL-2.0) — free to use, including commercially; if you distribute a modified version of MC Manager's files, those files must stay under the MPL-2.0 and their source must be available. See [LICENSE](LICENSE). Versions up to 2.5.0 were released under the MIT license.
