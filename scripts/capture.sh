#!/usr/bin/env bash
# capture.sh - screenshot the display that is lit for a given cell.
#
# The Duo simulator exposes two displays whose UUIDs change on every boot, so
# the right one is picked by pixel width (1398 outer, 2007 inner). Only one
# display is lit at a time and the other captures solid black; Xcode 27.2
# notes also warn that captures can be black for minutes after boot. Every
# capture is therefore validated and retried before it is accepted.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/capture.sh <out.png> [--cell <cell>] [--display <outer|inner>] [--retries <n>] [--json]

  --cell <cell>     cell name (closed-* -> outer display, otherwise inner); default closed-portrait
  --display <d>     force outer or inner
  --retries <n>     attempts before giving up (default 3, 2 s apart)
  --json            print {"path","display","width","height","black_ratio"} on stdout

Exit 1 when every attempt produced a black frame, 4 when tools are missing.
EOF
}

OUT=""; CELL="closed-portrait"; DISPLAY_SEL=""; RETRIES=3; JSON=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --cell) CELL="$2"; shift ;;
    --display) DISPLAY_SEL="$2"; shift ;;
    --retries) RETRIES="$2"; shift ;;
    --json) JSON=1 ;;
    -*) echo "unknown argument: $1" >&2; usage >&2; exit 4 ;;
    *) OUT="$1" ;;
  esac
  shift
done

# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

[ -n "$OUT" ] || { usage >&2; exit 4; }
duo_require_macos
duo_require_tool xcrun
duo_require_tool "$DUO_PY"

UDID="$(duo_sim_udid)" || duo_die "$DUO_EXIT_PREFLIGHT" "no iPhone Duo simulator booted (run: scripts/sim.sh ensure)"

if [ -z "$DISPLAY_SEL" ]; then
  case "$(duo_cell_pose "$CELL")" in
    closed) DISPLAY_SEL="outer" ;;
    *) DISPLAY_SEL="inner" ;;
  esac
fi
case "$DISPLAY_SEL" in
  outer) WANT_WIDTH=1398 ;;
  inner) WANT_WIDTH=2007 ;;
  *) duo_die "$DUO_EXIT_PREFLIGHT" "--display must be outer or inner" ;;
esac

# Parse `simctl io enumerate` with scripts/simdisplay.py. Xcode 27.1 lists the
# screens under "Connected Screens:" ((1) LCD / (3) LCD-1, each with a Unique
# ID and a Pixel Size; verified 27 Oct 2026) and `screenshot --display=`
# accepts that Unique ID. Older layouts fall back to a UUID + width heuristic.
ENUM_OUT="$(xcrun simctl io "$UDID" enumerate 2>/dev/null || true)"
DISPLAY_UUID="$(printf '%s\n' "$ENUM_OUT" | "$DUO_PY" "$DUO_SCRIPTS/simdisplay.py" --width "$WANT_WIDTH" || true)"

[ -n "$DISPLAY_UUID" ] || duo_die "$DUO_EXIT_PREFLIGHT" "could not find a $DISPLAY_SEL display (pixel width $WANT_WIDTH) in 'simctl io $UDID enumerate'; run it by hand and compare with scripts/simdisplay.py (references/simulator-control.md)"

mkdir -p "$(dirname "$OUT")"

attempt=1; RESULT=""
while [ "$attempt" -le "$RETRIES" ]; do
  xcrun simctl io "$UDID" screenshot --display="$DISPLAY_UUID" "$OUT" >/dev/null 2>&1 || true
  if [ -s "$OUT" ]; then
    RESULT="$("$DUO_PY" - "$OUT" <<'PY' || true
# Minimal PNG reader (standard library only): decodes the image, samples a
# grid of pixels and reports the fraction that are black.
import struct, sys, zlib, json
path = sys.argv[1]
data = open(path, "rb").read()
if data[:8] != b"\x89PNG\r\n\x1a\n":
    print(json.dumps({"error": "not a PNG"})); sys.exit(0)
pos, idat, width = 8, b"", None
while pos < len(data):
    length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
    chunk = data[pos + 8:pos + 8 + length]
    if ctype == b"IHDR":
        width, height, depth, color, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
    elif ctype == b"IDAT":
        idat += chunk
    elif ctype == b"IEND":
        break
    pos += 12 + length
if width is None or interlace != 0 or depth != 8:
    print(json.dumps({"error": "unsupported PNG layout", "width": width})); sys.exit(0)
channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
bpp = channels
stride = width * bpp
raw = zlib.decompress(idat)
rows, prev = [], bytearray(stride)
off = 0
for y in range(height):
    f = raw[off]; off += 1
    cur = bytearray(raw[off:off + stride]); off += stride
    for i in range(stride):
        a = cur[i - bpp] if i >= bpp else 0
        b = prev[i]
        c = prev[i - bpp] if i >= bpp else 0
        if f == 1: cur[i] = (cur[i] + a) & 255
        elif f == 2: cur[i] = (cur[i] + b) & 255
        elif f == 3: cur[i] = (cur[i] + ((a + b) >> 1)) & 255
        elif f == 4:
            p = a + b - c; pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            cur[i] = (cur[i] + pred) & 255
    rows.append(cur); prev = cur
step = max(1, min(width, height) // 64)
black = total = 0
for y in range(0, height, step):
    row = rows[y]
    for x in range(0, width, step):
        px = row[x * bpp:x * bpp + bpp]
        rgb = px[:3] if channels >= 3 else px[:1] * 3
        total += 1
        if max(rgb) < 8:
            black += 1
print(json.dumps({"width": width, "height": height, "black_ratio": round(black / max(total, 1), 4)}))
PY
)"
    ratio="$(printf '%s' "$RESULT" | "$DUO_PY" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("black_ratio", 1.0))' 2>/dev/null || echo 1.0)"
    if "$DUO_PY" -c 'import sys; sys.exit(0 if float(sys.argv[1]) <= 0.99 else 1)' "$ratio"; then
      break
    fi
    duo_warn "attempt $attempt: capture is $(printf '%s' "$ratio") black (display off or still warming up), retrying"
  else
    duo_warn "attempt $attempt: simctl produced no file"
  fi
  attempt=$(( attempt + 1 ))
  [ "$attempt" -le "$RETRIES" ] && sleep 2
done

if [ "$attempt" -gt "$RETRIES" ]; then
  duo_die "$DUO_EXIT_UI" "every capture of the $DISPLAY_SEL display was black for cell $CELL ($OUT). Check the pose with 'scripts/sim.sh wait-posture', and allow more time after boot."
fi

if [ "$JSON" -eq 1 ]; then
  printf '%s' "$RESULT" | "$DUO_PY" -c 'import json,sys; d=json.load(sys.stdin); d.update({"path": sys.argv[1], "display": sys.argv[2], "cell": sys.argv[3]}); print(json.dumps(d))' "$OUT" "$DISPLAY_SEL" "$CELL"
else
  echo "captured $DISPLAY_SEL display -> $OUT"
fi
exit 0
