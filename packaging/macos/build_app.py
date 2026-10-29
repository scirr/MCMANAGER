#!/usr/bin/env python3
"""
build_app.py — Assembles MCManager.app from a SwiftPM release build and zips it.

    cd apps/macos && swift build -c release
    python3 packaging/macos/build_app.py --bin-path "$(cd apps/macos && swift build -c release --show-bin-path)" --out dist

The bundle is not signed or notarized: macOS asks for confirmation on the first
launch (right-click the app, then Open). The icon is drawn here, so the build
needs no image tool.
"""
import argparse
import os
import plistlib
import re
import shutil
import stat
import struct
import sys
import zlib
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

APP_NAME = "MCManager"
BUNDLE_ID = "io.github.scirr.MCManager"
EXECUTABLE = "MCManagerApp"
ZIP_NAME = "MCManager-App-macOS.zip"
MIN_MACOS = "14.0"
ICON_SIZES = ((b"ic07", 128), (b"ic08", 256), (b"ic09", 512))


def read_version():
    with open(os.path.join(ROOT, "core", "mc_lang.py"), encoding="utf-8") as f:
        match = re.search(r'^VERSION = "([^"]+)"$', f.read(), re.M)
    if not match:
        raise RuntimeError("VERSION not found in core/mc_lang.py")
    return match.group(1)


def info_plist(version):
    return plistlib.dumps({
        "CFBundleName": "MC Manager",
        "CFBundleDisplayName": "MC Manager",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIconFile": APP_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
        "CFBundleDevelopmentRegion": "en",
        "CFBundleLocalizations": ["en", "fr"],
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticTermination": False,
    })


def _inside_rounded_square(u, v, radius):
    u, v = abs(u - 0.5), abs(v - 0.5)
    edge = 0.5 - radius
    if u <= edge or v <= edge:
        return u <= 0.5 and v <= 0.5
    return (u - edge) ** 2 + (v - edge) ** 2 <= radius ** 2


def _pixel(u, v):
    if not _inside_rounded_square(u, v, 0.2):
        return (0, 0, 0, 0)
    top, bottom = (84, 170, 73), (31, 98, 42)
    base = tuple(int(top[i] + (bottom[i] - top[i]) * v) for i in range(3))
    # Four blocks: three solid, one hollow, like a server rack seen from above.
    for row in range(2):
        for col in range(2):
            x0, y0 = 0.2 + col * 0.3, 0.2 + row * 0.3
            if x0 <= u < x0 + 0.26 and y0 <= v < y0 + 0.26:
                hollow = row == 1 and col == 1
                inner = x0 + 0.05 <= u < x0 + 0.21 and y0 + 0.05 <= v < y0 + 0.21
                if hollow and inner:
                    return base + (255,)
                return (245, 247, 242, 255)
    return base + (255,)


def render_png(size):
    samples = 2
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            acc = [0, 0, 0, 0]
            for sy in range(samples):
                for sx in range(samples):
                    px = _pixel((x + (sx + 0.5) / samples) / size, (y + (sy + 0.5) / samples) / size)
                    alpha = px[3]
                    acc[0] += px[0] * alpha
                    acc[1] += px[1] * alpha
                    acc[2] += px[2] * alpha
                    acc[3] += alpha
            if acc[3]:
                row += bytes(round(acc[i] / acc[3]) for i in range(3)) + bytes([round(acc[3] / (samples * samples))])
            else:
                row += b"\x00\x00\x00\x00"
        rows.append(bytes(row))

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b"")


def icns_bytes():
    chunks = b"".join(kind + struct.pack(">I", 8 + len(png)) + png
                      for kind, png in ((kind, render_png(size)) for kind, size in ICON_SIZES))
    return b"icns" + struct.pack(">I", 8 + len(chunks)) + chunks


def assemble(bin_path, app_dir, version):
    executable = os.path.join(bin_path, EXECUTABLE)
    if not os.path.isfile(executable):
        raise FileNotFoundError(f"{executable}: build the app first (swift build -c release)")
    if os.path.exists(app_dir):
        shutil.rmtree(app_dir)
    macos = os.path.join(app_dir, "Contents", "MacOS")
    resources = os.path.join(app_dir, "Contents", "Resources")
    os.makedirs(macos)
    os.makedirs(resources)
    target = os.path.join(macos, APP_NAME)
    shutil.copy2(executable, target)
    os.chmod(target, 0o755)  # nosec B103 - an executable inside an app bundle
    for name in sorted(os.listdir(bin_path)):
        if name.endswith(".bundle") and os.path.isdir(os.path.join(bin_path, name)):
            shutil.copytree(os.path.join(bin_path, name), os.path.join(resources, name), symlinks=True)
    with open(os.path.join(app_dir, "Contents", "Info.plist"), "wb") as f:
        f.write(info_plist(version))
    with open(os.path.join(app_dir, "Contents", "PkgInfo"), "wb") as f:
        f.write(b"APPL????")
    with open(os.path.join(resources, APP_NAME + ".icns"), "wb") as f:
        f.write(icns_bytes())
    return app_dir


def zip_app(app_dir, zip_path):
    if os.path.exists(zip_path):
        os.remove(zip_path)
    parent = os.path.dirname(app_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, dirs, files in os.walk(app_dir):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(base, name)
                arc = os.path.relpath(full, parent).replace(os.sep, "/")
                info = zipfile.ZipInfo.from_file(full, arc)
                mode = 0o755 if os.stat(full).st_mode & stat.S_IXUSR else 0o644
                info.external_attr = (stat.S_IFREG | mode) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                with open(full, "rb") as f:
                    zf.writestr(info, f.read())
    return zip_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build MCManager.app and its zip")
    parser.add_argument("--bin-path", required=True, help="SwiftPM release folder (swift build -c release --show-bin-path)")
    parser.add_argument("--out", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--app-dir", help="where to leave MCManager.app (default: next to the zip)")
    args = parser.parse_args(argv)

    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    app_dir = os.path.abspath(args.app_dir) if args.app_dir else os.path.join(out_dir, "app-build", APP_NAME + ".app")
    assemble(os.path.abspath(args.bin_path), app_dir, read_version())
    print(zip_app(app_dir, os.path.join(out_dir, ZIP_NAME)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
