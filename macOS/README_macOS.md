# MC Manager — macOS

Minecraft server manager for macOS 13 and later (Apple Silicon and Intel). It runs as a per-user launchd service (LaunchAgent) and a global `mc` command. The commands, the settings and the JSON output are the same as on Linux and Windows.

This guide covers what is specific to macOS. For everything else it points to the matching section of the [Linux guide](../Linux/README_Linux.md); read those sections as written, replacing the systemd service with the LaunchAgent and the Linux paths with the ones below.

| Topic | Where to read it |
|---|---|
| Creating, adding and reconfiguring a server | [Getting started](../Linux/README_Linux.md#getting-started), [`mc deploy`](../Linux/README_Linux.md#deploying-a-new-server-mc-deploy), [`mc add`](../Linux/README_Linux.md#adding-an-existing-server-mc-add), [`mc configure`](../Linux/README_Linux.md#reconfiguring-a-server-mc-configure) |
| Several servers, active server | [Multi-server](../Linux/README_Linux.md#multi-server), [Switching servers](../Linux/README_Linux.md#switching-servers-mc-switch) |
| All commands, exit codes | [Available commands](../Linux/README_Linux.md#available-commands), [Exit codes](../Linux/README_Linux.md#exit-codes) |
| Server states, monitoring | [Server states](../Linux/README_Linux.md#server-states), [Monitoring](../Linux/README_Linux.md#monitoring) |
| Players, worlds, tasks | [Players, worlds and scheduled tasks](../Linux/README_Linux.md#players-worlds-and-scheduled-tasks) |
| Mods, datapacks, modpacks, Java | [Datapacks and mods](../Linux/README_Linux.md#datapacks-and-mods), [Server types](../Linux/README_Linux.md#server-types) |
| Sleep mode | [Sleep mode](../Linux/README_Linux.md#sleep-mode) |
| Router | [Router](../Linux/README_Linux.md#router-mc-router) |
| Modes (schedule, always-on, maintenance) | [Modes](../Linux/README_Linux.md#modes-schedule--always-on--maintenance) |
| Backups, alerts | [Backups](../Linux/README_Linux.md#backups), [Alerts](../Linux/README_Linux.md#alerts-mc-alert) |
| Players from the internet | [Making the server accessible](../Linux/README_Linux.md#making-the-server-accessible-networking) |
| Local API, remote access | [Local API](../Linux/README_Linux.md#local-api), [Remote access](../Linux/README_Linux.md#remote-access) |
| Configuration, language, RCON console | [Configuration](../Linux/README_Linux.md#configuration-configjson), [Language](../Linux/README_Linux.md#language-fr--en), [RCON console](../Linux/README_Linux.md#rcon-console-mc-console) |

---

## Requirements

- macOS 13 or later (the desktop app needs macOS 14 or later)
- Python 3.10 or later: `xcode-select --install` or `brew install python`
- Java: MC Manager downloads the right runtime for each server (`mc java install <version>`, see [Java](../Linux/README_Linux.md#java)); you can also install one yourself, for example `brew install --cask temurin@21`
- [Pillow](https://python-pillow.org/) is optional and only used by `mc image`; `install.sh` installs it

---

## Installation

1. Download `MCManager-macOS.zip` from the [latest release](https://github.com/scirr/MCMANAGER/releases/latest) and unzip it in your home folder. This gives `~/MCManager`.
2. Run the installer **without sudo** (it refuses to run as root, because the service belongs to your user):

```bash
cd ~/MCManager
./install.sh
```

The installer:

1. creates a Python environment in `~/MCManager/venv`;
2. installs Pillow (a failure only disables `mc image`);
3. removes the quarantine flag from the folder, so macOS does not block the scripts;
4. installs the `mc` command in `/usr/local/bin/mc`, or in `~/bin/mc` when `/usr/local/bin` is not writable (then add `~/bin` to your `PATH`: `echo 'export PATH="$HOME/bin:$PATH"' >> ~/.zshrc`);
5. installs and starts the LaunchAgent.

3. Open a **new** terminal and create your first server:

```bash
mc deploy
```

The installer only warns when Java is missing; you need it when you start a server.

---

## The desktop app (MCManager.app)

`MCManager-App-macOS.zip` holds `MCManager.app`, the native app (macOS 14 or later, universal: Apple Silicon and Intel). It does not replace the installation above: it is a window on the daemon that `install.sh` set up, so install the zip package first. The app's tabs are described in [docs/APPS.md](../docs/APPS.md).

1. Unzip `MCManager-App-macOS.zip` and drag `MCManager.app` to Applications.
2. The app is **not signed or notarized**, so Gatekeeper blocks the first launch ("cannot be opened because the developer cannot be verified"). Right-click (or Control-click) the app, choose **Open**, then **Open** again in the dialog. macOS remembers the choice. Alternative: try to open the app once, then go to System Settings, Privacy & Security, and click **Open Anyway**.

If the app opens but shows no servers or an error about the daemon, see [Troubleshooting](../docs/TROUBLESHOOTING.md#the-app-does-not-connect-to-the-daemon).

---

## Where things live

| | Path |
|---|---|
| Program, Python environment | `~/MCManager` (`venv/`, `previous/` kept by `mc update`) |
| Servers (default for `mc deploy`) | `~/Library/Application Support/MCManager/Servers` |
| Downloaded Java runtimes and build tools | `~/Library/Caches/MCManager` |
| Service definition | `~/Library/LaunchAgents/io.github.scirr.mcmanager.plist` |
| Daemon log | `~/MCManager/logs/daemon.log` |
| launchd output (startup errors, tracebacks) | `~/MCManager/logs/launchd.log` |
| Local API socket | `~/MCManager/run/api.sock` |

The server folder is always changeable at the prompt of `mc deploy` and `mc add`. See [Logs](../Linux/README_Linux.md#logs-logs) for the log format.

---

## Service (LaunchAgent)

```bash
mc daemon start | stop | restart | status
```

The agent has `RunAtLoad` and `KeepAlive`: it starts at login and is restarted 10 seconds after a crash. Restarting it never stops your Minecraft servers (`AbandonProcessGroup`).

- `mc daemon stop` unloads the agent until the next `mc daemon start` or login.
- It is a **user** agent: the daemon only runs while you are logged in. Servers set to always-on, schedules, sleep-mode wake-up and backups do not run while you are logged out, and a Mac that sleeps pauses its servers. To keep a Mac available, disable sleep in System Settings, Energy, and stay logged in.
- Inspect launchd directly with `launchctl print gui/$(id -u)/io.github.scirr.mcmanager`.

See [Daemon](../Linux/README_Linux.md#daemon-systemd-service) for what the daemon does.

---

## Firewall

The macOS application firewall filters per application, not per port, so MC Manager cannot open a game port by itself (`mc doctor` and the deploy summary print the command instead). If the firewall is on and players cannot connect, allow Java:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$(command -v java)"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$(command -v java)"
```

On the first launch macOS may also ask whether Java may accept incoming connections: answer Allow. For a runtime downloaded by MC Manager, use the `java` path of the server (`mc java list`). Players outside your network also need a port forward on your router: see [Players on the internet](../Linux/README_Linux.md#players-on-the-internet-outside-your-network).

---

## Updating

```bash
mc update --check     # only check
mc update             # install the latest release
mc update --rollback  # go back to the previous version
```

Same behaviour as [Updating MC Manager](../Linux/README_Linux.md#updating-mc-manager): the release is downloaded as `MCManager-macOS.zip`, its signature and hash are verified, the previous version is kept in `previous/`, and servers, settings and backups are untouched. The daemon restarts itself. `mc update` does not touch the LaunchAgent; when a release changes it, the release notes say to re-run `./install.sh` from `~/MCManager`.

`mc update` never updates `MCManager.app`. Download the new `MCManager-App-macOS.zip` from the release and replace the app in Applications.

---

## Uninstalling

```bash
cd ~/MCManager
./uninstall.sh
```

After a confirmation, the script stops running servers, removes the LaunchAgent and the `mc` command, and deletes the generated files (`logs`, `run`, `previous`, `venv`). It offers to delete `servers.json`, the registry of your servers. The `.py` files stay in `~/MCManager`; delete the folder yourself afterwards. To remove the app, drag `MCManager.app` to the Trash.

Your servers, worlds, mods and backups are never deleted; the script prints where they are.

---

## What differs from Linux and Windows

| | macOS |
|---|---|
| Service | per-user LaunchAgent, not a system service: no sudo, runs only while you are logged in |
| Install | `./install.sh` without sudo; no `.deb`, `.rpm` or Flatpak |
| Firewall | per application (Java), never per port; manual command |
| Data folder | `~/Library/Application Support/MCManager/Servers` |
| Local API | Unix socket `run/api.sock`, like Linux (Windows uses 127.0.0.1 and a token) |
| Logs | `logs/daemon.log` and `logs/launchd.log` (no `journalctl`) |
| Desktop app | `MCManager.app`, unsigned: Gatekeeper needs right-click, Open |
| CPU affinity | not available |
