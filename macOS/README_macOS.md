# MC Manager — macOS

Minecraft server manager for macOS 13 and later (Apple Silicon and Intel), driven by a per-user launchd service (LaunchAgent) and a global `mc` command. Same commands as the Linux and Windows editions.

---

## Requirements

- macOS 13 or later
- Python 3.10+ (`xcode-select --install` or `brew install python`)
- Java 21: `brew install --cask temurin@21`, or let MC Manager download one with `mc java install 21`
- [Pillow](https://python-pillow.org/) (optional, only for `mc image` — installed by `install.sh`)

---

## Installation

1. Unzip `MCManager-macOS.zip` in your home folder (this gives `~/MCManager`).
2. Run the installer **without sudo**:

```bash
cd ~/MCManager
./install.sh
```

3. Open a **new** terminal and create your first server:

```
mc deploy
```

The installer creates `~/Library/LaunchAgents/io.github.scirr.mcmanager.plist` (started at login, restarted if it stops) and the `mc` command in `/usr/local/bin/mc`, or in `~/bin/mc` when `/usr/local/bin` is not writable (add `~/bin` to your `PATH` in that case).

Restarting the service never stops your Minecraft servers (`AbandonProcessGroup`).

---

## Where things live

| | Path |
|---|---|
| Servers | `~/Library/Application Support/MCManager/Servers` |
| Downloaded Java runtimes and build tools | `~/Library/Caches/MCManager` |
| Service definition | `~/Library/LaunchAgents/io.github.scirr.mcmanager.plist` |
| Daemon log | `~/MCManager/logs/` |

---

## Firewall

The macOS application firewall filters per application, not per port, so MC Manager cannot open a game port by itself. If the firewall is on and players cannot connect, allow Java:

```bash
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --add "$(command -v java)"
sudo /usr/libexec/ApplicationFirewall/socketfilterfw --unblockapp "$(command -v java)"
```

On first launch macOS may also ask whether Java may accept incoming connections: answer Allow.

---

## Service

```
mc daemon start | stop | restart | status
```

`mc daemon stop` unloads the LaunchAgent until the next `mc daemon start` or login. The daemon only runs while you are logged in; a Mac that sleeps pauses its servers.

---

## Uninstall

```bash
cd ~/MCManager
./uninstall.sh
```

Your servers, worlds and backups are never deleted.
