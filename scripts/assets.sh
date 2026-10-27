#!/usr/bin/env bash
# assets.sh - turn passing captures into App Store screenshots.
#
# App Store Connect accepts one iPhone Duo set that holds up to 10 images at
# any of the four Duo sizes (outer 1398x2034 / 2034x1398, inner 2007x2853 /
# 2853x2007). From April 2027 every submission of an app built with the iOS
# 27.1 SDK or later must include it; submitting it earlier earns the
# "optimized for iPhone Duo" badge. Apple has not said apps will be removed.
#
# Upload paths: fastlane deliver >= 2.241.1 (knows the Duo sizes) or the asc
# CLI (`asc screenshots upload --device-type APP_IPHONE_DUO`). Outer-display
# uploads have been confirmed by the community; inner-display uploads through
# the API have not, so verify the first inner set in the App Store Connect web
# UI (see references/asc-duo-specs.md).
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

Writes <output>/<locale>/<nn>_iphone_duo_<display>_<flow>-<cell>.png, a
manifest.json beside them, FEATURING.md at the project root, and prints the
upload commands. Exit 1 when a capture fails the size gate, 3 when no run.
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

[ -n "$LOCALE" ] || LOCALE="$(duo_cfg_list assets.locales | head -n 1)"
[ -n "$LOCALE" ] || LOCALE="en-US"
[ -n "$OUTPUT" ] || OUTPUT="$(duo_cfg assets.output fastlane/screenshots)"
DEST="$DUO_ROOT/$OUTPUT/$LOCALE"
mkdir -p "$DEST"

# Select captures: outer portrait from closed-portrait, inner landscape from
# open-landscape, inner portrait from open-portrait (book cells show the same
# window as open and would duplicate). Order: inner first, then outer, so the
# product page leads with the big display.
MANIFEST="$DEST/manifest.json"
"$DUO_PY" - "$RUN_DIR/ui.json" "$RUN_DIR/captures" "$DEST" "$FLOWS" "$INCLUDE_FAILED" "$MANIFEST" <<'PY'
import json, os, shutil, sys
ui_path, captures, dest, flows, include_failed, manifest = sys.argv[1:]
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
for i, (flow, cell, display, src, failing) in enumerate(chosen):
    # TODO-VERIFY: deliver's expected filename for the Duo size. fastlane >= 2.241.1
    # (PR #30444) detects the device by pixel size, not by name, in
    # deliver/lib/deliver/app_screenshot.rb; the "iphone_duo_<display>" token is
    # ours and only there for humans. Confirm against that file before relying on it.
    name = f"{i:02d}_iphone_duo_{display}_{flow}-{cell}.png"
    shutil.copyfile(src, os.path.join(dest, name))
    entries.append({"file": name, "flow": flow, "cell": cell, "display": display, "source": src, "assertions_failing": failing})
json.dump({"schema": 1, "locale": os.path.basename(dest), "screenshots": entries}, open(manifest, "w"), indent=2)
print(f"exported {len(entries)} screenshots to {dest}")
PY

# Size + alpha gate (another script owns the checks; it exits 1 on any bad file).
if [ -f "$DUO_SCRIPTS/assets_gate.py" ]; then
  "$DUO_PY" "$DUO_SCRIPTS/assets_gate.py" "$DEST" || duo_die "$DUO_EXIT_UI" "one or more exported screenshots fail the App Store Connect Duo size/alpha gate"
else
  duo_warn "scripts/assets_gate.py missing; sizes not verified"
fi

APP_NAME="$(duo_cfg scheme "your app")"
cat >"$DUO_ROOT/FEATURING.md" <<EOF
# Featuring nomination: $APP_NAME on iPhone Duo

Submit in App Store Connect under Featuring Nominations. Suggested "Helpful details":

> $APP_NAME is optimized for iPhone Duo. It adapts to the outer display when closed and
> to the inner display when open, including the partially folded (book) pose, both
> orientations and Split View. Toolbars and tab bars follow the system's vertical
> placement, interactive controls stay clear of the fold, and App Store screenshots
> cover both displays. Built with the iOS 27.1 SDK.

Edit this to describe what is genuinely Duo-specific in the app (arrangement views,
reserved-region handling, hinge interactions). Apple reviews nominations by hand;
claims it can see are the ones that help.
EOF

cat <<EOF

Upload options (pick one):
  fastlane deliver --screenshots_path "$OUTPUT" --skip_binary_upload --skip_metadata   # needs fastlane >= 2.241.1
  asc screenshots upload --version-localization <LOCALIZATION_ID> --path "$DEST" --device-type APP_IPHONE_DUO
  or drag the files into App Store Connect > App Previews and Screenshots > iPhone Duo.

Inner-display uploads through the API are not yet confirmed by anyone; check the first
inner set in the web UI. Nomination text written to FEATURING.md.
EOF

[ "$JSON" -eq 1 ] && cat "$MANIFEST"
exit 0
