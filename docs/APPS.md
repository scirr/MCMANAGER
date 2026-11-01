# Desktop applications

MC Manager has a native desktop app on each system. All three are windows onto the MC Manager daemon: they show and drive the same servers as the `mc` command, on this machine or on a remote one. Nothing runs without the daemon, so install the command-line package first (see the guide for your system: [Windows](../Windows/README_Windows.md), [Linux](../Linux/README_Linux.md), [macOS](../macOS/README_macOS.md)).

| | Windows | Linux | macOS |
|---|---|---|---|
| Toolkit | WinUI 3 | GTK 4 and libadwaita | SwiftUI |
| Requires | Windows 10 (1809) or later, 64-bit | GTK 4, libadwaita, PyGObject | macOS 14 or later |
| Where it comes from | `MCManager-Setup.exe` | `.deb` / `.rpm`, the `app/` folder of `MCManager-Linux.zip`, or the Flatpak | `MCManager-App-macOS.zip` |
| Start it | Start menu, **MC Manager** | menu entry **MC Manager**, or `mcmanager-app` | `MCManager.app` |
| Languages | English, French | English, French | English, French |

The app follows the language of the system. Labels quoted in this guide are the English ones; a few differ slightly between systems.

---

## Installing and starting

**Windows.** `MCManager-Setup.exe` installs the daemon, the `mc` command and the app. If SmartScreen shows "Windows protected your PC", choose *More info*, then *Run anyway* (see [Troubleshooting](TROUBLESHOOTING.md#windows-smartscreen)).

**Linux.** The `.deb` and `.rpm` packages install the app (`mcmanager-app`) with GTK as a recommended package. With the zip, run `./mcmanager-app` from the MC Manager folder; it needs `python3-gi`, `gir1.2-gtk-4.0` and `gir1.2-adw-1` (Fedora: `python3-gobject`, `gtk4`, `libadwaita`). The Flatpak (`io.github.scirr.MCManager`) talks to the daemon of a package install in `/opt/mcmanager`, and reaches remote machines over the network.

**macOS.** Unzip `MCManager-App-macOS.zip`, drag `MCManager.app` to Applications, and on the first launch right-click it, choose **Open**, then **Open** again (the app is not signed or notarized; see [Troubleshooting](TROUBLESHOOTING.md#macos-gatekeeper)).

**If the app finds no daemon.** It shows "MC Manager not found" or "Cannot reach MC Manager. Is the daemon running?" (wording varies by system). Start the service (`mc daemon start`) and refresh. See [the app does not connect](TROUBLESHOOTING.md#the-app-does-not-connect-to-the-daemon).

On Linux the welcome page asks which MC Manager to control (**This machine** or **A remote server**) and remembers the choice; on Windows the *Connection* page offers **This machine** and the saved remotes; macOS starts on **This Mac**. To control another computer, see [Connecting to a remote MC Manager](#connecting-to-a-remote-mc-manager).

---

## Layout

- **Server list** (left): every server with its state: Running, Starting, Crashed, Stopped, Closed, Sleeping, Maintenance. It updates live. The buttons at the top refresh the list and create a server.
- **Server page** (right): the actions of the server and its tabs.
- **System**: settings that belong to the whole MC Manager, not to one server.

| System | Opening the pages |
|---|---|
| Windows | Navigation on the left: **Servers**, **Connection**, **System** |
| Linux | Server list, with the main menu (top right) holding **System**, **This machine** and **A remote server** |
| macOS | Toolbar of the server list: **New server**, **System**, **Refresh**, and the connection menu (**This Mac** or a remote) |

### Server actions

**Start**, **Stop** and **Restart** apply to the selected server and are enabled only when they make sense for its state. Two more actions appear on all three systems:

- **Resume** (Windows, macOS, Linux) appears enabled while the server is in Maintenance; it leaves maintenance like `mc resume`.
- **Wake** (Windows, macOS, Linux) appears on a sleeping server.

While an action runs, the buttons show "In progress...". A toast or message confirms the result ("Server started", "Server stopped", "Server restarted").

---

## The server tabs

Tabs are in this order: Console, Players, Backups, Mods, Datapacks, World, Tasks, Alerts, Settings.

### Console

A live view of the server console (log lines as they arrive) and a field to type a command and send it (**Send command**). The console is available while the server runs; otherwise it says so. Commands go through RCON, like `mc console`.

### Players

Three lists: **Whitelist**, **Operators**, **Banned players**. Type a player name and **Add**, or remove an entry. Players online are listed with a **Kick** button. Equivalent to `mc whitelist`, `mc op`, `mc ban` and `mc kick`. It works with the server stopped (the file is edited) or running (through RCON).

### Backups

Lists the backups with their origin: *Noon (automatic)*, *Midnight (automatic)*, *Manual*, *Before a restore*, *Before an update*, and an "encrypted" mark.

- **Back up now** creates a backup.
- **Restore** asks for confirmation, stops the server, replaces the world with the backup, and keeps a safety copy first.

Retention and destinations are set in the Settings tab (retention) and with `mc backup` (remote destinations such as sftp, S3 and restic are not in the apps).

### Mods

- **Install a mod**: type a name, a URL or the path of a `.jar`, pick the **Source** (Automatic, Modrinth, CurseForge, Hangar) and **Install**. Dependencies are resolved like `mc mod add`. **Server only** keeps a local `.jar` from being offered to players.
- **Update all**, or update one mod.
- **Remove** moves the mod to the quarantine folder of the server. A mod marked "adds blocks" asks for a second confirmation, because removing it turns its blocks into air.
- **Update the modpack** applies to a server installed from a modpack (button in this tab).

After changes the app shows "Restart the server to apply."

### Datapacks

Each datapack shows Enabled or Disabled, with **Enable** and **Disable**. **Position when enabling** is Default, After built-in packs, Last or Before vanilla. Problems are flagged: "Folder nested one level too deep", "Not a datapack", "changes world generation". When the server is stopped the state shows as unknown. Datapacks are managed live: the server has to be running to enable or disable one.

### World

Shows the size of each world and the total, with **Reset** for a dimension (Nether, End; the Overworld asks for a stronger confirmation). Reset deletes and regenerates the dimension and **does not make a backup first**. **Pre-generation** (needs the Chunky mod and a running server) takes a radius in blocks and an optional centre `x,z`, and shows progress. Equivalent to `mc world`.

### Tasks

Scheduled tasks of the server: **New task** with an action (Restart, Backup, Command, Stop, Start), a 5-field cron schedule, an optional name, a command (for the Command action) and warning durations such as `10m,1m` (restart and stop only). Each task shows its next run and the result of the last one, and can be enabled, disabled, **run now** or deleted. Equivalent to `mc task`.

### Alerts

Messages sent when something happens to this server. **Add a channel** by type: Email (SMTP server, port, user, password, sender, recipients), Telegram (token, chat identifier), ntfy (server, topic), Webhook (URL, optional signing secret) or Discord. Pick the **Events**: Start, Stop, Crash, Crash loop, Backup failed, Update, Sleep, Wake. None selected means every event. **Send a test to every channel** checks delivery; a failing channel is named. Equivalent to `mc alert`. Passwords and tokens are never shown again after saving.

### Settings

Grouped sections; **Secrets** are write-only ("configured" / "not set").

- **General**: server name, domain.
- **Network**: port, RCON port.
- **Performance**: memory (for example `4G`), CPU affinity, jar file, stop timeout.
- **Backups**: backup folder, retention in days, number of backups to keep.
- **Operation**: **Mode** (Opening hours, Always on, Maintenance) and the open and close times (`HH:MM`); **Java**: automatic, system, or an installed version.
- **Secrets**: RCON password, webhook URL, CurseForge API key, backup encryption key file. Type a new value to replace it; empty leaves it unchanged.
- **Advanced**: internal port for the sleep hold mode, metrics address and whether metrics are reachable remotely.
- **Sleep**: **Sleep when idle**, idle time before sleeping (minutes, at least 5), **When a player joins a sleeping server** (refuse the connection while it wakes, or hold the connection until it is up), and **Freeze instead of stopping** (needs hold mode; not available on a Windows server). Sleep needs RCON to count players.

Changes to the port, memory or Java apply at the next restart.

---

## Creating a server

Use **New server** (the plus button of the server list). Windows and macOS use a three-step wizard (name and software, resources, summary and EULA); Linux shows one form.

1. **Name and software.** Server name (empty with a modpack: the modpack name), **Server software**, Minecraft version (empty: latest). All three apps offer Vanilla, Paper, Purpur, Spigot, Folia, Fabric, Quilt, Forge, NeoForge and the Velocity, Waterfall and BungeeCord proxies. For a **modpack**, enter its name or address and use **Look up the modpack**: the app shows what it found (Modrinth, CurseForge, FTB; CurseForge needs an API key, set under Settings, Secrets). The software and version then come from the pack.
2. **Resources.** Memory (for example `4G`), port and RCON port (empty: automatic).
3. **EULA.** Tick **I accept the Minecraft EULA** (required). Then **Create the server**.

The files are downloaded and installed in the background as a job; the server appears in the list when ready. Equivalent to `mc deploy`. Errors name the problem: "This port is already in use", "The target folder is not empty", "Unknown Minecraft version".

---

## The System page

Six tabs, the same on the three systems. Viewing Java, the router, updates and diagnostics is open to every role; changing them, and the whole Devices tab, needs **administrator** (see [Roles](#roles)).

- **Java**: the runtimes MC Manager installed and which servers use each one. **Install** a version, or **Remove** one (servers that use it will not start until you pick another). Equivalent to `mc java`.
- **Devices**: remote access and paired devices (see below).
- **Router**: one public port in front of several servers, chosen by the host name the player types. Switch the router on or off, pick the default server, add or remove **routes** (host name to server), and keep **allow** and **deny** address ranges (CIDR). "Restart needed" is shown when a server must restart to move to its internal port. Equivalent to `mc router`.
- **Update**: the installed version and the latest release. **Check again**, **Install the update** (verified by signature and checksum; running servers are not stopped), or **Go back to the previous version**. The app updates the MC Manager core only, not itself. Equivalent to `mc update`.
- **Diagnostics**: **Run the diagnostics** checks the machine and every server and lists each finding with a "Fix" command. Equivalent to `mc doctor`; see [Troubleshooting](TROUBLESHOOTING.md#mc-doctor).
- **Notifications**: see below.

---

## Remote access and pairing

### Allowing others to control this machine

In **System, Devices**, switch on **Allow remote access**. The tab shows the **Certificate fingerprint** (SHA-256) that clients must check. **Pair a device** generates a single-use 8-digit code, valid for a few minutes: set an optional device name and a **role**, then **Generate a code**. Switching remote access on and generating codes work only from this machine: a remote device cannot do it, and the app hides these controls when connected remotely. Equivalent to `mc remote enable` and `mc remote pair`. The port must be reachable by the other computer (default 8765).

Under **Paired devices** you can change a device's role or **Revoke** it (immediate, open connections are closed). **Recent activity** shows the audit log: who did what, and what was refused.

### Connecting to a remote MC Manager

On the machine you are sitting at:

1. Open the connection chooser: Windows **Connection**, Linux main menu **A remote server**, macOS the connection menu then **Add a remote...**.
2. Enter the **address** (`host:port`) and continue.
3. The app shows the server's **certificate fingerprint**. Compare it with the one on the remote machine (`mc remote status`, or System, Devices) and choose **Trust this fingerprint** only if they are identical (otherwise **Reject**).
4. Enter the **pairing code** (8 digits) and a **name for this device**, then **Pair**.

The fingerprint is pinned: if the remote certificate ever changes, the app refuses with "The server certificate does not match the pinned fingerprint". Switch between machines with **This machine** / **This Mac** and the saved remote; macOS also has **Remove this remote**. Equivalent to `mc remote add` and `mc --remote`.

---

## Roles

A paired device has a role per server. On this machine you are administrator.

| Role | Can |
|---|---|
| **Viewer** | See servers, state, players, backups, mods, datapacks, worlds, tasks, settings, alert channels, Java, router, update status and diagnostics. No console. |
| **Operator** | Everything a viewer can, plus start, stop, restart, resume and wake a server, use the console, edit the whitelist, operators and bans, kick, create a backup, run a task now, and send test alerts. |
| **Administrator** | Everything: restore backups, install, update and remove mods, enable datapacks, reset worlds and pre-generate, create and delete tasks, change settings, mode, hours and sleep, create servers, add and remove alert channels, manage Java, the router and updates, and manage devices, remote access and the audit log. |

When a role is not enough the app hides the control or shows "Your role does not allow this action" ("This device is not allowed to do this" on Windows). "Access refused: pair this device again" means the device was revoked: pair it again.

---

## Notifications

**System, Notifications** controls system notifications, sent only while the window is in the background:

| Switch | Default | Message |
|---|---|---|
| A server crashes | on | "<server> crashed" or "<server> keeps crashing" |
| A backup fails | on | "Backup of <server> failed" |
| A player connects | off | "Player connected on <server>" |

They are built from the daemon's event stream. Windows keeps the choices in `%APPDATA%\MCManager\notifications.json`, Linux in `~/.config/mcmanager-app/notifications.json`, macOS in the app preferences. On macOS the system asks you to allow notifications for the app.

---

## What the apps do not do

Some commands exist only in the `mc` command: freeze and thaw, switching the active server, shutdown announcements, the whitelist on/off switch, upgrading Minecraft, removing a server from the registry, world export and import, remote backup destinations, the static status page, metrics, daemon logs, and the list of long jobs. See the command list in the [Linux guide](../Linux/README_Linux.md#available-commands).
