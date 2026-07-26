import copy
import json
import os
import re
import shutil
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

from mc_lang import T

# Optional shared data directory. Set MCMANAGER_DATA_DIR to a folder on a disk
# shared between Windows and Linux (same physical folder, addressed by each OS's
# own path) and both installs use the same registry and server locations. Server
# paths are then stored relative to this dir so they resolve on either OS. When
# unset, behaviour is unchanged: a local registry next to the app.
_SHARED_DATA_DIR = os.environ.get("MCMANAGER_DATA_DIR", "").strip()
if _SHARED_DATA_DIR:
    DATA_DIR = os.path.abspath(os.path.expanduser(_SHARED_DATA_DIR))
    REGISTRY_FILE = os.path.join(DATA_DIR, "servers.json")
    DATA_ROOT = os.path.join(DATA_DIR, "Servers")
else:
    REGISTRY_FILE = os.path.join(BASE_DIR, "servers.json")
    DATA_ROOT = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "MCManager", "Servers")

# Directory the registry lives in — the anchor for portable (relative) paths.
REGISTRY_DIR = os.path.dirname(REGISTRY_FILE)

_EMPTY_REGISTRY = {"active": None, "next_id": 1, "servers": {}}


def _atomic_write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp_path = path + ".tmp"
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    os.replace(tmp_path, path)


def to_portable(dossier):
    """Return the on-disk (stored) form of a server folder.

    If the folder lives under the registry directory, store it relative with
    forward slashes so the same string resolves on Windows and Linux from a
    shared disk. Otherwise store an absolute path (only valid on this OS).
    """
    if not dossier:
        return ""
    absp = os.path.abspath(os.path.expanduser(dossier))
    try:
        rel = os.path.relpath(absp, REGISTRY_DIR)
    except ValueError:
        return absp  # different drive — not relativisable
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        return absp  # outside the registry dir — not portable
    return rel.replace(os.sep, "/")


def resolve_path(stored):
    """Resolve a stored server path to an absolute path for the current OS."""
    if not stored:
        return ""
    # POSIX absolute path written by Linux for a server outside the shared disk
    # → leave as-is; it will appear as "folder not found" on Windows.
    if stored.startswith("/"):
        return stored
    s = os.path.expanduser(stored)
    if os.path.isabs(s):        # Windows drive letter or UNC
        return os.path.abspath(s)
    s = s.replace("\\", os.sep).replace("/", os.sep)
    return os.path.abspath(os.path.join(REGISTRY_DIR, s))


def _same_dir(a, b):
    return os.path.normcase(resolve_path(a)) == os.path.normcase(resolve_path(b))


def load_registry():
    if not os.path.exists(REGISTRY_FILE):
        return copy.deepcopy(_EMPTY_REGISTRY)
    try:
        with open(REGISTRY_FILE, 'r', encoding='utf-8') as f:
            registry = json.load(f)
    except Exception:
        return copy.deepcopy(_EMPTY_REGISTRY)
    registry.setdefault("active", None)
    registry.setdefault("next_id", 1)
    registry.setdefault("servers", {})

    # Resolve stored (possibly portable/relative) paths to absolute for this OS
    # so every in-memory consumer sees a real path without knowing about sharing.
    for info in registry["servers"].values():
        if "dossier_serveur" in info:
            info["dossier_serveur"] = resolve_path(info["dossier_serveur"])

    missing_id = [info for info in registry["servers"].values() if "id" not in info]
    if missing_id:
        for info in missing_id:
            info["id"] = registry["next_id"]
            registry["next_id"] += 1
        save_registry(registry)

    return registry


def save_registry(registry):
    # Persist paths in portable form (relative to the registry dir when possible)
    # without disturbing the caller's in-memory absolute paths.
    to_write = copy.deepcopy(registry)
    for info in to_write.get("servers", {}).values():
        if "dossier_serveur" in info:
            info["dossier_serveur"] = to_portable(info["dossier_serveur"])
    _atomic_write_json(REGISTRY_FILE, to_write)


def slugify(name, existing_keys=()):
    slug = name.strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", slug).strip("-")
    if not slug:
        slug = "server"
    if slug not in existing_keys:
        return slug
    i = 2
    while f"{slug}-{i}" in existing_keys:
        i += 1
    return f"{slug}-{i}"


def register_server(name, dossier_serveur, port=None, rcon_port=None, set_active=True):
    registry = load_registry()
    existing_key = None
    for key, info in registry["servers"].items():
        if _same_dir(info.get("dossier_serveur", ""), dossier_serveur):
            existing_key = key
            break

    if existing_key:
        slug = existing_key
    else:
        slug = slugify(name, registry["servers"].keys())

    entry = registry["servers"].get(slug, {})
    if "id" not in entry:
        entry["id"] = registry["next_id"]
        registry["next_id"] += 1
    entry["dossier_serveur"] = os.path.abspath(os.path.expanduser(dossier_serveur))
    if port is not None:
        entry["port"] = port
    if rcon_port is not None:
        entry["rcon_port"] = rcon_port
    registry["servers"][slug] = entry

    if set_active or not registry.get("active"):
        registry["active"] = slug

    save_registry(registry)
    return slug


def set_dossier(name, dossier_serveur):
    registry = load_registry()
    if name not in registry["servers"]:
        return False
    registry["servers"][name]["dossier_serveur"] = os.path.abspath(os.path.expanduser(dossier_serveur))
    save_registry(registry)
    return True


def update_cached_ports(dossier_serveur, port=None, rcon_port=None):
    registry = load_registry()
    changed = False
    for info in registry["servers"].values():
        if _same_dir(info.get("dossier_serveur", ""), dossier_serveur):
            if port is not None and info.get("port") != port:
                info["port"] = port
                changed = True
            if rcon_port is not None and info.get("rcon_port") != rcon_port:
                info["rcon_port"] = rcon_port
                changed = True
    if changed:
        save_registry(registry)


def get_active_name():
    return load_registry().get("active")


def _lookup_key(servers, target):
    if target is None:
        return None
    target = str(target)
    if target.isdigit():
        wanted_id = int(target)
        for key, info in servers.items():
            if info.get("id") == wanted_id:
                return key
        return None
    return target if target in servers else None


def _format_available(servers):
    return ", ".join(f"{info.get('id', '?')}:{name}" for name, info in servers.items()) or T["no_servers_available"]


def set_active(target):
    registry = load_registry()
    key = _lookup_key(registry["servers"], target)
    if not key:
        return False
    registry["active"] = key
    save_registry(registry)
    return True


def remove_server(target):
    registry = load_registry()
    servers = registry["servers"]
    key = _lookup_key(servers, target)
    if not key:
        return False, T["server_not_found"].format(target=target, avail=_format_available(servers)), None

    dossier = servers[key].get("dossier_serveur", "")
    del servers[key]

    if registry.get("active") == key:
        registry["active"] = next(iter(servers), None)

    save_registry(registry)
    return True, key, dossier


def list_servers():
    return load_registry().get("servers", {})


def resolve_target(target=None, require_folder=True):
    registry = load_registry()
    servers = registry.get("servers", {})
    if not servers:
        print(f"\033[93m[{T['icon_warn']}]\033[0m {T['no_server_configured']}")
        return None

    if target is None:
        name = registry.get("active")
        if not name or name not in servers:
            print(f"\033[93m[{T['icon_warn']}]\033[0m {T['no_active_server'].format(avail=_format_available(servers))}")
            return None
    else:
        name = _lookup_key(servers, target)
        if not name:
            print(f"\033[93m[{T['icon_warn']}]\033[0m {T['server_not_found'].format(target=target, avail=_format_available(servers))}")
            return None

    dossier_serveur = servers[name].get("dossier_serveur", "")
    if require_folder and (not dossier_serveur or not os.path.exists(dossier_serveur)):
        print(f"\033[91m[{T['icon_err']}]\033[0m {T['server_dir_gone'].format(name=name, path=dossier_serveur)}")
        print(f"\033[90m[{T['icon_info']}]\033[0m {T['check_path_or_use']}")
        return None

    return name, dossier_serveur


def find_port_conflict(port=None, rcon_port=None, exclude_name=None):
    for name, info in list_servers().items():
        if name == exclude_name:
            continue
        if port is not None and str(info.get("port")) == str(port):
            return name
        if rcon_port is not None and str(info.get("rcon_port")) == str(rcon_port):
            return name
    return None


def stop_all_running():
    import mc_core
    import mc_config
    for name, info in list_servers().items():
        dossier = info.get("dossier_serveur", "")
        if not dossier or not os.path.exists(dossier):
            continue
        config = mc_config.load_config(dossier)
        config["dossier_serveur"] = dossier
        if mc_core.is_server_running(config):
            print(T["stopping_server"].format(name=name))
            mc_core.stop_server(config, manual=False)


def print_data_locations():
    import mc_config
    servers = list_servers()
    if not servers:
        return
    for name, info in servers.items():
        dossier = info.get("dossier_serveur", "")
        backup = ""
        if dossier and os.path.exists(dossier):
            config = mc_config.load_config(dossier)
            backup = config.get("dossier_backup", "")
        line = f"  - {name} : {dossier}"
        if backup:
            line += f"  (backup : {backup})"
        print(line)


def migrate_legacy_single_server():
    if os.path.exists(REGISTRY_FILE):
        return

    legacy_config = os.path.join(BASE_DIR, "config.json")
    if not os.path.exists(legacy_config):
        save_registry(copy.deepcopy(_EMPTY_REGISTRY))
        return

    try:
        with open(legacy_config, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except Exception:
        save_registry(copy.deepcopy(_EMPTY_REGISTRY))
        return

    dossier_serveur = config.get("dossier_serveur", "")
    if not dossier_serveur or not os.path.exists(dossier_serveur):
        save_registry(copy.deepcopy(_EMPTY_REGISTRY))
        return

    name = config.get("nom_serveur", "default")
    legacy_webhooks = os.path.join(BASE_DIR, "webhooks.json")
    legacy_pid = os.path.join(BASE_DIR, "server.pid")

    new_config_path = os.path.join(dossier_serveur, "config.json")
    new_webhooks_path = os.path.join(dossier_serveur, "webhooks.json")
    new_pid_path = os.path.join(dossier_serveur, "server.pid")

    if not os.path.exists(new_config_path):
        shutil.copy2(legacy_config, new_config_path)
    if os.path.exists(legacy_webhooks) and not os.path.exists(new_webhooks_path):
        shutil.copy2(legacy_webhooks, new_webhooks_path)
    if os.path.exists(legacy_pid) and not os.path.exists(new_pid_path):
        shutil.copy2(legacy_pid, new_pid_path)

    if not os.path.exists(new_config_path):
        return

    register_server(
        name, dossier_serveur,
        port=config.get("port"), rcon_port=config.get("rcon_port"),
        set_active=True
    )

    os.remove(legacy_config)
    if os.path.exists(legacy_webhooks) and os.path.exists(new_webhooks_path):
        os.remove(legacy_webhooks)
    if os.path.exists(legacy_pid) and os.path.exists(new_pid_path):
        os.remove(legacy_pid)

    print(f"\033[92m[{T['icon_ok']}]\033[0m {T['legacy_migrated'].format(name=name, path=dossier_serveur)}")
