#!/usr/bin/env bash
# assets.sh - turn passing captures into App Store screenshots.
#
# App Store Connect accepts one iPhone Duo set that holds up to 10 images at
# any of the four Duo sizes (outer 1398x2034 / 2034x1398, inner 2007x2853 /
# 2853x2007). From April 2027 every submission of an app built with the iOS
# 27.1 SDK or later must include it; submitting it earlier earns the
# "optimized for iPhone Duo" badge. Apple has not said apps will be removed.
#
# The skill stops at the files: it never uploads. The user drags them into
# App Store Connect (App Previews and Screenshots > iPhone Duo; one set holds
# all four sizes) or points an existing fastlane deliver lane (2.241.1+) at the
# folder. Inner-display uploads through the API are unverified by anyone
# (references/asc-duo-specs.md).
#
# simctl screenshots are RGBA PNGs (opaque alpha); App Store Connect refuses
# any alpha channel, so the export flattens them to RGB (pngio.flatten, pure
# python, a few seconds per inner capture).
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/assets.sh [--run <n>] [--locale <l>] [--output <dir>] [--flows a,b] [--include-failed] [--json]

  --run <n>          run number (default: latest with ui.json)
  --locale <l>       locale folder (default: assets.locales[0] from duo.yaml or en-US)
  --output <dir>     screenshot root (default: assets.output or fastlane/screenshots)
  --flows            comma-separated flows to include (default: all)
  --include-failed   also copy captures from cells with failing assertions
  --json             print the manifest on stdout

Writes <output>/<locale>/<nn>_iphone_duo_<display>_<flow>-<cell>.png (RGB; the
RGBA simulator captures are flattened on the way), a manifest.json beside them,
FEATURING.md at the project root, and says where to upload by hand (the skill
never uploads). Exit 1 when a capture fails the size gate, 3 when no run.
EOF
}

RUN=""; LOCALE=""; OUTPUT=""; FLOWS=""; INCLUDE_FAILED=0; JSON=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --run) RUN="$2"; shift ;;
    --locale) LOCALE="$2"; shift ;;
    --output) OUTPUT="$2"; shift ;;
    --flows) FLOWS="$2"; shift ;;
    --include-failed) INCLUDE_FAILED=1 ;;
    --json) JSON=1 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 4 ;;
  esac
  shift
done

# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

# This stage only moves files, so it runs anywhere python3 exists; the
# captures themselves can only come from a Mac.
duo_require_tool "$DUO_PY"
duo_require_config

[ -n "$RUN" ] || RUN="$(duo_latest_run)"
[ "$RUN" -gt 0 ] || duo_die "$DUO_EXIT_BUILD" "no run found; run the matrix first"
RUN_DIR="$(duo_run_dir "$RUN")"
[ -f "$RUN_DIR/ui.json" ] || duo_die "$DUO_EXIT_BUILD" "$RUN_DIR/ui.json missing; run scripts/run-matrix.sh --run $RUN"

[ -n "$LOCALE" ] || LOCALE="$(duo_cfg_list assets.locales | sed -n 1p)"
[ -n "$LOCALE" ] || LOCALE="en-US"
[ -n "$OUTPUT" ] || OUTPUT="$(duo_cfg assets.output fastlane/screenshots)"
DEST="$DUO_ROOT/$OUTPUT/$LOCALE"
mkdir -p "$DEST"

# Select captures: outer portrait from closed-portrait, inner landscape from
# open-landscape, inner portrait from open-portrait (book cells show the same
# window as open and would duplicate). Order: inner first, then outer, so the
# product page leads with the big display.
MANIFEST="$DEST/manifest.json"
"$DUO_PY" - "$RUN_DIR/ui.json" "$RUN_DIR/captures" "$DEST" "$FLOWS" "$INCLUDE_FAILED" "$MANIFEST" "$DUO_SCRIPTS" <<'PY'
import json, os, shutil, sys
ui_path, captures, dest, flows, include_failed, manifest, scripts = sys.argv[1:]
sys.path.insert(0, scripts)
import pngio
only = [f for f in flows.split(",") if f]
ui = json.load(open(ui_path))
ORDER = [("open-landscape", "inner"), ("open-portrait", "inner"), ("closed-portrait", "outer"), ("closed-landscape", "outer")]
chosen = []
for cell_name, display in ORDER:
    for cell in ui.get("cells", []):
        if cell.get("cell") != cell_name: continue
        if only and cell.get("flow") not in only: continue
        failing = any(r.get("status") == "fail" for r in cell.get("results", []))
        if failing and include_failed != "1": continue
        src = cell.get("screenshot") or os.path.join(captures, f"{cell['flow']}-{cell_name}.png")
        if not os.path.isfile(src): continue
        chosen.append((cell["flow"], cell_name, display, src, failing))
if not chosen:
    print("no passing captures to export (use --include-failed to export anyway)", file=sys.stderr); sys.exit(1)
chosen = chosen[:10]  # App Store Connect limit per set
entries = []
flattened = 0
for i, (flow, cell, display, src, failing) in enumerate(chosen):
    # fastlane deliver 2.241.2 (read on field test 5) picks the display type from
    # the pixel size (calculate_display_type, FastImage.size), not from the file
    # name, and puts inner and outer files into one APP_IPHONE_DUO set; the
    # "iphone_duo_<display>" token is ours and only there for humans.
    name = f"{i:02d}_iphone_duo_{display}_{flow}-{cell}.png"
    out = os.path.join(dest, name)
    try:
        did = pngio.flatten(src, out)
    except pngio.PNGError:
        did = False
    if did:
        flattened += 1
    else:
        shutil.copyfile(src, out)
    entries.append({"file": name, "flow": flow, "cell": cell, "display": display, "source": src,
                    "assertions_failing": failing, "flattened": did})
json.dump({"schema": 1, "locale": os.path.basename(dest), "screenshots": entries}, open(manifest, "w"), indent=2)
print(f"exported {len(entries)} screenshots to {dest}" + (f" ({flattened} flattened from RGBA to RGB)" if flattened else ""))
PY

# Size + alpha gate (another script owns the checks; it exits 1 on any bad file).
if [ -f "$DUO_SCRIPTS/assets_gate.py" ]; then
  "$DUO_PY" "$DUO_SCRIPTS/assets_gate.py" "$DEST" || duo_die "$DUO_EXIT_UI" "one or more exported screenshots fail the App Store Connect Duo size/alpha gate"
else
  duo_warn "scripts/assets_gate.py missing; sizes not verified"
fi

# The nomination text is built from the run's results (scripts/featuring.py):
# a fixed template claimed fold-safe controls while the run had twelve
# failures (field test 6).
APP_NAME="$(duo_cfg scheme "your app")"
DISPLAYS="$("$DUO_PY" -c 'import json,sys; print(",".join(sorted({e["display"] for e in json.load(open(sys.argv[1]))["screenshots"]})))' "$MANIFEST")"
"$DUO_PY" "$DUO_SCRIPTS/featuring.py" --run "$RUN" --root "$DUO_ROOT" --app "$APP_NAME" --displays "$DISPLAYS" --out "$DUO_ROOT/FEATURING.md"

cat <<EOF

Screenshots are in $DEST. The skill does not upload them: drag the files into
App Store Connect > App Previews and Screenshots > iPhone Duo (one set holds all
four sizes, up to 10 images). An existing fastlane deliver lane (2.241.1+) can read
"$OUTPUT" as well; an inner-display upload through the API is unverified by anyone, so
use the web uploader for the inner set. Nomination text is in FEATURING.md.
EOF

[ "$JSON" -eq 1 ] && cat "$MANIFEST"
exit 0
