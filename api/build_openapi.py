#!/usr/bin/env python3
"""Merge api/src/*.json into api/openapi.json (OpenAPI 3.1, 2-space indent, sorted keys).

Fails when two source files define the same path, the same component name or the
same top-level field.
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "src")
OUT = os.path.join(HERE, "openapi.json")


class MergeError(Exception):
    pass


def load_sources(src_dir=SRC):
    sources = []
    for path in sorted(glob.glob(os.path.join(src_dir, "*.json"))):
        with open(path, "r", encoding="utf-8") as f:
            sources.append((os.path.basename(path), json.load(f)))
    if not sources:
        raise MergeError(f"no source file in {src_dir}")
    return sources


def merge(sources):
    doc = {"paths": {}, "components": {}, "tags": []}
    owners = {}
    tag_names = set()

    def claim(key, name):
        if key in owners:
            raise MergeError(f"conflict on {key}: {owners[key]} and {name}")
        owners[key] = name

    for name, part in sources:
        for key, value in part.items():
            if key == "paths":
                for path, item in value.items():
                    claim(f"path {path}", name)
                    doc["paths"][path] = item
            elif key == "components":
                for kind, entries in value.items():
                    target = doc["components"].setdefault(kind, {})
                    for cname, entry in entries.items():
                        claim(f"component {kind}/{cname}", name)
                        target[cname] = entry
            elif key == "tags":
                for tag in value:
                    if tag["name"] in tag_names:
                        raise MergeError(f"conflict on tag {tag['name']}: {name}")
                    tag_names.add(tag["name"])
                    doc["tags"].append(tag)
            else:
                claim(f"field {key}", name)
                doc[key] = value
    return doc


def render(doc):
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build(src_dir=SRC):
    return render(merge(load_sources(src_dir)))


def main(argv):
    try:
        text = build()
    except (MergeError, ValueError, OSError) as e:
        print(f"build_openapi: {e}", file=sys.stderr)
        return 1
    if "--check" in argv:
        try:
            with open(OUT, "r", encoding="utf-8") as f:
                current = f.read()
        except OSError:
            current = None
        if current != text:
            print("api/openapi.json is out of date: run python3 api/build_openapi.py", file=sys.stderr)
            return 1
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
