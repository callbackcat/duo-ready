#!/usr/bin/env python3
"""Write FEATURING.md (App Store featuring nomination draft) from a run's results.

    featuring.py --run <n> [--root .] [--app <name>] [--out FEATURING.md] [--displays inner,outer]

The nomination text claims only what the run verified: a sentence per
assertion that passed everywhere it was evaluated, the poses that were
actually captured, the SDK stamp from the build, and the displays the
export covered. A fixed template promised fold-safe controls while the run
still had twelve failures (field test 6); a reviewer can see the fold.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import duolib  # noqa: E402

# assertion -> the sentence it earns when it has no fail in any cell
CLAIMS = [
    ("offscreen_elements", "nothing is laid out beyond the window edges in any pose"),
    ("clipped_text", "text is never clipped on either display"),
    ("tap_target_min", "tap targets stay at least 44 pt on both displays"),
    ("bars_vertical_expected", "toolbars and tab bars follow the system's vertical placement"),
    ("content_under_outer_camera", "foreground controls stay clear of the outer camera"),
    ("interactive_in_fold", "interactive controls stay clear of the fold in the book poses"),
    ("transition_stable", "state and controls survive folding and unfolding"),
]
POSE_WORDS = [
    ("closed", "the outer display when closed"),
    ("open", "the inner display when open"),
    ("book", "the partially folded (book) pose"),
    ("split-view", "Split View"),
]


def summarise(ui: dict | None) -> dict:
    cells = (ui or {}).get("cells", []) or []
    status: dict[str, set] = {}
    failing_cells = []
    for c in cells:
        bad = [r.get("assertion") for r in c.get("results", []) if r.get("status") == "fail"]
        if bad or c.get("errored"):
            failing_cells.append((c.get("flow"), c.get("cell"), bad or ["flow"]))
        for r in c.get("results", []):
            status.setdefault(r.get("assertion"), set()).add(r.get("status"))
    poses = set()
    rotated = False
    for c in cells:
        name = c.get("cell") or ""
        if ">" in name:
            continue
        pose = name.split("-")[0]
        poses.add(pose)
        if name.endswith("-portrait") and pose != "closed" or name.endswith("-landscape") and pose == "closed":
            rotated = True
    transitions = any(">" in (c.get("cell") or "") for c in cells)
    proven = [text for a, text in CLAIMS if status.get(a) and "pass" in status[a] and "fail" not in status[a]]
    return {"cells": len(cells), "failing": failing_cells, "poses": poses, "rotated": rotated,
            "transitions": transitions, "proven": proven, "verified": (ui or {}).get("verified"),
            "sdk_stamp": (ui or {}).get("sdk_stamp")}


def build(app: str, run: int, ui: dict | None, displays=("inner", "outer")) -> str:
    s = summarise(ui)
    lines = [f"# Featuring nomination: {app} on iPhone Duo", ""]
    if s["failing"]:
        lines.append(f"**Not ready to submit.** Run {run} still has {len(s['failing'])} failing cell(s): "
                     + "; ".join(f"{f} / {c} ({', '.join(a)})" for f, c, a in s["failing"][:8])
                     + (" and more" if len(s["failing"]) > 8 else "")
                     + ". The text below claims only what this run verified; fix the failures and rerun before nominating.")
        lines.append("")
    elif s["verified"] is False or not s["cells"]:
        lines.append(f"**Not ready to submit.** Run {run} verified no element trees, so the claims below are unproven.")
        lines.append("")
    lines.append("Submit in App Store Connect under Featuring Nominations. Suggested \"Helpful details\":")
    lines.append("")
    pose_bits = [w for p, w in POSE_WORDS if p in s["poses"]]
    if s["rotated"]:
        pose_bits.append("both orientations")
    adapt = ""
    if pose_bits:
        adapt = " It adapts to " + ", ".join(pose_bits[:-1]) + (" and " if len(pose_bits) > 1 else "") + pose_bits[-1] + "."
    lines.append(f"> {app} is optimized for iPhone Duo.{adapt}")
    if s["proven"]:
        proven = list(s["proven"])
        lines.append("> " + (", ".join(proven[:-1]) + (", and " if len(proven) > 1 else "") + proven[-1]).capitalize() + ".")
    disp = [d for d in ("inner", "outer") if d in set(displays)]
    if disp:
        lines.append("> App Store screenshots cover the " + " and ".join(disp) + (" displays." if len(disp) > 1 else " display."))
    if s["sdk_stamp"]:
        lines.append(f"> Built with the iOS {s['sdk_stamp']} SDK.")
    lines.append("")
    lines.append("Every sentence above comes from a pose matrix result (`.duo/runs/%d/ui.json`); claims the run did not "
                 "prove were left out. Add what is genuinely Duo-specific in the app (arrangement views, reserved-region "
                 "handling, hinge interactions). Apple reviews nominations by hand; claims it can see are the ones that help." % run)
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--app", default="your app")
    ap.add_argument("--out", default=None)
    ap.add_argument("--displays", default="inner,outer")
    args = ap.parse_args(argv)
    ui_path = os.path.join(duolib.run_dir(args.root, args.run), "ui.json")
    ui = duolib.load_json(ui_path) if os.path.exists(ui_path) else None
    text = build(args.app, args.run, ui, tuple(d for d in args.displays.split(",") if d))
    out = args.out or os.path.join(args.root, "FEATURING.md")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(text)
    n = len(summarise(ui)["failing"])
    print(f"nomination draft written to {out}" + (f" (marked not ready: {n} failing cell(s))" if n else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
