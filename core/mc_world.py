"""
mc_world.py — Worlds: dimensions, export, import, reset, Chunky pregeneration.
Nothing here prints.
"""
import datetime
import os
import re
import shutil
import tempfile
import zipfile

import mc_core
from mc_lang import T
from mc_platform import plat

EXPORT_SKIP_NAMES = ("session.lock",)
RESET_FOLDERS = ("region", "entities", "poi")
DIM_FOLDERS = ("DIM-1", "DIM1", "dimensions")


def result(ok, code, **data):
    return {"ok": ok, "code": code, **data}


def level_name(config):
    return mc_core._get_level_name(config["dossier_serveur"])


def world_roots(config):
    """Existing top-level world folders (overworld, Bukkit-style nether/end)."""
    base, level = config["dossier_serveur"], level_name(config)
    names = [level, f"{level}_nether", f"{level}_the_end"]
    return [n for n in names if os.path.isdir(os.path.join(base, n))]


def _tree_size(path, skip=()):
    total = 0
    for root, dirs, files in os.walk(path):
        if root == path:
            dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def dimensions(config):
    """[{id, paths, size_bytes}] for every dimension present on disk."""
    base, level = config["dossier_serveur"], level_name(config)
    found = []
    root = os.path.join(base, level)
    if os.path.isdir(root):
        found.append({"id": "overworld", "paths": [root], "size_bytes": _tree_size(root, DIM_FOLDERS)})
    for dim_id, candidates in (
            ("nether", [os.path.join(root, "DIM-1"), os.path.join(base, f"{level}_nether", "DIM-1")]),
            ("end", [os.path.join(root, "DIM1"), os.path.join(base, f"{level}_the_end", "DIM1")])):
        paths = [p for p in candidates if os.path.isdir(p)]
        if paths:
            found.append({"id": dim_id, "paths": paths, "size_bytes": sum(_tree_size(p) for p in paths)})
    custom = os.path.join(root, "dimensions")
    if os.path.isdir(custom):
        for namespace in sorted(os.listdir(custom)):
            ns_dir = os.path.join(custom, namespace)
            if not os.path.isdir(ns_dir):
                continue
            for name in sorted(os.listdir(ns_dir)):
                path = os.path.join(ns_dir, name)
                if os.path.isdir(path):
                    found.append({"id": f"{namespace}:{name}", "paths": [path], "size_bytes": _tree_size(path)})
    return found


def list_worlds(config):
    return result(True, "world_list", level=level_name(config), dimensions=dimensions(config),
                  size_bytes=sum(d["size_bytes"] for d in dimensions(config)))


def _stopped_or_frozen(config):
    import mc_api
    return (not mc_core.is_server_running(config)) or mc_api.is_frozen(config)


def default_export_name(config):
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.abspath(f"{level_name(config)}_{stamp}.zip")


def export_world(config, output=None):
    if not _stopped_or_frozen(config):
        return result(False, "server_running_not_frozen")
    roots = world_roots(config)
    if not roots:
        return result(False, "no_world")
    output = os.path.abspath(os.path.expanduser(output or default_export_name(config)))
    if os.path.exists(output):
        return result(False, "output_exists", path=output)
    base = config["dossier_serveur"]
    tmp = output + ".part"
    files = 0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in roots:
                for folder, _dirs, names in os.walk(os.path.join(base, name)):
                    for entry in names:
                        if entry in EXPORT_SKIP_NAMES or ".sqlite" in entry:
                            continue
                        full = os.path.join(folder, entry)
                        if os.path.abspath(full) in (output, tmp):
                            continue
                        try:
                            zf.write(full, os.path.relpath(full, base))
                            files += 1
                        except OSError:
                            continue
        plat.atomic_replace(tmp, output)
    except (OSError, zipfile.BadZipFile) as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        return result(False, "export_failed", detail=str(e))
    return result(True, "world_exported", path=output, files=files, size_bytes=os.path.getsize(output))


def _safe_member(name):
    clean = name.replace("\\", "/")
    return not (clean.startswith("/") or re.match(r"^[A-Za-z]:", clean)
                or ".." in clean.split("/"))


def _find_world_root(folder):
    """Shallowest directory under `folder` (itself included) holding level.dat."""
    best = None
    for root, dirs, files in os.walk(folder):
        if "level.dat" in files:
            depth = os.path.relpath(root, folder).count(os.sep) if root != folder else -1
            if best is None or depth < best[0]:
                best = (depth, root)
    return best[1] if best else None


def _backup_before(config, tag):
    if not world_roots(config):
        return None
    ok, message = mc_core.backup_server(config, tag)
    if not ok and message != T["no_world_found"]:
        return message
    return None


def import_world(config, source, confirmed=False):
    if mc_core.is_server_running(config):
        return result(False, "server_running")
    source = os.path.abspath(os.path.expanduser(source))
    if not os.path.exists(source):
        return result(False, "source_missing", path=source)
    base, level = config["dossier_serveur"], level_name(config)
    staging = tempfile.mkdtemp(prefix=".mcmanager_import_", dir=base)
    try:
        if os.path.isdir(source):
            extracted = source
        elif zipfile.is_zipfile(source):
            extracted = os.path.join(staging, "src")
            with zipfile.ZipFile(source) as zf:
                bad = [n for n in zf.namelist() if not _safe_member(n)]
                if bad:
                    return result(False, "unsafe_archive", path=bad[0])
                zf.extractall(extracted)
        else:
            return result(False, "not_an_archive", path=source)
        world = _find_world_root(extracted)
        if not world:
            return result(False, "no_level_dat", path=source)
        if not confirmed:
            return result(False, "confirmation_required", existing=bool(world_roots(config)))
        problem = _backup_before(config, "import")
        if problem:
            return result(False, "backup_failed", message=problem)

        copy = os.path.isdir(source)

        def place(src, dst):
            if copy:
                shutil.copytree(src, dst, symlinks=True)
            else:
                plat.atomic_replace(src, dst)

        parent, world_name = os.path.dirname(world), os.path.basename(world)
        prepared = os.path.join(staging, "new")
        os.makedirs(prepared)
        place(world, os.path.join(prepared, level))
        if world != extracted:
            for suffix in ("_nether", "_the_end"):
                sibling = os.path.join(parent, f"{world_name}{suffix}")
                if os.path.isdir(sibling):
                    place(sibling, os.path.join(prepared, f"{level}{suffix}"))

        aside = os.path.join(staging, "old")
        os.makedirs(aside)
        for name in world_roots(config):
            plat.atomic_replace(os.path.join(base, name), os.path.join(aside, name))
        for name in os.listdir(prepared):
            plat.atomic_replace(os.path.join(prepared, name), os.path.join(base, name))
        return result(True, "world_imported", level=level, source=source)
    except (OSError, zipfile.BadZipFile) as e:
        return result(False, "import_failed", detail=str(e))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def reset_dimension(config, dimension, confirmed=False, include_overworld=False):
    if mc_core.is_server_running(config):
        return result(False, "server_running")
    dims = {d["id"]: d for d in dimensions(config)}
    if dimension not in dims:
        return result(False, "unknown_dimension", dimension=dimension, available=sorted(dims))
    if dimension == "overworld" and not include_overworld:
        return result(False, "overworld_protected")
    if not confirmed:
        return result(False, "confirmation_required", dimension=dimension)
    problem = _backup_before(config, "reset")
    if problem:
        return result(False, "backup_failed", message=problem)
    removed = []
    for path in dims[dimension]["paths"]:
        for folder in RESET_FOLDERS:
            target = os.path.join(path, folder)
            if os.path.isdir(target):
                shutil.rmtree(target)
                removed.append(os.path.relpath(target, config["dossier_serveur"]))
    return result(True, "dimension_reset", dimension=dimension, removed=removed)


# ── Chunky pregeneration ─────────────────────────────────────────────────────

def chunky_installed(config):
    base = config["dossier_serveur"]
    for folder in ("mods", "plugins"):
        path = os.path.join(base, folder)
        if os.path.isdir(path) and any("chunky" in n.lower() for n in os.listdir(path)):
            return True
    return False


def parse_center(text):
    match = re.fullmatch(r"\s*(-?\d+)\s*[,; ]\s*(-?\d+)\s*", text or "")
    if not match:
        raise ValueError(text)
    return int(match.group(1)), int(match.group(2))


def pregen(config, radius, center=None, rcon=None):
    """Start a Chunky generation task around `center` (default: Chunky's own
    default, the world spawn) and return the first progress report."""
    if not chunky_installed(config):
        return result(False, "chunky_missing")
    if not mc_core.is_server_running(config):
        return result(False, "pregen_offline")
    if int(radius) < 1:
        return result(False, "invalid_radius", radius=radius)
    if rcon is None:
        import mc_api
        rcon = lambda cfg, cmd: mc_api.rcon_exec(cfg, cmd, wait=mc_api.RCON_RETRY)
    commands = []
    if center:
        commands.append(f"chunky center {center[0]} {center[1]}")
    commands += [f"chunky radius {int(radius)}", "chunky start"]
    replies = []
    for command in commands:
        ok, reply = rcon(config, command)
        if not ok:
            return result(False, "rcon_failed", detail=reply)
        replies.append(reply)
    ok, progress = rcon(config, "chunky progress")
    return result(True, "pregen_started", radius=int(radius), center=list(center) if center else None,
                  progress=progress if ok else None)


def pregen_progress(config, rcon=None):
    if not chunky_installed(config):
        return result(False, "chunky_missing")
    if not mc_core.is_server_running(config):
        return result(False, "pregen_offline")
    if rcon is None:
        import mc_api
        rcon = lambda cfg, cmd: mc_api.rcon_exec(cfg, cmd, wait=mc_api.RCON_RETRY)
    ok, reply = rcon(config, "chunky progress")
    if not ok:
        return result(False, "rcon_failed", detail=reply)
    return result(True, "pregen_progress", progress=reply)
