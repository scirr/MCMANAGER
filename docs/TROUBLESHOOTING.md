# Troubleshooting

Each entry gives the symptom, the usual cause, and the command to run. Commands are the same on Linux, Windows and macOS unless noted. Run them in a terminal (on Windows, one opened as administrator for anything that touches the service). `[server]` is a server name or number; without it the active server is used.

Start with `mc doctor`: most problems below show up in its report.

---

## mc doctor

```
mc doctor [server]        # the machine, then the server
mc doctor --json          # same report for scripts or a support ticket
```

The report starts with the machine (service, service definition, Java, leftover Java processes) and then checks the server. Each line is `ok`, `warn` (needs attention), `err` (broken) or `info`, and every problem comes with the command that fixes it. The exit code is 1 when a line is `err`, otherwise 0. For a bug report, attach `mc doctor --json` (it contains no passwords) and the output of `mc version`.

| Line | What it means | What to do |
|---|---|---|
| Service (`mc_manager` service line): not installed or stopped | The daemon is not running | See [The service does not run](#the-service-does-not-run) |
| systemd unit: older version | The installed service definition is outdated | Re-run the installer from the MC Manager folder: `sudo ./install.sh` (Linux), `./install.sh` (macOS), `install.bat` or the new `Setup.exe` (Windows). Servers and settings are kept |
| Java | `err`: no Java; `warn`: not Java 21 | `mc java install 21`, or `mc java use auto [server]` |
| JVM zombies | A Java process the daemon lost track of | `mc daemon restart` |
| Server folder: err | The path in the registry does not exist | `mc configure [server]`, or fix the path |
| RCON configured: missing | No RCON password | `mc configure [server]` |
| RCON reachable: warn | RCON does not answer | Check `enable-rcon=true` in `server.properties`, or restart the server |
| RCON password: shorter than 16 characters | Weak password | `mc config set mcrcon_pass $(openssl rand -hex 16) [server]`, then `mc stop [server]` and `mc resume [server]` |
| RCON port: also declared by another server | Two servers share a RCON port | `mc config set rcon_port <free port> [server]` |
| Port free: occupied by another process | Port conflict | See [The port is already in use](#the-port-is-already-in-use) |
| Firewall: port closed | The firewall blocks players | See [Players cannot connect](#players-cannot-connect) |
| RCON protected: err | The RCON port is exposed to the internet | Close it in the firewall (the report prints the command) |
| Crash | Automatic restarts were stopped after repeated failures | Fix the cause, then `mc resume [server]` |
| server.properties / Registry | `config.json` and `server.properties` disagree | Applied at the next `mc start`; `config.json` wins |

---

## The server does not start

**It stops right after launch.** The message is "The server exited immediately after launch (port in use? corrupted JAR?)" followed by a log path.

```
mc logs [server]               # the daemon's view
mc doctor [server]             # the checks above
```

Read the last lines of `logs/latest.log` in the server folder: the usual causes are an unaccepted EULA, a mod for another Minecraft version, a wrong Java version or too little memory.

- **Java.** Each Minecraft version needs a given Java (8, 16, 17, 21 or 25, from Mojang's metadata). MC Manager normally downloads the right one. Check with `mc java list`; force a version with `mc java use 21 [server]`; go back to automatic with `mc java use auto [server]`. If the download fails ("Could not download Java"), check your connection and retry `mc java install 21`.
- **Memory.** `ram_allocation` larger than the free RAM makes the JVM die. `mc config get ram_allocation [server]`, then `mc config set ram_allocation 4G [server]`.
- **EULA.** `mc deploy` asks for it; for scripts pass `--accept-eula`.
- **Wrong files.** `mc configure [server]` to re-check the jar name and type.

**It crashes in a loop.** After repeated failures the daemon stops restarting the server and `mc status` says it crashed, with the last errors from the log. Fix the cause, then:

```
mc resume [server]
```

**"The server is in maintenance (reason: ...): run 'mc resume' first."** A server in maintenance is left alone by the daemon, and `mc start` is refused. `mc resume [server]` leaves maintenance and the daemon starts the server within about 30 seconds. Do not run `mc start` after it.

**The server did not stop for good.** "{server} is not durably stopped: the daemon would relaunch it" means the server is in always-on mode. `mc stop [server]` first, or switch to maintenance with `mc mode maintenance [server]`.

### The port is already in use

"Port N is already in use: a server is most likely still running. Start cancelled to avoid a duplicate (locked world)", or "Port N is already held by <program> (PID n)".

```
mc status [server]             # is it running already?
mc stop --force [server]       # kill a stuck process
mc configure [server]          # or choose another port
```

On macOS and Linux, `lsof -iTCP:25565 -sTCP:LISTEN` shows who holds the port; on Windows `netstat -ano | findstr 25565`. A sleeping server legitimately holds its port (`mc doctor` says "held by native sleep mode"); `mc sleep disable [server]` releases it.

---

## Players cannot connect

Check in this order.

1. **Is the server up?** `mc status [server]` must say Running. A sleeping server answers pings with "sleeping" and wakes when a known player joins (see [Sleep mode does not wake the server](#sleep-mode-does-not-wake-the-server)).
2. **Firewall on the machine.** `mc doctor [server]` has a line "Firewall (game port)". Linux (ufw or firewalld) and Windows: MC Manager opens the port when a server is configured; if the line says closed, `mc configure [server]` re-applies the rule (so does `mc config set port <port> [server]`), or run the command `mc doctor` prints. macOS filters per application, not per port: allow Java with
   ```
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$(command -v java)"
   sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$(command -v java)"
   ```
3. **Same network.** Players on your LAN use the machine's local address and the server port, with the exact `port` from `mc config get port [server]`.
4. **From the internet.** The router (box) must forward the TCP game port to the machine, and the machine needs a fixed local address. The address players use is your public IP or a domain name pointing to it. See [Making the server accessible](../Linux/README_Linux.md#making-the-server-accessible-networking).
5. **Several servers on one port.** With the router (`mc router status`), each server needs a route for the host name players type: `mc router route add <host> <server>`. A name with no route goes to the default server.
6. **Version.** The player's Minecraft version must match the server's (or the proxy's), and modded servers need the same mods.

A player who is refused with "This server is sleeping. Only players it already knows can wake it up." has never joined before: start the server by hand or allow the player with `mc sleep allow <player> [server]`.

---

## Sleep mode does not wake the server

```
mc sleep status [server]
mc doctor [server]
```

- **"Sleep mode needs RCON to count players."** Set up RCON: `mc configure [server]`.
- **Unknown player.** Only players the server already knows (whitelist, ops, history) can wake it. Add others with `mc sleep allow <player> [server]`, or wake it yourself: `mc sleep wake [server]`.
- **Closed outside opening hours / in maintenance.** In `schedule` mode the server wakes only inside its hours ("The server is closed. It opens at ..."); a manual stop is never undone by a join.
- **Another tool holds the port.** `mc doctor` reports "port held by an external sleep tool (<program>)". `mc sleep enable [server]` replaces it with the built-in one.
- **Backup in progress.** The server wakes right after; reconnect in a minute.
- **"Reconnect in a minute".** In `kick` mode the first connection is refused while the server starts; use `--join-mode hold` to keep the player connected: `mc sleep enable --join-mode hold [server]`. If the server takes too long, raise `--hold-timeout` (for example `2m`).
- **Freeze.** `--freeze on` needs hold mode and does not exist on Windows (`unsupported_on_windows`: "This feature is not available on Windows"). On macOS and Linux a frozen server is thawed with `mc thaw [server]`.
- **The Mac or the PC sleeps.** The daemon cannot wake anything while the machine is suspended (and on macOS, while you are logged out).

---

## The service does not run

The daemon runs the schedules, sleep mode, the API and the restarts. Without it `mc` commands that need it answer "The service did not answer in time" (`daemon_timeout`). Servers already running are not stopped when the daemon stops.

```
mc daemon status
mc daemon restart
mc logs                       # daemon log
```

| System | Service | Where to look |
|---|---|---|
| Linux | systemd unit `mc_manager` | `systemctl status mc_manager`, `journalctl -u mc_manager -e`, `logs/daemon.log` in the MC Manager folder |
| Windows | NSSM service `MCManagerDaemon` | `sc query MCManagerDaemon`, `nssm\nssm.exe edit MCManagerDaemon`, `logs\daemon.log` in the MC Manager folder; `mc daemon start|stop|restart` need an administrator terminal |
| macOS | LaunchAgent `io.github.scirr.mcmanager` | `launchctl print gui/$(id -u)/io.github.scirr.mcmanager`, `~/MCManager/logs/daemon.log` and `~/MCManager/logs/launchd.log` |

- **"service not installed".** Run the installer again (`sudo ./install.sh`, `./install.sh`, or `install.bat` / `Setup.exe`). Servers and settings are kept.
- **macOS: the agent is a user agent.** It runs only while you are logged in; after `mc daemon stop` it stays off until `mc daemon start` or the next login.
- **Linux: the unit looks outdated.** `mc doctor` warns "systemd unit: older version": run `sudo ./install.sh` from the MC Manager folder.

### The app does not connect to the daemon

The desktop apps talk to the daemon on this machine through `run/api.sock` (Linux, macOS) or `127.0.0.1` with `run/api.token` (Windows). "MC Manager not found", "Cannot reach MC Manager. Is the daemon running?" or "The MC Manager daemon was not found" mean the daemon is not running or the app looks in another folder.

```
mc api status                 # is the local API on?
mc api enable                 # it is on by default; this turns it back on
mc daemon restart
```

If you moved or renamed the MC Manager folder, tell the app where the run folder is with the environment variable `MCMANAGER_RUN_DIR` (the `run/` folder of the install) before launching it. Linux Flatpak: it can only see `/opt/mcmanager/run`, so use it with a `.deb` or `.rpm` install, or connect to the machine as a remote.

---

## Updates

```
mc update --check
mc update
mc update --rollback
```

| Message | Cause | What to do |
|---|---|---|
| "Invalid signature for vX: installation refused, nothing was changed." | The release was altered, or this MC Manager carries an older public key | Do not force it. Download the release zip from the [releases page](https://github.com/scirr/MCMANAGER/releases) and run the installer |
| "The downloaded package does not match its hash" | Corrupted download | Retry `mc update`; nothing was changed |
| "Release vX is not signed: installation refused." | Releases before 2.7.0 are not signed | `mc update --rollback` to return to the previous version |
| "The package is not listed in SHA256SUMS" / "Invalid package" | A broken release | Retry later and report it on the issue tracker |
| "Cannot reach GitHub to check for updates (offline?)" | No connection | Check the network and retry |
| "Release vX has no package for this platform" | A release lacking your system's file | Report it |
| "MC Manager was installed from a package: update it with your package manager" | `.deb` or `.rpm` install | `sudo apt update && sudo apt install --only-upgrade mcmanager`, or `sudo dnf upgrade mcmanager`, or install the new package file |
| "No previous version kept" | Rollback only exists after an update | Nothing to roll back |
| Windows: permission error | The service needs an administrator terminal | Open Command Prompt as administrator and run `mc update` again |

`mc update` replaces program files only. Servers, worlds, `servers.json`, backups and settings are never touched. It does not reinstall the service definition: when a release changes it, the release notes say so, and `mc doctor` warns ("systemd unit: older version").

To check a download by hand: `sha256sum -c --ignore-missing SHA256SUMS` (see [SECURITY.md](../SECURITY.md)).

---

## Remote access and pairing

| Message | Cause | What to do |
|---|---|---|
| "Wrong, expired or malformed pairing code" | Codes last 5 minutes, work once, and five wrong tries cancel the code | On the server: `mc remote pair` for a new code |
| "Pairing locked after too many failures: try again later" (`pair_locked`) | Ten failures from one address | Wait 15 minutes |
| "Too many requests: try again in a moment" (`rate_limited`) | Rate limit | Wait a moment |
| "The server certificate does not match the pinned fingerprint" | The remote certificate changed, or someone is in the middle | Check the fingerprint on the remote (`mc remote status`); to re-trust it, `mc remote forget <profile>` then `mc remote add <profile> <host:port>` |
| "Access refused: pair this device again" / `device_revoked` | The device was revoked | Pair again |
| "Operation not allowed for this device" (`forbidden`) | The role is too low | An administrator changes the role in the app (System, Devices), or on the server revoke the device (`mc remote devices list`, `mc remote devices revoke <id>`) and pair it again with `mc remote pair --role operator` (see [Roles](APPS.md#roles)) |
| "The remote server cannot be reached" | Remote access is off, wrong port, or a firewall | On the server `mc remote status`; enable with `mc remote enable`; open the TCP port (default 8765) |
| "Cannot create the TLS certificate" (`tls_unavailable`) | Neither the `cryptography` module nor `openssl` is available | Install `openssl` or `python3-cryptography`; remote access stays off until then |

---

## Windows SmartScreen

`MCManager-Setup.exe` is signed only when the release was built with a certificate. Otherwise SmartScreen shows "Windows protected your PC". It is expected for an unsigned installer. Choose *More info*, then *Run anyway*. Verify the file first against `SHA256SUMS` from the release if you want to be sure: `certutil -hashfile MCManager-Setup.exe SHA256`.

## macOS Gatekeeper

`MCManager.app` is neither signed nor notarized, so the first launch is blocked ("cannot be opened because the developer cannot be verified"). Right-click (Control-click) the app, choose **Open**, then **Open** in the dialog. Or open System Settings, Privacy & Security, scroll to the message about MCManager and click **Open Anyway**. The shell scripts of the zip package are un-quarantined by `install.sh`; if you run them from a freshly downloaded folder on another path, run `xattr -dr com.apple.quarantine ~/MCManager` first.

---

## Still stuck

Collect `mc version`, `mc doctor --json` and the last lines of `mc logs`, then open an issue at <https://github.com/scirr/MCMANAGER/issues>. Do not paste passwords, webhook URLs or pairing codes. For a security problem, follow [SECURITY.md](../SECURITY.md) instead.
