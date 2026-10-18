# MC Manager — Windows

Automatic Minecraft server management tool for Windows, driven by a Windows service (NSSM) and a global `mc` command. The commands are the same as on Linux: both versions are built from the same code. Manages **multiple servers in parallel**, each with its own configuration.

---

## Requirements

- Windows 10/11
- [Python 3.10+](https://www.python.org/downloads/) — check **"Add Python to PATH"** during installation
- [Java 21](https://adoptium.net/temurin/releases/?version=21) (Temurin recommended)
- Internet connection (NSSM downloaded automatically)

---

## Installation

1. Place the MC Manager files in a folder (e.g. `D:\Code\MCMANAGER\Windows`) — this is the **program** folder, not the Minecraft server folder (servers live elsewhere, see [Multi-server](#multi-server)).
2. Right-click `install.bat` → **Run as administrator**.
3. Open a **new** terminal and create your first server:

```
mc deploy
```

> The installer downloads NSSM, installs the `MCManagerDaemon` Windows service and the `mc` command in `C:\Windows\System32\`. `mc deploy` downloads and configures a fresh Minecraft server — see [Three ways to get a server](#three-ways-to-get-a-server-deploy--add--configure) below. You can repeat this to manage multiple servers.

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
- **You already have a server** (created before MC Manager, copied from another PC…) → `mc add`. No jar download: just registration, then the exact same RCON/AutoModpack checks as `deploy`.
- **The server is already registered and you want to change its settings** (name, RAM, schedule, Discord webhook, or fix missing RCON) → `mc configure [target]`. Goes through all configuration sections; has no destructive effect if everything is already in place.

---

## Multi-server

Each server has a **number** (`[1]`, `[2]`…) in addition to its name, for quick reference. A single daemon (a single Windows service) supervises all registered servers.

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
- `C:\ProgramData\MCManager\Servers\<server-name>\Server\` — server files (jar, world, mods…)
- `C:\ProgramData\MCManager\Servers\<server-name>\Backup\` — its backups

Always changeable to any path (another drive, an existing folder…) at the prompt.

### Open a server folder (`mc open`)

```
mc open [target]
```

Opens the server folder in Windows Explorer — handy for browsing files, mods, or Minecraft logs without retyping the path.

---

## Making the server accessible (networking)

Having the server "ONLINE" is not always enough for other players to connect — it depends on where they are.

### Windows Firewall (mandatory, managed automatically)

Windows blocks unsolicited incoming connections by default. **`mc deploy`/`mc add`/`mc configure` automatically create** a Windows firewall rule for the configured game port. The RCON port is **never exposed**.

If automatic creation fails (terminal not run as administrator, restrictive group policy…), a message provides the exact command to paste into an **administrator** terminal:
```powershell
netsh advfirewall firewall add rule name="MCManager - Port 25565" dir=in action=allow protocol=TCP localport=25565
```
(replace `25565` with your actual port). `mc doctor` checks this rule for you — no need to remember these commands day-to-day.

### Players on your local network (LAN)

Give them your local IP address and port. To find it:
```powershell
ipconfig
```
(look for `IPv4 Address`, usually `192.168.x.x`). Example: `192.168.1.42:25565`.

### Players on the internet (outside your network)

Two extra steps beyond the Windows firewall, on your **router** side — MC Manager cannot do this for you:
1. Open your router's admin page (often `192.168.1.1` or `192.168.0.1`) and look for a "Port forwarding" section.
2. Forward the configured TCP port (e.g. `25565`) to this PC's local IP address.

Your friends connect using your **public IP address** (visible on your router's home page). For a stable address, use any free dynamic-DNS provider (DuckDNS, No-IP, …), point it to your public IP on their site, and set it as `domaine` (see [Configuration](#configuration-configjson)).

### Still not working?

```
mc doctor [target]
```
Diagnoses in one command: Java, RCON, firewall rule, `MCManagerDaemon` service, and port conflict — with the exact fix command for each issue.

---

## Updating MC Manager

```
mc update              # install the latest release
mc update --check      # only check (add --json for scripts)
mc update --to 2.6.0   # install a specific version, older ones included
mc update --rollback   # go back to the version installed before the last update
```

Every release is **signed**: `mc update` downloads the package with `SHA256SUMS` and its Ed25519 signature `SHA256SUMS.sig`, checks the signature against the key built into MC Manager, then the package hash, and refuses, changing nothing, at the slightest mismatch. Before installing, the current version is kept in `previous\`, which `--rollback` puts back (and a second `--rollback` undoes).

Only program files are replaced: servers, `servers.json`, configs, backups, logs and the chosen language are never touched. The daemon is restarted automatically.

`mc update` never replaces the Windows service or re-runs the installer. When a release changes them, the release notes say so, and `mc update` (and `mc doctor`) warns about an outdated service: right-click `install.bat` in the MC Manager folder and run it as administrator again. Servers and settings are kept.

The release ZIP keeps its `MCManager\` layout, so `mc update` also works from a 2.x Windows install. Updating by hand: stop the service with `mc daemon stop`, extract `MCManager.zip` over the program folder, then `mc daemon start`.

> Your server files, configs, and backups are stored outside the program folder and are never affected by an update.

---

## Uninstallation

Right-click `uninstall.bat` → **Run as administrator**.

The script:
1. Stops all currently online Minecraft servers.
2. Removes the `MCManagerDaemon` Windows service and the global `mc` command.
3. Cleans up files generated by the program (`logs/`, `server.pid`, `nssm/`, `__pycache__/`, `mc.bat`).

> **Your Minecraft server files (worlds, mods, backups) are never deleted.** The script displays the location of each server at the end.

---

## Deploying a new server (`mc deploy`)

```
mc deploy
```

Steps:
1. **Server name and description** — asked first (used to suggest a default folder).
2. **Installation folder** — default `C:\ProgramData\MCManager\Servers\<name-slug>\Server\`, editable. Detects if a server already exists inside and asks for confirmation before overwriting.
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

### Non-interactive deployment (scripts)

```powershell
mc deploy --yes --accept-eula --name survival --loader Paper --version 1.21.1 `
          [--dir PATH] [--port 25565] [--rcon-port 25575] [--ram 6G] [--json]
```

With `--yes`, nothing is asked: options not given take their default (latest Minecraft release, first free game and RCON ports, `C:\ProgramData\MCManager\Servers\<name>\Server`, 4G). `--accept-eula` is mandatory — deploying accepts the [Minecraft EULA](https://aka.ms/MinecraftEULA) on your behalf. With `--json`, progress goes to stderr and stdout carries `{"ok", "code", "server", "port", "rcon_port", "path", ...}`. Exit codes: 0 deployed, 2 invalid options (EULA not accepted, unknown type...), 1 failure (download, port taken...).

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
| `mc players history [target] [--days N] [--show-ip]` | Connections and disconnections read from the logs; the IP is only shown with `--show-ip` or `--json` |
| `mc whitelist add\|remove <player> [target]`, `list`, `on`, `off` | Whitelist (RCON when running, direct file edit when stopped) |
| `mc op add\|remove <player> [target]`, `list` | Operators |
| `mc ban add\|remove <player> [target] [--reason R]`, `list` | Player bans |
| `mc ban-ip add\|remove <ip> [target]`, `list` | IP bans |
| `mc kick <player> [target] [--reason R]` | Kick a connected player |
| `mc world list\|export\|import\|reset\|pregen [target]` | Worlds: dimensions, zip export/import, dimension reset, Chunky pregeneration |
| `mc task add\|list\|remove\|run\|enable\|disable [target]` | Scheduled tasks (cron) run by the daemon |
| `mc rcon "<command>" [target]` | Send one command to the server and print its reply (RCON password read from the config) |
| `mc config get [<key>] [target]` | Print one setting, or the whole `config.json` as JSON with secrets shown as `***` and listed in `secrets_set`; a secret key needs `--reveal` |
| `mc config set <key> <value> [target]` | Change a setting and propagate it everywhere it lives: `config.json`, `servers.json`, `server.properties`, firewall |
| `mc freeze [target] [--max 1h] [-- <command>]` | Freeze the world for an external backup (`save-off` + `save-all flush`); with `-- <command>`, runs it and always thaws afterwards |
| `mc thaw [target]` | Re-enable world saving |
| `mc switch <target> [--force]` | Hand the active server's place to another server: stop, swap game and RCON ports, start (refused while players are online unless `--force`) |
| `mc sleep enable\|disable\|status\|wake [target] [--after 2h]` | Automatic sleep when nobody plays; wakes when a known player joins |
| `mc sleep enable [target] --join-mode kick\|hold [--freeze on\|off] [--hold-timeout 2m]` | Sleep join behaviour: `hold` keeps the waking player connected and relays them once the server is ready; `--freeze on` suspends the JVM instead of stopping it (Linux only) |
| `mc router enable [--port N] [--proxy-in on\|off] [--proxy-out on\|off] [--trusted-proxy CIDR] [--per-ip N] [--per-second N]` / `disable` / `status` | Several servers behind one public port, chosen by the hostname in the handshake |
| `mc router route add\|remove <host> [<server>]` / `route list` / `default <server>` / `allow\|deny add\|remove <CIDR>` | Hostname table, default server, CIDR access lists |
| `mc sleep allow\|deny <player> [target]` | Let a player who never joined before wake the server (or stop letting them) |
| `mc metrics serve [--bind 127.0.0.1:9225] [--allow-remote]` | Prometheus metrics (`/metrics`) of every registered server, in the foreground |
| `mc status-page enable [target] [--dir D] [--interval 60] [--show-players]` | Public static status page, regenerated by the service |
| `mc status-page disable [target]` | Stop regenerating it and remove its two files |
| `mc datapack list\|enable\|disable [<pack>] [target]` | Manage datapacks live (`--before P`, `--after P`, `--first`, `--last` to order) |
| `mc mod list\|add\|remove\|update [<mod>] [target]` | Manage mods and plugins: add a `.jar` or a name from Modrinth/CurseForge/Hangar (dependencies included), update, remove to quarantine; AutoModpack copy included |
| `mc modpack install\|update\|info <source>` | Create a server from a modpack (Modrinth `.mrpack` or slug, `curseforge:<slug>`, `ftb:<id>`), update it, or describe it |
| `mc upgrade <version\|latest> [target]` | Move a server to another Minecraft version: backup first, refused while running, for a downgrade, or when the loader does not exist for that version |
| `mc java list\|install\|use\|remove` | Java runtimes (Eclipse Temurin) managed per server |
| `mc use <name/number>` | Change the active server (argument required) |
| `mc configure [target]` | Reconfigure an already registered server (also guarantees RCON/AutoModpack) |
| `mc remove <name/number>` | Unregister a server from the registry (deletes NO files) |
| `mc doctor [target]` | Full diagnostic (machine: service, Java, zombie JVMs; per server: config.json, server.properties consistency, RCON, firewall, port holder; the cgroup and swap lines are Linux only) — **all servers if `target` omitted** |
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
| `mc backup list [target] [--json]` | List the backups, newest first |
| `mc backup restore <id\|file\|latest> [target] [--yes]` | Replace the world with a backup (server stopped; safety backup first) |
| `mc backup remote add <name> <url> [target]` / `remove <name>` / `list` / `test [name]` | Remote destinations: `sftp://`, `s3://`, `restic:` |
| `mc alert add <type> [options] [target]` / `list` / `remove <name>` / `test [name]` | Alert channels: `email`, `telegram`, `ntfy`, `webhook`, `discord` |
| `mc image add <path> [target]` | Set the server icon (64×64 PNG, converted automatically) |
| `mc image rm [target]` | Remove the server icon |
| `mc edit config [target]` | Edit `config.json` in `%EDITOR%` (default: Notepad) |
| `mc edit webhooks [target]` | Edit `webhooks.json` in `%EDITOR%` (default: Notepad) |
| `mc logs [target]` | Show the last 30 log lines (filtered to `target` if given) |
| `mc daemon run` | Run the daemon in the foreground (debug) |
| `mc daemon start/stop/restart` | Control the `MCManagerDaemon` service |

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
mc add D:\Minecraft\OldServer    # register an existing server
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

## Monitoring

`mc metrics serve` (or `metrics_bind` for the service) exposes `/metrics` in the Prometheus text format 0.0.4, one `server` label on every series, sampled at most every 10 seconds:

| Metric | Meaning |
|---|---|
| `mcm_server_up` | 1 when the state is `running` |
| `mcm_server_state{state=…}` | one series per state, 1 for the current one |
| `mcm_players_online`, `mcm_players_max` | from RCON `list` (absent when the server does not answer) |
| `mcm_jvm_rss_bytes`, `mcm_jvm_cpu_seconds_total`, `mcm_uptime_seconds` | read from the process (absent when no JVM) |
| `mcm_tps` | 1-minute TPS: `tps` on Paper/Purpur/Spigot/Folia, `neoforge tps` / `forge tps` (overall line); absent on Vanilla and Fabric |
| `mcm_backup_last_success_timestamp` | modification time of the newest archive in `dossier_backup` |

It listens on `127.0.0.1:9225` by default; a non-local address is refused unless `--allow-remote` (command) or `metrics_allow_remote` (service) says so. There is no authentication.

`mc status-page enable` writes `index.html` (responsive, no external resource) and `status.json` in a folder a web server can serve, every `--interval` seconds (60 by default) through the service. They hold the name, state, players n/max, version, MOTD without `§` codes and the update time, and no secret, IP address or player name, unless `--show-players` is given. Files are replaced atomically.

---

## Sleep mode

```powershell
mc sleep enable --after 2h      # sleep after 2 hours without players
mc sleep status
mc sleep allow Alex             # a friend who has never joined yet
mc sleep wake                   # wake it now
```

When nobody has played for the chosen time, the server is saved and stopped (Discord: "sleeping"), and its state becomes `sleeping`. The service then holds the game port itself:

- the server **stays visible** in the multiplayer list, with a "sleeping" description and 0 players — whatever the players' game version;
- when a player **the server already knows** tries to join (anyone in `usercache.json`, `ops.json` or `whitelist.json` of any registered server, plus `mc sleep allow`), the server wakes up and the player is asked to reconnect a minute later. Unknown names — mostly internet scanners — get a polite refusal and never wake it;
- it never wakes during a world freeze (`mc freeze`: it waits for the thaw), outside opening hours in schedule mode, or after a manual `mc stop`.

Sleep requires RCON (to count players) and the service to be running. It frees all the server's memory while nobody plays.

### Hold mode and banned addresses

```
mc sleep enable --join-mode hold --hold-timeout 2m
```

In `hold` mode the listener is the permanent entry point on the public port and the server runs on an internal port (`internal_port`, by default port + 10000, on `127.0.0.1`; `server-port` and `server-ip` in `server.properties` are changed accordingly and restored with `--join-mode kick`). A known player who wakes the server stays connected: the login is kept alive while the server starts, then handshake and Login Start are replayed to the real server and bytes are relayed both ways. After `sleep_hold_timeout` (default 120 s) the player gets a polite disconnect. A restart of the server is needed after switching mode.

The server sees the listener's address unless it understands the PROXY protocol v2. For Paper-family servers MC Manager turns `proxy-protocol` on in `config/paper-global.yml` and sends the header (setting `sleep_proxy_protocol`: `auto`, `on`, `off`). Other loaders (Fabric, Forge, NeoForge, Vanilla) have no such option: they see `127.0.0.1` for every player, and IP bans and logs are affected. Do not expose such a server on its internal port.

`--freeze on` suspends the server after `save-all flush` instead of stopping it: memory stays allocated, CPU drops to zero, and waking is a resume (seconds). **Not available on Windows**: the option answers `unsupported_on_windows`, use `hold` without `--freeze`. The watchdog (`max-tick-time`, Spigot `timeout-time`) is relaxed while the option is on and restored when it is turned off. Settings cannot be changed while the server is suspended.

In both modes the listener refuses the addresses of the server's `banned-ips.json` (expired temporary bans are ignored).

## Router (`mc router`)

```
mc router route add play.example.fr survie
mc router route add crea.example.fr creatif
mc router default survie
mc router deny add 192.0.2.0/24
mc router enable --port 25565
```

One listener reads the server address of each handshake and relays the connection to the matching server. Names are lower-cased and cleaned of the DNS dot and of Forge markers (`host\0FML2\0`). A route marks its server as a router backend: it moves to an internal port on `127.0.0.1` (restart needed) and is woken on demand like a sleeping server. Status pings of a stopped server get its "sleeping" description. The table lives in `router.json`, next to `servers.json` (mode 0600, atomic writes), and the daemon applies changes within 5 seconds.

Limits (`--per-ip`, `--per-second`), `allow`/`deny` CIDR lists (a deny always wins; with an allow list, only listed addresses connect), and PROXY v2 on input (`--proxy-in on --trusted-proxy CIDR`, accepted only from trusted peers) and on output (`--proxy-out on`, or automatic for servers that expect it) are available. `mc router enable` refuses a port that a server still listens on: add the routes first (a routed server moves to its internal port), or use another port.

---

## Switching servers (`mc switch`)

```powershell
mc switch creative
```

Makes `creative` the active server **in place of** the current one: refuses if players are online (`--force` to override), stops the current server (reason `switch`) and waits for its process to exit, **swaps the game ports and the RCON ports** of the two servers (a shared RCON port is replaced by a free one), updates both `server.properties`, then starts `creative`. Players keep using the same address.

---

## Datapacks and mods

```powershell
mc datapack list                          # files, enabled state and order, problems
mc datapack enable terralith --first      # enable (or move) a pack
mc datapack disable terralith
mc mod add C:\Users\you\Downloads\create-1.0.jar     # into mods/ and the AutoModpack host modpack
mc mod add C:\Users\you\Downloads\spark.jar --server-only
mc mod remove create                      # moved to mods_quarantine/<date>/, never deleted
```

- A pack placed in a **sub-folder** of `world/datapacks` is ignored by Minecraft: `mc datapack list` flags it.
- A pack that changes world generation (`worldgen/`) only takes effect after a **restart**: MC Manager says so.
- Moving an already enabled pack works (Minecraft itself refuses; MC Manager disables and re-enables it at the requested position).
- With AutoModpack, a mod exists twice (`mods/` and `automodpack/host-modpack/main/mods/`): `mc mod` always handles both copies, so a removed mod is no longer shipped to players.
- Removing a mod that **adds blocks** turns those blocks into air in the world, and the server saves that. MC Manager refuses unless you add `--yes` — back the world up first.

---

## Players, worlds and scheduled tasks

### Players (`mc whitelist`, `op`, `ban`, `ban-ip`, `kick`)

```powershell
mc whitelist add Steve            # also: remove, list, on, off
mc op add Alex
mc ban add Griefer --reason "griefing"
mc ban-ip add 203.0.113.9
mc kick Steve --reason "restart soon"
mc players history --days 3 --show-ip
```

- **Server running**: the command goes through RCON, then the server's own JSON file (`whitelist.json`, `ops.json`, `banned-players.json`, `banned-ips.json`) is read back to confirm it was applied. **Server stopped**: the file is edited directly and atomically.
- A stopped server needs the player's UUID to add an entry: it comes from the Mojang API (`api.mojang.com`), or, when `online-mode=false`, from the offline UUID (version 3 MD5 of `OfflinePlayer:<name>`). Removing an entry never needs the network.
- Names must match `[A-Za-z0-9_]{3,16}`; `ban-ip` takes an IPv4 or IPv6 address.
- `mc players history` reads `logs/latest.log` and `logs/*.log.gz`: `[{player, ip, join, leave, duration_s}]`. A session cut by a crash or a restart has no `leave`.

### Worlds (`mc world`)

```powershell
mc world list                          # dimensions present and their size
mc world export --output backup.zip    # server stopped, or: mc freeze -- mc world export
mc world import world.zip --yes        # server stopped; backup first; level.dat required
mc world reset nether --yes            # deletes region/, entities/, poi/; backup first
mc world pregen 5000 --center 0,0      # needs Chunky (mod or plugin)
mc world pregen --status               # Chunky progress
```

`export` leaves out `session.lock` and Distant Horizons' `.sqlite` files. `reset overworld` needs `--include-overworld`. Without Chunky, `pregen` says to run `mc mod add chunky`.

### Scheduled tasks (`mc task`)

```powershell
mc task add --cron "0 4 * * *" --action restart --warn 10m,5m,1m --name nightly
mc task add --cron "*/30 * * * *" --action backup
mc task add --cron "0 12 * * 6" --action command --command "say Event at 8 pm"
mc task list                           # next run, last run and result
mc task run nightly --now              # run now, without the warnings
mc task disable nightly
```

- `--cron` is five fields, local time: minute hour day-of-month month day-of-week, with lists (`1,15`), ranges (`8-18`), steps (`*/10`, `0-30/5`) and names (`mon-fri`, `jan`). As in classic cron, when both day fields are restricted, either one matches.
- Actions: `restart`, `stop`, `start`, `backup`, `command` (needs `--command`). `--warn` (restart and stop only) announces the countdown in game: the cron time is when the action happens, the announcements come before it.
- `restart` and `stop` stop the server with the reason `scheduled`; `restart` then lifts the maintenance flag and the daemon starts the server again on its next tick. `start` only lifts a `scheduled` (or `sleep`) stop, never one made by hand.
- A task missed while the daemon was down is **not** caught up. Tasks live in `config.json` (`tasks`); executions are logged in `logs/daemon.log` and kept as `last_run` / `last_result` in `mc task list --json`.

---

## Starting through the service

`mc start`, `mc switch` and wake-ups are carried out **by the service** whenever it is running: the server is never a child of your terminal, so it survives the terminal closing, and restarting the service (`mc update`, `mc daemon restart`) does not stop it (`AppKillProcessTree 0`). When the service is not running, `mc start` launches the server directly and says so.

---

## Server types

`mc deploy` installs: **Vanilla, Paper, Folia, Purpur, Fabric, Quilt, Forge, NeoForge, Spigot** (compiled with BuildTools; needs `git`, takes a few minutes), and the proxies **Velocity, Waterfall, BungeeCord**. Every download is checked against the hash its publisher gives. Proxies have no world and no RCON: MC Manager writes their port into `velocity.toml` / `config.yml` and stops them with `SIGTERM`.

### Upgrading Minecraft (`mc upgrade`)

```powershell
mc stop survival
mc upgrade 1.21.4 survival      # or: mc upgrade latest survival
mc mod update --all survival
mc resume survival
```

Refused while the server runs, for a downgrade (a world cannot go back), and when the loader is not published for that version. The world is backed up first; the previous server jar is kept in `.mcmanager/previous-jars/`.

### Java

Every server runs on its own **Eclipse Temurin** runtime, the version its Minecraft version requires (Mojang's own metadata: Java 8, 17, 21, 25...), downloaded once into `java/` in the MC Manager folder and verified by its SHA-256. The system Java is no longer needed.

```powershell
mc java list                    # runtimes, and which server uses which
mc java use auto survival       # back to the version Minecraft requires
mc java use 21 survival         # force a version
mc java use system survival     # use the system Java
```

### Mods and plugins by name

```powershell
mc mod add lithium              # Modrinth (mods) — required dependencies installed too
mc mod add luckperms            # Paper/Purpur/Velocity: Hangar, then Modrinth
mc mod add jei --source curseforge
mc mod update --all
```

MC Manager picks the newest release built for the server's loader and Minecraft version, verifies its hash, refuses client-only mods, and keeps mods that players do not need out of the AutoModpack modpack. What was installed by name is tracked in `.mcmanager/content.json`, so `mc mod update` can replace it (the old file goes to quarantine). CurseForge needs a free API key: `mc config set curseforge_api_key <key>` (or `CURSEFORGE_API_KEY`).

### Modpacks

```powershell
mc modpack info cobblemon-fabric
mc modpack install cobblemon-fabric --accept-eula [--name N --port P --ram 8G]
mc modpack install ./MyPack.mrpack --accept-eula
mc modpack install curseforge:all-the-mods-10 --accept-eula
mc modpack install ftb:126 --accept-eula
mc modpack update survival
```

`install` creates a new server: the right loader and version, the server-side files only (client-only files are skipped), the pack's overrides, its own Java. `update` backs the world up, sets the old version's files aside in `mods_quarantine/`, and installs the new version; the world and your own additions are kept.

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
| Switch the active server | `mc switch <name> --json` |
| Sleep settings / state | `mc sleep status --json` |
| Datapacks, mods | `mc datapack list --json`, `mc mod list --json` |

Every action command with `--json` prints a result object: `{"schema": 1, "ok": true|false, "code": "<stable identifier>", ...}`. The `code` values are stable and meant for programs; the human text is derived from them in the chosen language.

### Architecture

Every operation lives in `mc_api.py` (plus `mc_content.py` for datapacks and mods): functions that take a server and return a result object, never print, and never depend on the terminal. The command line is one front end over this layer; a graphical interface can call the same functions, or the same commands with `--json`, and get exactly the same behaviour.

JSON documents carry `"schema": 1`. Within a schema version, fields may be added, never renamed or removed. Human messages always go to stderr or are absent in `--json` mode, so stdout is pure JSON. On an error, `--json` commands print `{"schema": 1, "error": {"code": ...}}` and exit with the codes documented above.

Example (`mc status --json`, abridged):

```json
{
  "schema": 1,
  "active": "survival",
  "servers": [
    {
      "name": "survival", "id": 1, "active": true, "path": "C:\\ProgramData\\MCManager\\Servers\\survival\\Server",
      "state": "running", "error": null, "mode": "always-on", "maintenance": false, "stop_reason": null,
      "port": 25565, "rcon_port": 25575, "loader": "Fabric", "version": "1.21.1", "frozen": false,
      "pid": 12345, "uptime_s": 7260, "rss_kb": 6291456, "swap_kb": null,
      "cgroup": null, "port_holder": null
    }
  ]
}
```

A server whose folder is missing or whose `config.json` is unreadable has `"state": null` and an `"error"` object (`folder_missing`, `config_unreadable`).

### Freezing the world for an external backup

```powershell
mc freeze -- restic backup C:\ProgramData\MCManager\Servers\survival\Server\world
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

## Daemon (Windows Service via NSSM)

The daemon runs as a Windows service, without a visible window, and starts automatically with Windows. It loops every 30 seconds over all registered servers.

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

```powershell
# NSSM graphical service editor
.\nssm\nssm.exe edit MCManagerDaemon

# Native Windows service query
sc query MCManagerDaemon
```

### Logs (`logs/`)

| File | Content |
|---|---|
| `logs/daemon.log` | Daemon log (INFO), all lines prefixed `[server_name]` |
| `logs/daemon_error.log` | Errors/tracebacks from the service |

---

## Security

- **Service control.** `mc daemon start|stop|restart` and `mc update` drive the `MCManagerDaemon` service; Windows asks for an administrator terminal, and the command printed on failure can be pasted into one.
- **Secrets stay private.** `config.json`, `webhooks.json` and `servers.json` (RCON password, Discord webhook URL) are written with `icacls` rights limited to your account, and `mc doctor` checks them.
- **RCON is never exposed.** New servers get a 32-character RCON password. `mc doctor` reports an error if a firewall rule opens the RCON port, or if RCON listens on every interface with no firewall active, and warns about passwords shorter than 16 characters.
- **Sleep listener limits.** At most 4 simultaneous connections per address and 32 in total; idle clients are cut after 3 seconds.
- **Signed updates** — see [Updating MC Manager](#updating-mc-manager). Vulnerability reports: see [SECURITY.md](../SECURITY.md).

---

## Configuration (`config.json`)

Each server has its own `config.json` in its server folder. `mc edit config [target]` opens it.

| Key | Description | Example |
|---|---|---|
| `nom_serveur` | Name displayed in Discord | `"survival"` |
| `dossier_serveur` | Absolute path to the server | `"C:\\ProgramData\\MCManager\\Servers\\survival\\Server"` |
| `dossier_backup` | Backup destination folder | `"C:\\ProgramData\\MCManager\\Servers\\survival\\Backup"` |
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
| `jar_name` | JAR file name (or `run.bat` for Forge/NeoForge) | `"fabric-server-launch.jar"` |
| `rcon_port` | RCON port | `25575` |
| `mcrcon_pass` | RCON password | `"password"` |
| `domaine` | Server domain/link shown to players (optional) | `"play.myserver.com"` |
| `webhook_url` | Discord Webhook URL | `"https://discord.com/api/webhooks/..."` |
| `backup_retention_days` | Days to keep backups (0 = unlimited); the newest backup is never deleted | `30` |
| `backup_keep` | Number of backups to keep (0 = unlimited); the newest backup is never deleted | `14` |
| `backup_encrypt_key_file` | Key file: archives sent to sftp/s3 are encrypted with `openssl enc -aes-256-cbc -pbkdf2` | `"C:\\Users\\you\\.mc-backup.key"` |
| `backup_remotes` | Remote backup destinations (managed by `mc backup remote`, secrets inside: the file is 0600) | `[]` |
| `alerts` | Alert channels (managed by `mc alert`, secrets inside: the file is 0600) | `[]` |
| `activer_automodpack` | AutoModpack enabled (1) or not (0) | `1` |
| `cle_automodpack` | AutoModpack certificate fingerprint — **detected automatically, never enter manually** | `"403e6792a7..."` |
| `mode_maintenance` | Maintenance active (1) or not (0) — set via `mc mode maintenance` / `mc resume` | `0` |
| `tasks` | Scheduled tasks, managed by `mc task` (see [Scheduled tasks](#scheduled-tasks-mc-task)) | `[]` |
| `stop_timeout` | Seconds `mc stop` waits for a clean shutdown before `SIGTERM` (optional) | `120` |
| `sleep_join_mode` | `kick` (default) or `hold`: see [Sleep mode](#sleep-mode) | `"hold"` |
| `sleep_hold_timeout` | Seconds a held player waits for the server (10-600) | `120` |
| `sleep_freeze` | Suspend the JVM instead of stopping it (hold mode only) | `1` |
| `sleep_proxy_protocol` | PROXY v2 towards the server: `auto`, `on`, `off` | `"auto"` |
| `internal_port` | Port the server really listens on in hold or router mode | `35565` |
| `stop_reason` | Why the server was stopped (`user`, `sleep`, `update`, `maintenance`, `switch`, `scheduled`) — set by `mc stop --reason`, cleared by `mc resume` | `"sleep"` |
| `metrics_bind` | `host:port`: the service serves `/metrics` there while any server defines it (first one found wins); empty or absent = off. Local addresses only unless `metrics_allow_remote` is 1 | `"127.0.0.1:9225"` |
| `metrics_allow_remote` | 1 allows a non-local `metrics_bind` (no authentication: put it behind a firewall or a reverse proxy) | `0` |
| `status_page_dir` | Folder of the status page — set by `mc status-page enable`, removed by `disable` | `"/var/www/status"` |
| `status_page_interval` | Seconds between two regenerations (10 minimum) | `60` |
| `status_page_players` | 1 publishes the names of connected players in the page and `status.json` | `0` |

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

**No path given:** running `mc image add` without an argument opens a file picker (tkinter) — browse to your image and confirm.

The source image is resized to 64×64 pixels using high-quality Lanczos resampling, converted to RGBA PNG, and saved as `server-icon.png` in the server folder. The change takes effect on the next server start.

> Requires [Pillow](https://python-pillow.org/) — installed by `install.bat`.

---

## CPU Affinity

Applied natively through `SetProcessAffinityMask`. Format in `config.json`:
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

All world dimensions (`world`, `world_nether`, `world_the_end` — following `level-name`) are included.

The world is frozen through the same mechanism as `mc freeze` (`save-off` + `save-all flush`) while it is copied, then saving is re-enabled before the archive is compressed and sent; a freeze set by someone else is left alone.

**Retention:** `backup_keep` (number of archives) and `backup_retention_days` (age) are applied after each backup, separately or together (`mc config set backup_keep 14`). `0` disables a rule. The most recent backup is never deleted, whatever the rules say.

### Listing and restoring

```
mc backup list
mc stop
mc backup restore backup_manuelle_2026-10-03_12-00-00 --yes
mc resume
```

`mc backup restore` takes an id (see `mc backup list`), a file name, a path or `latest`. The server must be stopped for good (`mc stop`): a server the daemon would relaunch is refused. The current world is backed up first (`backup_pre-restore_...`, its path is printed), the archive is extracted aside and swapped in; if any step fails the previous world is put back. Without `--yes` the command asks for confirmation, and refuses when it cannot ask (scripts, `--json`). Dimensions that exist now but not in the archive are replaced too, so the world stays consistent.

### Remote destinations

```
mc backup remote add vps sftp://backup@host.example:22/srv/mc --key C:\Users\you\.ssh\id_ed25519
mc backup remote add cloud s3://my-bucket/minecraft --access-key AKIA... --secret-key-file C:\Users\you\.s3secret --region eu-west-3
mc backup remote add minio s3://mc/backups --endpoint https://minio.lan:9000 --access-key ... --secret-key ...
mc backup remote add restic restic:sftp:backup@host:/srv/restic --password-file C:\Users\you\.restic-pass
mc backup remote test
```

Every new backup is sent to each destination right after it is written; a failing destination is reported (and raises the `backup_failed` alert) but never cancels the local backup nor the other destinations.

- **sftp**: uses the system `sftp` in batch mode (key authentication, no prompt); archives go to the given folder.
- **s3**: requests signed with AWS Signature Version 4, implemented with the standard library. `--endpoint` targets S3-compatible services (path-style addressing, `--no-path-style` for virtual-hosted). Objects are stored as `prefix/<server>/<archive>`. A single upload is limited to 5 GiB. Keys may also come from `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.
- **restic**: if `restic` is installed, `restic backup` of the backup folder (the repository is initialised when missing). The password lives in a file kept at 0600 (`--password-file`, or `--password` which writes `.mcmanager/restic-<name>.pass` in the server folder). restic encrypts natively.

Secrets are stored in `config.json`, which is always written 0600, and are masked in `mc backup remote list`.

**Encryption of sent archives:** `openssl` must be installed and in the `PATH` (it is not part of Windows). Set `backup_encrypt_key_file` (`openssl rand -base64 48 > C:\Users\you\.mc-backup.key`) and sftp/s3 archives are encrypted with `openssl enc -aes-256-cbc -pbkdf2` and uploaded as `.zip.enc`. If `openssl` is missing the archive is sent unencrypted, with a warning; if the key file is missing the upload is refused. Decrypt by hand with `openssl enc -d -aes-256-cbc -pbkdf2 -pass file:KEY -in x.zip.enc -out x.zip`, or point `mc backup restore` at the `.enc` file.

---

## Alerts (`mc alert`)

Besides the Discord announcements (`webhook_url`), a server can notify other channels. Events: `start`, `stop` (with its reason), `crash`, `crash_loop`, `backup_failed`, `update`, `sleep`, `wake`. Each channel picks the events it wants (`--events crash,backup_failed`, default all). Like the Discord announcements, alerts stay silent while the server is in maintenance.

```
mc alert add email --smtp-host smtp.example.org --smtp-port 587 --user mc@example.org --password-file C:\Users\you\.smtp-pass --from mc@example.org --to me@example.org,ops@example.org
mc alert add telegram --token 123456:ABC... --chat -1001234567890 --events crash,crash_loop
mc alert add ntfy --topic my-mc-alerts [--ntfy-server https://ntfy.example.org] [--token tk_...]
mc alert add webhook --url https://hooks.example.org/mc [--header "X-Key: 1"] [--secret S]
mc alert add discord --url https://discord.com/api/webhooks/... --name ops
mc alert list
mc alert test            # every channel, filters ignored; or: mc alert test telegram
mc alert remove telegram
```

- **E-mail** uses SMTP with STARTTLS (certificate checked); login is optional.
- **webhook** posts `{"schema":1,"event","server","title","message","reason","detail","time"}`; with `--secret` an `X-MCManager-Signature: sha256=<hmac>` header lets the receiver authenticate it.
- URLs must be `https://` (plain `http://` only towards the local machine). Tokens and passwords are stored in `config.json` (0600) and masked in `mc alert list`; the legacy Discord webhook appears there as `discord`.
- A channel that fails never delays or breaks a start, stop or backup: the failure is written to the daemon log.

---

## Local API

The service answers an HTTP/JSON API described by `openapi.json` (shipped next to the program). It listens
on `127.0.0.1` on a free port and requires a random 256-bit token: both are written to `run\api.token`
(JSON `{"port": ..., "token": ...}`, readable by your account only) and removed when the service stops.

```bat
mc api status [--json]      & rem enabled, listening, address
mc api disable              & rem stop listening (the option lives in api.json)
mc api enable
```

Send the token in the `Authorization: Bearer <token>` header (`GET /v1` alone is public). Every `GET`
returns the same document as the matching `mc ... --json` command. Long operations answer `202` with a
`Location: /v1/jobs/<id>` to poll; `GET /v1/events` and `GET /v1/servers/<server>/console` are
Server-Sent Events. Bodies are limited to 1 MiB. Secrets are never returned.

## Remote access

Off by default. The service can serve the same API on the network, always over TLS 1.3, to devices you pair
one by one. The local API above is not affected and never goes through these checks.

```
mc remote enable [--bind 0.0.0.0:8765]   # certificate, listener, firewall rule "MC Manager API"
mc remote status [--json]                # state, bind, certificate fingerprint (SHA-256)
mc remote pair [--role viewer|operator|admin] [--servers a,b|all] [--name Phone]
mc remote devices list | revoke <id>
mc remote disable                        # closes the listener and the firewall rule
```

- A self-signed certificate (EC P-256, 10 years) is created on first use in `run/remote/`, with the
  `cryptography` module or `openssl`; without either, `mc remote enable` refuses (`tls_unavailable`).
- `mc remote pair` prints an 8-digit code valid 5 minutes, single use. The device sends it to
  `POST /v1/pair` and receives a 256-bit token, shown once and stored hashed. Five wrong codes cancel the
  code; ten failures from one IP lock pairing for 15 minutes.
- Roles: `viewer` reads, `operator` starts, stops, backs up and uses the console, `admin` changes
  configuration and manages devices. A device can be limited to some servers.
- At most 20 requests per second and 3 console streams per device. Every request is logged in
  `logs/audit.log` (no token, code or body), rotated at 5 MiB.
- Client side: `mc remote add <profile> <host:port>` shows the certificate fingerprint, asks for the pairing
  code and saves the profile in `remotes.json` (0600). Then `mc --remote <profile> status|start|stop|players|logs|backup|console`
  works like the local command, and refuses any server whose certificate fingerprint changed.

## Automatic updates

MC Manager checks the latest published release in the background (throttled to once every few hours, silent if offline). When a newer version exists, every `mc` command shows a discreet line:

```
Update available: 2.3.1 — run 'mc update'
```

Run `mc update` to download, verify and apply it (see [Updating MC Manager](#updating-mc-manager)). The daemon is restarted automatically (run `mc daemon restart` from an administrator terminal if it could not).

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
## What is not available on Windows

| Feature | Windows behaviour |
|---|---|
| `mc sleep enable --freeze on` (suspend the JVM while sleeping) | refused with `{"ok": false, "code": "unsupported_on_windows"}`; sleep with `hold` or `kick` works |
| cgroup of the server process (`mc status --json`, `mc doctor`) | `"cgroup": null`, no check |
| swap used by the server process | `"swap_kb": null`, no check |

Everything else (`mc freeze` / `mc thaw`, sleep, router, tasks, backups, alerts, metrics, status page, mods, datapacks, worlds, players, upgrade, modpacks, JSON API) behaves as on Linux.

---

## Shared disk / dual-boot (cross-OS registry)

If you run both Windows and Linux on the same machine (dual-boot) and your Minecraft servers live on a shared data partition, you can make MC Manager use the same `servers.json` and the same server folders from both operating systems — without having to run `mc add` twice.

### How it works

Set the environment variable `MCMANAGER_DATA_DIR` to the path of a folder on the shared partition **before starting MC Manager** (and before running `install.bat`). Both the Windows and Linux installs must point to the **same physical folder** (different mount paths are fine, as long as they resolve to the same disk location).

Server paths stored under this folder are written as forward-slash relative paths (e.g. `Servers/survival/Server`), so they resolve correctly on either OS.

### Setup (Windows)

1. Create a persistent **User environment variable** named `MCMANAGER_DATA_DIR`:
   - Win + R → `sysdm.cpl` → **Advanced** → **Environment Variables** → **New** (User variables)
   - Name: `MCMANAGER_DATA_DIR`
   - Value: path to your shared folder, e.g. `E:\MCManagerData`
2. Open a **new** terminal (so the variable is picked up).
3. Run `mc deploy` — the wizard will suggest `E:\MCManagerData\Servers\<name>\Server\` as the default folder.

The daemon service propagates the variable automatically: `install.bat` / `mc configure` → NSSM picks it up via `AppEnvironmentExtra` so the service sees the same registry as the CLI.

### Limitations

- A server whose folder is **outside** the shared partition stores an absolute Windows path (`C:\...`), which Linux sees as "folder not found". Only servers inside the shared partition are visible cross-OS.
- A server created on Linux with a POSIX path (`/home/...`) outside the shared partition shows as "folder not found" on Windows — this is expected.

