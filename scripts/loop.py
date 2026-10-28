#!/usr/bin/env python3
"""Agent loop driver: turn failures into payloads, track iterations, cap them.

    loop.py --run <n> [--root .] [--max-iterations 3] [--agent "<cmd>"] [--json]
    loop.py --mark-fixed <rule-id> --sites <n> [--root .]
    loop.py --reset [--root .]

Reads .duo/runs/<n>/failures.json, prints each payload as one JSON line (or
pipes them to --agent's stdin), records the iteration in .duo/loop.json and
prints the `--flows a,b --cells x,y` arguments for scripts/run-matrix.sh so
only failed cells are rerun. When the cap is reached it writes DUO-TODO.md
with the remaining failures and fix hints instead of looping forever.
Exit codes: 0 nothing left to do or cap reached (DUO-TODO.md written),
1 payloads emitted and another iteration is expected.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import duolib  # noqa: E402

DEFAULT_MAX = 3


def _state_path(root: str) -> str:
    return os.path.join(duolib.duo_dir(root), "loop.json")


def load_state(root: str) -> dict:
    p = _state_path(root)
    if os.path.exists(p):
        return duolib.load_json(p)
    return {"iterations": 0, "max_iterations": None, "history": []}


def save_state(root: str, state: dict) -> None:
    duolib.write_json(_state_path(root), state)


def max_iterations(root: str, override) -> int:
    if override:
        return int(override)
    cfg_path = os.path.join(root, "duo.yaml")
    if os.path.exists(cfg_path):
        cfg = duolib.load_yaml(cfg_path) or {}
        try:
            return int(((cfg.get("loop") or {}).get("max_iterations")) or DEFAULT_MAX)
        except (TypeError, ValueError):
            return DEFAULT_MAX
    return DEFAULT_MAX


def rerun_args(failures) -> str:
    flows, cells = [], []
    for f in failures:
        if f.get("flow") and f["flow"] not in flows:
            flows.append(f["flow"])
        if f.get("cell") and f["cell"] not in cells:
            cells.append(f["cell"])
    parts = []
    if flows:
        parts.append("--flows " + ",".join(flows))
    if cells:
        parts.append("--cells " + ",".join(cells))
    return " ".join(parts)


def write_todo(root: str, run: int, failures, state: dict) -> str:
    path = os.path.join(root, "DUO-TODO.md")
    lines = [
        "# DUO-TODO",
        "",
        f"The duo-ready agent loop stopped after {state.get('iterations', 0)} iteration(s) (cap {state.get('max_iterations')}). "
        f"Run {run} still has {len(failures)} failure(s). Fix these by hand, then rerun `scripts/run-matrix.sh {rerun_args(failures)}`.",
        "",
        "Reminder: iPhone Duo screenshots become required from April 2027 for apps built with the iOS 27.1 SDK or later. Apple has not said apps will be removed.",
        "",
    ]
    by_cell: dict[str, list] = {}
    for f in failures:
        by_cell.setdefault(f"{f.get('flow')} / {f.get('cell')}", []).append(f)
    for key, fs in by_cell.items():
        lines.append(f"## {key}")
        lines.append("")
        for f in fs:
            lines.append(f"- [ ] `{f.get('assertion')}`" + (f" (scan rule `{f['matched_rule']}` at `{f.get('source_hint')}`)" if f.get("matched_rule") else ""))
            for e in f.get("elements") or []:
                lines.append(f"  - element `{e.get('id')}` frame {e.get('frame')}")
            if f.get("fix_hint"):
                lines.append(f"  - fix: {f['fix_hint']}")
            if f.get("screenshot"):
                lines.append(f"  - screenshot: `{f['screenshot']}`")
        lines.append("")
    if state.get("history"):
        lines.append("## Fixes recorded by the loop")
        lines.append("")
        for h in state["history"]:
            lines.append(f"- {h.get('message')} ({h.get('at')})")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return path


def emit(failures, agent_cmd: str | None) -> None:
    payload_lines = [json.dumps(f) for f in failures]
    if agent_cmd:
        proc = subprocess.run(agent_cmd, input="\n".join(payload_lines) + "\n", shell=True, text=True, check=False)
        if proc.returncode != 0:
            print(f"agent command exited {proc.returncode}", file=sys.stderr)
    else:
        for line in payload_lines:
            print(line)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=int)
    ap.add_argument("--root", default=".")
    ap.add_argument("--max-iterations", type=int)
    ap.add_argument("--agent", help="command that receives one JSON payload per line on stdin")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--mark-fixed", metavar="RULE_ID", help="record a fix commit for a rule id")
    ap.add_argument("--sites", type=int, default=1, help="number of sites fixed (with --mark-fixed)")
    ap.add_argument("--reset", action="store_true", help="forget the iteration count")
    args = ap.parse_args(argv)

    root = args.root
    state = load_state(root)

    if args.reset:
        save_state(root, {"iterations": 0, "max_iterations": None, "history": []})
        print("loop state reset")
        return 0

    if args.mark_fixed:
        msg = f"duo: fix {args.mark_fixed} ({args.sites} sites)"
        state.setdefault("history", []).append({"rule": args.mark_fixed, "sites": args.sites, "message": msg,
                                                "at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        save_state(root, state)
        print(msg)
        return 0

    if args.run is None:
        ap.error("--run is required unless --mark-fixed or --reset is given")

    cap = max_iterations(root, args.max_iterations)
    state["max_iterations"] = cap
    rdir = duolib.run_dir(root, args.run)
    fpath = os.path.join(rdir, "failures.json")
    if not os.path.exists(fpath):
        # run-matrix stopped before assert.py, or assert.py was never run; "no
        # failures; loop complete" would be a lie here (field test, run 1).
        reason = f"no failures.json for run {args.run}: the matrix did not reach assert.py; nothing to loop on"
        if args.json:
            print(json.dumps({"run": args.run, "failures": None, "action": "no_assertions", "reason": reason}))
        else:
            print(reason, file=sys.stderr)
        return duolib.exit_codes.UI_FAIL
    failures = duolib.load_json(fpath) or []
    ui_path = os.path.join(rdir, "ui.json")
    ui = duolib.load_json(ui_path) if os.path.exists(ui_path) else None

    if not failures:
        state["iterations"] = 0
        save_state(root, state)
        if ui is not None and ui.get("verified") is False:
            reason = ("no failures, but no cell had an element tree: the layout assertions were skipped, not passed "
                      "(install AXe or add the DuoUITests target, then rerun the matrix)")
            if args.json:
                print(json.dumps({"run": args.run, "failures": 0, "action": "unverified", "reason": reason}))
            else:
                print(reason, file=sys.stderr)
            return duolib.exit_codes.UI_FAIL
        out = {"run": args.run, "failures": 0, "action": "done"}
        print(json.dumps(out) if args.json else "no failures; loop complete")
        return 0

    if state.get("iterations", 0) >= cap:
        todo = write_todo(root, args.run, failures, state)
        save_state(root, state)
        out = {"run": args.run, "failures": len(failures), "action": "cap_reached", "todo": todo, "rerun": rerun_args(failures)}
        print(json.dumps(out) if args.json else f"iteration cap {cap} reached; wrote {todo}")
        return 0

    state["iterations"] = state.get("iterations", 0) + 1
    save_state(root, state)
    if not args.json:
        emit(failures, args.agent)
    out = {"run": args.run, "iteration": state["iterations"], "max_iterations": cap, "failures": len(failures),
           "action": "patch", "rerun": rerun_args(failures)}
    if args.json:
        out["payloads"] = failures
        print(json.dumps(out))
    else:
        print(f"iteration {state['iterations']}/{cap}: {len(failures)} payload(s) above; after patching rerun: scripts/run-matrix.sh {out['rerun']}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
