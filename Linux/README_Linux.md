# MC Manager — Linux

Automatic Minecraft server management tool for Linux (Fedora and other systemd distributions), driven by a systemd service and a global `mc` command. Manages **multiple servers in parallel**, each with its own configuration.

---

## Requirements

- Linux with systemd (Fedora, Ubuntu, Debian, Arch…)
- Python 3.10+
- [Java 21](https://adoptium.net/temurin/releases/?version=21) (`sudo dnf install java-21-openjdk-headless` on Fedora)
- [Pillow](https://python-pillow.org/) (optional, only for `mc image` — installed by `install.sh`)
- firewalld (optional, for automatic firewall management — pre-installed on Fedora)

> No `screen`, `curl`, `zip` or `mcrcon` binary needed: process management, HTTP and the RCON protocol are handled natively in Python.

---

## Installation

1. Place the MC Manager files in a folder (e.g. `~/MCMANAGER/Linux`) — this is the **program** folder, not the Minecraft server folder (servers live elsewhere, see [Multi-server](#multi-server)).
2. Run the installer as root:

```bash
chmod +x install.sh
sudo ./install.sh
```

3. Open a **new** terminal and create your first server:

```
mc deploy
```

> The installer installs the `mc_manager` systemd service and the `mc` command in `/usr/local/bin/`. `mc deploy` downloads and configures a fresh Minecraft server — see [Three ways to get a server](#three-ways-to-get-a-server-deploy--add--configure) below. You can repeat this to manage multiple servers.

---

## Getting started

Before diving into the detailed documentation below, here is the shortest path from a fresh install to a server your friends can connect to:

```
mc deploy     # 1. create your first server (Paper or Fabric if unsure — the most common)
mc start      # 2. start it
mc status     # 3. verify it shows "ONLINE"
mc doctor     # 4. verify everything is correctly configured (Java, RCON, firewall, service);
              #    fix any reported issue before inviting people
```

Then share your address with friends — see [Making the server accessible](#making-the-server-accessible-networking) below depending on whether they are on your local network or the internet. Finish with `mc stop` when done (or leave it running, see [Modes](#modes-schedule--always-on--maintenance)).

---

## Three ways to get a server: `deploy` / `add` / `configure`

| | `mc deploy` | `mc add [path]` | `mc configure [target]` |
|---|---|---|---|
| Purpose | Create a **new** server | Register an **existing** server | Reconfigure an **already registered** server |
| Downloads the jar? | Yes (Vanilla/Paper/Fabric/Forge/NeoForge) | No | No |
| Asks for type/version? | Yes (you choose) | No (auto-detects jar, best-effort) | No |
| Creates a registry entry? | Yes, becomes the active server | Yes, becomes the active server | No — requires an existing entry |
| Guarantees RCON + offers AutoModpack? | Yes | Yes | Yes (can "repair" an old server) |
| Can fix name/folder/port after the fact? | — | — | Yes (via "Base" section) |

- **You want a brand new server** (e.g. Fabric 1.21.4) → `mc deploy`. Downloads the jar, accepts the EULA, configures RCON (mandatory) and offers AutoModpack if available.
- **You already have a server** (created before MC Manager, copied from another machine…) → `mc add`. No jar download: just registration, then the exact same RCON/AutoModpack checks as `deploy`.
- **The server is already registered and you want to change its settings** (name, RAM, schedule, Discord webhook, or fix missing RCON) → `mc configure [target]`. Goes through all configuration sections; has no destructive effect if everything is already in place.

---

## Multi-server

Each server has a **number** (`[1]`, `[2]`…) in addition to its name, for quick reference. A single daemon (a single systemd service) supervises all registered servers.

Running `mc` alone (no argument) displays a dashboard: one box per server (status, mode, version/loader, folder, port), with a summary of the main commands below. `mc status` displays only that dashboard (useful in scripts), `mc status <name/number>` filters to a single server.

**Targeting a server:** every command that acts on a server accepts its name or number as the last argument (`mc stop survival`, `mc stop 2`). If omitted, the command acts on the **active server** — the one marked `ACTIVE` in the dashboard, changeable with `mc use <name/number>`.

```
mc deploy              # deploys a new server, which automatically becomes active
mc status              # check the list and numbers
mc use survival        # switch to the "survival" server (or: mc use 1)
mc start               # start the active server (target omitted -> "survival")
mc stop creative       # stop "creative" without changing the active server
```

When a command acts on the active server without an explicit target, a line `[i] Target: <name> (<number>)` reminds you which one was used.

### Default data location

By default, `mc deploy`/`mc add` suggest:
- `~/MCManager/Servers/<server-name>/Server/` — server files (jar, world, mods…)
- `~/MCManager/Servers/<server-name>/Backup/` — its backups

Always changeable to any path (another drive, an existing folder…) at the prompt.

### Sharing servers across a dual-boot (Windows ⇄ Linux)

If you dual-boot and keep a disk shared between Windows and Linux, you can have **the same servers appear on both** — no re-registering per OS. Point both installs at one shared folder with the `MCMANAGER_DATA_DIR` environment variable:

- **Linux** — add to `~/.bashrc` (or `~/.profile`):
  ```bash
  export MCMANAGER_DATA_DIR="/run/media/you/SharedDisk/MCManagerData"
  ```
- **Windows** — set a user environment variable `MCMANAGER_DATA_DIR` to the *same physical folder* via its Windows path, e.g. `E:\MCManagerData`.

When set, the registry (`servers.json`) and new servers live under that folder, and each server's path is stored **relative to it** — so the one `servers.json` resolves correctly on either OS. Deploy a server once (on either OS, into the shared `Servers/` folder) and it shows up in `mc` on both. If you already installed the daemon, re-run the installer so the systemd service picks up the variable.

> Never run the same server from both OSes at once (world corruption). In dual-boot that never happens — only one OS is booted at a time.

### Open a server folder (`mc open`)

```
mc open [target]
```

Opens the server folder in your file manager (via `xdg-open`) — handy for browsing files, mods, or Minecraft logs without retyping the path.

---

## Making the server accessible (networking)

Having the server "ONLINE" is not always enough for other players to connect — it depends on where they are.

### Firewall (managed automatically via firewalld)

Fedora blocks unsolicited incoming connections by default. **`mc deploy`/`mc add`/`mc configure` automatically open** the configured game port in firewalld (permanent rule). The RCON port is **never exposed**.

If automatic opening fails (not run as root, firewalld inactive…), a message provides the exact command to paste into a terminal:
```bash
sudo firewall-cmd --permanent --add-port=25565/tcp && sudo firewall-cmd --reload
```
(replace `25565` with your actual port). `mc doctor` checks this rule for you — no need to remember these commands day-to-day.

### Players on your local network (LAN)

Give them your local IP address and port. To find it:
```bash
ip -4 addr
```
(look for an address like `192.168.x.x`). Example: `192.168.1.42:25565`.

### Players on the internet (outside your network)

Two extra steps beyond the firewall, on your **router** side — MC Manager cannot do this for you:
1. Open your router's admin page (often `192.168.1.1` or `192.168.0.1`) and look for a "Port forwarding" section.
2. Forward the configured TCP port (e.g. `25565`) to this machine's local IP address.

Your friends connect using your **public IP address** (visible on your router's home page). For a stable address, use any free dynamic-DNS provider (DuckDNS, No-IP, …), point it to your public IP on their site, and set it as `domaine` (see [Configuration](#configuration-configjson)).

### Still not working?

```
mc doctor [target]
```
Diagnoses in one command: Java, RCON, firewall rule, `mc_manager` service, and port conflict — with the exact fix command for each issue.

---

## Updating MC Manager

1. Download the latest ZIP from the [Releases page](https://github.com/scirr/MCMANAGER/releases).
2. Stop the daemon if it is running:
   ```
   mc daemon stop
   ```
3. Extract the ZIP and copy all `.py` files, `install.sh`, `uninstall.sh`, and `webhook_templates.json` from the archive into your existing MC Manager folder, overwriting the old files.
4. Restart the daemon:
   ```
   mc daemon start
   ```

> Your server files, configs, and backups are stored outside the program folder and are never affected by an update.

`mc update` replaces the program files and restarts the daemon, but never the systemd unit. When a release changes the unit, `mc update` (and `mc doctor`) says so: re-run `sudo ./install.sh` from the MC Manager folder — servers and settings are kept.

---

## Uninstallation

```bash
sudo ./uninstall.sh
```

The script:
1. Stops all currently online Minecraft servers.
2. Removes the `mc_manager` systemd service and the global `mc` command.
3. Cleans up files generated by the program (`logs/`, `__pycache__/`, `mc`).

> **Your Minecraft server files (worlds, mods, backups) are never deleted.** The script displays the location of each server at the end.

---

## Deploying a new server (`mc deploy`)

```
mc deploy
```

Steps:
1. **Server name and description** — asked first (used to suggest a default folder).
2. **Installation folder** — default `~/MCManager/Servers/<name-slug>/Server/`, editable. Detects if a server already exists inside and asks for confirmation before overwriting.
3. **Server type** — Vanilla, Paper, Fabric, Forge or NeoForge.
4. **Minecraft version** — lists the 15 latest releases (Mojang API) or free input.
5. **Port** — checked against already registered servers; on collision, another value is immediately requested.
6. **Download / installation** — fetches the correct JAR (or runs the official installer for Forge/NeoForge), accepts `eula.txt` automatically.
7. **RCON (mandatory)** — RCON lets MC Manager send commands to the server and verify it has actually stopped. Without it, `mc stop`, backups and the interactive console do not work. Sets up password/port — the RCON protocol is spoken natively by MC Manager, no external binary is downloaded. Not skippable.
8. **`server.properties`** — generated with the port, MOTD and RCON settings; if the file already exists, only missing keys are added (never overwritten).
9. **AutoModpack (optional, if available)** — see [AutoModpack availability](#automodpack-availability) below.
10. **Backup folder**.
11. **Registration** — the server is added to the registry and becomes the active server.
12. **Flow into advanced options** — directly offers the schedule / CPU·RAM / domain·Discord sections of `mc configure`, without repeating already-answered questions. Saying no leaves those settings at defaults, adjustable later with `mc configure`.

---

## Adding an existing server (`mc add`)

To register a Minecraft server you already have — created before MC Manager, copied from another machine, etc. — without downloading anything:

```
mc add
```

Steps:
1. **Existing server folder** — verifies it looks like a Minecraft server (jar, `eula.txt` or `server.properties` present); warns otherwise.
2. **Name and description** — default name suggested from the folder name.
3. **JAR file** — automatically detected among the `.jar` files in the folder.
4. **Loader and version** — auto-detected from the jar name (best-effort). A Fabric jar never includes the MC version in its name, so the version often shows as `?` in the dashboard until corrected via `mc edit config`.
5. **Port** — pre-filled from `server.properties` if present, otherwise `25565`; collision-checked.
6. **Backup folder**.
7. **Registration** — becomes the active server.
8. **RCON + AutoModpack** — same checks as `mc deploy`.
9. **Flow into advanced options** — same as `mc deploy`.

---

## Reconfiguring a server (`mc configure`)

```
mc configure [target]
```

Goes through **all** configuration sections of an already registered server:
1. **Base** — name, description, folder, backup folder, port.
2. **RCON + AutoModpack** — re-runs the same check as `deploy`/`add`; asks nothing if already configured, useful to repair a server that never had RCON.
3. **Schedule & backups**.
4. **Performance** (CPU, RAM, JAR).
5. **Integrations** (domain, Discord webhook, AutoModpack on/off).

### AutoModpack availability

AutoModpack requires a mod loader (Fabric, Forge or NeoForge) — it is never offered for Vanilla or Paper. MC Manager queries Modrinth for the exact (loader, Minecraft version) pair:
- **No build available for this version** → a message explains it and skips the step.
- **Build available** → the exact version found is displayed before offering installation.

### AutoModpack key — fully automatic detection

AutoModpack generates its own self-signed certificate on first server start and computes a SHA-256 fingerprint. This fingerprint is **the same for all players and never changes** — it appears in the Discord webhook (`{cle}`) and players confirm it once in-game on first connection.

MC Manager reads this certificate automatically at every `mc start` — **no manual input needed** at any point.

> **Note:** the certificate only exists after the server's first real start. The very first `mc start` announcement will not contain the fingerprint; from the second start onward it appears automatically.

---

## Available commands

Unless otherwise noted, `[target]` is optional (server name or number) and falls back to the active server if omitted.

| Command | Description |
|---|---|
| `mc` | Dashboard (all servers) + command summary |
| `mc help` | Full command list |
| `mc version` | Show the installed MC Manager version |
| `mc update` | Download and apply the latest version |
| `mc language [fr\|en]` | Show or change the interface language |
| `mc deploy` | Deploy a new server (Vanilla/Paper/Fabric/Forge/NeoForge) |
| `mc add [path]` | Register an existing server without downloading anything |
| `mc status [target]` | Dashboard; filtered to a single server if `target` is given. Shows the state, and when running: PID, real RAM (RSS), uptime, players, next backup |
| `mc status [target] --json` | Same information as JSON, for scripts (see [Scripting](#scripting-json-api)) |
| `mc active [--path\|--json]` | Name of the active server (`--path`: its folder; `--json`: its full state) |
| `mc players [target] [--json]` | Players online (vanilla, Paper and Essentials-style `list` replies are all understood) |
| `mc rcon "<command>" [target]` | Send one command to the server and print its reply (RCON password read from the config) |
| `mc config get [<key>] [target]` | Print one setting (or the whole `config.json` as JSON) |
| `mc config set <key> <value> [target]` | Change a setting and propagate it everywhere it lives: `config.json`, `servers.json`, `server.properties`, firewall |
| `mc freeze [target] [--max 1h] [-- <command>]` | Freeze the world for an external backup (`save-off` + `save-all flush`); with `-- <command>`, runs it and always thaws afterwards |
| `mc thaw [target]` | Re-enable world saving |
| `mc use <name/number>` | Change the active server (argument required) |
| `mc configure [target]` | Reconfigure an already registered server (also guarantees RCON/AutoModpack) |
| `mc remove <name/number>` | Unregister a server from the registry (deletes NO files) |
| `mc doctor [target]` | Full diagnostic (machine: service, systemd unit, Java, zombie JVMs; per server: config.json, server.properties consistency, RCON, firewall, port holder, cgroup, swap) — **all servers if `target` omitted** |
| `mc open [target]` | Open the server folder in the file manager |
| `mc start [target]` | Start the server |
| `mc stop [target]` | Stop the server gracefully and wait until its process has really exited (switches to maintenance mode) |
| `mc stop --force [target]` | Kill the server's processes (SIGKILL) when RCON is unavailable |
| `mc stop [target] --reason <r> [--quiet]` | Stop and record why: `user` (default), `sleep`, `update`, `maintenance`, `switch`. Picks the matching Discord announcement and the state shown by `mc status`; `--quiet` sends no announcement |
| `mc mode <value> [target]` | Change mode: `schedule`, `always-on` or `maintenance` |
| `mc resume [target]` | Exit maintenance mode (automatically resumes the previous mode) |
| `mc schedule H M H M [target]` | Set open/close schedule (switches to `schedule` mode) |
| `mc console [target]` | Interactive RCON console with live log streaming (type `exit` to quit) |
| `mc announce [target]` | Manually send the opening announcement to Discord |
| `mc fingerprint [target]` | Show the server's AutoModpack key (fingerprint) |
| `mc backup [target]` | Run a manual ZIP backup |
| `mc image add <path> [target]` | Set the server icon (64×64 PNG, converted automatically) |
| `mc image rm [target]` | Remove the server icon |
| `mc edit config [target]` | Edit `config.json` in `$EDITOR` (default: nano) |
| `mc edit webhooks [target]` | Edit `webhooks.json` in `$EDITOR` (default: nano) |
| `mc logs [target]` | Show the last 30 log lines (filtered to `target` if given) |
| `mc daemon run` | Run the daemon in the foreground (debug) |
| `mc daemon start/stop/restart` | Control the systemd service |

> `mc doctor` with no target diagnoses **all registered servers** — all other commands fall back to the active server.

### How `mc stop` stops a server

1. warns the players, then `save-all flush` — from here on the world is on disk;
2. sends `stop` over RCON and waits for the process to **really** exit (up to `stop_timeout` seconds, 120 by default). The game port is released a moment before the JVM ends, so waiting for the port alone is not enough;
3. if the server hangs in its shutdown: `SIGTERM`, then `SIGKILL` 30 s later. No data is lost — the world was flushed in step 1.

A server's processes are identified by their PID file **and** by "java running in the server folder" — never by the port alone. Another program holding the port (another server, a proxy) is shown as `port 25565 held by <program> (PID)` and is never adopted or killed.

### Exit codes

Every command ends with a documented exit code, so scripts can rely on it:

| Code | Meaning |
|---|---|
| `0` | Success — or the requested state already holds (`mc start` on a running server, `mc stop` on a stopped one) |
| `1` | The command failed (message printed says why and what to do) |
| `2` | Invalid command line |
| `3` | No server configured, unknown server name/number, or server folder missing |
| `130` | Interrupted (Ctrl+C) |

Output is plain text (no colour codes) when it is not a terminal, or when `NO_COLOR` is set. MC Manager never shows a raw Python traceback: an unexpected error is summarised in one line and its details are written to `logs/cli-error.log` (set `MCMANAGER_DEBUG=1` to see the traceback instead).

### Examples

```
mc deploy                       # create a new server
mc add ~/Minecraft/OldServer    # register an existing server
mc configure survival           # fix/complete the settings of "survival"
mc doctor                       # diagnose all servers (Java, RCON, firewall, service)
mc remove test                  # unregister "test" from the registry (files kept)
mc schedule 20 0 0 30           # open at 20:00, close at 00:30 (active server)
mc mode maintenance creative    # put "creative" in maintenance without changing the active server
mc resume                       # take the active server out of maintenance
mc stop survival                # stop "survival" directly, without selecting it first
```

---

## Server states

`mc status` (and the `state` field of `mc status --json`) shows one explicit state per server:

| State | Meaning |
|---|---|
| `running` | The server process is alive and the game port accepts connections |
| `starting` | The process is alive, the game port is not listening yet |
| `stopped` | Not running; the daemon will start it (24/7 mode, or within opening hours) |
| `closed` | Not running; schedule mode, outside opening hours |
| `stopped-by-user` | Stopped with `mc stop` (or `--reason user`); the daemon leaves it alone |
| `sleeping` | Stopped with `mc stop --reason sleep` |
| `maintenance` | In maintenance for another reason (`mc mode maintenance`, `--reason update/maintenance/switch`) |

The last three all rely on `mode_maintenance = 1` in `config.json` — still the one and only switch that makes the daemon leave a server alone. The reason is stored next to it in `stop_reason`, and `mc resume` clears both.

---

## Scripting (JSON API)

Third-party scripts should use these commands rather than read MC Manager's files: the commands keep working when the files evolve.

| Need | Command |
|---|---|
| Active server name / folder | `mc active` / `mc active --path` |
| State of every server | `mc status --json` |
| State of one server | `mc status <name> --json` or `mc active --json` |
| Players online | `mc players --json` |
| Run a Minecraft command | `mc rcon "say hello"` |
| Read a setting | `mc config get port` |
| Change a port consistently | `mc config set port 25566` |
| Stop without announcing, for a known reason | `mc stop --reason sleep --quiet` |
| Consistent external backup | `mc freeze -- restic backup /path/to/world` |

JSON documents carry `"schema": 1`. Within a schema version, fields may be added, never renamed or removed. Human messages always go to stderr or are absent in `--json` mode, so stdout is pure JSON. On an error, `--json` commands print `{"schema": 1, "error": {"code": ...}}` and exit with the codes documented above.

Example (`mc status --json`, abridged):

```json
{
  "schema": 1,
  "active": "survival",
  "servers": [
    {
      "name": "survival", "id": 1, "active": true, "path": "/home/user/MCManager/Servers/survival/Server",
      "state": "running", "error": null, "mode": "always-on", "maintenance": false, "stop_reason": null,
      "port": 25565, "rcon_port": 25575, "loader": "Fabric", "version": "1.21.1", "frozen": false,
      "pid": 12345, "uptime_s": 7260, "rss_kb": 6291456, "swap_kb": 0,
      "cgroup": "/system.slice/mc_manager.service", "port_holder": null
    }
  ]
}
```

A server whose folder is missing or whose `config.json` is unreadable has `"state": null` and an `"error"` object (`folder_missing`, `config_unreadable`).

### Freezing the world for an external backup

```bash
mc freeze -- restic backup ~/MCManager/Servers/survival/Server/world
```

`mc freeze` sends `save-off` then `save-all flush`: once it returns, the world on disk is complete and no longer changes. With `-- <command>`, MC Manager runs the command and **always** thaws afterwards — even if the command fails or is interrupted — then exits with the command's own code. Without it, call `mc thaw` yourself (from a `trap ... EXIT` in shell, never as a plain last line). Either way, a freeze is exclusive (a second `mc freeze` fails) and has a deadline (`--max`, 1 hour by default): if its owner dies, the daemon thaws the world automatically when it expires. MC Manager's own backups never lift a freeze they did not set.

---

## Modes (schedule / always-on / maintenance)

A server is always in one of these three modes, displayed in the dashboard (`mc status`):

| Mode | Meaning | How to activate |
|---|---|---|
| `schedule` | Starts/stops automatically at configured hours every day | `mc mode schedule [target]` or `mc schedule H M H M [target]` |
| `always-on` | Runs continuously, restarted by the daemon if it crashes | `mc mode always-on [target]` |
| `maintenance` | Suspended: the daemon ignores this server, Discord webhooks are silent | `mc mode maintenance [target]` or `mc stop [target]` |

`mc resume [target]` exits maintenance and **automatically restores the previous mode** (schedule or always-on) — no need to specify it again.

> **`mc resume` also brings the server back up.** Leaving maintenance hands the server back to the daemon, which starts it on its next tick: within ~30 seconds in `always-on` mode, or at the next opening time in `schedule` mode. **Do not chain `mc start` after it** — the server is already coming up, and a second launch is refused (the port is taken) to avoid a duplicate instance on a locked world.

`mc mode always-on` clears existing schedule fields; `mc mode schedule` keeps them if they exist, otherwise applies defaults (20:00 → 03:00, adjustable with `mc schedule`).

---

## Daemon (systemd service)

The daemon runs as a systemd service (`mc_manager`) and starts automatically with the system. It loops every 30 seconds over all registered servers.

It automatically manages, for each server:
- Starting at the configured open time (`schedule` mode) or restarting if it crashes (`always-on` mode)
- Mid-session backup, or noon/midnight backup in `always-on` mode
- Shutdown warnings (10, 5, 2, 1 min) in `schedule` mode
- Nightly shutdown and backup in `schedule` mode
- Sending Discord webhooks (silent in `maintenance` mode)

```
mc daemon start      # Start the service
mc daemon stop       # Stop the service
mc daemon restart    # Restart the service
mc daemon run        # Foreground, for debugging (Ctrl+C to quit)
```

```bash
# Native systemd service queries
systemctl status mc_manager
journalctl -u mc_manager -f
```

### Logs (`logs/`)

| File | Content |
|---|---|
| `logs/daemon.log` | Daemon log (INFO), all lines prefixed `[server_name]` |
| `journalctl -u mc_manager` | Errors/tracebacks from the service |

---

## Configuration (`config.json`)

Each server has its own `config.json` in its server folder. `mc edit config [target]` opens it.

| Key | Description | Example |
|---|---|---|
| `nom_serveur` | Name displayed in Discord | `"survival"` |
| `dossier_serveur` | Absolute path to the server | `"/home/user/MCManager/Servers/survival/Server"` |
| `dossier_backup` | Backup destination folder | `"/home/user/MCManager/Servers/survival/Backup"` |
| `port` | Minecraft port | `25565` |
| `loader` | Server type (displayed in dashboard) | `"Fabric"` |
| `mc_version` | Minecraft version (displayed in dashboard) | `"1.21.4"` |
| `always_on` | Always-on mode (1) or schedule (0) — set via `mc mode` | `0` |
| `heure_ouverture` | Open hour (schedule mode) | `20` |
| `minute_ouverture` | Open minute | `0` |
| `heure_fermeture` | Close hour | `0` |
| `minute_fermeture` | Close minute | `30` |
| `cpu_affinity` | CPU cores assigned to the server | `"8-15"` |
| `ram_allocation` | RAM allocated to Java (Forge/NeoForge: written into `user_jvm_args.txt` on each start) | `"8G"` |
| `jar_name` | JAR file name (or `run.sh` for Forge/NeoForge) | `"fabric-server-launch.jar"` |
| `rcon_port` | RCON port | `25575` |
| `mcrcon_pass` | RCON password | `"password"` |
| `domaine` | Server domain/link shown to players (optional) | `"play.myserver.com"` |
| `webhook_url` | Discord Webhook URL | `"https://discord.com/api/webhooks/..."` |
| `backup_retention_days` | Days to keep daily backup folders (0 = unlimited) | `30` |
| `activer_automodpack` | AutoModpack enabled (1) or not (0) | `1` |
| `cle_automodpack` | AutoModpack certificate fingerprint — **detected automatically, never enter manually** | `"403e6792a7..."` |
| `mode_maintenance` | Maintenance active (1) or not (0) — set via `mc mode maintenance` / `mc resume` | `0` |
| `stop_timeout` | Seconds `mc stop` waits for a clean shutdown before `SIGTERM` (optional) | `120` |
| `stop_reason` | Why the server was stopped (`user`, `sleep`, `update`, `maintenance`, `switch`) — set by `mc stop --reason`, cleared by `mc resume` | `"sleep"` |

`config.json` is the **single source of truth** for the ports and RCON: on every start, `server-port`, `enable-rcon`, `rcon.port` and `rcon.password` in `server.properties` (and the ports cached in `servers.json`) are brought in line with it, and each correction is printed. JSON files saved with a UTF-8 BOM (Windows editors, PowerShell) are read normally. An unreadable `config.json` only affects its own server: `mc status` and `mc doctor` show the error and how to fix it, and the daemon keeps supervising the other servers.

---

## Discord Webhooks (`webhooks.json`)

Each server has its own `webhooks.json` — two servers can have different Discord messages. `mc edit webhooks [target]` opens it.

Four events trigger a Discord message:

| Key | Trigger |
|---|---|
| `start_automod` | Start with AutoModpack enabled |
| `start_normal` | Start without AutoModpack |
| `stop` | Manual stop (`mc stop`, `--reason user`) |
| `stop_sleep` | `mc stop --reason sleep` |
| `stop_update` | `mc stop --reason update` |
| `stop_maintenance` | `mc stop --reason maintenance` |
| `stop_switch` | `mc stop --reason switch` |
| `fermeture_nuit` | Automatic nightly shutdown |

Templates added by a new version are appended to each server's `webhooks.json` automatically; your edits to the existing ones are kept. `mc stop --quiet` sends nothing.

Each webhook supports the fields:
- `title` — Embed title (supports `{nom}`, `{cle}`)
- `description` — Message body
- `color` — Bar color (decimal integer)
- `show_ip` — Show the server's IP address (`true`/`false`)
- `show_version` — Show the loader/version field (`true`/`false`)

> Webhooks are **silent in maintenance mode** — with one exception: leaving maintenance with `mc resume` is a reopening, so the start the daemon then performs **is announced**. Routine restarts (a crashed server brought back up in `always-on` mode) stay silent, otherwise a flapping server would post every 30 seconds.

---

## Server Icon (`mc image`)

Minecraft displays a 64×64 PNG icon next to your server in the multiplayer list. MC Manager handles resizing and conversion automatically — any common image format works (PNG, JPG, WEBP…).

```
mc image add <path> [target]   # set the icon
mc image rm [target]           # remove the icon
```

**No path given:** running `mc image add` without an argument opens a file picker (tkinter, or zenity/kdialog on GNOME/KDE) — browse to your image and confirm.

The source image is resized to 64×64 pixels using high-quality Lanczos resampling, converted to RGBA PNG, and saved as `server-icon.png` in the server folder. The change takes effect on the next server start.

> Requires [Pillow](https://python-pillow.org/) — installed automatically by `install.sh`.

---

## CPU Affinity

Applied natively via `sched_setaffinity` (equivalent of `taskset`). Format in `config.json`:
- `"8-15"` → cores 8 to 15
- `"0-7"` → cores 0 to 7
- `"0,2,4"` → specific cores

---

## Backups

Backups are created in `backup_folder/YYYY-MM-DD/backup_TYPE_DATETIME.zip`.

Backup types:
- `manuelle` → `mc backup`
- `milieu` → Automatic mid-session (schedule mode)
- `fermeture` → Nightly shutdown (schedule mode)
- `midi` / `minuit` → Always-on mode

The world is safely frozen with `save-off` during the backup (with a 10 s flush delay), then `save-on` is sent when done. All world dimensions (`world`, `world_nether`, `world_the_end` — following `level-name`) are included.

**Retention:** set `backup_retention_days` in `config.json` (also asked by `mc configure`) to automatically delete daily backup folders older than N days after each backup. `0` (default) keeps everything forever.

---

## Automatic updates

MC Manager checks the latest published release in the background (throttled to once every few hours, silent if offline). When a newer version exists, every `mc` command shows a discreet line:

```
Update available: 2.3.1 — run 'mc update'
```

Run `mc update` to download and apply it. It replaces only the program files — your servers, `servers.json`, configs, backups and chosen language are never touched. The daemon is restarted automatically (run `sudo mc daemon restart` if it could not).

## Language (FR / EN)

MC Manager ships as a **single bilingual build**. On the **first `mc` command** it asks you to choose French or English; the choice is saved (in `language.txt`, next to the app) and used from then on. Change it anytime:

```
mc language        # show the current language
mc language en     # switch to English
mc language fr     # switch to French
```

## RCON Console (`mc console`)

`mc console [target]` opens an interactive RCON session directly in the terminal, with the server log streamed live above your prompt:

```
> list
> say Hello everyone
> time set day
> exit
```

> If RCON is unreachable, the console falls back to read-only log streaming.
