#!/usr/bin/env bash
# perf.sh - run DuoPerfTests per cell and gate against the baseline.
#
# Metrics (references/perf.md): launch_ms per pose (XCTApplicationLaunchMetric),
# fold_relayout_ms (XCTClockMetric from the pose change to the first stable
# frame), memory_delta_mb and cpu across a transition; parsed by perfparse.py.
# Simulator numbers are not device numbers, so the default mode compares to
# the project's own baseline (.duo/baselines/perf.json); absolute thresholds
# apply only with `mode: absolute` or --absolute (meant for real hardware).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/perf.sh [--run <n>] [--cells c1,c2] [--udid <udid>] [--absolute] [--write-baseline] [--json]

  --run <n>          run number (default: latest)
  --cells            comma-separated cells (default: duo.yaml cells + transitions)
  --udid <udid>      measure on this booted simulator instead of the "duo-ready" one
  --absolute         gate on duo.yaml thresholds instead of the baseline
  --write-baseline   copy this run's perf.json to .duo/baselines/perf.json
  --json             print perf.json on stdout

Requires a UI test target named DuoPerfTests built from templates/DuoPerfTests.swift;
without it there is nothing to measure and the script exits 4 (never "pass").
Exit 0 pass, 2 perf failure, 3 no build (or the app dies at launch), 4 missing tool
or target or no metrics at all.
EOF
}

RUN=""; CELLS=""; ABSOLUTE=0; WRITE_BASELINE=0; JSON=0; UDID_OPT=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --run) RUN="$2"; shift ;;
    --cells) CELLS="$2"; shift ;;
    --udid) UDID_OPT="$2"; shift ;;
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

UDID="$(duo_select_sim "$UDID_OPT")"
export DUOCTL_UDID="$UDID" HINGE_DEVICE="$UDID"
DERIVED="$(duo_derived_data)"
POSE_ENV=()
[ -n "${DUO_POSE_URL:-}" ] && POSE_ENV=(TEST_RUNNER_DUO_POSE_URL="$DUO_POSE_URL")
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
  # Transition names carry ">" which is not a valid file name everywhere; files
  # use "-to-" and perfparse.py maps them back to the contract name.
  cell_file="$(printf '%s' "$cell" | sed 's/>/-to-/g')"
  result="$PERF_DIR/$cell_file.xcresult"
  rm -rf "$result"
  duo_log "perf: $cell"
  # xcodebuild forwards only TEST_RUNNER_-prefixed variables to a UI test
  # runner (they arrive without the prefix); a plain DUO_CELL never reached the
  # test on field test 2, so launch was measured in transition cells.
  env TEST_RUNNER_DUO_CELL="$cell" ${POSE_ENV[@]+"${POSE_ENV[@]}"} \
    xcodebuild ${CONTAINER[@]+"${CONTAINER[@]}"} -scheme "$SCHEME" -derivedDataPath "$DERIVED" \
      -destination "platform=iOS Simulator,id=$UDID" -only-testing:DuoPerfTests \
      -resultBundlePath "$result" ${XB_ARGS[@]+"${XB_ARGS[@]}"} test-without-building >"$PERF_DIR/$cell_file.log" 2>&1 \
    || duo_warn "DuoPerfTests reported failures for $cell (log: $PERF_DIR/$cell_file.log)"
  if grep "no test bundles available to test" "$PERF_DIR/$cell_file.log" >/dev/null; then
    duo_die_host "DuoPerfTests target not found in scheme $SCHEME: add templates/DuoPerfTests.swift to a UI test target named DuoPerfTests (templates/add-duo-test-targets.rb does it without Xcode; SKILL.md stage 6); without it there are no metrics"
  fi
  # Extract metrics. On Xcode 27.1 `xcresulttool get test-results metrics` is
  # the form that carries measurements; the legacy root object
  # (`get --legacy --format json`) has none and produced exit 4 with real
  # numbers in the log (field test 2). The legacy dump is kept as a fallback
  # for older toolchains.
  if ! xcrun xcresulttool get test-results metrics --path "$result" >"$PERF_DIR/$cell_file.metrics.json" 2>/dev/null; then
    rm -f "$PERF_DIR/$cell_file.metrics.json"
    xcrun xcresulttool get --legacy --format json --path "$result" >"$PERF_DIR/$cell_file.json" 2>/dev/null \
      || xcrun xcresulttool get --format json --path "$result" >"$PERF_DIR/$cell_file.json" 2>/dev/null \
      || printf '{}' >"$PERF_DIR/$cell_file.json"
  fi
done

STATUS=0
"$DUO_PY" "$DUO_SCRIPTS/perfparse.py" --run "$RUN" --perf-dir "$PERF_DIR" --out "$RUN_DIR/perf.json" \
  --baseline "$DUO_DIR/baselines/perf.json" --mode "$MODE" --config "$DUO_CONFIG" --log-dir "$PERF_DIR" || STATUS=$?

if [ "$WRITE_BASELINE" -eq 1 ] && [ "$STATUS" -ne 4 ]; then
  mkdir -p "$DUO_DIR/baselines"
  cp "$RUN_DIR/perf.json" "$DUO_DIR/baselines/perf.json"
  duo_log "baseline written to .duo/baselines/perf.json"
fi
[ "$JSON" -eq 1 ] && cat "$RUN_DIR/perf.json"
case "$STATUS" in
  0)
    # "pass" with nothing compared is not a pass (field test 3, note 10): the
    # first run of a project has no baseline, and perf.json says so.
    if "$DUO_PY" -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("status") == "baseline" else 1)' "$RUN_DIR/perf.json" 2>/dev/null; then
      if [ "$WRITE_BASELINE" -eq 1 ]; then
        echo "perf: baseline written from this run, nothing gated yet -> $RUN_DIR/perf.json"
      else
        echo "perf: baseline recorded, nothing gated (no .duo/baselines/perf.json yet; rerun with --write-baseline once the numbers look sane) -> $RUN_DIR/perf.json"
      fi
    else
      echo "perf: pass ($MODE mode) -> $RUN_DIR/perf.json"
    fi ;;
  4) echo "perf: NO METRICS -> $RUN_DIR/perf.json (its reason field says whether the target is missing or the parser found nothing)" ;;
  *) echo "perf: FAIL ($MODE mode) -> $RUN_DIR/perf.json" ;;
esac
exit "$STATUS"
