#!/usr/bin/env python3
"""Turn DuoPerfTests result bundles into perf.json.

    perfparse.py --run <n> --perf-dir <dir> --out <perf.json> [--baseline <path>]
                 [--mode regression|absolute] [--config duo.yaml] [--log-dir <dir>]

Reads `<cell>.metrics.json` files written by perf.sh with
`xcrun xcresulttool get test-results metrics --path <cell>.xcresult`
(the only xcresulttool form that carries measurements on Xcode 27.1; the
legacy `get --format json` root object has none, which is why the second
field test got exit 4 with real numbers in the log). Falls back to walking
any JSON for `measurements` so older dumps still parse.

Metric names (references/perf.md) are decided by test and metric identifier:

  testLaunch       XCTMetric_ApplicationLaunch duration   -> launch_ms
                   XCTMetric_Clock (whole measure block)   -> launch_wall_ms (reported, not gated)
                   XCTMetric_Memory.physical_peak          -> memory_peak_mb (reported, not gated)
                   XCTMetric_Memory.physical               -> memory_delta_mb
  testFoldRelayout XCTMetric_Clock                         -> fold_relayout_ms
                   XCTMetric_Memory.physical               -> memory_delta_mb
                   XCTMetric_CPU                           -> cpu_s (reported, not gated)

Cell names: perf.sh writes transitions as `closed-to-open`; here they become `closed>open`.
Exit 0 pass, 2 at least one fail, 4 no metrics at all (never a pass).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import duolib  # noqa: E402

GATED = ("launch_ms", "fold_relayout_ms", "memory_delta_mb")


def metric_name(test_id: str, ident: str) -> str | None:
    t = (test_id or "").lower()
    i = (ident or "").lower()
    relayout = "relayout" in t or "fold" in t
    if "applicationlaunch" in i or i.endswith(".duration"):
        return "launch_ms"
    if "clock" in i:
        return "fold_relayout_ms" if relayout else "launch_wall_ms"
    if "memory" in i:
        return "memory_peak_mb" if "peak" in i else "memory_delta_mb"
    if "cpu" in i:
        return "cpu_s"
    if "relayout" in i or "fold" in i:
        return "fold_relayout_ms"
    if "launch" in i:
        return "launch_ms"
    return None


def convert(metric: str, value: float, unit: str) -> float:
    u = (unit or "").lower()
    if metric.endswith("_ms") and u.startswith("s"):
        return value * 1000.0
    if metric.endswith("_mb"):
        if u.startswith("kb"):
            return value / 1024.0
        if u.startswith("bytes") or u == "b":
            return value / (1024.0 * 1024.0)
    return value


def _values(meas) -> list[float]:
    if isinstance(meas, dict):
        meas = meas.get("_values", [])
    out = []
    for m in meas or []:
        v = m.get("_value", m) if isinstance(m, dict) else m
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            pass
    return out


def parse_metrics_doc(doc) -> list[tuple[str, str, float, str, int]]:
    """Return (test_id, identifier, median, unit, n) tuples from a metrics dump."""
    found = []
    if isinstance(doc, list) and doc and isinstance(doc[0], dict) and "testRuns" in doc[0]:
        for test in doc:
            tid = str(test.get("testIdentifier") or test.get("testName") or "")
            for run in test.get("testRuns") or []:
                for m in run.get("metrics") or []:
                    vals = _values(m.get("measurements"))
                    if vals:
                        found.append((tid, str(m.get("identifier") or m.get("displayName") or ""), statistics.median(vals),
                                      str(m.get("unitOfMeasurement") or m.get("unit") or ""), len(vals)))
        return found

    def walk(node, tid):
        if isinstance(node, dict):
            if "testIdentifier" in node:
                tid = str(node.get("testIdentifier"))
            ident = str(node.get("identifier", node.get("name", node.get("displayName", ""))))
            if node.get("measurements") is not None:
                vals = _values(node.get("measurements"))
                if vals:
                    found.append((tid, ident, statistics.median(vals), str(node.get("unitOfMeasurement", node.get("unit", ""))), len(vals)))
            for v in node.values():
                walk(v, tid)
        elif isinstance(node, list):
            for v in node:
                walk(v, tid)
    walk(doc, "")
    return found


def cell_from_filename(fn: str) -> str:
    stem = re.sub(r"\.metrics\.json$|\.json$", "", fn)
    return stem.replace("-to-", ">")


def _measured_in_logs(log_dir: str | None) -> bool:
    if not log_dir or not os.path.isdir(log_dir):
        return False
    for fn in os.listdir(log_dir):
        if fn.endswith(".log"):
            try:
                with open(os.path.join(log_dir, fn), "r", encoding="utf-8", errors="replace") as f:
                    if "measured [" in f.read():
                        return True
            except OSError:
                pass
    return False


def build(run: int, perf_dir: str, baseline_path: str | None, mode: str, cfg: dict, log_dir: str | None = None) -> tuple[dict, int]:
    baseline = {}
    if baseline_path and os.path.isfile(baseline_path):
        for m in (duolib.load_json(baseline_path) or {}).get("metrics", []):
            baseline[(m.get("flow", "*"), m["cell"], m["metric"])] = m["value"]
    metrics = []
    files = sorted(fn for fn in os.listdir(perf_dir) if fn.endswith(".json")) if os.path.isdir(perf_dir) else []
    cells_with_metrics = {cell_from_filename(fn) for fn in files if fn.endswith(".metrics.json")}
    for fn in files:
        cell = cell_from_filename(fn)
        if not fn.endswith(".metrics.json") and cell in cells_with_metrics:
            continue  # prefer the test-results dump over a legacy root dump of the same cell
        try:
            doc = duolib.load_json(os.path.join(perf_dir, fn))
        except Exception:  # noqa: BLE001 - an unparsable dump is simply "no metrics"
            doc = None
        for tid, ident, value, unit, n in parse_metrics_doc(doc):
            metric = metric_name(tid, ident)
            if not metric:
                continue
            value = convert(metric, value, unit)
            base = baseline.get(("*", cell, metric))
            thr = cfg.get(metric) if isinstance(cfg.get(metric), dict) else {}
            status = "pass"
            if metric not in GATED or (metric == "memory_delta_mb" and "launch" in (tid or "").lower()):
                # memory_delta_mb from testLaunch is the launch-to-terminate delta,
                # about zero at 735% RSD on field test 3: reported, never gated.
                status = "info"
            elif mode == "absolute":
                if "fail" in thr and value > float(thr["fail"]):
                    status = "fail"
                elif "warn" in thr and value > float(thr["warn"]):
                    status = "warn"
            else:
                if base is None:
                    status = "baseline"
                elif value > base * 1.25:
                    status = "fail"
                elif value > base * 1.10:
                    status = "warn"
            metrics.append({"flow": "*", "cell": cell, "metric": metric, "value": round(value, 2), "baseline": base,
                            "status": status, "unit": "ms" if metric.endswith("_ms") else ("MB" if metric.endswith("_mb") else unit),
                            "identifier": ident, "test": tid, "iterations": n})
    doc = {"schema": 1, "run": int(run), "mode": mode,
           "generated": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "metrics": metrics}
    measured = list(metrics)
    if not measured:
        doc["status"] = "skip"
        if _measured_in_logs(log_dir):
            doc["reason"] = ("the xcodebuild log shows measurements but no <cell>.metrics.json carried any: "
                             "`xcrun xcresulttool get test-results metrics --path <cell>.xcresult` printed nothing this parser "
                             "understands (xcresulttool format changed?); attach one .xcresult to an issue")
        else:
            doc["reason"] = "no metrics collected (DuoPerfTests target missing, every cell skipped, or no measurements in the result bundles)"
        return doc, 4
    # A cell that ran and measured nothing is a skip row with its reason, not
    # an absence: field test 3 lost the three transition cells silently because
    # testFoldRelayout needs a hinge bridge the skill does not ship.
    seen_cells = {cell_from_filename(fn) for fn in files}
    # perf.sh writes <cell>.refused.txt when the app refused the orientation
    # (portrait lock): a skip row with that reason (field test 4).
    refused = {}
    for fn in (sorted(os.listdir(perf_dir)) if os.path.isdir(perf_dir) else []):
        if fn.endswith(".refused.txt"):
            try:
                with open(os.path.join(perf_dir, fn), "r", encoding="utf-8", errors="replace") as f:
                    refused[cell_from_filename(fn[:-len(".refused.txt")] + ".json")] = f.read().strip()
            except OSError:
                pass
    for cell in sorted((seen_cells | set(refused)) - {m["cell"] for m in measured}):
        if cell in refused:
            reason = refused[cell] or "the app refused the cell's orientation; nothing was measured"
            metric = "fold_relayout_ms" if ">" in cell else "launch_ms"
        elif ">" in cell:
            reason = ("DuoPerfTests skipped testFoldRelayout: TEST_RUNNER_DUO_POSE_URL is not set (the skill ships no "
                      "hinge bridge), so fold_relayout_ms and memory_delta_mb were not measured")
            metric = "fold_relayout_ms"
        else:
            reason = "no measurements in the result bundle (DuoPerfTests skipped or failed in this cell; see its .log)"
            metric = "launch_ms"
        metrics.append({"flow": "*", "cell": cell, "metric": metric, "value": None, "baseline": None,
                        "status": "skip", "unit": "ms", "reason": reason})
    gated = [m for m in measured if m["metric"] in GATED and m["status"] != "info"]
    if any(m["status"] == "fail" for m in measured):
        doc["status"] = "fail"
        return doc, 2
    if mode == "regression" and gated and all(m["status"] == "baseline" for m in gated):
        # Nothing was compared: say so instead of "pass" (field test 3, note 10).
        doc["status"] = "baseline"
        doc["reason"] = "no .duo/baselines/perf.json: every gated metric is a candidate baseline, nothing was gated"
    else:
        doc["status"] = "pass"
    doc["gated"] = sum(1 for m in gated if m["status"] in ("pass", "warn", "fail"))
    return doc, 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--perf-dir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--baseline")
    ap.add_argument("--mode", default="regression")
    ap.add_argument("--config")
    ap.add_argument("--log-dir")
    args = ap.parse_args(argv)
    cfg = {}
    if args.config and os.path.exists(args.config):
        cfg = (duolib.load_yaml(args.config) or {}).get("perf", {}) or {}
    doc, code = build(args.run, args.perf_dir, args.baseline, args.mode, cfg, args.log_dir or args.perf_dir)
    duolib.write_json(args.out, doc)
    return code


if __name__ == "__main__":
    sys.exit(main())
