#!/usr/bin/env bash
# perf.sh - run DuoPerfTests per cell and gate against the baseline.
#
# Metrics (references/perf.md): launch_ms per pose (XCTClockMetric around
# XCUIApplication.launch), fold_relayout_ms (signpost from the pose change to
# the first stable frame), memory_delta_mb and cpu across a transition.
# Simulator numbers are not device numbers, so the default mode compares to
# the project's own baseline (.duo/baselines/perf.json); absolute thresholds
# apply only with `mode: absolute` or --absolute (meant for real hardware).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/perf.sh [--run <n>] [--cells c1,c2] [--absolute] [--write-baseline] [--json]

  --run <n>          run number (default: latest)
  --cells            comma-separated cells (default: duo.yaml cells + transitions)
  --absolute         gate on duo.yaml thresholds instead of the baseline
  --write-baseline   copy this run's perf.json to .duo/baselines/perf.json
  --json             print perf.json on stdout

Requires a UI test target named DuoPerfTests built from templates/DuoPerfTests.swift;
without it there is nothing to measure and the script exits 4 (never "pass").
Exit 0 pass, 2 perf failure, 3 no build (or the app dies at launch), 4 missing tool
or target or no metrics at all.
EOF
}

RUN=""; CELLS=""; ABSOLUTE=0; WRITE_BASELINE=0; JSON=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --run) RUN="$2"; shift ;;
    --cells) CELLS="$2"; shift ;;
    --absolute) ABSOLUTE=1 ;;
    --write-baseline) WRITE_BASELINE=1 ;;
    --json) JSON=1 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 4 ;;
  esac
  shift
done

# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

duo_require_macos
duo_require_tool xcodebuild "install Xcode 27.1+"
duo_require_tool xcrun
duo_require_tool "$DUO_PY"
duo_require_config

[ -n "$RUN" ] || RUN="$(duo_latest_run)"
[ "$RUN" -gt 0 ] || duo_die "$DUO_EXIT_BUILD" "no run found; run scripts/build.sh first"
RUN_DIR="$(duo_run_dir "$RUN")"
[ -f "$RUN_DIR/build.json" ] || duo_die "$DUO_EXIT_BUILD" "$RUN_DIR/build.json missing"
PERF_DIR="$RUN_DIR/perf"
mkdir -p "$PERF_DIR"

MODE="$(duo_cfg perf.mode regression)"
[ "$ABSOLUTE" -eq 1 ] && MODE="absolute"
SCHEME="$(duo_cfg scheme)"
WS="$(duo_cfg workspace "")"; PROJ="$(duo_cfg project "")"
CONTAINER=()
if [ -n "$WS" ]; then CONTAINER=(-workspace "$WS"); elif [ -n "$PROJ" ]; then CONTAINER=(-project "$PROJ"); fi

if [ -n "$CELLS" ]; then
  CELL_LIST="$(printf '%s' "$CELLS" | tr ',' '\n')"
else
  CELL_LIST="$(duo_cfg_list cells; duo_cfg_list transitions)"
fi
[ -n "$CELL_LIST" ] || CELL_LIST="$(printf 'closed-portrait\nopen-landscape\nclosed>open\n')"

UDID="$("$DUO_SCRIPTS/sim.sh" ensure --quiet)"
export DUOCTL_UDID="$UDID" HINGE_DEVICE="$UDID"
DERIVED="$(duo_derived_data)"
XB_ARGS=()
while IFS= read -r xb_arg; do [ -n "$xb_arg" ] && XB_ARGS+=("$xb_arg"); done <<EOF
$(duo_xcodebuild_args)
EOF
BUNDLE_ID="$("$DUO_PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("bundle_id", ""))' "$RUN_DIR/build.json" 2>/dev/null || true)"

printf '%s\n' "$CELL_LIST" | while IFS= read -r cell; do
  [ -n "$cell" ] || continue
  case "$cell" in
    *">"*) pose="${cell%%>*}"; orient="portrait"; [ "$pose" != "closed" ] && orient="landscape" ;;
    *) pose="$(duo_cell_pose "$cell")"; orient="$(duo_cell_orientation "$cell")" ;;
  esac
  "$DUO_SCRIPTS/sim.sh" pose "$pose" >/dev/null
  # Put the app in front before rotating (SpringBoard is portrait-only on the
  # outer display); a cell the app refuses is skipped, not fatal.
  [ -z "$BUNDLE_ID" ] || "$DUO_SCRIPTS/sim.sh" launch "$BUNDLE_ID" >/dev/null
  st=0; "$DUO_SCRIPTS/sim.sh" rotate "$orient" >/dev/null || st=$?
  if [ "$st" -eq "$DUO_EXIT_UNSUPPORTED" ]; then duo_warn "perf: $cell skipped (the app refused the $orient orientation)"; continue; fi
  [ "$st" -eq 0 ] || exit "$st"
  result="$PERF_DIR/$cell.xcresult"
  rm -rf "$result"
  duo_log "perf: $cell"
  env DUO_CELL="$cell" DUO_SCRIPTS_DIR="$DUO_SCRIPTS" \
    xcodebuild ${CONTAINER[@]+"${CONTAINER[@]}"} -scheme "$SCHEME" -derivedDataPath "$DERIVED" \
      -destination "platform=iOS Simulator,id=$UDID" -only-testing:DuoPerfTests \
      -resultBundlePath "$result" ${XB_ARGS[@]+"${XB_ARGS[@]}"} test-without-building >"$PERF_DIR/$cell.log" 2>&1 \
    || duo_warn "DuoPerfTests reported failures for $cell (log: $PERF_DIR/$cell.log)"
  if grep -q "no test bundles available to test" "$PERF_DIR/$cell.log"; then
    duo_die_host "DuoPerfTests target not found in scheme $SCHEME: add templates/DuoPerfTests.swift to a UI test target named DuoPerfTests (SKILL.md stage 6); without it there are no metrics"
  fi
  # Extract metrics. Xcode 27.1 requires --legacy for `get --format json`
  # (verified 27 Oct 2026); newer builds may drop it, hence the fallback. The
  # parser below looks for any object carrying "identifier"/"name" +
  # "measurements" and keeps the median. TODO-VERIFY against a real
  # DuoPerfTests result bundle (the field test had no target).
  xcrun xcresulttool get --legacy --format json --path "$result" >"$PERF_DIR/$cell.json" 2>/dev/null \
    || xcrun xcresulttool get --format json --path "$result" >"$PERF_DIR/$cell.json" 2>/dev/null \
    || printf '{}' >"$PERF_DIR/$cell.json"
done

STATUS=0
"$DUO_PY" - "$RUN" "$PERF_DIR" "$RUN_DIR/perf.json" "$DUO_DIR/baselines/perf.json" "$MODE" "$DUO_CONFIG" "$DUO_SCRIPTS" <<'PY' || STATUS=$?
import json, os, sys, statistics, datetime
run, perf_dir, out, baseline_path, mode, cfg_path, scripts = sys.argv[1:]
sys.path.insert(0, scripts)
import duolib
cfg = duolib.load_yaml(cfg_path).get("perf", {}) or {}

NAME_MAP = {
    "launch": "launch_ms", "clock": "launch_ms", "duration": "launch_ms",
    "relayout": "fold_relayout_ms", "fold": "fold_relayout_ms",
    "memory": "memory_delta_mb", "physical": "memory_delta_mb",
    "cpu": "cpu_pct",
}

def walk(node, found):
    if isinstance(node, dict):
        ident = str(node.get("identifier", node.get("name", node.get("displayName", ""))))
        meas = node.get("measurements")
        if meas is not None:
            vals = []
            if isinstance(meas, dict):
                meas = meas.get("_values", [])
            for m in meas:
                v = m.get("_value", m) if isinstance(m, dict) else m
                try: vals.append(float(v))
                except (TypeError, ValueError): pass
            if vals:
                found.append((ident.lower(), statistics.median(vals), str(node.get("unitOfMeasurement", node.get("unit", "")))))
        for v in node.values(): walk(v, found)
    elif isinstance(node, list):
        for v in node: walk(v, found)

baseline = {}
if os.path.isfile(baseline_path):
    for m in json.load(open(baseline_path)).get("metrics", []):
        baseline[(m["flow"], m["cell"], m["metric"])] = m["value"]

metrics = []
for fn in sorted(os.listdir(perf_dir)):
    if not fn.endswith(".json"): continue
    cell = fn[:-5]
    try: doc = json.load(open(os.path.join(perf_dir, fn)))
    except Exception: doc = {}
    found = []
    walk(doc, found)
    for ident, value, unit in found:
        metric = next((v for k, v in NAME_MAP.items() if k in ident), None)
        if not metric: continue
        if metric == "launch_ms" and unit.startswith("s"): value *= 1000.0
        if metric == "memory_delta_mb" and unit.lower().startswith("kb"): value /= 1024.0
        key = ("*", cell, metric)
        base = baseline.get(key)
        status = "pass"
        thr = cfg.get(metric) or {}
        if mode == "absolute":
            if "fail" in thr and value > thr["fail"]: status = "fail"
            elif "warn" in thr and value > thr["warn"]: status = "warn"
        else:
            if base is None: status = "baseline"
            elif value > base * 1.25: status = "fail"
            elif value > base * 1.10: status = "warn"
        metrics.append({"flow": "*", "cell": cell, "metric": metric, "value": round(value, 2), "baseline": base, "status": status, "unit": unit})

doc = {"schema": 1, "run": int(run), "mode": mode, "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "metrics": metrics}
if not metrics:
    # No metrics is not a pass: the target is missing, every cell was skipped,
    # or the result bundles carried no measurements.
    doc["status"] = "skip"
    doc["reason"] = "no metrics collected (DuoPerfTests target missing, every cell skipped, or no measurements in the result bundles)"
json.dump(doc, open(out, "w"), indent=2); open(out, "a").write("\n")
if not metrics:
    sys.exit(4)
sys.exit(2 if any(m["status"] == "fail" for m in metrics) else 0)
PY

if [ "$WRITE_BASELINE" -eq 1 ] && [ "$STATUS" -ne 4 ]; then
  mkdir -p "$DUO_DIR/baselines"
  cp "$RUN_DIR/perf.json" "$DUO_DIR/baselines/perf.json"
  duo_log "baseline written to .duo/baselines/perf.json"
fi
[ "$JSON" -eq 1 ] && cat "$RUN_DIR/perf.json"
case "$STATUS" in
  0) echo "perf: pass ($MODE mode) -> $RUN_DIR/perf.json" ;;
  4) echo "perf: NO METRICS (DuoPerfTests target missing or nothing measured) -> $RUN_DIR/perf.json" ;;
  *) echo "perf: FAIL ($MODE mode) -> $RUN_DIR/perf.json" ;;
esac
exit "$STATUS"
