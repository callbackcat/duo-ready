#!/usr/bin/env bash
# preflight.sh - verify this Mac can run every duo-ready stage.
#
# Checks, in order: macOS, Xcode >= 27.1, iOS 27.1 simulator runtime, the
# iPhone Duo device type, python3, duoctl + hinge, a Duo simulator (created
# and booted if needed), and finally that pose control actually works by
# driving the hinge to 180 and reading it back. Pose control relies on a
# private HID protocol (see references/simulator-control.md); if the readback
# fails the protocol has probably changed and every pose stage must be
# skipped, not faked. fastlane is checked but only warned about.
#
# Exit codes: 0 ok, 4 missing tool / wrong host, 5 pose control unavailable.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/preflight.sh [--json] [--skip-pose] [--no-boot] [--timeout <s>]

  --json         print a machine-readable summary on stdout
  --skip-pose    do not prove pose control (checks tools only)
  --no-boot      do not create/boot a simulator (implies --skip-pose)
  --timeout <s>  seconds to wait for the hinge readback (default 15)

Exit 0 when every stage can run, 4 when a tool or host requirement is
missing, 5 when duoctl/hinge are installed but the simulator ignores them.
EOF
}

JSON=0; SKIP_POSE=0; NO_BOOT=0; TIMEOUT=15
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --json) JSON=1 ;;
    --skip-pose) SKIP_POSE=1 ;;
    --no-boot) NO_BOOT=1; SKIP_POSE=1 ;;
    --timeout) TIMEOUT="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 4 ;;
  esac
  shift
done

# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

# With --json the exit-4 path must produce JSON too (the field test got an
# empty stdout and had to read stderr).
duo_die_host() {
  printf 'cannot run on this host: %s\n' "$*" >&2
  [ "$JSON" -eq 1 ] && printf '{"ok":false,"exit":4,"reason":"%s"}\n' "$(duo_json_escape "$*" 2>/dev/null || true)"
  exit "$DUO_EXIT_PREFLIGHT"
}

MIN_XCODE="27.1"
MIN_FASTLANE="2.241.1"
RUNTIME_ID="com.apple.CoreSimulator.SimRuntime.iOS-27-1"
DEVICE_TYPE="iPhone Duo"

XCODE_VERSION=""; RUNTIME_OK=0; DEVTYPE_OK=0; DUOCTL_VER=""; HINGE_VER=""
FASTLANE_VER=""; FASTLANE_OK=0; SIM_UDID=""; POSE_OK="skipped"; WARNINGS=""

warn() { duo_warn "$*"; WARNINGS="$WARNINGS$*; "; }

duo_require_macos
duo_require_tool xcodebuild "install Xcode 27.1 or later from the App Store"
duo_require_tool xcrun
duo_require_tool "$DUO_PY" "python3 comes with Xcode's command line tools: xcode-select --install"

# --- Xcode version ---------------------------------------------------------
# Capture first, then parse: `xcodebuild -version | awk '... exit'` under
# pipefail dies with SIGPIPE (exit 141) about one run in eight (field test).
XCODEBUILD_OUT="$(xcodebuild -version 2>/dev/null || true)"
XCODE_VERSION="$(printf '%s\n' "$XCODEBUILD_OUT" | awk '/^Xcode/ && !done {print $2; done=1}')"
if [ -z "$XCODE_VERSION" ]; then
  duo_die_host "xcodebuild -version returned nothing (run: sudo xcode-select -s /Applications/Xcode.app)"
fi
if ! duo_version_ge "$XCODE_VERSION" "$MIN_XCODE"; then
  duo_die_host "Xcode $XCODE_VERSION found, $MIN_XCODE or later required for the iPhone Duo SDK and simulator"
fi
duo_log "Xcode $XCODE_VERSION"

# --- iOS 27.1 runtime and Duo device type ---------------------------------
RUNTIME_JSON="$(xcrun simctl list runtimes -j 2>/dev/null || echo '{}')"
if printf '%s' "$RUNTIME_JSON" | "$DUO_PY" -c '
import json, sys
data = json.load(sys.stdin)
for r in data.get("runtimes", []):
    if r.get("identifier") == sys.argv[1] and r.get("isAvailable", True):
        sys.exit(0)
sys.exit(1)' "$RUNTIME_ID"; then
  RUNTIME_OK=1
else
  duo_die_host "iOS 27.1 simulator runtime missing (run: xcodebuild -downloadPlatform iOS, or Xcode > Settings > Components)"
fi

DEVTYPES="$(xcrun simctl list devicetypes 2>/dev/null || true)"
if printf '%s
' "$DEVTYPES" | grep -F "iPhone-Duo" >/dev/null; then
  DEVTYPE_OK=1
else
  duo_die_host "device type 'iPhone Duo' not listed by simctl (Xcode $XCODE_VERSION may lack Duo support)"
fi
duo_log "iOS 27.1 runtime and iPhone Duo device type present"

# --- pose control tools ----------------------------------------------------
# Homebrew 7 refuses formulae from untrusted third-party taps until `brew trust`
# has been run for the tap (field test 2); the hints include that step.
BREW_HINT="brew tap skarol/tap artemnovichkov/tap && brew trust skarol/tap artemnovichkov/tap && brew install skarol/tap/duoctl artemnovichkov/tap/hinge  (on macOS 27 Homebrew first needs the Command Line Tools for Xcode 27: Software Update, or xcode-select --install)"
duo_require_tool duoctl "$BREW_HINT"
duo_require_tool hinge "$BREW_HINT"
DUOCTL_VER="$(duoctl --version 2>/dev/null | sed -n 1p || echo unknown)"
HINGE_VER="$(hinge --version 2>/dev/null | sed -n 1p || echo unknown)"
duo_log "duoctl ($DUOCTL_VER) and hinge ($HINGE_VER) installed"

# --- fastlane (warn only; needed for the assets stage) ---------------------
if command -v fastlane >/dev/null 2>&1; then
  FASTLANE_OUT="$(fastlane --version 2>/dev/null || true)"
  FASTLANE_VER="$(printf '%s\n' "$FASTLANE_OUT" | awk '/^fastlane [0-9]/ && !done {print $2; done=1}')"
  if [ -n "$FASTLANE_VER" ] && duo_version_ge "$FASTLANE_VER" "$MIN_FASTLANE"; then
    FASTLANE_OK=1
  else
    FASTLANE_BIN="$(command -v fastlane)"
    FASTLANE_REAL="$(readlink "$FASTLANE_BIN" 2>/dev/null || echo "$FASTLANE_BIN")"
    case "$FASTLANE_REAL" in
      *Cellar*|*homebrew*|*linuxbrew*) FASTLANE_UPDATE="brew upgrade fastlane" ;;
      *) FASTLANE_UPDATE="gem update fastlane" ;;
    esac
    warn "fastlane ${FASTLANE_VER:-?} is older than $MIN_FASTLANE; only matters if your own deliver lane sends the Duo set, the skill does not upload ($FASTLANE_UPDATE)"
  fi
else
  warn "fastlane not installed; fine, the skill does not upload (screenshots are exported to fastlane/screenshots for a by-hand upload)"
fi

# --- flow driver and element trees (warn only) -----------------------------
# Maestro drives the closed-pose flows of React Native/Expo apps; AXe gives
# `duoctl elements` the element trees that every layout assertion reads.
# Without AXe the trees are empty and assert.py reports those assertions as
# skipped, not passed. Neither was installed on the first field-test Mac.
MAESTRO_OK=0; AXE_OK=0
if command -v maestro >/dev/null 2>&1; then
  MAESTRO_OK=1
else
  warn "maestro not installed; React Native/Expo closed-pose flows fall back to the duoctl interpreter (launch, deeplink, wait, sleep; no taps on the outer display): brew tap mobile-dev-inc/tap && brew trust mobile-dev-inc/tap && brew install mobile-dev-inc/tap/maestro  (not the unrelated 'maestro' cask; the curl installer is refused by agent sandboxes)"
fi
if command -v axe >/dev/null 2>&1; then
  AXE_OK=1
else
  warn "AXe not installed; element trees will be empty and layout assertions skipped: brew tap cameroncooke/axe && brew trust cameroncooke/axe && brew install axe"
fi

# --- simulator -------------------------------------------------------------
if [ "$NO_BOOT" -eq 0 ]; then
  SIM_UDID="$("$DUO_SCRIPTS/sim.sh" ensure --no-wait --quiet)"
  duo_log "simulator $SIM_UDID booted"
fi

# --- prove the element tree path -------------------------------------------
# `command -v axe` is not proof: field test 2 had AXe installed and still got
# empty trees from a bad flag. One `duoctl elements` against the booted
# simulator (SpringBoard when nothing is in front) must return a JSON list.
ELEMENTS_OK="untested"
if [ "$NO_BOOT" -eq 0 ] && [ "$AXE_OK" -eq 1 ]; then
  # SpringBoard's accessibility tree is reachable only some seconds after
  # `simctl bootstatus -b` returns, so a cold preflight reported "failed" and
  # "trees will be unavailable" for a simulator that answered 30 s later (field
  # test 3, note 1). Retry for up to 30 s before believing a failure.
  ELEMENTS_OUT=""; deadline=$(( $(date +%s) + 30 ))
  while :; do
    ELEMENTS_OUT="$(DUOCTL_UDID="$SIM_UDID" duoctl elements 2>&1 || true)"
    if printf '%s' "$ELEMENTS_OUT" | "$DUO_PY" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(1)
sys.exit(0 if isinstance(d, list) and d else 1)'; then
      ELEMENTS_OK="ok"; break
    fi
    [ "$(date +%s)" -lt "$deadline" ] || break
    sleep 2
  done
  if [ "$ELEMENTS_OK" = "ok" ]; then
    duo_log "element trees verified (duoctl elements returned a list)"
  else
    ELEMENTS_OK="failed"
    warn "duoctl elements did not return an element list within 30 s ($(printf '%s' "$ELEMENTS_OUT" | sed -n 1p | cut -c1-120)); trees will be unavailable and layout assertions skipped"
  fi
fi

# --- prove pose control ----------------------------------------------------
if [ "$SKIP_POSE" -eq 0 ]; then
  export DUOCTL_UDID="$SIM_UDID" HINGE_DEVICE="$SIM_UDID"
  POSE_OK="failed"
  if hinge open >/dev/null 2>&1; then
    deadline=$(( $(date +%s) + TIMEOUT ))
    while [ "$(date +%s)" -lt "$deadline" ]; do
      angle="$(hinge posture --json 2>/dev/null | "$DUO_PY" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
a = d.get("angle", d.get("hingeAngle"))
print(int(round(float(a))) if a is not None else "")' || true)"
      if [ "$angle" = "180" ]; then POSE_OK="ok"; break; fi
      sleep 1
    done
  fi
  if [ "$POSE_OK" != "ok" ]; then
    hinge close >/dev/null 2>&1 || true
    printf '%s\n' "duo: error: hinge open did not reach 180 degrees within ${TIMEOUT}s. The private HID protocol that duoctl/hinge use has probably changed in this Xcode ($XCODE_VERSION). Skip the pose stages (ui matrix, perf transitions, assets) or set poses by hand in Device Hub; do not report them as passed." >&2
    [ "$JSON" -eq 1 ] && printf '{"ok":false,"exit":5,"xcode":"%s","pose_control":"failed"}\n' "$XCODE_VERSION"
    exit "$DUO_EXIT_POSE"
  fi
  hinge close >/dev/null 2>&1 || true
  duo_log "pose control verified (hinge 180 readback)"
fi

if [ "$JSON" -eq 1 ]; then
  printf '{"ok":true,"exit":0,"xcode":"%s","runtime_ios_27_1":%s,"device_type_duo":%s,"duoctl":"%s","hinge":"%s","maestro":%s,"axe":%s,"elements":"%s","fastlane":"%s","fastlane_ok":%s,"sim_udid":"%s","pose_control":"%s","warnings":"%s"}\n' \
    "$XCODE_VERSION" "$([ $RUNTIME_OK -eq 1 ] && echo true || echo false)" "$([ $DEVTYPE_OK -eq 1 ] && echo true || echo false)" \
    "$(duo_json_escape "$DUOCTL_VER")" "$(duo_json_escape "$HINGE_VER")" \
    "$([ $MAESTRO_OK -eq 1 ] && echo true || echo false)" "$([ $AXE_OK -eq 1 ] && echo true || echo false)" "$ELEMENTS_OK" "$FASTLANE_VER" \
    "$([ $FASTLANE_OK -eq 1 ] && echo true || echo false)" "$SIM_UDID" "$POSE_OK" "$(duo_json_escape "$WARNINGS")"
else
  echo "preflight ok: Xcode $XCODE_VERSION, iOS 27.1 runtime, duoctl, hinge, pose control $POSE_OK, maestro $([ $MAESTRO_OK -eq 1 ] && echo yes || echo no), axe $([ $AXE_OK -eq 1 ] && echo yes || echo no), element trees $ELEMENTS_OK"
  [ -n "$WARNINGS" ] && echo "warnings: $WARNINGS"
fi
exit 0
