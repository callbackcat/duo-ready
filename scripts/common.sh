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

# UDID of the duo-ready simulator (set by sim.sh ensure) or any booted Duo.
duo_sim_udid() {
  if [ -n "${DUOCTL_UDID:-}" ]; then
    echo "$DUOCTL_UDID"; return 0
  fi
  if [ -f "$DUO_DIR/sim.udid" ]; then
    cat "$DUO_DIR/sim.udid"; return 0
  fi
  xcrun simctl list devices booted -j 2>/dev/null | "$DUO_PY" -c '
import json, sys
data = json.load(sys.stdin)
for runtime, devices in data.get("devices", {}).items():
    for d in devices:
        if "Duo" in d.get("name", "") or "iPhone-Duo" in d.get("deviceTypeIdentifier", ""):
            print(d["udid"]); sys.exit(0)
sys.exit(1)
'
}
