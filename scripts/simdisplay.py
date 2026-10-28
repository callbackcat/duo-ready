#!/usr/bin/env python3
"""Pick an iPhone Duo simulator display from `xcrun simctl io <udid> enumerate`.

    xcrun simctl io "$UDID" enumerate | simdisplay.py --width 1398   # outer
    xcrun simctl io "$UDID" enumerate | simdisplay.py --width 2007   # inner
    xcrun simctl io "$UDID" enumerate | simdisplay.py --json         # every screen

Xcode 27.1 (verified 27 Oct 2026 on build 27A9275) lists the screens under a
"Connected Screens:" section of the DisplayAdapter port:

    (1) LCD:
        Unique ID: A8A21E67-...
        Device Name: primary
        Pixel Size: {1398, 2034}
    (3) LCD-1:
        Unique ID: EA823FDE-...
        Device Name: primary-1
        Pixel Size: {2007, 2853}

`simctl io screenshot --display=` accepts that Unique ID (also the port UUID,
`primary` and the screen number). Older Xcode builds printed a flatter
"Display: UUID ... width ..." layout, kept as a fallback. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

_UUID = r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}"


def parse_screens(text: str) -> list[dict]:
    """Return [{uuid, name, device_name, width, height, orientation}] from Connected Screens."""
    out = []
    section = text.split("Connected Screens:", 1)
    if len(section) < 2:
        return out
    for block in re.split(r"(?m)^\s*\(\d+\)\s", section[1])[1:]:
        m_uuid = re.search(r"Unique ID:\s*(" + _UUID + ")", block)
        m_px = re.search(r"Pixel Size:\s*\{\s*(\d+)\s*,\s*(\d+)\s*\}", block)
        if not (m_uuid and m_px):
            continue
        m_name = re.match(r"\s*([^:\n]+):", block)
        m_dev = re.search(r"Device Name:\s*(\S+)", block)
        m_or = re.search(r"UI Orientation:\s*([^\n]+)", block)
        out.append({
            "uuid": m_uuid.group(1),
            "name": m_name.group(1).strip() if m_name else "",
            "device_name": m_dev.group(1) if m_dev else "",
            "width": int(m_px.group(1)),
            "height": int(m_px.group(2)),
            "orientation": m_or.group(1).strip() if m_or else "",
        })
    return out


def parse_legacy(text: str) -> list[dict]:
    """Fallback for older layouts: a UUID and a width number inside the same Display/Port block."""
    out = []
    for b in re.split(r"(?im)^\s*(?:display|port)\b", text):
        m_uuid = re.search("(" + _UUID + ")", b)
        m_w = re.search(r"width\D{0,5}(\d{3,5})", b, re.I)
        m_h = re.search(r"height\D{0,5}(\d{3,5})", b, re.I)
        if m_uuid and m_w:
            out.append({"uuid": m_uuid.group(1), "name": "", "device_name": "",
                        "width": int(m_w.group(1)), "height": int(m_h.group(1)) if m_h else 0, "orientation": ""})
    return out


def pick(text: str, width: int) -> str | None:
    """UUID of the screen whose pixel size has `width` on either axis (captures may come out rotated)."""
    screens = parse_screens(text)
    for s in screens:
        if width in (s["width"], s["height"]):
            return s["uuid"]
    if screens:
        return None  # the new layout was present but no screen matched; do not guess from ports
    for s in parse_legacy(text):
        if abs(s["width"] - width) <= 2 or abs(s["height"] - width) <= 2:
            return s["uuid"]
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--width", type=int, help="pixel width (or height) of the wanted display: 1398 outer, 2007 inner")
    ap.add_argument("--json", action="store_true", help="print every screen found")
    args = ap.parse_args(argv)
    text = sys.stdin.read()
    if args.json:
        print(json.dumps(parse_screens(text) or parse_legacy(text), indent=2))
        return 0
    if args.width is None:
        ap.error("--width or --json is required")
    uuid = pick(text, args.width)
    if not uuid:
        return 1
    print(uuid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
