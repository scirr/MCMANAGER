"""
mc_modpack.py — Modpacks: Modrinth (.mrpack), CurseForge (server pack) and FTB.

Every source is turned into the same plan — Minecraft version, loader and
loader version, the server-side files with their hashes, and the override
folders — then installed the same way: the right loader through
mc_software, each file verified, client-only files skipped, paths confined to
the server folder. The installed pack is recorded in config.json
('modpack'), so 'mc modpack update' knows what to replace.

Sources:
  <file>.mrpack | https://....mrpack | modrinth:<slug>[@<version>] | <slug>
  curseforge:<slug|id>[@<fileId>]    (API key: mc config set curseforge_api_key)
  ftb:<id>[@<versionId>]
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)

import mc_http
import mc_software

MODRINTH = "https://api.modrinth.com/v2"
CURSEFORGE = "https://api.curseforge.com/v1"
FTB = "https://api.feed-the-beast.com/v1/modpacks/public/modpack"
CF_GAME_ID, CF_CLASS_MODPACKS = 432, 4471

MRPACK_LOADERS = {"fabric-loader": "Fabric", "quilt-loader": "Quilt", "forge": "Forge", "neoforge": "NeoForge"}


def result(ok, code, **data):
    return {"ok": ok, "code": code, **data}


class PackError(Exception):
    def __init__(self, code, **data):
        super().__init__(code)
        self.code = code
        self.data = data


# ── helpers ──────────────────────────────────────────────────────────────────

def safe_join(folder, relative):
    """folder/relative, refusing absolute paths and anything escaping folder."""
    relative = str(relative).replace("\\", "/")
    while relative.startswith("./"):
        relative = relative[2:]
    if relative.startswith("/") or ".." in relative.split("/") or ":" in relative.split("/")[0]:
        raise PackError("unsafe_path", path=relative)
    target = os.path.realpath(os.path.join(folder, relative))
    if not target.startswith(os.path.realpath(folder) + os.sep):
        raise PackError("unsafe_path", path=relative)
    return target


def _copy_tree(src, dest_root):
    """Copy an extracted override folder into the server, file by file."""
    copied = []
    for root, _dirs, files in os.walk(src):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), src).replace(os.sep, "/")
            target = safe_join(dest_root, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(os.path.join(root, name), target)
            copied.append(rel)
    return copied


def _extract(zip_path, dest):
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            safe_join(dest, member.rstrip("/") or ".")
        zf.extractall(dest)


# ── Modrinth ─────────────────────────────────────────────────────────────────

def _modrinth_mrpack(ref):
    """(local .mrpack path to download into, url, hashes, meta) for a slug[@version]."""
    slug, _, wanted = str(ref).partition("@")
    try:
        project = mc_http.get_json(f"{MODRINTH}/project/{slug}")
    except mc_http.HttpError as e:
        if e.status == 404:
            raise PackError("modpack_not_found", source=ref)
        raise
    if project.get("project_type") != "modpack":
        raise PackError("not_a_modpack", name=project.get("title"))
    versions = mc_http.get_json(f"{MODRINTH}/project/{project['id']}/version")
    if wanted:
        versions = [v for v in versions if wanted in (v.get("version_number"), v.get("id"))]
    elif any(v.get("version_type") == "release" for v in versions):
        versions = [v for v in versions if v.get("version_type") == "release"]
    if not versions:
        raise PackError("pack_version_not_found", source=ref)
    version = versions[0]
    files = version.get("files") or []
    pack = next((f for f in files if f.get("primary") and f["filename"].endswith(".mrpack")),
                next((f for f in files if f["filename"].endswith(".mrpack")), None))
    if not pack:
        raise PackError("pack_version_not_found", source=ref)
    return pack["url"], {k: v for k, v in (pack.get("hashes") or {}).items() if k in ("sha512", "sha1")}, {
        "source": "modrinth", "project": project.get("slug") or project["id"], "title": project.get("title"),
        "version_id": version["id"], "version": version.get("version_number")}


def plan_from_mrpack(path, meta=None):
    with zipfile.ZipFile(path) as zf:
        try:
            index = json.loads(zf.read("modrinth.index.json").decode("utf-8"))
        except KeyError:
            raise PackError("bad_pack", detail="modrinth.index.json missing")
    deps = index.get("dependencies") or {}
    loader = next((MRPACK_LOADERS[k] for k in deps if k in MRPACK_LOADERS), "Vanilla")
    loader_key = next((k for k in deps if k in MRPACK_LOADERS), None)
    files = []
    for f in index.get("files", []):
        if (f.get("env") or {}).get("server") == "unsupported":
            continue
        if not f.get("downloads"):
            continue
        files.append({"path": f["path"], "url": f["downloads"][0],
                      "hashes": {k: v for k, v in (f.get("hashes") or {}).items() if k in ("sha512", "sha1")}})
    meta = dict(meta or {"source": "file", "project": os.path.basename(path)})
    meta.setdefault("title", index.get("name"))
    meta.setdefault("version", index.get("versionId"))
    return {
        "meta": meta, "mc_version": deps.get("minecraft"), "loader": loader,
        "loader_version": deps.get(loader_key) if loader_key else None,
        "files": files, "archive": path, "overrides": ["overrides", "server-overrides"],
    }


# ── CurseForge ───────────────────────────────────────────────────────────────

def _cf(key, path, **params):
    if not key:
        raise PackError("curseforge_key_missing")
    return mc_http.get_json(mc_http.url(f"{CURSEFORGE}{path}", **params), headers={"x-api-key": key})


def plan_from_curseforge(ref, key, tmp):
    slug, _, wanted = str(ref).partition("@")
    if slug.isdigit():
        mod = _cf(key, f"/mods/{slug}")["data"]
    else:
        found = _cf(key, "/mods/search", gameId=CF_GAME_ID, classId=CF_CLASS_MODPACKS, slug=slug).get("data") or []
        if not found:
            raise PackError("modpack_not_found", source=ref)
        mod = found[0]
    if wanted:
        pack_file = _cf(key, f"/mods/{mod['id']}/files/{wanted}")["data"]
    else:
        files = _cf(key, f"/mods/{mod['id']}/files").get("data") or []
        releases = [f for f in files if f.get("releaseType") == 1] or files
        if not releases:
            raise PackError("pack_version_not_found", source=ref)
        pack_file = max(releases, key=lambda f: f.get("fileDate", ""))
    server_id = pack_file.get("serverPackFileId")
    if not server_id:
        raise PackError("no_server_pack", name=mod.get("name"))
    server_file = _cf(key, f"/mods/{mod['id']}/files/{server_id}")["data"]
    if not server_file.get("downloadUrl"):
        raise PackError("curseforge_no_distribution", name=mod.get("name"))
    archive = os.path.join(tmp, server_file["fileName"])
    sha1 = next((h["value"] for h in server_file.get("hashes", []) if h.get("algo") == 1), None)
    mc_http.download(server_file["downloadUrl"], archive, {"sha1": sha1} if sha1 else None)

    versions = pack_file.get("gameVersions") or []
    mc_version = next((v for v in versions if v[:1].isdigit()), None)
    loader = next((mc_software.canonical(v) for v in versions if mc_software.canonical(v)), None)
    loader_version = None
    with zipfile.ZipFile(archive) as zf:
        manifest_name = next((n for n in zf.namelist() if n.rsplit("/", 1)[-1] == "manifest.json"), None)
        if manifest_name:
            manifest = json.loads(zf.read(manifest_name).decode("utf-8"))
            mc_version = (manifest.get("minecraft") or {}).get("version") or mc_version
            for ml in (manifest.get("minecraft") or {}).get("modLoaders", []):
                name, _, ver = str(ml.get("id", "")).partition("-")
                if mc_software.canonical(name):
                    loader, loader_version = mc_software.canonical(name), ver
    return {
        "meta": {"source": "curseforge", "project": str(mod["id"]), "title": mod.get("name"),
                 "version_id": str(pack_file["id"]), "version": pack_file.get("displayName")},
        "mc_version": mc_version, "loader": loader or "Vanilla", "loader_version": loader_version,
        "files": [], "archive": archive, "overrides": [""], "strip_root": True,
    }


# ── FTB ──────────────────────────────────────────────────────────────────────

def plan_from_ftb(ref):
    pack_id, _, wanted = str(ref).partition("@")
    try:
        pack = mc_http.get_json(f"{FTB}/{pack_id}")
    except mc_http.HttpError as e:
        if e.status == 404:
            raise PackError("modpack_not_found", source=ref)
        raise
    versions = pack.get("versions") or []
    if wanted:
        versions = [v for v in versions if str(v.get("id")) == wanted or v.get("name") == wanted]
    else:
        releases = [v for v in versions if str(v.get("type", "")).lower() == "release"]
        versions = sorted(releases or versions, key=lambda v: v.get("updated", 0), reverse=True)
    if not versions:
        raise PackError("pack_version_not_found", source=ref)
    version = mc_http.get_json(f"{FTB}/{pack_id}/{versions[0]['id']}")
    mc_version = loader = loader_version = None
    for target in version.get("targets", []):
        if target.get("type") == "game":
            mc_version = target.get("version")
        elif target.get("type") == "modloader":
            loader, loader_version = mc_software.canonical(target.get("name")), target.get("version")
    files = []
    for f in version.get("files", []):
        if f.get("clientonly"):
            continue
        if not f.get("url"):
            raise PackError("pack_file_unavailable", name=f.get("name"))
        files.append({"path": f"{f.get('path', './').rstrip('/')}/{f['name']}",
                      "url": f["url"], "hashes": {"sha1": f["sha1"]} if f.get("sha1") else {}})
    return {
        "meta": {"source": "ftb", "project": str(pack_id), "title": pack.get("name"),
                 "version_id": str(version.get("id")), "version": version.get("name")},
        "mc_version": mc_version, "loader": loader or "Vanilla", "loader_version": loader_version,
        "files": files, "archive": None, "overrides": [],
    }


# ── resolve / install ────────────────────────────────────────────────────────

def plan(source, tmp, curseforge_key=None, progress=None):
    source = str(source).strip()
    kind, sep, ref = source.partition(":")
    if source.endswith(".mrpack") and os.path.isfile(os.path.expanduser(source)):
        return plan_from_mrpack(os.path.expanduser(source))
    if source.startswith("https://") and source.split("?")[0].endswith(".mrpack"):
        archive = os.path.join(tmp, "pack.mrpack")
        mc_http.download(source, archive, progress=progress)
        return plan_from_mrpack(archive, {"source": "url", "project": source})
    if sep and kind == "curseforge":
        return plan_from_curseforge(ref, curseforge_key, tmp)
    if sep and kind == "ftb":
        return plan_from_ftb(ref)
    ref = ref if sep and kind == "modrinth" else source
    address, hashes, meta = _modrinth_mrpack(ref)
    archive = os.path.join(tmp, "pack.mrpack")
    mc_http.download(address, archive, hashes, progress=progress)
    return plan_from_mrpack(archive, meta)


def _apply(folder, the_plan, tmp, progress=None):
    """Download the plan's files and copy its overrides. Returns the list of
    pack-managed paths (relative), used by the next update."""
    written = []
    for f in the_plan["files"]:
        target = safe_join(folder, f["path"])
        mc_http.download(f["url"], target, f["hashes"], progress=progress)
        written.append(os.path.relpath(target, folder).replace(os.sep, "/"))
    if the_plan.get("archive") and the_plan.get("overrides"):
        extracted = os.path.join(tmp, "extracted")
        _extract(the_plan["archive"], extracted)
        roots = [os.path.join(extracted, o) for o in the_plan["overrides"]]
        if the_plan.get("strip_root"):
            entries = os.listdir(extracted)
            if len(entries) == 1 and os.path.isdir(os.path.join(extracted, entries[0])):
                roots = [os.path.join(extracted, entries[0])]
        for root in roots:
            if os.path.isdir(root):
                written += _copy_tree(root, folder)
    return sorted(set(written))


def info(source, curseforge_key=None):
    with tempfile.TemporaryDirectory() as tmp:
        try:
            p = plan(source, tmp, curseforge_key)
        except PackError as e:
            return result(False, e.code, **e.data)
        except mc_http.HttpError as e:
            return result(False, "source_unreachable", detail=e.detail)
    return result(True, "pack_info", title=p["meta"].get("title"), version=p["meta"].get("version"),
                  mc_version=p["mc_version"], loader=p["loader"], loader_version=p["loader_version"],
                  server_files=len(p["files"]), source=p["meta"]["source"])


def install_into(folder, source, curseforge_key=None, java="java", progress=None):
    """Install a modpack into an empty folder: loader + files + overrides.
    Returns a result with jar_name, loader, mc_version and the 'modpack'
    record to store in config.json."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            p = plan(source, tmp, curseforge_key, progress)
            if not p.get("mc_version"):
                raise PackError("bad_pack", detail="no Minecraft version")
            os.makedirs(folder, exist_ok=True)
            java_path = java(p["mc_version"], p["loader"]) if callable(java) else java
            soft = mc_software.install(folder, p["loader"], p["mc_version"], p["loader_version"], java_path, progress)
            if not soft["ok"]:
                return soft
            files = _apply(folder, p, tmp, progress)
        except PackError as e:
            return result(False, e.code, **e.data)
        except mc_http.HttpError as e:
            return result(False, "source_unreachable", detail=e.detail)
    record = dict(p["meta"], files=files, installed=datetime.date.today().isoformat())
    return result(True, "pack_installed", title=p["meta"].get("title"), version=p["meta"].get("version"),
                  mc_version=p["mc_version"], loader=p["loader"], loader_version=soft.get("loader_version"),
                  jar_name=soft["jar_name"], modpack=record, files=len(files))


def update(config, curseforge_key=None, java="java", progress=None):
    """Move a server to the newest version of its modpack. The world and
    anything the pack does not manage are kept; files the old version
    installed are moved to mods_quarantine/<date>/modpack-<old version>/."""
    record = config.get("modpack")
    if not record:
        return result(False, "no_modpack")
    if record["source"] in ("file", "url"):
        return result(False, "pack_not_updatable", source=record["source"])
    source = {"modrinth": "modrinth:", "curseforge": "curseforge:", "ftb": "ftb:"}[record["source"]] + record["project"]
    folder = config["dossier_serveur"]
    with tempfile.TemporaryDirectory() as tmp:
        try:
            p = plan(source, tmp, curseforge_key, progress)
            if p["meta"].get("version_id") == record.get("version_id"):
                return result(True, "pack_up_to_date", title=record.get("title"), version=record.get("version"))
            stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            quarantine = os.path.join(folder, "mods_quarantine", stamp, f"modpack-{record.get('version')}")
            for rel in record.get("files", []):
                path = safe_join(folder, rel)
                if os.path.isfile(path):
                    dest = os.path.join(quarantine, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(path, dest)
            soft = None
            if (p["loader"], p["mc_version"], p["loader_version"]) != (
                    config.get("loader"), config.get("mc_version"), config.get("loader_version")):
                soft = mc_software.install(folder, p["loader"], p["mc_version"], p["loader_version"], java, progress)
                if not soft["ok"]:
                    return soft
            files = _apply(folder, p, tmp, progress)
        except PackError as e:
            return result(False, e.code, **e.data)
        except mc_http.HttpError as e:
            return result(False, "source_unreachable", detail=e.detail)
    config["modpack"] = dict(p["meta"], files=files, installed=datetime.date.today().isoformat())
    config["mc_version"], config["loader"] = p["mc_version"], p["loader"]
    if soft:
        config["jar_name"], config["loader_version"] = soft["jar_name"], soft.get("loader_version")
    return result(True, "pack_updated", title=p["meta"].get("title"), previous=record.get("version"),
                  version=p["meta"].get("version"), quarantine=quarantine, restart_required=True)
