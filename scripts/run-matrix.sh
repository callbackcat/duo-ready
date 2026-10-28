#!/usr/bin/env bash
# run-matrix.sh - run every flow in every cell, capture, dump trees, assert.
#
# For each flow x cell from duo.yaml: pose + rotate the simulator, wait for the
# hinge readback, launch the app, execute the flow steps, capture the lit
# display and the element tree, then run scripts/assert.py over the run.
# Transitions ("closed>open") run the flow to its last step, change the pose
# mid-session, wait, and capture again, because a fold can resize the app
# while the user is in the middle of something.
#
# Runners:
#   native (uikit/swiftui/mixed)  xcodebuild test-without-building with the
#                                 DuoUITests target (templates/DuoUITests.swift),
#                                 FLOW/CELL/STEPS passed through the environment.
#                                 The test attaches <flow>-<cell>.tree.json.
#   react-native/expo             Maestro for closed-* cells when installed (it
#                                 misreports inner-display geometry and taps the
#                                 cover screen: mobile-dev-inc/maestro#3617);
#                                 open/book cells, and closed cells without
#                                 Maestro, use the small interpreter below built
#                                 on duoctl tap/swipe/elements and simctl openurl.
#   flutter/capacitor             same as react-native.
#
# Order inside a cell: pose, then the flow's steps (which launch the app), then
# the rotation, then tree + capture. Rotating before the app is in front asks
# SpringBoard to rotate, and on the outer display it is portrait-only, so every
# closed-landscape cell used to be refused (field test, 27 Oct 2026). A cell the
# app itself refuses is written as <flow>-<cell>.skip.json and reported by
# assert.py as skipped; it does not stop the matrix.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/run-matrix.sh [--run <n>] [--flows a,b] [--cells c1,c2] [--only-failed <failures.json>]
                             [--udid <udid>] [--driver duoctl] [--skip-transitions] [--no-assert] [--json]

  --run <n>              run number (default: latest build's run)
  --flows / --cells      comma-separated subsets of duo.yaml
  --only-failed <file>   rerun only the (flow, cell) pairs listed in failures.json
  --udid <udid>          drive this booted simulator instead of the "duo-ready" one
                         (for flows behind a sign-in; DUOCTL_UDID does the same)
  --driver duoctl        never use Maestro, even for closed cells (deeplink/wait/sleep
                         only on the outer display; nothing extra is installed)
  --skip-transitions     do not execute mid-flow pose transitions
  --no-assert            capture only; do not call scripts/assert.py
  --json                 print ui.json on stdout when done

Exit 0 pass, 1 assertion failures or a flow step that failed, 3 no build for the run (or the
app dies at launch), 4 missing tool, 5 pose control failed. Cells the app refuses (portrait-only)
are skipped, not fatal; a flow whose step fails is recorded as <flow>-<cell>.error.json and the
matrix carries on with the next cell.
EOF
}

RUN=""; FLOWS=""; CELLS=""; ONLY_FAILED=""; SKIP_TRANSITIONS=0; NO_ASSERT=0; JSON=0; UDID_OPT=""; DRIVER=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --run) RUN="$2"; shift ;;
    --flows) FLOWS="$2"; shift ;;
    --cells) CELLS="$2"; shift ;;
    --only-failed) ONLY_FAILED="$2"; shift ;;
    --udid) UDID_OPT="$2"; shift ;;
    --driver) DRIVER="$2"; shift ;;
    --skip-transitions) SKIP_TRANSITIONS=1 ;;
    --no-assert) NO_ASSERT=1 ;;
    --json) JSON=1 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 4 ;;
  esac
  shift
done

# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

duo_require_macos
duo_require_tool xcrun
duo_require_tool "$DUO_PY"
duo_require_config

[ -n "$RUN" ] || RUN="$(duo_latest_run)"
[ "$RUN" -gt 0 ] || duo_die "$DUO_EXIT_BUILD" "no run found; run scripts/build.sh first"
RUN_DIR="$(duo_run_dir "$RUN")"
BUILD_JSON="$RUN_DIR/build.json"
[ -f "$BUILD_JSON" ] || duo_die "$DUO_EXIT_BUILD" "$BUILD_JSON missing; run scripts/build.sh --run $RUN"
CAPTURES="$RUN_DIR/captures"
mkdir -p "$CAPTURES"

bjson() { "$DUO_PY" -c 'import json,sys; print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))' "$BUILD_JSON" "$1"; }
APP_PATH="$(bjson app)"
BUNDLE_ID="$(bjson bundle_id)"
SDK_STAMP="$(bjson sdk_stamp)"
STACK="$(duo_cfg stack)"
[ -n "$BUNDLE_ID" ] || BUNDLE_ID="$(duo_cfg bundle_id)"

if ! duo_version_ge "$SDK_STAMP" "27.1"; then
  duo_die "$DUO_EXIT_BUILD" "build $RUN is stamped SDK $SDK_STAMP; vertical bars and reserved regions only exist from 27.1, so the matrix would measure the wrong behaviour. Rebuild, or pass --allow-older to build.sh and accept that."
fi

# --- which flows and cells -------------------------------------------------
if [ -n "$CELLS" ]; then
  CELL_LIST="$(printf '%s' "$CELLS" | tr ',' '\n')"
else
  CELL_LIST="$(duo_cfg_list cells)"
  [ -n "$CELL_LIST" ] || CELL_LIST="$(printf 'closed-portrait\nclosed-landscape\nopen-landscape\nopen-portrait\nbook-landscape\nbook-portrait\n')"
fi
TRANSITION_LIST="$(duo_cfg_list transitions)"
[ "$SKIP_TRANSITIONS" -eq 1 ] && TRANSITION_LIST=""

# flows as "name<TAB>step1<US>step2..." lines, produced from duo.yaml by python
FLOW_LINES="$("$DUO_PY" - "$DUO_CONFIG" "$FLOWS" "$DUO_SCRIPTS" <<'PY'
import sys, os
sys.path.insert(0, sys.argv[3])
import duolib
doc = duolib.load_yaml(sys.argv[1])
only = [f for f in sys.argv[2].split(",") if f]
for flow in doc.get("flows") or []:
    name = flow.get("name")
    if only and name not in only:
        continue
    steps = flow.get("steps") or []
    print(name + "\t" + "\x1f".join(str(s) for s in steps))
PY
)"
[ -n "$FLOW_LINES" ] || duo_die "$DUO_EXIT_PREFLIGHT" "no flows in duo.yaml (add 2-5 flows; see templates/flows.yaml)"

# --only-failed: keep (flow,cell) pairs present in failures.json
pair_wanted() {  # pair_wanted <flow> <cell>
  [ -z "$ONLY_FAILED" ] && return 0
  "$DUO_PY" -c '
import json, sys
flow, cell = sys.argv[2], sys.argv[3]
for f in json.load(open(sys.argv[1])):
    if f.get("flow") == flow and f.get("cell") == cell:
        sys.exit(0)
sys.exit(1)' "$ONLY_FAILED" "$1" "$2"
}

# --- simulator -------------------------------------------------------------
[ -n "${DUOCTL_UDID:-}" ] && DUOCTL_UDID_GIVEN=1
UDID="$(duo_select_sim "$UDID_OPT")"
export DUOCTL_UDID="$UDID" HINGE_DEVICE="$UDID"
"$DUO_SCRIPTS/sim.sh" install "$APP_PATH" >/dev/null
duo_log "run $RUN: app $BUNDLE_ID (sdk $SDK_STAMP) installed on $UDID$([ -n "$UDID_OPT${DUOCTL_UDID_GIVEN:-}" ] && echo ' (chosen with --udid)')"
DERIVED="$(duo_derived_data)"
XB_ARGS=()
while IFS= read -r xb_arg; do [ -n "$xb_arg" ] && XB_ARGS+=("$xb_arg"); done <<EOF
$(duo_xcodebuild_args)
EOF

# A cell the app refuses (the outer display honours a portrait lock, so
# closed-landscape cannot exist for a portrait-only app) becomes a skip file
# next to the captures; assert.py reports it with status "skip".
skip_cell() {  # skip_cell <capture-base> <flow> <cell-label> <reason>
  "$DUO_PY" - "$1.skip.json" "$2" "$3" "$4" <<'PY'
import json, sys
out, flow, cell, reason = sys.argv[1:]
json.dump({"flow": flow, "cell": cell, "skipped": True, "reason": reason}, open(out, "w"), indent=2)
PY
  duo_warn "skipped $2 / $3: $4"
}

# A flow step that fails (timed-out wait, Maestro assertion, tap not found) is a
# result for that cell, not the end of the matrix: the cell gets
# <flow>-<cell>.error.json, assert.py reports it as a failed "flow" assertion,
# and the other cells still produce evidence. Field test 2 lost 16 good cells
# because one removed flow ended the run before assert.py (note 23).
error_cell() {  # error_cell <capture-base> <flow> <cell-label> <reason>
  rm -f "$1.tree.json" "$1.png" "$1.before.tree.json"
  "$DUO_PY" - "$1.error.json" "$2" "$3" "$4" <<'PY'
import json, sys
out, flow, cell, reason = sys.argv[1:]
json.dump({"flow": flow, "cell": cell, "error": True, "reason": reason}, open(out, "w"), indent=2)
PY
  duo_warn "flow $2 failed in $3: $4 (recorded, continuing with the next cell)"
}

# guarded <run_cell|run_transition> <flow> <cell-label> <capture-base> <args...>
# Runs the cell in a subshell so a duo_die inside a step (exit 1) becomes an
# error cell; build, tool and pose failures (3, 4, 5) still stop the matrix.
guarded() {
  local fn="$1" flow="$2" label="$3" base="$4"
  shift 4
  local st=0 errf="$RUN_DIR/last-cell.stderr" reason
  ( "$fn" "$@" ) 2>"$errf" || st=$?
  cat "$errf" >&2
  case "$st" in
    0) ;;
    "$DUO_EXIT_UI")
      reason="$(grep 'duo: error:' "$errf" | tail -n 1 | sed 's/^duo: error: //')"
      error_cell "$base" "$flow" "$label" "${reason:-step failed (see $errf)}" ;;
    *) exit "$st" ;;
  esac
  return 0
}

set_pose() {  # set_pose <cell>
  "$DUO_SCRIPTS/sim.sh" pose "$(duo_cell_pose "$1")" >/dev/null
  case "$1" in
    split-view-*)
      # TODO-VERIFY: no scripted way to enter Split View multitasking was found
      # for the Duo simulator (Maestro #3617 reports multitasking as unsupported
      # in the device profile). Split-view cells are captured in the open pose
      # and flagged "unverified" in ui.json by assert.py.
      duo_warn "cell $1: Split View cannot be scripted; capturing the open pose and marking the cell unverified" ;;
  esac
}

# Returns 6 when the app in front refuses the orientation; other failures exit.
set_orientation() {  # set_orientation <cell>
  local st=0
  "$DUO_SCRIPTS/sim.sh" rotate "$(duo_cell_orientation "$1")" >/dev/null || st=$?
  [ "$st" -eq 0 ] || [ "$st" -eq "$DUO_EXIT_UNSUPPORTED" ] || exit "$st"
  return "$st"
}

# --- step interpreter for non-native stacks (duoctl based) -----------------
# Grammar (references/pipeline-contracts.md): launch | reset | tap "x" | wait "x" |
# wait id:x | scroll n | deeplink url | pose p | rotate o | sleep s
run_steps_duoctl() {  # run_steps_duoctl <steps separated by US>
  local steps="$1" step verb arg
  # printf '%s\n': without the trailing newline `read` drops the last step.
  printf '%s\n' "$steps" | tr '\037' '\n' | while IFS= read -r step; do
    verb="${step%% *}"
    arg="${step#* }"; [ "$arg" = "$step" ] && arg=""
    arg="${arg#\"}"; arg="${arg%\"}"
    case "$verb" in
      launch) "$DUO_SCRIPTS/sim.sh" launch "$BUNDLE_ID" >/dev/null; sleep 2 ;;
      tap)
        # duoctl taps the inner touchscreen only ("no touchscreen for display"
        # on the cover); closed cells need Maestro or a deep link for taps.
        duoctl tap --label "$arg" >/dev/null || duo_die "$DUO_EXIT_UI" "step failed: $step (duoctl cannot tap the outer display; use Maestro for closed cells, or reach the screen by deep link)" ;;
      wait)
        # `wait "label"` or `wait id:some-test-id`; the AXe tree lists both.
        local i=0 needle="${arg#id:}" listing=""
        while :; do
          listing="$(duoctl elements 2>/dev/null || true)"
          if printf '%s' "$listing" | grep -F "$needle" >/dev/null; then break; fi
          i=$(( i + 1 )); [ "$i" -ge 20 ] && duo_die "$DUO_EXIT_UI" "step timed out: $step (not in the element tree after 10 s)"; sleep 0.5
        done ;;
      reset)
        # Clear app state: there is no simctl "clear data", so reinstall.
        xcrun simctl terminate "$UDID" "$BUNDLE_ID" >/dev/null 2>&1 || true
        xcrun simctl uninstall "$UDID" "$BUNDLE_ID" >/dev/null 2>&1 || true
        "$DUO_SCRIPTS/sim.sh" install "$APP_PATH" >/dev/null ;;
      scroll)
        # duoctl state (0.2.0) reports sizePoints: [w, h] of the active screen.
        local n="${arg:-1}" k=0 state w h
        state="$(duoctl state 2>/dev/null || echo '{}')"
        w="$(printf '%s' "$state" | "$DUO_PY" -c 'import json,sys; d=json.load(sys.stdin); s=d.get("sizePoints") or [d.get("width", 466), d.get("height", 678)]; print(int(s[0]))' 2>/dev/null || echo 466)"
        h="$(printf '%s' "$state" | "$DUO_PY" -c 'import json,sys; d=json.load(sys.stdin); s=d.get("sizePoints") or [d.get("width", 466), d.get("height", 678)]; print(int(s[1]))' 2>/dev/null || echo 678)"
        while [ "$k" -lt "$n" ]; do
          duoctl swipe $(( w / 2 )) $(( h * 3 / 4 )) $(( w / 2 )) $(( h / 4 )) >/dev/null || true
          k=$(( k + 1 )); sleep 0.5
        done ;;
      deeplink)
        # The first custom-scheme link on a fresh simulator can show an
        # "Open in <App>?" sheet that nothing here can confirm on the outer
        # display; run the flow once by hand or use a universal link
        # (references/simulator-control.md).
        xcrun simctl openurl "$UDID" "$arg"; sleep 1.5 ;;
      pose) "$DUO_SCRIPTS/sim.sh" pose "$arg" >/dev/null ;;
      rotate) "$DUO_SCRIPTS/sim.sh" rotate "$arg" >/dev/null ;;
      sleep) sleep "$arg" ;;
      "") ;;
      *) duo_warn "unknown step '$step' ignored" ;;
    esac
  done
}

run_steps_maestro() {  # run_steps_maestro <flow> <steps>
  duo_require_tool maestro "https://maestro.mobile.dev"
  local yaml="$RUN_DIR/maestro-$1.yaml"
  "$DUO_PY" - "$yaml" "$BUNDLE_ID" "$2" <<'PY'
import sys
out, app, steps = sys.argv[1], sys.argv[2], sys.argv[3].split("\x1f")
lines = [f"appId: {app}", "---"]
for s in steps:
    verb, _, arg = s.partition(" ")
    arg = arg.strip().strip('"')
    if verb == "launch": lines.append("- launchApp")
    elif verb == "reset": lines.append("- clearState")
    elif verb == "tap":
        # a bare string is a text/label regex to Maestro; `id:` selects a testID
        lines.append(f'- tapOn:\n    id: "{arg[3:]}"' if arg.startswith("id:") else f'- tapOn: "{arg}"')
    elif verb == "wait":
        sel = f'visible:\n      id: "{arg[3:]}"' if arg.startswith("id:") else f'visible: "{arg}"'
        lines.append(f'- extendedWaitUntil:\n    {sel}\n    timeout: 10000')
    elif verb == "scroll": lines += ["- scroll"] * int(arg or 1)
    elif verb == "deeplink": lines.append(f'- openLink: "{arg}"')
    elif verb == "sleep": lines.append(f"- waitForAnimationToEnd:\n    timeout: {int(float(arg or 1) * 1000)}")
    # pose / rotate are handled by the shell around Maestro
open(out, "w").write("\n".join(lines) + "\n")
PY
  maestro --udid "$UDID" test "$yaml" >"$RUN_DIR/maestro-$1.log" 2>&1 || duo_die "$DUO_EXIT_UI" "maestro flow $1 failed (log: $RUN_DIR/maestro-$1.log)"
}

run_steps() {  # run_steps <flow> <cell> <steps>: Maestro for closed cells when installed, else duoctl
  case "$2" in
    closed-*)
      if [ "$DRIVER" != "duoctl" ] && command -v maestro >/dev/null 2>&1; then
        run_steps_maestro "$1" "$3"
      else
        [ -n "${MAESTRO_WARNED:-}" ] || { duo_warn "maestro not installed: closed cells use the duoctl interpreter (launch, deeplink, sleep, pose, rotate; no taps on the outer display)"; MAESTRO_WARNED=1; }
        run_steps_duoctl "$3"
      fi ;;
    *) run_steps_duoctl "$3" ;;
  esac
}

dump_tree_duoctl() {  # dump_tree_duoctl <out.tree.json>
  # `duoctl elements` prints JSON by default and has no --json flag (duoctl
  # 0.2.0; the flag made every tree "unavailable" on field test 2). The raw
  # list is normalised by scripts/tree.py (types, duplicates, interactive).
  if duoctl elements >"$1.raw" 2>"$1.err" && "$DUO_PY" "$DUO_SCRIPTS/tree.py" from-axe "$1.raw" "$1" --udid "$UDID" --driver run-matrix 2>>"$1.err"; then
    rm -f "$1.raw" "$1.err"
  else
    local why
    why="$(sed -n 1p "$1.err" 2>/dev/null || true)"
    rm -f "$1.raw" "$1.err"
    "$DUO_PY" - "$1" "${why:-no output}" <<'PY'
import json, sys
json.dump({"elements": [], "source": "unavailable",
           "note": "duoctl elements failed: " + sys.argv[2] + " (AXe missing? brew tap cameroncooke/axe && brew trust cameroncooke/axe && brew install axe)"}, open(sys.argv[1], "w"), indent=2)
PY
    [ -n "${AXE_WARNED:-}" ] || { duo_warn "duoctl elements failed (${why:-no output}): element trees are unavailable and assert.py reports tree-based assertions as skipped, not passed (AXe missing? brew tap cameroncooke/axe && brew trust cameroncooke/axe && brew install axe)"; AXE_WARNED=1; }
  fi
}

run_native_cell() {  # run_native_cell <flow> <cell> <steps> <capture-base>
  duo_require_tool xcodebuild
  local scheme ws proj container=() result="$RUN_DIR/xcresult-$1-$2.xcresult"
  scheme="$(duo_cfg scheme)"; ws="$(duo_cfg workspace "")"; proj="$(duo_cfg project "")"
  if [ -n "$ws" ]; then container=(-workspace "$ws"); elif [ -n "$proj" ]; then container=(-project "$proj"); fi
  rm -rf "$result"
  # DuoUITests is the template target; the user adds templates/DuoUITests.swift
  # to a UI test target of that name (SKILL.md stage 5). xcodebuild forwards
  # only TEST_RUNNER_-prefixed variables to a UI test runner, where they arrive
  # without the prefix (field test 2: a plain DUO_CELL never reached the test).
  local pose_env=()
  [ -n "${DUO_POSE_URL:-}" ] && pose_env=(TEST_RUNNER_DUO_POSE_URL="$DUO_POSE_URL")
  if ! env TEST_RUNNER_DUO_FLOW="$1" TEST_RUNNER_DUO_CELL="$2" TEST_RUNNER_DUO_STEPS="$3" TEST_RUNNER_DUO_TREE_OUT="$4.tree.json" \
      ${pose_env[@]+"${pose_env[@]}"} \
      xcodebuild ${container[@]+"${container[@]}"} -scheme "$scheme" -derivedDataPath "$DERIVED" \
      -destination "platform=iOS Simulator,id=$UDID" -only-testing:DuoUITests \
      -resultBundlePath "$result" ${XB_ARGS[@]+"${XB_ARGS[@]}"} test-without-building >"$RUN_DIR/xcodebuild-$1-$2.log" 2>&1; then
    if grep -q "no test bundles available to test" "$RUN_DIR/xcodebuild-$1-$2.log"; then
      duo_die_host "DuoUITests target not found in scheme $scheme: add templates/DuoUITests.swift to a UI test target named DuoUITests (SKILL.md stage 5)"
    fi
    duo_warn "DuoUITests failed for $1/$2 (log: $RUN_DIR/xcodebuild-$1-$2.log); capturing whatever is on screen"
  fi
  # Export the tree attachment the test wrote.
  if [ ! -f "$4.tree.json" ] && [ -d "$result" ]; then
    xcrun xcresulttool export attachments --path "$result" --output-path "$RUN_DIR/attachments-$1-$2" >/dev/null 2>&1 || true
    found="$(find "$RUN_DIR/attachments-$1-$2" -name '*tree*.json' 2>/dev/null | sed -n 1p)"
    [ -n "$found" ] && cp "$found" "$4.tree.json"
  fi
  [ -f "$4.tree.json" ] || printf '{"elements":[],"source":"unavailable","note":"DuoUITests attachment not found"}\n' >"$4.tree.json"
}

run_cell() {  # run_cell <flow> <cell> <steps>
  local base="$CAPTURES/$1-$2"
  rm -f "$base.skip.json"
  set_pose "$2"
  case "$STACK" in
    uikit|swiftui|mixed)
      # XCUITest launches the app itself; put it in front first so the rotation
      # is applied to the app, not to SpringBoard. The device orientation
      # survives the relaunch.
      "$DUO_SCRIPTS/sim.sh" launch "$BUNDLE_ID" >/dev/null
      if ! set_orientation "$2"; then
        skip_cell "$base" "$1" "$2" "the app refused to rotate to $(duo_cell_orientation "$2") in pose $(duo_cell_pose "$2") (portrait-only there; orientation locks are honoured on the outer display)"
        return 0
      fi
      run_native_cell "$1" "$2" "$3" "$base" ;;
    *)
      run_steps "$1" "$2" "$3"
      if ! set_orientation "$2"; then
        skip_cell "$base" "$1" "$2" "the app refused to rotate to $(duo_cell_orientation "$2") in pose $(duo_cell_pose "$2") (portrait-only there; orientation locks are honoured on the outer display)"
        return 0
      fi
      dump_tree_duoctl "$base.tree.json" ;;
  esac
  "$DUO_SCRIPTS/capture.sh" "$base.png" --cell "$2" >/dev/null
  duo_log "captured $1 / $2"
}

run_transition() {  # run_transition <flow> <steps> <from>to<to>
  # one `local` per assignment: `local a="$x" b="$a"` expands every word before
  # any of them is assigned, so $a is unbound under set -u (field test)
  local from to base from_cell to_cell
  from="${3%%>*}"
  to="${3#*>}"
  base="$CAPTURES/$1-$from-to-$to"
  from_cell="$from-landscape"; to_cell="$to-landscape"
  [ "$from" = "closed" ] && from_cell="closed-portrait"
  [ "$to" = "closed" ] && to_cell="closed-portrait"
  rm -f "$base.skip.json"
  set_pose "$from_cell"
  case "$STACK" in
    uikit|swiftui|mixed)
      "$DUO_SCRIPTS/sim.sh" launch "$BUNDLE_ID" >/dev/null
      if ! set_orientation "$from_cell"; then
        skip_cell "$base" "$1" "$3" "the app refused the $from_cell orientation before the transition"
        return 0
      fi
      run_native_cell "$1" "$from_cell" "$2" "$CAPTURES/$1-$from_cell"
      # element tree before the pose change feeds assert.py's transition_stable check
      [ -f "$CAPTURES/$1-$from_cell.tree.json" ] && cp "$CAPTURES/$1-$from_cell.tree.json" "$base.before.tree.json" ;;
    *)
      run_steps "$1" "$from_cell" "$2"
      if ! set_orientation "$from_cell"; then
        skip_cell "$base" "$1" "$3" "the app refused the $from_cell orientation before the transition"
        return 0
      fi
      dump_tree_duoctl "$base.before.tree.json" ;;
  esac
  "$DUO_SCRIPTS/sim.sh" pose "$to" >/dev/null
  sleep 1
  # The inner display comes up portrait after an unfold (2007 x 2853 captures on
  # field test 2), not in the landscape the cell name suggests; record what the
  # hinge reports and let assert.py size the window from the capture.
  local actual
  actual="$("$DUO_SCRIPTS/sim.sh" orientation 2>/dev/null || true)"
  [ -n "$actual" ] && [ "$to" != "closed" ] && to_cell="$to-$actual"
  case "$STACK" in
    uikit|swiftui|mixed) : ;;  # tree after transition comes from the next cell run
    *) dump_tree_duoctl "$base.tree.json" ;;
  esac
  "$DUO_SCRIPTS/capture.sh" "$base.png" --cell "$to_cell" >/dev/null
  duo_log "captured transition $1 / $3 (after: $to_cell)"
}

# --- main loop ---------------------------------------------------------------
printf '%s\n' "$FLOW_LINES" | while IFS="$(printf '\t')" read -r flow steps; do
  [ -n "$flow" ] || continue
  printf '%s\n' "$CELL_LIST" | while IFS= read -r cell; do
    [ -n "$cell" ] || continue
    pair_wanted "$flow" "$cell" || continue
    guarded run_cell "$flow" "$cell" "$CAPTURES/$flow-$cell" "$flow" "$cell" "$steps"
  done
  if [ -n "$TRANSITION_LIST" ]; then
    printf '%s\n' "$TRANSITION_LIST" | while IFS= read -r tr; do
      [ -n "$tr" ] || continue
      pair_wanted "$flow" "$tr" || continue
      guarded run_transition "$flow" "$tr" "$CAPTURES/$flow-${tr%%>*}-to-${tr#*>}" "$flow" "$steps" "$tr"
    done
  fi
done

"$DUO_SCRIPTS/sim.sh" pose closed >/dev/null 2>&1 || true

if [ "$NO_ASSERT" -eq 1 ]; then
  echo "captures written to $CAPTURES (assertions skipped)"
  exit 0
fi

[ -f "$DUO_SCRIPTS/assert.py" ] || duo_die "$DUO_EXIT_PREFLIGHT" "scripts/assert.py missing"
status=0
"$DUO_PY" "$DUO_SCRIPTS/assert.py" --run "$RUN" || status=$?
[ "$JSON" -eq 1 ] && [ -f "$RUN_DIR/ui.json" ] && cat "$RUN_DIR/ui.json"
exit "$status"
