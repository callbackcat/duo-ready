#!/usr/bin/env bash
# sdk-stamp.sh - which iOS SDK a built .app was linked against.
#
# iPhone Duo behaviour is decided by the SDK stamp in the binary, not by the
# Xcode that happens to be installed (see references/device-facts.md):
#   < 27.0  boxed 375x667 window, compact height everywhere
#   27.0    fills the display but no vertical bars, no reserved regions
#   27.1+   edge to edge, vertical bars, reserved regions
# A 27.0 stamp invalidates every later measurement, so build.sh calls this and
# run-matrix.sh refuses to continue unless --allow-older is given.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/sdk-stamp.sh <path/to/App.app> [--json] [--allow-older]

Prints the SDK version from the LC_BUILD_VERSION load command of the app's
main executable and the iPhone Duo tier it maps to (26, 27.0, 27.1).
Exit 0 for 27.1 or later, 3 for an older stamp (0 with --allow-older),
4 when otool/plutil are unavailable.
EOF
}

APP=""; JSON=0; ALLOW_OLDER=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --json) JSON=1 ;;
    --allow-older) ALLOW_OLDER=1 ;;
    -*) echo "unknown argument: $1" >&2; usage >&2; exit 4 ;;
    *) APP="$1" ;;
  esac
  shift
done

# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

[ -n "$APP" ] || { usage >&2; exit 4; }
duo_require_macos
duo_require_tool otool "xcode-select --install"
duo_require_tool plutil

[ -d "$APP" ] || duo_die "$DUO_EXIT_BUILD" "$APP is not a directory (expected a built .app bundle)"
INFO="$APP/Info.plist"
[ -f "$INFO" ] || duo_die "$DUO_EXIT_BUILD" "$INFO not found"

EXEC_NAME="$(plutil -extract CFBundleExecutable raw -o - "$INFO" 2>/dev/null || true)"
[ -n "$EXEC_NAME" ] || duo_die "$DUO_EXIT_BUILD" "CFBundleExecutable missing in $INFO"
BINARY="$APP/$EXEC_NAME"
[ -f "$BINARY" ] || duo_die "$DUO_EXIT_BUILD" "main executable $BINARY not found"

# otool -l prints one LC_BUILD_VERSION block per architecture; the sdk line
# inside it looks like "      sdk 27.1". Take the first.
# The otool output is captured first: `otool | awk '... exit'` under pipefail
# dies with SIGPIPE (exit 141) whenever awk quits before otool finishes writing.
OTOOL_OUT="$(otool -l "$BINARY" 2>/dev/null || true)"
SDK="$(printf '%s\n' "$OTOOL_OUT" | awk '
  /LC_BUILD_VERSION/ { inblock = 1 }
  inblock && !done && $1 == "sdk" { print $2; done = 1 }
  /^Load command/ { inblock = 0 }
')"
if [ -z "$SDK" ]; then
  # Older toolchains emit LC_VERSION_MIN_IPHONEOS instead.
  SDK="$(printf '%s\n' "$OTOOL_OUT" | awk '
    /LC_VERSION_MIN_IPHONEOS/ { inblock = 1 }
    inblock && !done && $1 == "sdk" { print $2; done = 1 }
    /^Load command/ { inblock = 0 }
  ')"
fi
[ -n "$SDK" ] || duo_die "$DUO_EXIT_BUILD" "could not read an sdk value from $BINARY (otool -l)"

if duo_version_ge "$SDK" "27.1"; then
  TIER="27.1"; BEHAVIOUR="edge to edge, vertical bars, reserved regions"
elif duo_version_ge "$SDK" "27.0"; then
  TIER="27.0"; BEHAVIOUR="fills the display but no vertical bars and no reserved regions"
else
  TIER="26"; BEHAVIOUR="boxed 375x667 window, compact height everywhere"
fi

if [ "$JSON" -eq 1 ]; then
  printf '{"app":"%s","binary":"%s","sdk":"%s","tier":"%s","behaviour":"%s","duo_ready":%s}\n' \
    "$(duo_json_escape "$APP")" "$(duo_json_escape "$BINARY")" "$SDK" "$TIER" "$BEHAVIOUR" \
    "$([ "$TIER" = "27.1" ] && echo true || echo false)"
else
  echo "sdk stamp: $SDK (tier $TIER: $BEHAVIOUR)"
fi

if [ "$TIER" != "27.1" ] && [ "$ALLOW_OLDER" -eq 0 ]; then
  duo_die "$DUO_EXIT_BUILD" "binary is stamped with SDK $SDK; rebuild with Xcode 27.1+ (check SDKROOT / xcode-select) before measuring anything"
fi
exit 0
