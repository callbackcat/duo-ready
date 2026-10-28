#!/usr/bin/env bash
# Shared helpers for duo-ready shell scripts. Source it; do not execute it.
#
# bash 3.2 compatible (macOS default): no associative arrays, no mapfile,
# no ${var,,}. Exit codes follow references/pipeline-contracts.md.

DUO_EXIT_PASS=0
DUO_EXIT_UI=1
DUO_EXIT_PERF=2
DUO_EXIT_BUILD=3
DUO_EXIT_PREFLIGHT=4
DUO_EXIT_POSE=5
DUO_EXIT_UNSUPPORTED=6   # the app refused the cell (e.g. portrait-only on the outer display)

# Directory that holds the scripts, regardless of the caller's cwd.
DUO_SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The user's project root is the cwd (duo.yaml lives there).
DUO_ROOT="${DUO_ROOT:-$(pwd)}"
DUO_DIR="$DUO_ROOT/.duo"
DUO_CONFIG="${DUO_CONFIG:-$DUO_ROOT/duo.yaml}"

# python3 ships with Xcode's command line tools. Allow an override for odd hosts.
DUO_PY="${DUO_PY:-python3}"

duo_log()  { printf '%s\n' "duo: $*" >&2; }
duo_warn() { printf '%s\n' "duo: warning: $*" >&2; }

# The one-line contract message for a host that cannot run this stage.
duo_die_host() {
  printf 'cannot run on this host: %s\n' "$*" >&2
  exit "$DUO_EXIT_PREFLIGHT"
}

duo_die() {  # duo_die <code> <message>
  local code="$1"; shift
  printf 'duo: error: %s\n' "$*" >&2
  exit "$code"
}

duo_require_macos() {
  if [ "$(uname -s 2>/dev/null)" != "Darwin" ]; then
    duo_die_host "macOS required (this stage drives Xcode and the iOS Simulator)"
  fi
}

# duo_require_tool <name> [hint]
duo_require_tool() {
  if ! command -v "$1" >/dev/null 2>&1; then
    if [ -n "${2:-}" ]; then
      duo_die_host "$1 not found ($2)"
    fi
    duo_die_host "$1 not found"
  fi
}

duo_require_config() {
  [ -f "$DUO_CONFIG" ] || duo_die "$DUO_EXIT_PREFLIGHT" "duo.yaml not found at $DUO_CONFIG (run scripts/detect.py first)"
}

# duo_cfg <dotted.key> [default]
duo_cfg() {
  if [ $# -ge 2 ]; then
    "$DUO_PY" "$DUO_SCRIPTS/duocfg.py" "$1" --file "$DUO_CONFIG" --default "$2"
  else
    "$DUO_PY" "$DUO_SCRIPTS/duocfg.py" "$1" --file "$DUO_CONFIG"
  fi
}

# duo_cfg_list <dotted.key>  -> one item per line (empty when missing)
duo_cfg_list() {
  "$DUO_PY" "$DUO_SCRIPTS/duocfg.py" "$1" --file "$DUO_CONFIG" --list --default "" 2>/dev/null || true
}

# Latest run number, or 0 when none exist.
duo_latest_run() {
  local runs="$DUO_DIR/runs" n latest=0
  if [ -d "$runs" ]; then
    for n in "$runs"/*; do
      n="$(basename "$n")"
      case "$n" in
        ''|*[!0-9]*) ;;
        *) [ "$n" -gt "$latest" ] && latest="$n" ;;
      esac
    done
  fi
  echo "$latest"
}

duo_next_run() {
  echo $(( $(duo_latest_run) + 1 ))
}

duo_run_dir() {  # duo_run_dir <n>
  echo "$DUO_DIR/runs/$1"
}

# Escape a string for inclusion in JSON (double quotes added by caller).
duo_json_escape() {
  printf '%s' "$1" | "$DUO_PY" -c 'import json,sys; print(json.dumps(sys.stdin.read())[1:-1])'
}

# Compare dotted versions: returns 0 when $1 >= $2.
duo_version_ge() {
  "$DUO_PY" - "$1" "$2" <<'PY'
import sys
def parse(v):
    out = []
    for p in v.strip().split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return out
a, b = parse(sys.argv[1]), parse(sys.argv[2])
n = max(len(a), len(b))
a += [0] * (n - len(a)); b += [0] * (n - len(b))
sys.exit(0 if a >= b else 1)
PY
}

# Pose and orientation of a cell name ("book-landscape" -> "book" / "landscape").
duo_cell_pose() {
  case "$1" in
    split-view-*) echo "open" ;;
    *) echo "${1%%-*}" ;;
  esac
}
duo_cell_orientation() {
  case "$1" in
    split-view-*) echo "landscape" ;;
    *) echo "${1#*-}" ;;
  esac
}

# DerivedData lives outside the project by default. Inside it, a project that
# sits in iCloud Drive (Desktop & Documents sync) gets FinderInfo attributes on
# every new folder, codesign refuses them ("resource fork, Finder information,
# or similar detritus not allowed") and iCloud uploads gigabytes of build
# output: one such build took 37 minutes, the same build outside iCloud 3.5
# (field test, 27 Oct 2026). Override with DUO_DERIVED_DATA or derived_data in duo.yaml.
duo_derived_data() {
  if [ -n "${DUO_DERIVED_DATA:-}" ]; then echo "$DUO_DERIVED_DATA"; return 0; fi
  local cfg scheme
  cfg="$(duo_cfg derived_data "" 2>/dev/null || true)"
  if [ -n "$cfg" ]; then echo "$cfg"; return 0; fi
  scheme="$(duo_cfg scheme app 2>/dev/null || echo app)"
  echo "$HOME/Library/Developer/Xcode/DerivedData/duo-ready-$(printf '%s' "$scheme" | tr -c 'A-Za-z0-9._-' '_')"
}

# Extra xcodebuild arguments, one per line: duo.yaml `xcodebuild_args` list plus
# the space-separated DUO_XCODEBUILD_SETTINGS environment variable. Xcode 27.1
# refuses targets below iOS 15 (CocoaPods resource bundles often are), and
# IPHONEOS_DEPLOYMENT_TARGET=15.0 here is the quickest way past that.
duo_xcodebuild_args() {
  duo_cfg_list xcodebuild_args
  if [ -n "${DUO_XCODEBUILD_SETTINGS:-}" ]; then
    printf '%s\n' $DUO_XCODEBUILD_SETTINGS
  fi
}

# UDID of the duo-ready simulator (set by sim.sh ensure). There is deliberately
# no fallback to "any booted iPhone Duo": a developer's own simulator may hold a
# signed-in production account, and the matrix would install over it and drive
# it. Set DUOCTL_UDID to use a specific simulator on purpose.
duo_sim_udid() {
  if [ -n "${DUOCTL_UDID:-}" ]; then
    echo "$DUOCTL_UDID"; return 0
  fi
  if [ -f "$DUO_DIR/sim.udid" ]; then
    cat "$DUO_DIR/sim.udid"; return 0
  fi
  return 1
}
