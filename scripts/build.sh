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
Usage: scripts/build.sh [--run <n>] [--json] [--allow-older] [--configuration <c>] [--prebuild]

  --run <n>           run number to write build.json into (default: the latest run
                      without a build.json, else the next one)
  --configuration <c> xcodebuild configuration (default: Release for react-native/expo,
                      because a Debug build loads its JavaScript from Metro, which
                      nothing here starts; Debug for native stacks)
  --prebuild          expo: run `expo prebuild --clean` even when ios/ exists
                      (needed after changing app.json or a config plugin)
  --allow-older       accept an SDK stamp below 27.1 (measurements become meaningless)
  --json              print build.json on stdout

DerivedData goes to ~/Library/Developer/Xcode/DerivedData/duo-ready-<scheme>
(override: DUO_DERIVED_DATA or `derived_data:` in duo.yaml). Extra build
settings: `xcodebuild_args:` in duo.yaml or DUO_XCODEBUILD_SETTINGS, e.g.
IPHONEOS_DEPLOYMENT_TARGET=15.0 when Xcode 27.1 refuses old Pods.
Writes .duo/runs/<n>/build.json and .duo/runs/<n>/build.log.
EOF
}

RUN=""; JSON=0; ALLOW_OLDER=0; CONFIGURATION=""; PREBUILD=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --run) RUN="$2"; shift ;;
    --json) JSON=1 ;;
    --allow-older) ALLOW_OLDER=1 ;;
    --configuration) CONFIGURATION="$2"; shift ;;
    --prebuild) PREBUILD=1 ;;
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

if [ -z "$RUN" ]; then
  # Reuse the latest run directory while its build has not succeeded: a failed
  # attempt must not push the retry to run N+1 (field test).
  RUN="$(duo_latest_run)"
  if [ "$RUN" -eq 0 ] || [ -f "$(duo_run_dir "$RUN")/build.json" ]; then RUN="$(duo_next_run)"; fi
fi
RUN_DIR="$(duo_run_dir "$RUN")"
mkdir -p "$RUN_DIR"
LOG="$RUN_DIR/build.log"
DERIVED="$(duo_derived_data)"
XB_ARGS=()
while IFS= read -r xb_arg; do [ -n "$xb_arg" ] && XB_ARGS+=("$xb_arg"); done <<EOF
$(duo_xcodebuild_args)
EOF

STACK="$(duo_cfg stack)"
SCHEME="$(duo_cfg scheme "")"
WORKSPACE="$(duo_cfg workspace "")"
PROJECT="$(duo_cfg project "")"
APP_PATH=""
if [ -z "$CONFIGURATION" ]; then
  case "$STACK" in
    react-native|expo) CONFIGURATION="Release" ;;
    *) CONFIGURATION="Debug" ;;
  esac
fi

duo_log "building stack=$STACK scheme=$SCHEME configuration=$CONFIGURATION (log: $LOG, DerivedData: $DERIVED)"

build_hints() {  # build_hints <log>: name the failures every first run on Xcode 27.1 hits
  if grep -q "range of supported deployment target versions" "$1"; then
    duo_warn "Xcode 27.1 refuses targets below iOS 15 (usually CocoaPods resource bundles). Raise them in the Podfile post_install, or pass a floor: DUO_XCODEBUILD_SETTINGS=IPHONEOS_DEPLOYMENT_TARGET=15.0 (or xcodebuild_args in duo.yaml)"
  fi
  if grep -q "resource fork, Finder information, or similar detritus" "$1"; then
    duo_warn "codesign rejected FinderInfo attributes: DerivedData ($DERIVED) is probably inside an iCloud Drive folder; point DUO_DERIVED_DATA (or derived_data in duo.yaml) outside ~/Documents and ~/Desktop"
  fi
}

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
      -derivedDataPath "$DERIVED" ${XB_ARGS[@]+"${XB_ARGS[@]}"} build >>"$LOG" 2>&1; then
    tail -n 40 "$LOG" >&2
    build_hints "$LOG"
    duo_die "$DUO_EXIT_BUILD" "xcodebuild failed (full log: $LOG)"
  fi
  APP_PATH="$(find "$DERIVED/Build/Products" -maxdepth 2 -name '*.app' -path "*${CONFIGURATION}-iphonesimulator*" 2>/dev/null | sed -n 1p)"
}

case "$STACK" in
  uikit|swiftui|mixed|react-native|capacitor)
    run_xcodebuild
    ;;
  expo)
    if [ ! -d "$DUO_ROOT/ios" ] || [ "$PREBUILD" -eq 1 ]; then
      duo_require_tool npx "install Node.js for Expo prebuild"
      duo_log "running expo prebuild (managed workflow)"
      prebuild_flags=""; [ "$PREBUILD" -eq 1 ] && prebuild_flags="--clean"
      # shellcheck disable=SC2086
      (cd "$DUO_ROOT" && npx expo prebuild --platform ios --no-install $prebuild_flags >>"$LOG" 2>&1) \
        || duo_die "$DUO_EXIT_BUILD" "expo prebuild failed (log: $LOG)"
      if command -v pod >/dev/null 2>&1; then
        # CocoaPods needs a UTF-8 locale (it warns, and crashes on non-ASCII
        # paths); agent shells often have none set (field test 2).
        (cd "$DUO_ROOT/ios" && LANG="${LANG:-en_US.UTF-8}" LC_ALL="${LC_ALL:-en_US.UTF-8}" pod install >>"$LOG" 2>&1) || duo_die "$DUO_EXIT_BUILD" "pod install failed (log: $LOG)"
      fi
    else
      duo_log "using the existing ios/ (pass --prebuild after changing app.json or a config plugin; the scan reports Duo fixes against app.json, not ios/)"
    fi
    if [ -z "$WORKSPACE" ]; then
      WORKSPACE="$(find "$DUO_ROOT/ios" -maxdepth 1 -name '*.xcworkspace' | sed -n 1p)"
    fi
    run_xcodebuild
    ;;
  flutter)
    duo_require_tool flutter
    (cd "$DUO_ROOT" && flutter build ios --simulator --debug >"$LOG" 2>&1) \
      || { tail -n 40 "$LOG" >&2; duo_die "$DUO_EXIT_BUILD" "flutter build failed (log: $LOG)"; }
    APP_PATH="$(find "$DUO_ROOT/build/ios/iphonesimulator" -maxdepth 1 -name '*.app' | sed -n 1p)"
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

# UIScene gate. An app built with the iOS 27 SDK and no scene life cycle is
# killed by UIKit about 2 s after launch ("UIScene life cycle is required for
# apps built with this SDK"); Expo and React Native templates up to SDK 54 /
# 0.81 ship without one. SwiftUI `App` apps adopt scenes without the plist
# key, so this is a warning; sim.sh launch catches the real thing.
SCENE_OK=true
if duo_version_ge "$SDK" "27.0" && ! plutil -extract UIApplicationSceneManifest raw -o - "$APP_PATH/Info.plist" >/dev/null 2>&1; then
  SCENE_OK=false
  case "$STACK" in
    react-native|expo) duo_warn "Info.plist has no UIApplicationSceneManifest: built with SDK $SDK this app will be killed 2 s after launch. The scan's no-scene-delegate / expo-no-scene-lifecycle finding is a launch blocker, not a layout warning" ;;
    *) duo_warn "Info.plist has no UIApplicationSceneManifest; fine for a SwiftUI App, a launch blocker for a UIKit AppDelegate app built with SDK $SDK" ;;
  esac
fi

"$DUO_PY" - "$RUN_DIR/build.json" "$RUN" "$STACK" "$SCHEME" "$CONFIGURATION" "$APP_PATH" "$SDK" "$BUNDLE_ID" "$LOG" "$DERIVED" "$SCENE_OK" <<'PY'
import json, sys, datetime
out, run, stack, scheme, conf, app, sdk, bundle, log, derived, scene_ok = sys.argv[1:]
doc = {
    "schema": 1, "run": int(run), "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "stack": stack, "scheme": scheme, "configuration": conf, "app": app,
    "bundle_id": bundle, "sdk_stamp": sdk, "log": log, "derived_data": derived,
    "scene_manifest": scene_ok == "true",
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
