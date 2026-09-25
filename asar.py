"""Read and patch Electron asar archives.

Unchanged files are copied byte for byte in their original order; unpacked entries stay untouched.
Usage: asar.py apply SRC DST PATCH.json...   |   asar.py check ASAR PATCH.json...
"""
import fnmatch
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

BLOCK = 4 * 1024 * 1024


class PatchError(Exception):
    pass


def _header(path):
    with open(path, "rb") as f:
        _, header_size, _, json_size = struct.unpack("<IIII", f.read(16))
        header = json.loads(f.read(json_size))
    return header, 8 + header_size


def _walk(node, prefix=""):
    for name, entry in node.get("files", {}).items():
        path = f"{prefix}{name}"
        if "files" in entry:
            yield from _walk(entry, path + "/")
        else:
            yield path, entry


def _packed(entry):
    return "offset" in entry and not entry.get("unpacked")


def entries(path):
    return list(_walk(_header(path)[0]))


def read_file(path, name):
    header, base = _header(path)
    entry = dict(_walk(header))[name]
    with open(path, "rb") as f:
        f.seek(base + int(entry["offset"]))
        return f.read(entry["size"])


def _resolve(files, patch, read, needle):
    """Exact "file" as is; a glob "file" must match exactly one packed file that contains NEEDLE."""
    name = patch["file"]
    if not any(c in name for c in "*?["):
        return name
    hits = [p for p, e in files.items() if _packed(e) and fnmatch.fnmatchcase(p, name) and needle in read(p, "replace")]
    if len(hits) != 1:
        raise PatchError(f"patch '{patch['id']}': {name} matched {len(hits)} files containing the anchor, expected 1")
    return hits[0]


def _edit(text, patch):
    for i, edit in enumerate(patch["edits"]):
        expected = edit.get("count", 1)
        found = text.count(edit["find"])
        if found != expected:
            raise PatchError(f"patch '{patch['id']}' edit {i}: anchor found {found}x, expected {expected}x in {patch['file']}")
        text = text.replace(edit["find"], edit["replace"])
    return text


def _integrity(data):
    blocks = [hashlib.sha256(data[i:i + BLOCK]).hexdigest() for i in range(0, len(data), BLOCK)]
    return {"algorithm": "SHA256", "hash": hashlib.sha256(data).hexdigest(), "blockSize": BLOCK, "blocks": blocks}


def _serialize(header):
    # Chromium pickle layout: [4][len(header pickle)] + [len(payload)][len(json)][json][pad to 4]
    raw = json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload = struct.pack("<I", len(raw)) + raw + b"\0" * (-len(raw) % 4)
    pickle = struct.pack("<I", len(payload)) + payload
    return struct.pack("<II", 4, len(pickle)) + pickle


def apply(src, dst, patches):
    """Write SRC with PATCHES applied to DST. Any anchor mismatch raises before DST exists."""
    header, base = _header(src)
    files = dict(_walk(header))
    changed = {}
    with open(src, "rb") as f:
        def read(name, errors="strict"):
            if name not in changed:
                f.seek(base + int(files[name]["offset"]))
                return f.read(files[name]["size"]).decode("utf-8", errors)
            return changed[name]

        for patch in patches:
            name = _resolve(files, patch, read, patch["edits"][0]["find"])
            entry = files.get(name)
            if entry is None or not _packed(entry):
                raise PatchError(f"patch '{patch['id']}': {name} is not a packed file in the archive")
            changed[name] = _edit(read(name), {**patch, "file": name})

    new_data = {name: text.encode("utf-8") for name, text in changed.items()}
    layout = sorted((int(e["offset"]), e["size"], name, e) for name, e in files.items() if _packed(e))
    offset = 0
    for _, _, name, entry in layout:
        entry["offset"] = str(offset)
        if name in new_data:
            entry["size"] = len(new_data[name])
            entry["integrity"] = _integrity(new_data[name])
        offset += entry["size"]

    dst = Path(dst)
    tmp = dst.with_name(dst.name + ".partial")
    try:
        with open(src, "rb") as f, open(tmp, "wb") as out:
            out.write(_serialize(header))
            for src_offset, src_size, name, _ in layout:
                if name in new_data:
                    out.write(new_data[name])
                    continue
                f.seek(base + src_offset)
                remaining = src_size
                while remaining:
                    chunk = f.read(min(remaining, 1 << 20))
                    out.write(chunk)
                    remaining -= len(chunk)
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            tmp.unlink()


def check(path, patches):
    """Return {patch id: True if every edit's replacement is present}."""
    files, cache, result = dict(entries(path)), {}, {}

    def read(name, errors="strict"):
        if name not in cache:
            cache[name] = read_file(path, name).decode("utf-8", errors)
        return cache[name]

    for patch in patches:
        try:
            name = _resolve(files, patch, read, patch["edits"][0]["replace"])
        except PatchError:
            result[patch["id"]] = False
            continue
        result[patch["id"]] = all(edit["replace"] in read(name) for edit in patch["edits"])
    return result


def _load(paths):
    return [json.loads(Path(p).read_text("utf-8")) for p in paths]


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    try:
        if cmd == "apply" and len(args) >= 2:
            apply(args[0], args[1], _load(args[2:]))
            print(json.dumps({"ok": True}))
        elif cmd == "check" and args:
            print(json.dumps(check(args[0], _load(args[1:]))))
        else:
            sys.exit(__doc__)
    except PatchError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(2)
