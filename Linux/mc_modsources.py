"""
mc_modsources.py — Mods and plugins by name: Modrinth, CurseForge, Hangar.

'mc mod add <slug>' picks the newest release compatible with the server's
loader and Minecraft version, verifies its hash, installs its required
dependencies, and records everything in <server>/.mcmanager/content.json so
'mc mod update' knows what came from where. Files land through mc_content,
so the AutoModpack double copy and the quarantine rules still apply.

Client-only mods (Modrinth server_side 'unsupported') are refused; mods that
players do not need (client_side 'unsupported') are kept out of the
AutoModpack modpack.
"""
import json
import os
import shutil
import sys
import tempfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import mc_content
import mc_http
import mc_software

MODRINTH = "https://api.modrinth.com/v2"
CURSEFORGE = "https://api.curseforge.com/v1"
HANGAR = "https://hangar.papermc.io/api/v1"
CF_GAME_ID = 432
CF_CLASS_MODS, CF_CLASS_PLUGINS = 6, 5
CF_LOADER_TYPES = {"Forge": 1, "Fabric": 4, "Quilt": 5, "NeoForge": 6}

# Modrinth loader names accepted by each server type, best first.
MODRINTH_LOADERS = {
    "Fabric": ["fabric"], "Quilt": ["quilt", "fabric"], "Forge": ["forge"], "NeoForge": ["neoforge"],
    "Paper": ["paper", "spigot", "bukkit"], "Purpur": ["purpur", "paper", "spigot", "bukkit"],
    "Folia": ["folia"], "Spigot": ["spigot", "bukkit"],
    "Velocity": ["velocity"], "Waterfall": ["waterfall", "bungeecord"], "BungeeCord": ["bungeecord"],
}
HANGAR_PLATFORMS = {"Paper": "PAPER", "Purpur": "PAPER", "Folia": "PAPER", "Spigot": "PAPER",
                    "Velocity": "VELOCITY", "Waterfall": "WATERFALL", "BungeeCord": "WATERFALL"}


def result(ok, code, **data):
    return {"ok": ok, "code": code, **data}


class SourceError(Exception):
    def __init__(self, code, **data):
        super().__init__(code)
        self.code = code
        self.data = data


# ── server context ───────────────────────────────────────────────────────────

def context(config):
    loader = mc_software.canonical(config.get("loader"))
    if not loader:
        import mc_core
        loader = mc_software.canonical(mc_core.guess_loader_and_version(config)[0])
    if loader not in mc_software.MOD_LOADERS and loader not in mc_software.PLUGIN_LOADERS:
        raise SourceError("no_content_loader", loader=loader or "Vanilla")
    kind = "mod" if loader in mc_software.MOD_LOADERS else "plugin"
    mc_version = None if loader in mc_software.PROXIES else config.get("mc_version")
    return loader, mc_version, kind


def _manifest_path(config):
    return os.path.join(config["dossier_serveur"], ".mcmanager", "content.json")


def load_manifest(config):
    try:
        with open(_manifest_path(config), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"entries": {}}
    except (OSError, ValueError):
        return {"entries": {}}


def save_manifest(config, manifest):
    path = _manifest_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _curseforge_key(config):
    return (config.get("curseforge_api_key") or os.environ.get("CURSEFORGE_API_KEY") or "").strip()


# ── Modrinth ─────────────────────────────────────────────────────────────────

def modrinth_project(slug):
    try:
        return mc_http.get_json(f"{MODRINTH}/project/{slug}")
    except mc_http.HttpError as e:
        if e.status == 404:
            return None
        raise


def modrinth_best_version(project_id, loader, mc_version):
    params = {"loaders": MODRINTH_LOADERS[loader]}
    if mc_version:
        params["game_versions"] = [mc_version]
    versions = mc_http.get_json(mc_http.url(f"{MODRINTH}/project/{project_id}/version", **params))
    if not versions:
        return None
    releases = [v for v in versions if v.get("version_type") == "release"]
    return (releases or versions)[0]


def _modrinth_candidate(project, version):
    files = version.get("files") or []
    primary = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not primary:
        return None
    deps = [{"source": "modrinth", "project": d.get("project_id"), "version": d.get("version_id")}
            for d in version.get("dependencies", []) if d.get("dependency_type") == "required"]
    return {
        "source": "modrinth", "project_id": project["id"], "slug": project.get("slug"),
        "title": project.get("title"), "version_id": version["id"],
        "version": version.get("version_number"), "file": primary["filename"],
        "url": primary["url"], "hashes": {k: v for k, v in (primary.get("hashes") or {}).items()
                                          if k in ("sha512", "sha1")},
        "server_only": project.get("client_side") == "unsupported",
        "dependencies": deps,
    }


def resolve_modrinth(ref, loader, mc_version, version_id=None):
    project = modrinth_project(ref)
    if not project:
        return None
    if project.get("project_type") not in ("mod", "plugin"):
        raise SourceError("not_a_mod", name=project.get("title"), type=project.get("project_type"))
    if project.get("server_side") == "unsupported":
        raise SourceError("client_only", name=project.get("title"))
    if version_id:
        version = mc_http.get_json(f"{MODRINTH}/version/{version_id}")
    else:
        version = modrinth_best_version(project["id"], loader, mc_version)
    if not version:
        raise SourceError("no_compatible_version", name=project.get("title"), loader=loader,
                          mc_version=mc_version or "-")
    return _modrinth_candidate(project, version)


# ── CurseForge (API key required) ────────────────────────────────────────────

def _cf(config, path, **params):
    key = _curseforge_key(config)
    if not key:
        raise SourceError("curseforge_key_missing")
    return mc_http.get_json(mc_http.url(f"{CURSEFORGE}{path}", **params), headers={"x-api-key": key})


def resolve_curseforge(config, ref, loader, mc_version, kind):
    if str(ref).isdigit():
        mod = _cf(config, f"/mods/{ref}")["data"]
    else:
        found = _cf(config, "/mods/search", gameId=CF_GAME_ID, slug=ref,
                    classId=CF_CLASS_MODS if kind == "mod" else CF_CLASS_PLUGINS).get("data") or []
        if not found:
            return None
        mod = found[0]
    params = {"gameVersion": mc_version}
    if loader in CF_LOADER_TYPES:
        params["modLoaderType"] = CF_LOADER_TYPES[loader]
    files = _cf(config, f"/mods/{mod['id']}/files", **params).get("data") or []
    files = [f for f in files if f.get("isAvailable", True)]
    if not files:
        raise SourceError("no_compatible_version", name=mod.get("name"), loader=loader, mc_version=mc_version or "-")
    releases = [f for f in files if f.get("releaseType") == 1]
    chosen = max(releases or files, key=lambda f: f.get("fileDate", ""))
    if not chosen.get("downloadUrl"):
        raise SourceError("curseforge_no_distribution", name=mod.get("name"))
    sha1 = next((h["value"] for h in chosen.get("hashes", []) if h.get("algo") == 1), None)
    deps = [{"source": "curseforge", "project": str(d["modId"]), "version": None}
            for d in chosen.get("dependencies", []) if d.get("relationType") == 3]
    return {
        "source": "curseforge", "project_id": str(mod["id"]), "slug": mod.get("slug"),
        "title": mod.get("name"), "version_id": str(chosen["id"]), "version": chosen.get("displayName"),
        "file": chosen["fileName"], "url": chosen["downloadUrl"], "hashes": {"sha1": sha1} if sha1 else {},
        "server_only": False, "dependencies": deps,
    }


# ── Hangar (Paper, Velocity, Waterfall plugins) ──────────────────────────────

def resolve_hangar(ref, loader, mc_version):
    platform = HANGAR_PLATFORMS.get(loader)
    if not platform:
        return None
    try:
        project = mc_http.get_json(f"{HANGAR}/projects/{ref}")
    except mc_http.HttpError as e:
        if e.status == 404:
            return None
        raise
    params = {"platform": platform, "limit": 25}
    if mc_version:
        params["platformVersion"] = mc_version
    versions = mc_http.get_json(mc_http.url(f"{HANGAR}/projects/{ref}/versions", **params)).get("result") or []
    versions = [v for v in versions if (v.get("downloads") or {}).get(platform)]
    if not versions:
        raise SourceError("no_compatible_version", name=project.get("name", ref), loader=loader,
                          mc_version=mc_version or "-")
    releases = [v for v in versions if str((v.get("channel") or {}).get("name", "")).lower() == "release"]
    version = (releases or versions)[0]
    dl = version["downloads"][platform]
    address = dl.get("downloadUrl") or dl.get("externalUrl")
    if not address:
        raise SourceError("no_compatible_version", name=project.get("name", ref), loader=loader,
                          mc_version=mc_version or "-")
    info = dl.get("fileInfo") or {}
    deps = [{"source": "hangar", "project": d["name"], "version": None}
            for d in (version.get("pluginDependencies") or {}).get(platform, [])
            if d.get("required") and not d.get("externalUrl")]
    return {
        "source": "hangar", "project_id": str(project.get("id", ref)), "slug": project.get("name", ref),
        "title": project.get("name", ref), "version_id": version.get("name"), "version": version.get("name"),
        "file": info.get("name") or f"{ref}-{version.get('name')}.jar", "url": address,
        "hashes": {"sha256": info["sha256Hash"]} if info.get("sha256Hash") else {},
        "server_only": True, "dependencies": deps,
    }


# ── resolution ───────────────────────────────────────────────────────────────

def resolve(config, ref, source=None):
    """Find `ref` (slug, or CurseForge id) for this server. Tries the given
    source, else: plugins -> Hangar then Modrinth; mods -> Modrinth then
    CurseForge (when a key is configured)."""
    loader, mc_version, kind = context(config)
    if source:
        order = [source]
    elif kind == "plugin":
        order = ["hangar", "modrinth"]
    else:
        order = ["modrinth"] + (["curseforge"] if _curseforge_key(config) else [])
    for name in order:
        if name == "modrinth":
            found = resolve_modrinth(ref, loader, mc_version)
        elif name == "curseforge":
            found = resolve_curseforge(config, ref, loader, mc_version, kind)
        elif name == "hangar":
            found = resolve_hangar(ref, loader, mc_version)
        else:
            raise SourceError("unknown_source", source=name)
        if found:
            return found
    raise SourceError("content_not_found", name=ref, sources=", ".join(order))


def _resolve_dependency(config, dep):
    loader, mc_version, kind = context(config)
    if dep["source"] == "modrinth":
        return resolve_modrinth(dep["project"], loader, mc_version, dep.get("version"))
    if dep["source"] == "curseforge":
        return resolve_curseforge(config, dep["project"], loader, mc_version, kind)
    return resolve_hangar(dep["project"], loader, mc_version)


# ── install / update ─────────────────────────────────────────────────────────

def _target_dir(config, kind):
    return os.path.join(config["dossier_serveur"], "mods" if kind == "mod" else "plugins")


def _installed_files(config, kind):
    try:
        return set(os.listdir(_target_dir(config, kind)))
    except FileNotFoundError:
        return set()


def _place(config, kind, candidate, progress=None):
    """Download and put one file in place (both AutoModpack copies for mods)."""
    with tempfile.TemporaryDirectory(dir=config["dossier_serveur"]) as tmp:
        path = os.path.join(tmp, candidate["file"])
        mc_http.download(candidate["url"], path, candidate["hashes"], progress=progress)
        if kind == "mod":
            res = mc_content.mod_add(config, path, server_only=candidate["server_only"])
            if not res["ok"]:
                raise SourceError(res["code"], **{k: v for k, v in res.items() if k not in ("ok", "code")})
        else:
            folder = _target_dir(config, kind)
            os.makedirs(folder, exist_ok=True)
            if os.path.exists(os.path.join(folder, candidate["file"])):
                raise SourceError("mod_exists", file=candidate["file"], folder=folder)
            shutil.copy2(path, os.path.join(folder, candidate["file"]))


def _record(manifest, candidate, kind, required_by=None):
    entry = {k: candidate[k] for k in ("source", "project_id", "slug", "title", "version_id",
                                        "version", "file", "server_only")}
    entry["kind"] = kind
    if required_by:
        entry["required_by"] = required_by
    manifest.setdefault("entries", {})[f"{candidate['source']}:{candidate['project_id']}"] = entry


def add(config, ref, source=None, progress=None):
    """Install `ref` and its required dependencies. Returns a result with the
    list of installed files."""
    try:
        _loader, _mc, kind = context(config)
        root = resolve(config, ref, source)
        manifest = load_manifest(config)
        key = f"{root['source']}:{root['project_id']}"
        if key in manifest.get("entries", {}):
            return result(False, "already_installed", name=root["title"], file=manifest["entries"][key]["file"])
        queue, seen, plan = [(root, None)], {key}, []
        while queue:
            candidate, parent = queue.pop(0)
            plan.append((candidate, parent))
            for dep in candidate["dependencies"]:
                dep_key = f"{dep['source']}:{dep['project']}"
                if dep_key in seen or dep_key in manifest.get("entries", {}):
                    continue
                seen.add(dep_key)
                found = _resolve_dependency(config, dep)
                if not found:
                    raise SourceError("dependency_missing", name=dep["project"], parent=candidate["title"])
                if f"{found['source']}:{found['project_id']}" in manifest.get("entries", {}):
                    continue
                queue.append((found, candidate["title"]))
        present = _installed_files(config, kind)
        installed, skipped = [], []
        for candidate, parent in plan:
            if candidate["file"] in present:
                skipped.append(candidate["file"])
            else:
                _place(config, kind, candidate, progress)
                installed.append(candidate["file"])
            _record(manifest, candidate, kind, parent)
        save_manifest(config, manifest)
    except SourceError as e:
        return result(False, e.code, **e.data)
    except mc_http.HttpError as e:
        return result(False, "source_unreachable", detail=e.detail)
    return result(True, "content_added", name=root["title"], version=root["version"],
                  installed=installed, already_present=skipped, restart_required=True)


def forget(config, file_name):
    """Drop the manifest entry of a file removed with 'mc mod remove'."""
    manifest = load_manifest(config)
    entries = manifest.get("entries", {})
    for key in [k for k, v in entries.items() if v.get("file") == file_name]:
        del entries[key]
    save_manifest(config, manifest)


def update(config, name=None, progress=None):
    """Update one tracked mod/plugin (by slug or file name), or all of them."""
    manifest = load_manifest(config)
    entries = manifest.get("entries", {})
    targets = [(k, v) for k, v in entries.items()
               if name is None or name in (v.get("slug"), v.get("file"), v.get("title"))]
    if name is not None and not targets:
        return result(False, "not_tracked", name=name)
    updated, current, failed = [], [], []
    for key, entry in targets:
        try:
            dep = {"source": entry["source"], "project": entry["slug"] if entry["source"] == "hangar"
                   else entry["project_id"], "version": None}
            latest = _resolve_dependency(config, dep)
            if not latest or latest["version_id"] == entry["version_id"]:
                current.append(entry["file"])
                continue
            kind = entry.get("kind", "mod")
            if kind == "mod":
                removed = mc_content.mod_remove(config, entry["file"], confirm_blocks=True)
                if not removed["ok"] and removed["code"] != "mod_not_found":
                    raise SourceError(removed["code"])
            else:
                old = os.path.join(_target_dir(config, kind), entry["file"])
                if os.path.exists(old):
                    stamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    dest = os.path.join(config["dossier_serveur"], mc_content.QUARANTINE_DIR, stamp, "plugins")
                    os.makedirs(dest, exist_ok=True)
                    shutil.move(old, os.path.join(dest, entry["file"]))
            _place(config, kind, latest, progress)
            _record(manifest, latest, kind, entry.get("required_by"))
            updated.append(f"{entry['file']} -> {latest['file']}")
        except (SourceError, mc_http.HttpError) as e:
            failed.append(f"{entry['file']}: {getattr(e, 'code', None) or getattr(e, 'detail', e)}")
    save_manifest(config, manifest)
    ok = not failed
    return result(ok, "content_updated" if ok else "content_update_partial",
                  updated=updated, current=current, failed=failed, restart_required=bool(updated))
