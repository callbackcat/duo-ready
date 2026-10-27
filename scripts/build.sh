#!/usr/bin/env bash
# build.sh - build the app for the iOS Simulator and record the SDK stamp.
#
# Reads stack/scheme/workspace|project from duo.yaml. Native and RN/Expo
# projects go through xcodebuild (Expo managed projects are prebuilt first);
# Flutter uses its own build. Output: .duo/runs/<n>/build.json with the .app
# path, scheme and the SDK stamp from sdk-stamp.sh. Exit 3 on build failure
# or an SDK stamp below 27.1 (unless --allow-older).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/build.sh [--run <n>] [--json] [--allow-older] [--configuration <c>]

  --run <n>           run number to write build.json into (default: next)
  --configuration <c> xcodebuild configuration (default Debug)
  --allow-older       accept an SDK stamp below 27.1 (measurements become meaningless)
  --json              print build.json on stdout

Writes .duo/runs/<n>/build.json and .duo/runs/<n>/build.log.
EOF
}

RUN=""; JSON=0; ALLOW_OLDER=0; CONFIGURATION="Debug"
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --run) RUN="$2"; shift ;;
    --json) JSON=1 ;;
    --allow-older) ALLOW_OLDER=1 ;;
    --configuration) CONFIGURATION="$2"; shift ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 4 ;;
  esac
  shift
done

# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

duo_require_macos
duo_require_tool xcodebuild "install Xcode 27.1+"
duo_require_tool "$DUO_PY"
duo_require_config

[ -n "$RUN" ] || RUN="$(duo_next_run)"
RUN_DIR="$(duo_run_dir "$RUN")"
mkdir -p "$RUN_DIR"
LOG="$RUN_DIR/build.log"
DERIVED="$DUO_DIR/DerivedData"

STACK="$(duo_cfg stack)"
SCHEME="$(duo_cfg scheme "")"
WORKSPACE="$(duo_cfg workspace "")"
PROJECT="$(duo_cfg project "")"
APP_PATH=""

duo_log "building stack=$STACK scheme=$SCHEME configuration=$CONFIGURATION (log: $LOG)"

run_xcodebuild() {
  local container=()
  if [ -n "$WORKSPACE" ]; then
    container=(-workspace "$WORKSPACE")
  elif [ -n "$PROJECT" ]; then
    container=(-project "$PROJECT")
  fi
  [ -n "$SCHEME" ] || duo_die "$DUO_EXIT_BUILD" "scheme not set in duo.yaml"
  # ${arr[@]+"${arr[@]}"} keeps bash 3.2 + set -u happy when the array is empty.
  if ! xcodebuild ${container[@]+"${container[@]}"} -scheme "$SCHEME" -configuration "$CONFIGURATION" \
      -sdk iphonesimulator -destination 'generic/platform=iOS Simulator' \
      -derivedDataPath "$DERIVED" build >"$LOG" 2>&1; then
    tail -n 40 "$LOG" >&2
    duo_die "$DUO_EXIT_BUILD" "xcodebuild failed (full log: $LOG)"
  fi
  APP_PATH="$(find "$DERIVED/Build/Products" -maxdepth 2 -name '*.app' -path "*${CONFIGURATION}-iphonesimulator*" 2>/dev/null | head -n 1)"
}

case "$STACK" in
  uikit|swiftui|mixed|react-native|capacitor)
    run_xcodebuild
    ;;
  expo)
    if [ ! -d "$DUO_ROOT/ios" ]; then
      duo_require_tool npx "install Node.js for Expo prebuild"
      duo_log "ios/ missing: running expo prebuild (managed workflow)"
      (cd "$DUO_ROOT" && npx expo prebuild --platform ios --no-install >>"$LOG" 2>&1) \
        || duo_die "$DUO_EXIT_BUILD" "expo prebuild failed (log: $LOG)"
      if command -v pod >/dev/null 2>&1; then
        (cd "$DUO_ROOT/ios" && pod install >>"$LOG" 2>&1) || duo_die "$DUO_EXIT_BUILD" "pod install failed (log: $LOG)"
      fi
    fi
    if [ -z "$WORKSPACE" ]; then
      WORKSPACE="$(find "$DUO_ROOT/ios" -maxdepth 1 -name '*.xcworkspace' | head -n 1)"
    fi
    run_xcodebuild
    ;;
  flutter)
    duo_require_tool flutter
    (cd "$DUO_ROOT" && flutter build ios --simulator --debug >"$LOG" 2>&1) \
      || { tail -n 40 "$LOG" >&2; duo_die "$DUO_EXIT_BUILD" "flutter build failed (log: $LOG)"; }
    APP_PATH="$(find "$DUO_ROOT/build/ios/iphonesimulator" -maxdepth 1 -name '*.app' | head -n 1)"
    ;;
  *)
    duo_die "$DUO_EXIT_BUILD" "unknown stack '$STACK' in duo.yaml"
    ;;
esac

[ -n "$APP_PATH" ] && [ -d "$APP_PATH" ] || duo_die "$DUO_EXIT_BUILD" "built .app not found (see $LOG)"

STAMP_ARGS=(--json)
[ "$ALLOW_OLDER" -eq 1 ] && STAMP_ARGS+=(--allow-older)
STAMP_JSON="$("$DUO_SCRIPTS/sdk-stamp.sh" "$APP_PATH" "${STAMP_ARGS[@]}")"
SDK="$(printf '%s' "$STAMP_JSON" | "$DUO_PY" -c 'import json,sys; print(json.load(sys.stdin)["sdk"])')"

BUNDLE_ID="$(plutil -extract CFBundleIdentifier raw -o - "$APP_PATH/Info.plist" 2>/dev/null || duo_cfg bundle_id "")"

"$DUO_PY" - "$RUN_DIR/build.json" "$RUN" "$STACK" "$SCHEME" "$CONFIGURATION" "$APP_PATH" "$SDK" "$BUNDLE_ID" "$LOG" <<'PY'
import json, sys, datetime
out, run, stack, scheme, conf, app, sdk, bundle, log = sys.argv[1:]
doc = {
    "schema": 1, "run": int(run), "generated": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "stack": stack, "scheme": scheme, "configuration": conf, "app": app,
    "bundle_id": bundle, "sdk_stamp": sdk, "log": log,
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2); f.write("\n")
PY

if [ "$JSON" -eq 1 ]; then
  cat "$RUN_DIR/build.json"
else
  echo "built $APP_PATH (sdk $SDK) -> $RUN_DIR/build.json"
fi
exit 0
