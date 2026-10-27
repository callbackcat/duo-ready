#!/usr/bin/env python3
"""Visual diff between two PNG captures (standard library only).

    diff.py a.png b.png [--ignore x,y,w,h ...] [--tolerance 16] [--out diff.png] [--json]

Prints the fraction of compared pixels that differ. Two pixels are equal when
every channel differs by at most --tolerance (default 16 of 255), which hides
simulator anti-aliasing noise without hiding a moved button. A size mismatch
is reported as fraction 1.0 with a reason instead of an exception, so a cell
whose window size changed (wrong SDK stamp, wrong pose) shows up as a hard
diff rather than a crash. Ignore rectangles are in pixels of image a.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pngio  # noqa: E402


def compare(a_path: str, b_path: str, ignore=None, tolerance: int = 16, out: str | None = None) -> dict:
    ignore = ignore or []
    try:
        aw, ah, ach, arows = pngio.read(a_path)
        bw, bh, bch, brows = pngio.read(b_path)
    except (OSError, pngio.PNGError) as e:
        return {"fraction": 1.0, "changed": 0, "total": 0, "reason": f"unreadable: {e}", "size_a": None, "size_b": None}
    result = {"size_a": [aw, ah], "size_b": [bw, bh], "reason": None}
    if (aw, ah) != (bw, bh):
        result.update({"fraction": 1.0, "changed": 0, "total": 0, "reason": f"size mismatch {aw}x{ah} vs {bw}x{bh}"})
        return result

    def masked(x: int, y: int) -> bool:
        for ix, iy, iw, ih in ignore:
            if ix <= x < ix + iw and iy <= y < iy + ih:
                return True
        return False

    changed = 0
    total = 0
    out_rows = pngio.solid(aw, ah, (0, 0, 0)) if out else None
    nch = min(ach, bch, 3)
    for y in range(ah):
        ra, rb = arows[y], brows[y]
        orow = out_rows[y] if out_rows is not None else None
        for x in range(aw):
            if ignore and masked(x, y):
                if orow is not None:
                    orow[x * 3 : x * 3 + 3] = b"\x40\x40\x40"
                continue
            total += 1
            pa = ra[x * ach : x * ach + nch]
            pb = rb[x * bch : x * bch + nch]
            same = True
            for c in range(nch):
                if abs(pa[c] - pb[c]) > tolerance:
                    same = False
                    break
            if not same:
                changed += 1
                if orow is not None:
                    orow[x * 3 : x * 3 + 3] = b"\xff\x00\x00"
            elif orow is not None:
                g = sum(pa) // max(1, nch)
                v = 128 + g // 2
                orow[x * 3 : x * 3 + 3] = bytes((v, v, v))
    fraction = (changed / total) if total else 0.0
    result.update({"fraction": round(fraction, 6), "changed": changed, "total": total})
    if out and out_rows is not None:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        pngio.write(out, aw, ah, 3, out_rows)
        result["out"] = out
    return result


def parse_rect(s: str):
    parts = [int(p) for p in s.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("rect must be x,y,w,h")
    return tuple(parts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--ignore", type=parse_rect, action="append", default=[], help="x,y,w,h rectangle to skip (repeatable)")
    ap.add_argument("--tolerance", type=int, default=16)
    ap.add_argument("--out", help="write a diff image (changed pixels red, ignored grey)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    res = compare(args.a, args.b, args.ignore, args.tolerance, args.out)
    if args.json:
        print(json.dumps(res))
    else:
        line = f"{res['fraction']:.4f}"
        if res.get("reason"):
            line += f"  ({res['reason']})"
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
