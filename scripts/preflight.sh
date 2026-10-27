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
XCODE_VERSION="$(xcodebuild -version 2>/dev/null | awk '/^Xcode/ {print $2; exit}')"
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

if xcrun simctl list devicetypes 2>/dev/null | grep -q "iPhone-Duo"; then
  DEVTYPE_OK=1
else
  duo_die_host "device type 'iPhone Duo' not listed by simctl (Xcode $XCODE_VERSION may lack Duo support)"
fi
duo_log "iOS 27.1 runtime and iPhone Duo device type present"

# --- pose control tools ----------------------------------------------------
BREW_HINT="brew install skarol/tap/duoctl artemnovichkov/tap/hinge"
duo_require_tool duoctl "$BREW_HINT"
duo_require_tool hinge "$BREW_HINT"
DUOCTL_VER="$(duoctl --version 2>/dev/null | head -n 1 || echo unknown)"
HINGE_VER="$(hinge --version 2>/dev/null | head -n 1 || echo unknown)"
duo_log "duoctl ($DUOCTL_VER) and hinge ($HINGE_VER) installed"

# --- fastlane (warn only; needed for the assets stage) ---------------------
if command -v fastlane >/dev/null 2>&1; then
  FASTLANE_VER="$(fastlane --version 2>/dev/null | awk '/^fastlane [0-9]/ {print $2; exit}')"
  if [ -n "$FASTLANE_VER" ] && duo_version_ge "$FASTLANE_VER" "$MIN_FASTLANE"; then
    FASTLANE_OK=1
  else
    warn "fastlane ${FASTLANE_VER:-?} is older than $MIN_FASTLANE; deliver will not know the iPhone Duo screenshot sizes (gem update fastlane)"
  fi
else
  warn "fastlane not installed; the assets stage will print the asc CLI alternative instead"
fi

# --- simulator -------------------------------------------------------------
if [ "$NO_BOOT" -eq 0 ]; then
  SIM_UDID="$("$DUO_SCRIPTS/sim.sh" ensure --no-wait --quiet)"
  duo_log "simulator $SIM_UDID booted"
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
  printf '{"ok":true,"exit":0,"xcode":"%s","runtime_ios_27_1":%s,"device_type_duo":%s,"duoctl":"%s","hinge":"%s","fastlane":"%s","fastlane_ok":%s,"sim_udid":"%s","pose_control":"%s","warnings":"%s"}\n' \
    "$XCODE_VERSION" "$([ $RUNTIME_OK -eq 1 ] && echo true || echo false)" "$([ $DEVTYPE_OK -eq 1 ] && echo true || echo false)" \
    "$(duo_json_escape "$DUOCTL_VER")" "$(duo_json_escape "$HINGE_VER")" "$FASTLANE_VER" \
    "$([ $FASTLANE_OK -eq 1 ] && echo true || echo false)" "$SIM_UDID" "$POSE_OK" "$(duo_json_escape "$WARNINGS")"
else
  echo "preflight ok: Xcode $XCODE_VERSION, iOS 27.1 runtime, duoctl, hinge, pose control $POSE_OK"
  [ -n "$WARNINGS" ] && echo "warnings: $WARNINGS"
fi
exit 0
