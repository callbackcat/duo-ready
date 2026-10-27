#!/usr/bin/env python3
"""Validate App Store screenshots for iPhone Duo before upload.

    assets_gate.py <dir> [--json] [--strict]

Walks <dir> (fastlane layout: <dir>/<locale>/*.png|jpg, or files directly in
<dir>). For every image: reads dimensions, requires an exact Duo size
(1398x2034, 2034x1398 outer; 2007x2853, 2853x2007 inner), rejects PNGs with
an alpha channel or tRNS chunk (App Store Connect refuses transparency), and
enforces at most 10 Duo screenshots per locale (one Duo set holds all four
sizes). Images that are not a Duo size are listed as "ignored" because a
fastlane folder usually also holds other devices' screenshots; --strict turns
them into violations. Exit 1 on any violation.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngio  # noqa: E402

DUO_SIZES = {
    (1398, 2034): ("outer", "portrait"),
    (2034, 1398): ("outer", "landscape"),
    (2007, 2853): ("inner", "portrait"),
    (2853, 2007): ("inner", "landscape"),
}
MAX_PER_LOCALE = 10
IMAGE_EXT = (".png", ".jpg", ".jpeg")


def jpeg_info(path: str) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG file")
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        if marker == 0xD9:
            break
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", data[pos + 5 : pos + 9])
            return {"width": w, "height": h, "has_alpha": False, "format": "jpeg"}
        pos += 2 + length
    raise ValueError("no SOF marker found")


def image_info(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".png":
        inf = pngio.info(path)
        inf["format"] = "png"
        return inf
    return jpeg_info(path)


def gate(directory: str, strict: bool = False) -> dict:
    if not os.path.isdir(directory):
        return {"directory": directory, "violations": [f"not a directory: {directory}"], "files": [], "ignored": [], "ok": False}
    groups: dict[str, list[str]] = {}
    for entry in sorted(os.listdir(directory)):
        full = os.path.join(directory, entry)
        if os.path.isdir(full):
            imgs = [os.path.join(full, f) for f in sorted(os.listdir(full)) if f.lower().endswith(IMAGE_EXT)]
            if imgs:
                groups[entry] = imgs
        elif entry.lower().endswith(IMAGE_EXT):
            groups.setdefault("(root)", []).append(full)

    files, ignored, violations = [], [], []
    for locale, paths in groups.items():
        duo_count = 0
        for p in paths:
            rel = os.path.relpath(p, directory).replace("\\", "/")
            try:
                inf = image_info(p)
            except Exception as e:  # noqa: BLE001
                violations.append(f"{rel}: unreadable ({e})")
                continue
            size = (inf["width"], inf["height"])
            if size not in DUO_SIZES:
                msg = f"{rel}: {size[0]}x{size[1]} is not an iPhone Duo size"
                if strict:
                    violations.append(msg)
                else:
                    ignored.append(msg)
                continue
            display, orientation = DUO_SIZES[size]
            duo_count += 1
            rec = {"file": rel, "locale": locale, "width": size[0], "height": size[1], "display": display, "orientation": orientation, "format": inf.get("format")}
            if inf.get("has_alpha"):
                violations.append(f"{rel}: PNG has an alpha channel or tRNS chunk; App Store Connect rejects transparency")
                rec["alpha"] = True
            files.append(rec)
        if duo_count > MAX_PER_LOCALE:
            violations.append(f"{locale}: {duo_count} iPhone Duo screenshots, limit is {MAX_PER_LOCALE} per locale")
    return {"directory": directory, "files": files, "ignored": ignored, "violations": violations, "ok": not violations}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="treat non-Duo sizes as violations")
    args = ap.parse_args(argv)
    res = gate(args.dir, args.strict)
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        for f in res["files"]:
            print(f"ok   {f['file']}  {f['width']}x{f['height']}  {f['display']} {f['orientation']}")
        for i in res["ignored"]:
            print(f"skip {i}")
        for v in res["violations"]:
            print(f"FAIL {v}")
        print(f"{len(res['files'])} Duo screenshot(s), {len(res['ignored'])} ignored, {len(res['violations'])} violation(s)")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
