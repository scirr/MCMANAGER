"""
mc_content.py — Datapacks and mods.

Pure data in, structured results out (see mc_api.result): no printing, so the
CLI and any other front end render the same outcome their own way.

Datapack pitfalls handled here:
- a pack stored in a sub-folder of world/datapacks is ignored by Minecraft
  ("Found non-pack entry"): reported as a problem, never silently listed;
- a pack containing worldgen/ only takes effect after a restart (/reload is
  not enough): flagged, and every enable/disable of it says so;
- 'datapack enable X before Y' refuses to move a pack that is already
  enabled: we disable it first;
- a newly added pack always lands at the end of the list.

Mod pitfalls:
- with AutoModpack, a mod lives in mods/ AND in the host modpack
  (automodpack/host-modpack/main/mods/): removing only one copy keeps
  shipping it to players — both are handled together;
- removal moves files to a quarantine folder instead of deleting them;
- a mod that defines blocks (assets/*/models/block/) turns those blocks into
  air in the world once removed, and the server saves that: removal requires
  an explicit confirmation.
"""
import datetime
import os
import re
import shutil
import zipfile

import mc_core
from mc_api import result

HOST_MODPACK_MODS = os.path.join("automodpack", "host-modpack", "main", "mods")
QUARANTINE_DIR = "mods_quarantine"


# ── datapacks ────────────────────────────────────────────────────────────────

def datapacks_dir(config):
    return os.path.join(config["dossier_serveur"], mc_core._get_level_name(config["dossier_serveur"]), "datapacks")


def _zip_names(path):
    try:
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()
    except Exception:
        return []


def _dir_names(path):
    names = []
    for root, dirs, files in os.walk(path):
        rel = os.path.relpath(root, path).replace(os.sep, "/")
        prefix = "" if rel == "." else rel + "/"
        names += [prefix + d + "/" for d in dirs] + [prefix + f for f in files]
    return names


_WORLDGEN = re.compile(r"^data/[^/]+/worldgen/")


def inspect_pack(path):
    """{"is_pack", "worldgen", "nested"} for one entry of world/datapacks."""
    names = _zip_names(path) if os.path.isfile(path) else _dir_names(path)
    is_pack = "pack.mcmeta" in names
    nested = False
    if not is_pack and os.path.isdir(path):
        nested = any(n.endswith("/pack.mcmeta") or n.endswith(".zip") for n in names)
    return {
        "is_pack": is_pack,
        "worldgen": any(_WORLDGEN.match(n) for n in names),
        "nested": nested,
    }


_BRACKETS = re.compile(r"\[([^\]]+?)(?: \(([^)]*)\))?\]")


def parse_datapack_list(text):
    """['vanilla', 'file/x.zip', ...] in the order the server reports them."""
    return [m.group(1).strip() for m in _BRACKETS.finditer(text or "")]


def _rcon(config, command):
    import mc_api
    return mc_api.rcon_exec(config, command)


def datapack_list(config):
    """Files in world/datapacks merged with the server's live view."""
    folder = datapacks_dir(config)
    running = mc_core.is_server_running(config)
    enabled = None
    if running:
        ok, reply = _rcon(config, "datapack list enabled")
        if ok:
            enabled = parse_datapack_list(reply)
    packs = []
    try:
        entries = sorted(os.listdir(folder))
    except FileNotFoundError:
        entries = []
    for entry in entries:
        path = os.path.join(folder, entry)
        info = inspect_pack(path)
        pack_id = f"file/{entry}"
        problem = None
        if not info["is_pack"]:
            problem = "nested" if info["nested"] else "not_a_pack"
        packs.append({
            "id": pack_id,
            "file": entry,
            "enabled": (pack_id in enabled) if enabled is not None else None,
            "order": enabled.index(pack_id) if enabled and pack_id in enabled else None,
            "worldgen": info["worldgen"],
            "problem": problem,
        })
    builtin = [p for p in (enabled or []) if not p.startswith("file/")]
    return result(True, "ok", running=running, folder=folder, packs=packs,
                  enabled_order=enabled, builtin=builtin)


def _match_pack(packs, name):
    wanted = name[5:] if name.startswith("file/") else name
    for pack in packs:
        if pack["file"] == wanted or os.path.splitext(pack["file"])[0] == wanted:
            return pack
    return None


def datapack_set(config, name, enable=True, before=None, after=None, first=False, last=False):
    """Enable (optionally at a position) or disable a pack, live, over RCON."""
    listing = datapack_list(config)
    if not listing["running"]:
        return result(False, "server_offline")
    if listing["enabled_order"] is None:
        return result(False, "rcon_failed")
    pack = _match_pack(listing["packs"], name)
    if not pack:
        return result(False, "pack_not_found", name=name,
                      available=[p["file"] for p in listing["packs"]])
    if pack["problem"]:
        return result(False, f"pack_{pack['problem']}", name=pack["file"])

    pid = pack["id"]
    if not enable:
        if not pack["enabled"]:
            return result(True, "already_disabled", pack=pack["file"], restart_required=False)
        ok, reply = _rcon(config, f'datapack disable "{pid}"')
        if not ok:
            return result(False, "rcon_failed", detail=reply)
        return result(True, "disabled", pack=pack["file"], restart_required=pack["worldgen"], reply=reply)

    position = ""
    anchor = before or after
    if anchor:
        other = _match_pack(listing["packs"], anchor)
        other_id = other["id"] if other else anchor
        if other_id not in listing["enabled_order"]:
            return result(False, "anchor_not_enabled", anchor=anchor)
        position = f' {"before" if before else "after"} "{other_id}"'
    elif first:
        position = " first"
    elif last:
        position = " last"

    if pack["enabled"]:
        if not position:
            return result(True, "already_enabled", pack=pack["file"], restart_required=False)
        # Minecraft refuses to move an enabled pack: take it out first.
        ok, reply = _rcon(config, f'datapack disable "{pid}"')
        if not ok:
            return result(False, "rcon_failed", detail=reply)
    ok, reply = _rcon(config, f'datapack enable "{pid}"{position}')
    if not ok:
        return result(False, "rcon_failed", detail=reply)
    return result(True, "enabled", pack=pack["file"], restart_required=pack["worldgen"], reply=reply)


# ── mods ─────────────────────────────────────────────────────────────────────

def mod_dirs(config):
    """(server mods dir, host-modpack mods dir or None). Plugin servers
    (Paper, Purpur, Folia, Spigot, proxies) use plugins/ and have no modpack."""
    dossier = config["dossier_serveur"]
    import mc_software
    if mc_software.canonical(config.get("loader")) in mc_software.PLUGIN_LOADERS:
        return os.path.join(dossier, "plugins"), None
    host = os.path.join(dossier, HOST_MODPACK_MODS)
    return os.path.join(dossier, "mods"), (host if os.path.isdir(host) else None)


_BLOCK_MODELS = re.compile(r"^assets/[^/]+/models/block/")


def defines_blocks(jar_path):
    return any(_BLOCK_MODELS.match(n) for n in _zip_names(jar_path))


def _jars(folder):
    try:
        return sorted(f for f in os.listdir(folder) if f.endswith(".jar"))
    except (FileNotFoundError, TypeError):
        return []


def mod_list(config):
    mods_dir, host_dir = mod_dirs(config)
    server, host = set(_jars(mods_dir)), set(_jars(host_dir))
    mods = [{"file": f, "server": f in server, "modpack": f in host} for f in sorted(server | host)]
    return result(True, "ok", mods=mods, mods_dir=mods_dir, modpack_dir=host_dir)


def mod_add(config, source, server_only=False):
    """Copy a jar into mods/ and, unless server_only, into the host modpack."""
    source = os.path.abspath(os.path.expanduser(source))
    if not os.path.isfile(source) or not source.endswith(".jar"):
        return result(False, "not_a_jar", path=source)
    if not zipfile.is_zipfile(source):
        return result(False, "not_a_jar", path=source)
    mods_dir, host_dir = mod_dirs(config)
    name = os.path.basename(source)
    targets = [mods_dir] + ([host_dir] if host_dir and not server_only else [])
    for folder in targets:
        if os.path.exists(os.path.join(folder, name)):
            return result(False, "mod_exists", file=name, folder=folder)
    for folder in targets:
        os.makedirs(folder, exist_ok=True)
        shutil.copy2(source, os.path.join(folder, name))
    return result(True, "added", file=name, copies=targets, restart_required=True)


def _find_mod(config, name):
    listing = mod_list(config)["mods"]
    exact = [m for m in listing if m["file"] == name or m["file"] == name + ".jar"]
    if exact:
        return exact
    low = name.lower()
    return [m for m in listing if low in m["file"].lower()]


def mod_remove(config, name, confirm_blocks=False):
    """Move every copy of a mod to the quarantine folder."""
    matches = _find_mod(config, name)
    if not matches:
        return result(False, "mod_not_found", name=name)
    if len(matches) > 1:
        return result(False, "mod_ambiguous", name=name, candidates=[m["file"] for m in matches])
    mod = matches[0]
    mods_dir, host_dir = mod_dirs(config)
    copies = []
    if mod["server"]:
        copies.append(os.path.join(mods_dir, mod["file"]))
    if mod["modpack"] and host_dir:
        copies.append(os.path.join(host_dir, mod["file"]))

    if not confirm_blocks and any(defines_blocks(p) for p in copies):
        return result(False, "defines_blocks", file=mod["file"])

    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    quarantine = os.path.join(config["dossier_serveur"], QUARANTINE_DIR, stamp)
    moved = []
    for path in copies:
        sub = "modpack" if host_dir and path.startswith(host_dir) else "mods"
        dest_dir = os.path.join(quarantine, sub)
        os.makedirs(dest_dir, exist_ok=True)
        shutil.move(path, os.path.join(dest_dir, mod["file"]))
        moved.append(path)
    return result(True, "removed", file=mod["file"], moved=moved, quarantine=quarantine,
                  restart_required=True)
