#!/usr/bin/env python3
"""Element-tree normalisation shared by run-matrix.sh and assert.py.

    tree.py from-axe <raw.json> <out.tree.json> [--udid <udid>] [--driver <name>]

`duoctl elements` (AXe) prints a JSON list of
`{"type": "Button", "label": "...", "identifier": null, "frame": {"x","y","width","height"}}`
with no `--json` flag (duoctl 0.2.0, verified 28 Oct 2026). Types are
capitalised XCUIElement names (`Application`, `Button`, `StaticText`, `Group`,
`GenericElement`, `TextField`, `Slider`, `Heading`). Three artefacts, all seen
on the second field test, are handled here or in assert.py:

- the root `Application` element is reported unrotated in landscape cells
  (`[0, 0, 669, 951]` inside a 951 x 669 window) and is dropped as a container;
- every `StaticText` appears twice with the same frame; duplicates are removed;
- `interactive` must be derived from the type case-insensitively, otherwise no
  element is interactive and tap_target_min / interactive_in_fold pass vacuously.

Standard library only.
"""
from __future__ import annotations

import json
import sys

INTERACTIVE_TYPES = {
    "button", "link", "textfield", "securetextfield", "textview", "switch", "toggle", "slider",
    "tab", "tabbar", "segmentedcontrol", "cell", "stepper", "picker", "searchfield", "menuitem",
}
# Container types: never content. assert.py drops them from offscreen / camera
# checks when they span the window; the list lives here so both sides agree.
CONTAINER_TYPES = {
    "application", "window", "group", "other", "view", "sheet",
    "scroll", "scrollview", "table", "collectionview", "collection",
}


def is_interactive_type(type_name: str) -> bool:
    return str(type_name or "").lower() in INTERACTIVE_TYPES


def _frame(fr) -> list[float]:
    if isinstance(fr, list) and len(fr) == 4:
        return [float(v) for v in fr]
    if isinstance(fr, dict):
        return [float(fr.get("x", 0)), float(fr.get("y", 0)), float(fr.get("width", 0)), float(fr.get("height", 0))]
    return [0.0, 0.0, 0.0, 0.0]


def from_axe(raw, udid: str | None = None, driver: str | None = None) -> dict:
    """Convert raw `duoctl elements` output to the pipeline-contracts tree format."""
    items = raw if isinstance(raw, list) else (raw or {}).get("elements", [])
    out = []
    seen = set()
    for e in items:
        if not isinstance(e, dict):
            continue
        type_name = str(e.get("type") or "other")
        label = e.get("label") or ""
        ident = e.get("identifier") or e.get("id") or label
        frame = _frame(e.get("frame"))
        key = (ident, type_name, tuple(round(v, 1) for v in frame))
        if key in seen:
            continue  # AXe lists every StaticText twice (field test 2)
        seen.add(key)
        text = e.get("value")
        if text in (None, ""):
            text = label
        out.append({
            "id": ident, "type": type_name, "label": label, "frame": frame,
            "interactive": is_interactive_type(type_name),
            "text": text or "", "truncated": False,
        })
    doc = {"elements": out, "source": "duoctl elements", "ancestry": False}
    if udid:
        doc["udid"] = udid
    if driver:
        doc["driver"] = driver
    return doc


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 3 or argv[0] != "from-axe":
        print(__doc__, file=sys.stderr)
        return 2
    raw_path, out_path = argv[1], argv[2]
    udid = driver = None
    rest = argv[3:]
    while rest:
        flag = rest.pop(0)
        if flag == "--udid" and rest:
            udid = rest.pop(0)
        elif flag == "--driver" and rest:
            driver = rest.pop(0)
    with open(raw_path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    doc = from_axe(raw, udid=udid, driver=driver)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
