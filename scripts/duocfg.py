#!/usr/bin/env python3
"""Print a value from duo.yaml for shell scripts.

    python3 scripts/duocfg.py scheme
    python3 scripts/duocfg.py perf.launch_ms.fail
    python3 scripts/duocfg.py cells --list          # one item per line
    python3 scripts/duocfg.py flows --json          # raw JSON
    python3 scripts/duocfg.py workspace --default ""

Exit 1 when the key is missing and no --default was given, so `set -e`
scripts stop instead of continuing with an empty value.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import duolib  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("key", help="dotted key, e.g. perf.launch_ms.fail")
    ap.add_argument("--file", default="duo.yaml")
    ap.add_argument("--list", action="store_true", help="print list items one per line")
    ap.add_argument("--json", action="store_true", help="print the value as JSON")
    ap.add_argument("--default", default=None, help="value to print when the key is missing")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        if args.default is not None:
            print(args.default)
            return 0
        print(f"duocfg: {args.file} not found (run scripts/detect.py first)", file=sys.stderr)
        return 1

    doc = duolib.load_yaml(args.file)
    node = doc
    for part in args.key.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            node = None
            break

    if node is None:
        if args.default is not None:
            print(args.default)
            return 0
        print(f"duocfg: key '{args.key}' not set in {args.file}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(node))
    elif isinstance(node, list):
        for item in node:
            print(item if not isinstance(item, (dict, list)) else json.dumps(item))
    elif isinstance(node, dict):
        print(json.dumps(node))
    elif isinstance(node, bool):
        print("true" if node else "false")
    else:
        print(node)
    return 0


if __name__ == "__main__":
    sys.exit(main())
