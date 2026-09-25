"""Read and set Electron fuses (FuseV1) in an Electron executable.

Usage: fuses.py read EXE   |   fuses.py apply EXE [CONFIG.json]
"""
import json
import os
import sys
from pathlib import Path

SENTINEL = b"dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX"
# Wire order from @electron/fuses FuseV1Options.
NAMES = [
    "RunAsNode",
    "EnableCookieEncryption",
    "EnableNodeOptionsEnvironmentVariable",
    "EnableNodeCliInspectArguments",
    "EnableEmbeddedAsarIntegrityValidation",
    "OnlyLoadAppFromAsar",
    "LoadBrowserProcessSpecificV8Snapshot",
    "GrantFileProtocolExtraPrivileges",
    "WasmTrapHandlers",
]
CONFIG = Path(__file__).resolve().with_name("fuses.json")


class FuseError(Exception):
    pass


def _locate(data):
    start = data.find(SENTINEL)
    if start < 0 or data.find(SENTINEL, start + 1) >= 0:
        raise FuseError("fuse sentinel not found exactly once")
    base = start + len(SENTINEL)
    if data[base] != 1:
        raise FuseError(f"unsupported fuse version {data[base]}")
    length = data[base + 1]
    wire = data[base + 2: base + 2 + length].decode("ascii")
    if set(wire) - set("01r"):
        raise FuseError(f"unexpected fuse wire {wire!r}")
    return base + 2, wire


def read(path):
    _, wire = _locate(Path(path).read_bytes())
    return {"wire": wire, "fuses": {name: wire[i] == "1" for i, name in enumerate(NAMES) if i < len(wire)}}


def set_fuses(path, desired):
    unknown = set(desired) - set(NAMES)
    if unknown:
        raise FuseError(f"unknown fuses: {sorted(unknown)}")
    path = Path(path)
    data = bytearray(path.read_bytes())
    offset, wire = _locate(data)
    for name, enabled in desired.items():
        i = NAMES.index(name)
        if i >= len(wire) or wire[i] == "r":
            raise FuseError(f"fuse {name} is not present in this build")
        data[offset + i] = ord("1" if enabled else "0")
    tmp = path.with_name(path.name + ".partial")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def load_config(path=CONFIG):
    return json.loads(Path(path).read_text("utf-8"))


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    try:
        if cmd == "read" and len(args) == 1:
            print(json.dumps(read(args[0])))
        elif cmd == "apply" and args:
            set_fuses(args[0], load_config(*args[1:2]))
            print(json.dumps({"ok": True, **read(args[0])}))
        else:
            sys.exit(__doc__)
    except FuseError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(2)
