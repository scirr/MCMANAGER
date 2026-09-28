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
- **Sleep mode** — Frees the server's memory when nobody plays; the server stays listed and wakes when a known player joins (Linux)
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
├── Linux/              # Fedora / Linux version (systemd service, multi-server)
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
│   ├── mc_sleep.py     # sleep listener (Minecraft status/login protocol)
│   ├── mc_ipc.py       # request channel CLI -> daemon
│   ├── mc_setup.py     # Java check
│   ├── install.sh / uninstall.sh
│   ├── webhook_templates.json
│   └── README_Linux.md
│
└── Windows/            # Windows version (NSSM service, multi-server)
    ├── mc_cli.py
    ├── mc_core.py
    ├── mc_config.py
    ├── mc_servers.py
    ├── mc_deploy.py
    ├── mc_daemon.py
    ├── mc_doctor.py
    ├── mc_firewall.py
    ├── mc_image.py
    ├── mc_lang.py
    ├── mc_validate.py
    ├── mc_setup.py
    ├── install.bat
    ├── uninstall.bat
    ├── webhook_templates.json
    └── README_Windows.md
```

---

## 🚀 Quick Start

### Linux

```bash
cd Linux/
chmod +x install.sh
sudo ./install.sh
mc deploy
```

### Windows

Right-click `install.bat` → **Run as administrator**, then open a new terminal:

```
mc deploy
```

> Both platforms share the same multi-server workflow (`mc deploy`/`mc add`/`mc configure`, dashboard, modes...). See the **[Linux guide](Linux/README_Linux.md)** or **[Windows guide](Windows/README_Windows.md)** for the full walkthrough.

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
| `mc datapack` / `mc mod` | Manage datapacks and mods (AutoModpack copy, quarantine) — Linux |
| `mc console` | Attach to the interactive RCON console |
| `mc logs` | Show recent server logs |
| `mc backup` | Manual ZIP backup |
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

MIT — Free to use, modify and distribute.
