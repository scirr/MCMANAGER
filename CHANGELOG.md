# Changelog

All notable changes to MC Manager, newest first. Each version links to its full release notes.

## [3.0.0](release-notes/v3.0.0.md)

- Windows at full parity with Linux: the same modules, every command, the daemon as the NSSM service `MCManagerDaemon`.
- macOS support: LaunchAgent daemon, same core and commands.
- Local `/v1` HTTP API (OpenAPI 3.1 contract in `api/openapi.json`) and opt-in remote access over TLS 1.3 with device pairing and `viewer`, `operator`, `admin` roles; `mc --remote <profile> <command>`.
- First desktop apps: GTK 4 / libadwaita (also a Flatpak), WinUI 3 and SwiftUI.
- Linux `.deb` and `.rpm` packages and a Windows installer (`MCManager-Setup.exe`).
- Fixes: stop followed by resume taken for a crash, sleep listener race, Windows API module not loading, eleven API failures answered `500`.

## [2.11.0](release-notes/v2.11.0.md)

- Advanced sleep mode: hold the connecting player, optional JVM freeze.
- Hostname router: several servers behind one public port, with per-IP limits and CIDR lists.
- Prometheus metrics (`mc metrics serve`) and a static status page.
- `--json` accepted by more commands; a secrets leak closed.

## [2.10.0](release-notes/v2.10.0.md)

- Players: whitelist, ops, bans, kick and `mc players history`.
- Worlds: `mc world` list, export, import, reset and Chunky pregeneration.
- Scheduled tasks (`mc task add --cron`) and `mc backup list|restore`.
- Backups to sftp, S3 or restic; alerts by e-mail, Telegram, ntfy, webhook or Discord.

## [2.9.0](release-notes/v2.9.0.md)

- More server types: Paper, Folia, Purpur, Fabric, Quilt, Forge, NeoForge, Spigot and the Velocity, Waterfall and BungeeCord proxies.
- `mc upgrade` moves a server to another Minecraft version.
- Modpacks from Modrinth, CurseForge and FTB; mods and plugins by name.
- A managed Eclipse Temurin Java runtime per server.

## [2.8.0](release-notes/v2.8.0.md)

- Hardening: polkit instead of sudo and a sandboxed systemd service.
- Secrets readable by their owner only; 32-character RCON passwords and an exposure check in `mc doctor`.
- Connection limits on the sleep listener.
- Scriptable deployment with `mc deploy --yes`; first `SECURITY.md`.

## [2.7.0](release-notes/v2.7.0.md)

- Signed updates: `SHA256SUMS` signed with Ed25519, verified before anything is installed.
- `mc update --rollback`, `--to <version>` and `--check`.
- Releases built, signed and attested by CI.
- ufw support next to firewalld; continuous integration on every push.

## [2.6.0](release-notes/v2.6.0.md)

- Sleep mode and server switching.
- Datapack and mod management.
- Documented exit codes and no raw Python traceback.
- One operations layer returning structured results, shared by the command line and future interfaces.
- Licence changed from MIT to MPL-2.0 after 2.5.0.

## [2.5.0](release-notes/v2.5.0.md)

- Explicit server states: `running`, `starting`, and more.
- `mc status --json` with a versioned schema.
- Scripting commands: `mc active`, `mc players`, `mc rcon`, `mc config get|set`.
- `mc stop --reason` to say why a server was stopped.

## [2.4.9](release-notes/v2.4.9.md)

- A UTF-8 BOM no longer stops supervision.
- No more zombie JVMs and no more false "port already in use".
- A server is identified by its JVM, not by its port.
- `mc stop` waits for the process to really exit; RCON no longer hangs.
