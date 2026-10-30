#!/usr/bin/env bash
# sim.sh - create, boot and pose the iPhone Duo simulator.
#
# Pose changes go through duoctl/hinge, which replay the vendor HID event that
# Device Hub sends (private protocol; see references/simulator-control.md).
# Every pose command is followed by a readback so a silently ignored change
# fails instead of producing screenshots of the wrong display.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/sim.sh <command> [args]

  ensure [--no-wait] [--quiet]   create "duo-ready" sim on iOS 27.1 if missing, boot it,
                                 wait 30 s for the post-boot black-screenshot window; prints UDID
  udid                           print the UDID in use
  pose <closed|open|book>        set the hinge (0 / 180 / 127 degrees) and wait for readback
  rotate <portrait|landscape>    rotate the active display (exit 6 when the app refuses)
  orientation                    print portrait|landscape of the lit display (window size from
                                 duoctl state, capture size as fallback; never the hinge label)
  wait-posture <closed|open|book> [--timeout <s>]   poll until the hinge reports the pose
  install <App.app>              simctl install
  launch [--no-check] <bundle.id> [args...]   simctl terminate + launch, then verify the
                                 process is still alive 3 s later (exit 3 when it died)
  terminate <bundle.id>
  shutdown                       simctl shutdown

Environment: DUOCTL_UDID / HINGE_DEVICE are exported for the child tools.
Exit 3 when a launched app dies, 4 when tools are missing, 5 when a pose change is
not confirmed, 6 when the app refuses a rotation (portrait-only on that display).
EOF
}

[ $# -gt 0 ] || { usage >&2; exit 4; }
case "$1" in -h|--help) usage; exit 0 ;; esac

# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

duo_require_macos
duo_require_tool xcrun
duo_require_tool "$DUO_PY"

SIM_NAME="duo-ready"
RUNTIME_ID="com.apple.CoreSimulator.SimRuntime.iOS-27-1"
DEVICE_TYPE="iPhone Duo"
UDID_FILE="$DUO_DIR/sim.udid"

pose_angle() {
  case "$1" in
    closed) echo 0 ;;
    book) echo 127 ;;
    open) echo 180 ;;
    *) duo_die "$DUO_EXIT_PREFLIGHT" "unknown pose '$1' (closed|open|book)" ;;
  esac
}

# Current hinge angle as an integer, or empty when unreadable.
read_angle() {
  hinge posture --json 2>/dev/null | "$DUO_PY" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
a = d.get("angle", d.get("hingeAngle"))
print(int(round(float(a))) if a is not None else "")' 2>/dev/null || true
}

angle_matches() {  # angle_matches <angle> <pose>
  local a="$1" want
  [ -n "$a" ] || return 1
  want="$(pose_angle "$2")"
  case "$2" in
    closed) [ "$a" -le 5 ] ;;
    open)   [ "$a" -ge 175 ] ;;
    book)   [ "$a" -ge $(( want - 10 )) ] && [ "$a" -le $(( want + 10 )) ] ;;
  esac
}

find_sim() {
  xcrun simctl list devices -j 2>/dev/null | "$DUO_PY" -c '
import json, sys
name, runtime = sys.argv[1], sys.argv[2]
data = json.load(sys.stdin)
for rt, devices in data.get("devices", {}).items():
    if rt != runtime:
        continue
    for d in devices:
        if d.get("name") == name and d.get("isAvailable", True):
            print(d["udid"] + " " + d.get("state", ""))
            sys.exit(0)
sys.exit(1)' "$SIM_NAME" "$RUNTIME_ID" || true
}

cmd="$1"; shift
case "$cmd" in
  ensure)
    WAIT=1; QUIET=0
    while [ $# -gt 0 ]; do
      case "$1" in --no-wait) WAIT=0 ;; --quiet) QUIET=1 ;; esac; shift
    done
    found="$(find_sim)"
    udid="${found%% *}"; state="${found#* }"
    if [ -z "$udid" ]; then
      [ "$QUIET" -eq 1 ] || duo_log "creating simulator '$SIM_NAME' ($DEVICE_TYPE, iOS 27.1)"
      udid="$(xcrun simctl create "$SIM_NAME" "$DEVICE_TYPE" "$RUNTIME_ID")" \
        || duo_die_host "simctl could not create an iPhone Duo on $RUNTIME_ID (install the iOS 27.1 runtime)"
      state="Shutdown"
    fi
    if [ "$state" != "Booted" ]; then
      [ "$QUIET" -eq 1 ] || duo_log "booting $udid (first boot can take minutes)"
      xcrun simctl boot "$udid" >/dev/null 2>&1 || true
      xcrun simctl bootstatus "$udid" -b >/dev/null 2>&1 || duo_die "$DUO_EXIT_PREFLIGHT" "simulator $udid did not finish booting"
      if [ "$WAIT" -eq 1 ]; then
        # Xcode 27.2 notes: Duo screenshots can be black for minutes after boot.
        [ "$QUIET" -eq 1 ] || duo_log "waiting 30 s for the display pipeline (black-screenshot window)"
        sleep 30
      fi
    fi
    mkdir -p "$DUO_DIR"
    printf '%s\n' "$udid" >"$UDID_FILE"
    echo "$udid"
    ;;
  udid)
    duo_sim_udid || duo_die "$DUO_EXIT_PREFLIGHT" "no iPhone Duo simulator booted (run: scripts/sim.sh ensure)"
    ;;
  pose)
    [ $# -ge 1 ] || { usage >&2; exit 4; }
    duo_require_tool duoctl "brew tap skarol/tap && brew trust skarol/tap && brew install skarol/tap/duoctl"
    duo_require_tool hinge "brew tap artemnovichkov/tap && brew trust artemnovichkov/tap && brew install artemnovichkov/tap/hinge"
    udid="$(duo_sim_udid)" || duo_die "$DUO_EXIT_PREFLIGHT" "no iPhone Duo simulator booted"
    export DUOCTL_UDID="$udid" HINGE_DEVICE="$udid"
    angle="$(pose_angle "$1")"
    case "$1" in
      closed) duoctl close >/dev/null 2>&1 || hinge close >/dev/null 2>&1 || true ;;
      open)   duoctl open  >/dev/null 2>&1 || hinge open  >/dev/null 2>&1 || true ;;
      book)   duoctl hinge "$angle" >/dev/null 2>&1 || hinge "$angle" >/dev/null 2>&1 || true ;;
    esac
    "$0" wait-posture "$1" --timeout 8
    ;;
  rotate)
    [ $# -ge 1 ] || { usage >&2; exit 4; }
    duo_require_tool duoctl "brew tap skarol/tap && brew trust skarol/tap && brew install skarol/tap/duoctl"
    udid="$(duo_sim_udid)" || duo_die "$DUO_EXIT_PREFLIGHT" "no iPhone Duo simulator booted"
    export DUOCTL_UDID="$udid" HINGE_DEVICE="$udid"
    case "$1" in
      portrait|landscape) ;;
      *) duo_die "$DUO_EXIT_PREFLIGHT" "orientation must be portrait or landscape" ;;
    esac
    # devicectl and XCUIDevice.orientation are silent no-ops on the Duo; duoctl
    # verifies the rotation against the active display and fails otherwise.
    # Two distinct failures (field test, 27 Oct 2026):
    #   "the active screen did not rotate ... (the app may not support it)" is
    #   the foreground app refusing: a portrait-locked app on the outer display,
    #   or SpringBoard, which is portrait-only there. That is a cell result
    #   (exit 6), not a protocol change. It is also intermittently reported
    #   right after a fold, so it is retried before being believed.
    # The current orientation is the window's (`sim.sh orientation`), not the
    # hinge's label: on the inner display that label is the device's and reads
    # "portrait" for a 951 x 669 landscape window, so 0.3.0 returned early here
    # and never rotated an inner cell (field test 3).
    cur="$("$0" orientation 2>/dev/null || true)"
    if [ "$cur" = "$1" ]; then exit 0; fi
    err=""; ok=0; i=0
    while [ "$i" -lt 3 ]; do
      if err="$(duoctl rotate "$1" 2>&1 >/dev/null)"; then ok=1; break; fi
      case "$err" in
        *"did not rotate"*|*"may not support"*) i=$(( i + 1 )); sleep 1 ;;
        *) break ;;
      esac
    done
    if [ "$ok" -ne 1 ]; then
      case "$err" in
        *"did not rotate"*|*"may not support"*)
          duo_refuse "the app in front refused to rotate to $1 on the active display (portrait-only there, or no app in front); $err" ;;
        *) duo_die "$DUO_EXIT_POSE" "duoctl could not rotate to $1: ${err:-no output} (private protocol changed?)" ;;
      esac
    fi
    # duoctl checks the rotation itself, but the readback lags by a few seconds
    # and a cell photographed in the wrong orientation passes under the wrong
    # name, so wait until the window agrees before returning (exit 1 otherwise:
    # an error cell in the matrix, never a pass).
    i=0; cur=""
    while [ "$i" -lt 12 ]; do
      cur="$("$0" orientation 2>/dev/null || true)"
      [ "$cur" = "$1" ] && break
      i=$(( i + 1 )); sleep 0.5
    done
    [ "$cur" = "$1" ] || duo_die "$DUO_EXIT_UI" "rotation to $1 did not take effect: the lit display still reports ${cur:-no orientation} after 6 s"
    ;;
  orientation)
    # Which display is lit comes from the hinge (`activeDisplay`); the window's
    # orientation comes from the size `duoctl state` reports for it. The hinge's
    # own `orientation` is the device's: on the inner display it reads
    # "portrait" for the 951 x 669 landscape window and lags a rotation by 2 to
    # 4 s (field test 3: 0.3.0 believed it, returned early from
    # `rotate portrait`, and photographed every inner portrait cell in
    # landscape). `duoctl state` is stale for a few seconds after a fold (field
    # test 2, note 11), so it is believed only once its activeScreen agrees with
    # the hinge; the capture size is the fallback.
    udid="$(duo_sim_udid)" || duo_die "$DUO_EXIT_PREFLIGHT" "no iPhone Duo simulator booted"
    export DUOCTL_UDID="$udid" HINGE_DEVICE="$udid"
    posture="$(hinge posture --json 2>/dev/null || true)"
    lit="$(printf '%s' "$posture" | "$DUO_PY" -c 'import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
a = str(d.get("activeDisplay", ""))
print("inner" if a.endswith("-1") else ("outer" if a else ""))' 2>/dev/null || true)"
    orient=""; i=0
    while [ "$i" -lt 8 ]; do
      state="$(duoctl state 2>/dev/null || true)"
      orient="$(printf '%s' "$state" | "$DUO_PY" -c 'import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
screen = {"cover": "outer", "inner": "inner"}.get(str(d.get("activeScreen", "")).lower(), "")
if sys.argv[1] and screen and screen != sys.argv[1]:
    sys.exit(0)  # stale: still the display that was lit before the fold
s = d.get("sizePoints") or []
if len(s) == 2 and s[0] and s[1]:
    print("landscape" if float(s[0]) > float(s[1]) else "portrait")' "$lit" 2>/dev/null || true)"
      [ -n "$orient" ] && break
      i=$(( i + 1 )); sleep 0.5
    done
    if [ -z "$orient" ]; then
      tmpd="$(mktemp -d)"
      cap="$("$DUO_SCRIPTS/capture.sh" "$tmpd/orientation.png" --display "${lit:-outer}" --retries 1 --json 2>/dev/null || true)"
      rm -rf "$tmpd"
      orient="$(printf '%s' "$cap" | "$DUO_PY" -c 'import json, sys
try:
    d = json.load(sys.stdin)
    print("landscape" if int(d["width"]) > int(d["height"]) else "portrait")
except Exception:
    pass' 2>/dev/null || true)"
    fi
    case "$orient" in
      landscape) echo landscape ;;
      portrait) echo portrait ;;
      *) exit 1 ;;
    esac
    ;;
  wait-posture)
    [ $# -ge 1 ] || { usage >&2; exit 4; }
    duo_require_tool hinge "brew tap artemnovichkov/tap && brew trust artemnovichkov/tap && brew install artemnovichkov/tap/hinge"
    want="$1"; shift; timeout=5
    while [ $# -gt 0 ]; do case "$1" in --timeout) timeout="$2"; shift ;; esac; shift; done
    udid="$(duo_sim_udid)" || duo_die "$DUO_EXIT_PREFLIGHT" "no iPhone Duo simulator booted"
    export DUOCTL_UDID="$udid" HINGE_DEVICE="$udid"
    deadline=$(( $(date +%s) + timeout ))
    while [ "$(date +%s)" -le "$deadline" ]; do
      a="$(read_angle)"
      if angle_matches "$a" "$want"; then
        # The active display switches 1-2.5 s after the angle (sim measurement).
        sleep 2.5
        echo "$want ${a}"
        exit 0
      fi
      sleep 0.5
    done
    duo_die "$DUO_EXIT_POSE" "hinge did not report pose '$want' within ${timeout}s (last angle: '${a:-unreadable}'); the private pose protocol may have changed, skip pose stages"
    ;;
  install)
    [ $# -ge 1 ] || { usage >&2; exit 4; }
    udid="$(duo_sim_udid)" || duo_die "$DUO_EXIT_PREFLIGHT" "no iPhone Duo simulator booted"
    xcrun simctl install "$udid" "$1"
    ;;
  launch)
    CHECK=1
    [ "${1:-}" = "--no-check" ] && { CHECK=0; shift; }
    [ $# -ge 1 ] || { usage >&2; exit 4; }
    udid="$(duo_sim_udid)" || duo_die "$DUO_EXIT_PREFLIGHT" "no iPhone Duo simulator booted"
    bundle="$1"; shift
    xcrun simctl terminate "$udid" "$bundle" >/dev/null 2>&1 || true
    xcrun simctl launch "$udid" "$bundle" "$@"
    # `simctl launch` returning a pid proves nothing: an app built with the
    # iOS 27 SDK and no UIScene life cycle is killed by UIKit about 2 s later
    # ("UIScene life cycle is required for apps built with this SDK", SIGTRAP),
    # and the matrix would then photograph the home screen (field test, 27 Oct
    # 2026). So wait and check the process is still there.
    if [ "$CHECK" -eq 1 ]; then
      sleep 3
      # Capture the list, then search it. `launchctl list | grep -q` under
      # pipefail returned SIGPIPE (141) 18 times out of 20 on the field test,
      # which reported a running app as dead and the matrix stopped at the
      # third cell.
      jobs="$(xcrun simctl spawn "$udid" launchctl list 2>/dev/null || true)"
      if ! printf '%s\n' "$jobs" | grep -F "$bundle" >/dev/null; then
        reason="exited within 3 s of launch"
        # Exclude the `log` process itself: it logs its own command line, which
        # contains the predicate text and matched it (field test 2).
        killed="$(xcrun simctl spawn "$udid" log show --last 1m --style compact --predicate 'eventMessage CONTAINS "UIScene life cycle is required" AND process != "log"' 2>/dev/null || true)"
        if printf '%s\n' "$killed" | grep -F "UIScene life cycle" >/dev/null; then
          reason="killed by UIKit: 'UIScene life cycle is required for apps built with this SDK'. The build is stamped with the iOS 27 SDK but the app has no UIApplicationSceneManifest / scene delegate (scan rule no-scene-delegate; Expo and React Native templates up to SDK 54 / 0.81 are in this state). Fix the life cycle before measuring anything"
        fi
        duo_die "$DUO_EXIT_BUILD" "$bundle $reason (log: xcrun simctl spawn $udid log show --last 2m --predicate 'process == \"<executable name>\"')"
      fi
    fi
    ;;
  terminate)
    [ $# -ge 1 ] || { usage >&2; exit 4; }
    udid="$(duo_sim_udid)" || exit 0
    xcrun simctl terminate "$udid" "$1" >/dev/null 2>&1 || true
    ;;
  shutdown)
    udid="$(duo_sim_udid)" || exit 0
    xcrun simctl shutdown "$udid" >/dev/null 2>&1 || true
    ;;
  *)
    echo "unknown command: $cmd" >&2; usage >&2; exit 4 ;;
esac
