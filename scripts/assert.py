#!/usr/bin/env python3
"""Layout assertions over captured screenshots + element trees.

    assert.py --run <n> [--root .] [--json] [--include-warn]

Reads .duo/runs/<n>/captures/<flow>-<cell>.png + .tree.json, evaluates the
assertions listed in references/assertions.md, writes ui.json and
failures.json (agent payloads) per references/pipeline-contracts.md.
Exit 1 when any assertion fails, 0 otherwise. Standard library only.

Capture naming:
    <flow>-<cell>.png                       e.g. feed-book-landscape.png
    <flow>-<from>-to-<to>.png               transition, after the pose change
    <flow>-<from>-to-<to>.before.tree.json  element tree before the change (optional)
Cells are reported in ui.json as the contract names (`closed>open` for transitions).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import diff as _diff  # noqa: E402
import duolib  # noqa: E402
import pngio  # noqa: E402
import tree as _tree  # noqa: E402

POSES = ("closed", "open", "book")
ORIENTATIONS = ("portrait", "landscape")
STATIC_CELLS = [f"{p}-{o}" for p in POSES for o in ORIENTATIONS] + ["split-view-left", "split-view-right"]

# Window size in points per cell, per SDK tier (references/device-facts.md).
GEOMETRY = {
    "27.1": {
        "closed-portrait": (466, 678), "closed-landscape": (678, 466),
        "open-landscape": (951, 669), "book-landscape": (951, 669),
        "open-portrait": (669, 951), "book-portrait": (669, 951),
        "split-view-left": (455, 669), "split-view-right": (455, 669),
    },
    "27.0": {
        "closed-portrait": (386, 678), "closed-landscape": (678, 386),
        "open-landscape": (871, 669), "book-landscape": (871, 669),
        "open-portrait": (669, 871), "book-portrait": (669, 871),
        "split-view-left": (435, 669), "split-view-right": (435, 669),
    },
    "26": {
        "closed-portrait": (375, 667), "closed-landscape": (667, 375),
        "open-landscape": (375, 667), "book-landscape": (375, 667),
        "open-portrait": (375, 667), "book-portrait": (375, 667),
        "split-view-left": (375, 667), "split-view-right": (375, 667),
    },
}
STATUS_COLUMN_PT = 84          # trailing system column when bars are vertical
STATUS_TOP_BAND_PT = 82        # open-portrait status area height
CAMERA_PT = 37                 # outer front camera occlusion, square
FOLD_HALF_WIDTH_PT = 20        # fold region is 40 pt wide, centred
DISPLAY_SCALE = 3
VERTICAL_BAR_CELLS = {"closed-portrait", "closed-landscape", "open-landscape", "book-landscape"}
SCROLL_TYPES = {"scroll", "scrollview", "list", "table", "collection", "collectionview", "tableview", "feed", "web", "webview"}
FOREGROUND_TYPES = {"label", "text", "textfield", "textview", "button", "switch", "slider", "segmented", "link", "tab", "toolbaritem", "searchfield"}
GENERIC_ID_WORDS = {"button", "view", "label", "cell", "controller", "screen", "text", "image", "bar", "item", "row", "header", "footer"}
BAR_TYPES = {"tabbar", "toolbar", "navigationbar", "tab", "toolbaritem"}
# Scan rules that explain each assertion (references/assertions.md); source_hint
# only ever points at one of these, never at an unrelated rule whose file name
# happens to share a token with the app's own name (field test 2, note 27).
ASSERTION_RULES = {
    "offscreen_elements": ["screen-main-bounds", "hardcoded-size", "layout-once", "rn-dimensions-module-scope", "rn-stylesheet-fixed-width",
                           "rn-fixed-height", "rn-window-height-fraction", "window-frame-init", "stored-uiscreen"],
    "clipped_text": ["hardcoded-size", "rn-stylesheet-fixed-width", "rn-adjusts-font-fixed-lineheight", "rn-hardcoded-breakpoint", "layout-once"],
    "tap_target_min": ["hardcoded-size", "rn-fixed-height"],
    "bars_vertical_expected": ["custom-bar-class", "rn-js-tab-bar", "toolbar-item-no-symbol", "custom-overflow-menu"],
    "content_under_outer_camera": ["symmetric-safe-area", "rn-safe-area-missing", "fill-media", "rn-symmetric-insets", "rn-image-cover"],
    "interactive_in_fold": ["centered-grid-odd-columns", "cached-reserved-regions", "rn-expo-hinge-for-layout"],
    "transition_stable": ["layout-once", "orientation-layout", "rn-orientation-lock", "rn-dimensions-no-listener", "fixed-orientation-plist"],
    "visual_diff": [],
    "flow": [],
}

DEFAULT_ORIENTATION = {"closed": "portrait", "open": "landscape", "book": "landscape"}

# Assertion name -> duo.yaml assert key for its severity, default severity
SEVERITY_KEYS = {
    "offscreen_elements": ("offscreen_elements", "fail"),
    "clipped_text": ("clipped_text", "fail"),
    "tap_target_min": ("tap_target", "fail"),
    "bars_vertical_expected": ("bars_vertical_expected", "warn"),
    "content_under_outer_camera": ("content_under_outer_camera", "fail"),
    "interactive_in_fold": ("interactive_in_fold", "fail"),
    "visual_diff": ("visual_diff", "fail"),
    "transition_stable": ("transition_stable", "fail"),
    "flow": ("flow", "fail"),
}

FIX_HINTS = {
    "offscreen_elements": "Size relative to the container, not UIScreen.main or hardcoded iPhone dimensions; recompute layout in viewDidLayoutSubviews / onGeometryChange.",
    "clipped_text": "Let labels grow with the container: avoid fixed widths, use size classes, and allow multi-line text where the cell has room.",
    "tap_target_min": "Keep interactive elements at least 44 x 44 pt in every pose; vertical bars shrink the usable width on the outer display.",
    "bars_vertical_expected": "Build toolbars/tab bars with NavigationStack/TabView or UINavigationController/UITabBarController and give items a symbol; custom UIToolbar/UINavigationBar/UITabBar never go vertical.",
    "content_under_outer_camera": "Keep foreground controls inside the safe area; only background art may extend under the outer camera and status column.",
    "interactive_in_fold": "Keep interactive elements out of the fold region in book poses: use ReservedRegion / UIView.ReservedRegion, ArrangementView, or an even column count centred on the division frame.",
    "visual_diff": "Compare against the committed baseline; accept intentional changes by updating .duo/baselines, otherwise fix the regression.",
    "transition_stable": "State and controls must survive a fold/unfold: don't rebuild the view hierarchy on size change; pop stale compact layouts when width becomes regular instead of dropping elements.",
    "flow": "A flow step failed in this cell (wait timed out, tap not found, Maestro error): fix the flow or the screen it could not reach, then rerun this cell; the other cells were not affected.",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def sdk_tier(stamp) -> str:
    """'27.1' -> '27.1', '27.0' -> '27.0', anything older/unknown -> '26'."""
    if stamp is None:
        return "27.1"
    s = str(stamp)
    m = re.match(r"(\d+)(?:\.(\d+))?", s)
    if not m:
        return "27.1"
    major, minor = int(m.group(1)), int(m.group(2) or 0)
    if major > 27 or (major == 27 and minor >= 1):
        return "27.1"
    if major == 27:
        return "27.0"
    return "26"


def parse_capture_name(stem: str):
    """Return (flow, cell, kind) or None. kind: 'cell' | 'transition'."""
    m = re.match(r"^(.+)-(closed|open|book)(?:-to-|>)(closed|open|book)$", stem)
    if m:
        return m.group(1), f"{m.group(2)}>{m.group(3)}", "transition"
    for cell in STATIC_CELLS:
        if stem.endswith("-" + cell):
            return stem[: -len(cell) - 1], cell, "cell"
    return None


def window_for(cell: str, tier: str):
    if ">" in cell:
        to = cell.split(">")[1]
        cell = f"{to}-{DEFAULT_ORIENTATION[to]}"
    return GEOMETRY.get(tier, GEOMETRY["27.1"]).get(cell, (466, 678))


KNOWN_WINDOWS = {tuple(v) for tier in GEOMETRY.values() for v in tier.values()}


def window_from_png(path):
    """(w, h) in points from a capture's pixel size, or None when it is not a
    known Duo display size. The inner display comes up portrait after a
    closed>open unfold (2007 x 2853 captures, field test 2), while the runner
    assumed landscape; the screenshot is the truth."""
    if not path or not os.path.exists(path):
        return None
    try:
        inf = pngio.info(path)
    except Exception:  # noqa: BLE001 - any unreadable file means "unknown"
        return None
    w, h = int(round(inf["width"] / DISPLAY_SCALE)), int(round(inf["height"] / DISPLAY_SCALE))
    for kw, kh in KNOWN_WINDOWS:
        if abs(kw - w) <= 2 and abs(kh - h) <= 2:
            return (kw, kh)
    return None


def frame_of(el) -> tuple[float, float, float, float]:
    f = el.get("frame") or [0, 0, 0, 0]
    return float(f[0]), float(f[1]), float(f[2]), float(f[3])


def intersects(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def contains(outer, inner) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox - 0.5 and iy >= oy - 0.5 and ix + iw <= ox + ow + 0.5 and iy + ih <= oy + oh + 0.5


def is_scroll(el) -> bool:
    return str(el.get("type", "")).lower() in SCROLL_TYPES


def is_interactive(el) -> bool:
    # AXe reports `Button`, `TextField`...; run-matrix 0.2.0 compared lowercase
    # names and made every element non-interactive (field test 2, note 10).
    return bool(el.get("interactive")) or _tree.is_interactive_type(el.get("type"))


def is_scroll_indicator(el, W, H) -> bool:
    """A UIScrollView indicator: AXe reports it as an adjustable `Slider`, thin
    (32 pt or less) and as long as most of the window along its axis. VoiceOver
    can adjust it; nothing taps it, so it is neither a tap target nor a control
    on the fold (field test 3, note 12: one in every den and wardrobe cell)."""
    if str(el.get("type", "")).lower() != "slider":
        return False
    _, _, w, h = frame_of(el)
    if w <= 0 or h <= 0:
        return False
    if w >= h:
        return h <= 32 and w >= 0.4 * W
    return w <= 32 and h >= 0.4 * H


def interactive_elements(elements, W, H):
    return [el for el in elements if is_interactive(el) and not is_scroll_indicator(el, W, H)]


def _bar_row(items, extent, axis):
    """Items that form a bar along `axis` (0: a row across the width, 1: a
    column down the height): at least two, spread over half of `extent`.
    Used for the bottom band, where a bar spans the width."""
    if len(items) < 2:
        return []
    starts = [frame_of(e)[axis] for e in items]
    ends = [frame_of(e)[axis] + frame_of(e)[axis + 2] for e in items]
    return items if max(ends) - min(starts) >= 0.5 * extent else []


def is_container(el, W, H) -> bool:
    """Root and full-window groups are structure, not content. The AXe root
    `Application` element is also reported unrotated in landscape cells
    ([0, 0, 669, 951] in a 951 x 669 window), so a frame equal to the rotated
    window counts as the root too."""
    t = str(el.get("type", "")).lower()
    x, y, w, h = frame_of(el)
    if t == "application":
        return True
    if t not in _tree.CONTAINER_TYPES:
        return False
    if w <= 0 or h <= 0:
        return True
    if abs(w - H) <= 1 and abs(h - W) <= 1 and abs(x) <= 1 and abs(y) <= 1:
        return True  # rotated root
    return w * h >= 0.9 * W * H


def content_elements(elements, W, H):
    return [el for el in elements if not is_container(el, W, H)]


def brief(el) -> dict:
    out = {"id": el.get("id") or el.get("label") or "?", "frame": el.get("frame")}
    if el.get("type"):
        out["type"] = el["type"]
    return out


def id_tokens(ident: str) -> list[str]:
    parts = re.findall(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+", ident or "")
    return [p.lower() for p in parts if p.lower() not in GENERIC_ID_WORDS and len(p) >= 3]


# ---------------------------------------------------------------------------
# individual assertions: each returns (status, extra) with status pass|fail|skip
# ---------------------------------------------------------------------------


def a_offscreen(elements, W, H, ancestry=True):
    bad, below = [], []
    scrolls = [frame_of(e) for e in elements if is_scroll(e)]
    for el in content_elements(elements, W, H):
        x, y, w, h = frame_of(el)
        if w <= 0 or h <= 0:
            continue
        if x < -0.5 or y < -0.5 or x + w > W + 0.5 or y + h > H + 0.5:
            vertical_only = x >= -0.5 and x + w <= W + 0.5 and y >= -0.5
            in_scroll = any(sx - 0.5 <= x and x + w <= sx + sw + 0.5 and y >= sy - 0.5 for sx, sy, sw, sh in scrolls)
            if vertical_only and (in_scroll or not ancestry):
                below.append(brief(el))
            else:
                bad.append(brief(el))
    extra = {"elements": bad, "window": [W, H]}
    if bad:
        return "fail", extra
    if below and not ancestry:
        # AXe trees carry no scroll ancestry, so content below the window bottom
        # may be scrollable (normal) or clipped (a bug); report it, do not fail it.
        extra["elements"] = below
        extra["reason"] = ("below the window bottom; the tree has no scroll ancestry so this may be scroll content, "
                           "check the screenshot (DuoUITests trees carry ancestry and fail only clipped content)")
        return "warn", extra
    return "pass", extra


def a_clipped_text(elements, W, H):
    bad = []
    for el in elements:
        text = el.get("text") or ""
        if el.get("truncated") is True:
            bad.append(brief(el))
            continue
        if text.rstrip().endswith(("…", "...")):
            x, y, w, h = frame_of(el)
            parent = None
            parea = None
            for other in elements:
                if other is el:
                    continue
                of = frame_of(other)
                if of[2] <= 0 or of[3] <= 0 or not contains(of, (x, y, w, h)):
                    continue
                area = of[2] * of[3]
                if parea is None or area < parea:
                    parent, parea = of, area
            if parent is None:
                parent = (0.0, 0.0, float(W), float(H))
            available = parent[0] + parent[2] - x
            if w < available - 1:
                bad.append(brief(el))
    return ("fail" if bad else "pass"), {"elements": bad}


def a_tap_target(elements, minimum, W=None, H=None):
    bad = []
    for el in elements:
        if not is_interactive(el) or (W and H and is_scroll_indicator(el, W, H)):
            continue
        _, _, w, h = frame_of(el)
        if w <= 0 or h <= 0:
            continue
        if w < minimum or h < minimum:
            bad.append(brief(el))
    return ("fail" if bad else "pass"), {"elements": bad, "min": minimum}


def a_bars_vertical(elements, cell, W, H, tier):
    if cell not in VERTICAL_BAR_CELLS:
        return "skip", {"reason": "cell keeps horizontal bars"}
    if tier != "27.1":
        return "skip", {"reason": f"SDK tier {tier} does not place bars vertically"}
    bar_typed = any(str(e.get("type", "")).lower() in BAR_TYPES for e in elements)
    # A bar is a row (or column) of items inside the window that spans most of
    # it. Controls that merely sit low on a scrolled screen, below the window
    # bottom, are content (field test 3, note 12: a task field, two 42 pt
    # buttons and a scroll indicator were read as a bottom bar).
    bottom = _bar_row([e for e in interactive_elements(elements, W, H)
                       if frame_of(e)[1] >= H - STATUS_COLUMN_PT and frame_of(e)[1] + frame_of(e)[3] <= H + 1
                       and frame_of(e)[3] < STATUS_COLUMN_PT], W, axis=0)
    # A vertical bar is short (two or three items near the top of the trailing
    # column), so the trailing test asks only that the items be inside the window.
    trailing = [e for e in interactive_elements(elements, W, H)
                if frame_of(e)[0] >= W - STATUS_COLUMN_PT and frame_of(e)[0] + frame_of(e)[2] <= W + 1]
    if not bar_typed and len(bottom) < 2 and len(trailing) < 2:
        return "skip", {"reason": "no tab bar or toolbar elements in the tree; nothing to move to the trailing edge (a JS-drawn bar is reported by scan rule rn-js-tab-bar)"}
    column = [el for el in elements if is_interactive(el) and frame_of(el)[0] >= W - STATUS_COLUMN_PT]
    column.sort(key=lambda e: frame_of(e)[1])
    stacked = []
    for el in column:
        if not stacked:
            stacked.append(el)
            continue
        px, py, pw, ph = frame_of(stacked[-1])
        x, y, w, h = frame_of(el)
        if y >= py + ph - 1:
            stacked.append(el)
    if len(stacked) >= 2:
        return "pass", {"elements": [brief(e) for e in stacked]}
    return "fail", {"elements": [], "reason": "no vertically stacked interactive items in the trailing 84 pt column"}


def a_outer_camera(elements, cell, W, H):
    if not cell.startswith("closed"):
        return "skip", {"reason": "outer camera only on the outer display"}
    margin = (STATUS_COLUMN_PT - CAMERA_PT) / 2.0
    cam = (W - STATUS_COLUMN_PT + margin, 10.0, float(CAMERA_PT), float(CAMERA_PT))
    bad = []
    for el in content_elements(elements, W, H):
        if is_scroll(el):
            continue
        # Only foreground content matters: controls and text. Containers and
        # background art may extend under the camera (Apple: background can
        # ignore the safe area, foreground cannot).
        foreground = is_interactive(el) or bool(el.get("text")) or str(el.get("type", "")).lower() in FOREGROUND_TYPES
        if not foreground:
            continue
        f = frame_of(el)
        if f[2] <= 0 or f[3] <= 0:
            continue
        if intersects(f, cam):
            bad.append(brief(el))
    return ("fail" if bad else "pass"), {"elements": bad, "camera": list(cam)}


def a_fold(elements, cell, W, H):
    if not cell.startswith("book"):
        return "skip", {"reason": "fold is only active in book poses"}
    if cell.endswith("landscape"):
        band = (W / 2.0 - FOLD_HALF_WIDTH_PT, 0.0, 2.0 * FOLD_HALF_WIDTH_PT, float(H))
    else:
        band = (0.0, H / 2.0 - FOLD_HALF_WIDTH_PT, float(W), 2.0 * FOLD_HALF_WIDTH_PT)
    bad = []
    for el in elements:
        if not is_interactive(el) or is_scroll(el) or is_scroll_indicator(el, W, H):
            continue
        f = frame_of(el)
        if f[2] <= 0 or f[3] <= 0:
            continue
        if intersects(f, band):
            bad.append(brief(el))
    return ("fail" if bad else "pass"), {"elements": bad, "fold": list(band)}


def ignore_regions_for(cell: str, img_w: int, img_h: int):
    if cell in ("open-portrait", "book-portrait"):
        return [(0, 0, img_w, STATUS_TOP_BAND_PT * DISPLAY_SCALE)]
    if cell in VERTICAL_BAR_CELLS:
        col = STATUS_COLUMN_PT * DISPLAY_SCALE
        return [(max(0, img_w - col), 0, col, img_h)]
    return []


def a_visual_diff(screenshot, baseline, cell, threshold, out_path=None):
    if not baseline or not os.path.exists(baseline):
        return "skip", {"reason": "no baseline"}
    if not screenshot or not os.path.exists(screenshot):
        return "skip", {"reason": "no screenshot"}
    try:
        inf = _diff.pngio.info(screenshot)
        ignore = ignore_regions_for(cell, inf["width"], inf["height"])
    except Exception:  # noqa: BLE001 - unreadable file is reported by compare()
        ignore = []
    res = _diff.compare(screenshot, baseline, ignore=ignore, out=out_path)
    frac = res["fraction"]
    extra = {"diff": frac, "threshold": threshold, "baseline": baseline}
    if res.get("reason"):
        extra["reason"] = res["reason"]
    if res.get("out"):
        extra["diff_image"] = res["out"]
    if frac <= threshold:
        return "pass", extra
    if frac <= 2 * threshold:
        return "warn", extra
    return "fail", extra


def a_transition(before_elements, after_elements, may_remove):
    if before_elements is None:
        return "skip", {"reason": "no before-tree for transition"}
    before = {e.get("id") for e in before_elements if e.get("id")}
    after = {e.get("id") for e in after_elements if e.get("id")}
    missing = sorted(i for i in before - after if i not in set(may_remove or []))
    if missing:
        return "fail", {"elements": [{"id": i} for i in missing], "missing": missing}
    return "pass", {"kept": len(before & after)}


# ---------------------------------------------------------------------------
# driver
# ---------------------------------------------------------------------------


def load_tree(path):
    if not path or not os.path.exists(path):
        return None
    data = duolib.load_json(path)
    if isinstance(data, dict):
        return data.get("elements") or []
    return data if isinstance(data, list) else []


def tree_meta(path) -> dict:
    """{"source": str|None, "ancestry": bool} for a tree file."""
    if not path or not os.path.exists(path):
        return {"source": None, "ancestry": False}
    data = duolib.load_json(path)
    if isinstance(data, dict):
        src = data.get("source")
        anc = data.get("ancestry")
        if anc is None:
            anc = str(src or "").lower() != "duoctl elements"
        return {"source": src, "ancestry": bool(anc)}
    return {"source": None, "ancestry": True}


def tree_available(path) -> bool:
    """False when the tree file is missing or was written with source=unavailable.

    run-matrix writes that stub when `duoctl elements` fails (AXe not installed)
    or the DuoUITests attachment is missing. An empty tree used to make every
    tree-based assertion pass; the first field test reported 25 green cells
    that way. Those assertions are skipped instead.
    """
    if not path or not os.path.exists(path):
        return False
    data = duolib.load_json(path)
    if isinstance(data, dict):
        return data.get("source") != "unavailable"
    return isinstance(data, list)


def severity_for(name: str, cfg: dict) -> str:
    key, default = SEVERITY_KEYS[name]
    val = cfg.get(key, default)
    if val is None:
        return default
    if val is False:  # YAML reads a bare `off` as boolean false
        return "off"
    if val is True:
        return default
    val = str(val).lower()
    return val if val in ("fail", "warn", "off") else default


def apply_severity(status: str, severity: str) -> str:
    if severity == "off":
        return "skip"
    if status == "fail" and severity == "warn":
        return "warn"
    return status


def match_scan(finding_list, element_ids, assertion=None):
    """Return the scan finding most likely behind a failure, or None.

    Only rules listed for the assertion in ASSERTION_RULES qualify (an
    offscreen element is never explained by an AppState rule). Among those, a
    finding whose file stem shares a token with a failing element id wins;
    otherwise the most severe finding of a qualifying rule is returned with
    `confidence: "rule"` so the agent knows the file was not matched."""
    allowed = ASSERTION_RULES.get(assertion) if assertion else None
    candidates = [f for f in finding_list if allowed is None or f.get("rule") in allowed]
    if not candidates:
        return None
    rank = {"error": 0, "warn": 1, "info": 2}
    best = None
    for ident in element_ids:
        toks = id_tokens(ident)
        if not toks:
            continue
        for f in candidates:
            stem = os.path.splitext(os.path.basename(f.get("file", "")))[0]
            ftoks = id_tokens(stem)
            hit = any(t == ft or ft.startswith(t) or t.startswith(ft) for t in toks for ft in ftoks)
            if hit and (best is None or rank.get(f.get("severity"), 9) < rank.get(best.get("severity"), 9)):
                best = dict(f, confidence="file")
    if best:
        return best
    if allowed is None:
        return None
    first = sorted(candidates, key=lambda f: rank.get(f.get("severity"), 9))[0]
    return dict(first, confidence="rule")


def evaluate_run(root: str, run: int, include_warn: bool = False) -> tuple[dict, list]:
    rdir = duolib.run_dir(root, run)
    cap = os.path.join(rdir, "captures")
    if not os.path.isdir(cap):
        raise SystemExit(f"no captures directory: {cap}")

    cfg_path = os.path.join(root, "duo.yaml")
    cfg = duolib.load_yaml(cfg_path) if os.path.exists(cfg_path) else {}
    acfg = (cfg or {}).get("assert") or {}
    flows_cfg = {f.get("name"): f for f in ((cfg or {}).get("flows") or []) if isinstance(f, dict)}
    threshold = float(acfg.get("visual_diff_threshold", 0.02) or 0.02)
    tap_min = float(acfg.get("tap_target_min", 44) or 44)

    build_path = os.path.join(rdir, "build.json")
    build = duolib.load_json(build_path) if os.path.exists(build_path) else {}
    stamp = build.get("sdk_stamp") or build.get("sdk")
    tier = sdk_tier(stamp)

    scan_path = os.path.join(duolib.duo_dir(root), "scan.json")
    findings = duolib.load_json(scan_path).get("findings", []) if os.path.exists(scan_path) else []

    cells_out = []
    failures = []
    no_tree = {"reason": "no element tree: install AXe (duoctl elements) or add the DuoUITests target; nothing was checked"}
    for name in sorted(os.listdir(cap)):
        if name.endswith(".error.json"):
            # run-matrix wrote this when a flow step failed in the cell (timed-out
            # wait, Maestro error); the matrix carried on with the next cell.
            parsed = parse_capture_name(name[: -len(".error.json")])
            if parsed:
                info = duolib.load_json(os.path.join(cap, name)) or {}
                reason = info.get("reason") or "flow step failed"
                cells_out.append({
                    "flow": parsed[0], "cell": parsed[1], "screenshot": None, "tree": None,
                    "window": list(window_for(parsed[1], tier)), "errored": True, "tree_available": False,
                    "results": [{"assertion": "flow", "status": "fail", "reason": reason}],
                })
                failures.append({"flow": parsed[0], "cell": parsed[1], "assertion": "flow", "status": "fail",
                                 "elements": [], "screenshot": None, "matched_rule": None, "source_hint": None,
                                 "reason": reason, "fix_hint": FIX_HINTS["flow"]})
            continue
        if name.endswith(".skip.json"):
            # run-matrix wrote this when the app refused the cell (portrait-only on that display)
            parsed = parse_capture_name(name[: -len(".skip.json")])
            if parsed:
                info = duolib.load_json(os.path.join(cap, name)) or {}
                cells_out.append({
                    "flow": parsed[0], "cell": parsed[1], "screenshot": None, "tree": None,
                    "window": list(window_for(parsed[1], tier)), "skipped": True, "tree_available": False,
                    "results": [{"assertion": "cell", "status": "skip", "reason": info.get("reason") or "cell skipped by run-matrix"}],
                })
            continue
        if not name.endswith(".tree.json") or name.endswith(".before.tree.json"):
            continue
        stem = name[: -len(".tree.json")]
        parsed = parse_capture_name(stem)
        if not parsed:
            continue
        flow, cell, kind = parsed
        tree_path = os.path.join(cap, name)
        shot = os.path.join(cap, stem + ".png")
        elements = load_tree(tree_path) or []
        available = tree_available(tree_path)
        meta = tree_meta(tree_path)
        ancestry = meta["ancestry"]
        W, H = window_for(cell, tier)
        window_source = "cell"
        actual = window_from_png(shot)
        if actual and (actual[0], actual[1]) != (W, H):
            W, H = actual
            window_source = "screenshot"
        results = []

        def checked(fn):
            """Tree-based assertions are skipped, not passed, when there is no tree to read."""
            return fn() if available else ("skip", dict(no_tree))

        def add(aname, status, extra):
            sev = severity_for(aname, acfg)
            final = apply_severity(status, sev)
            entry = {"assertion": aname, "status": final}
            entry.update({k: v for k, v in extra.items() if k != "window" or final != "pass"})
            results.append(entry)
            if final == "fail" or (include_warn and final == "warn"):
                ids = [e.get("id") for e in extra.get("elements", []) if e.get("id")]
                hit = match_scan(findings, ids, aname)
                failures.append({
                    "flow": flow, "cell": cell, "assertion": aname, "status": final,
                    "elements": extra.get("elements", []),
                    "screenshot": _rel(root, shot) if os.path.exists(shot) else None,
                    "matched_rule": hit.get("rule") if hit else None,
                    # A rule-level match names a rule, not a file: the first finding
                    # of that rule blamed an onboarding video for den buttons (field test 3).
                    "source_hint": f"{hit['file']}:{hit.get('line')}" if hit and hit.get("confidence") == "file" else None,
                    "source_confidence": hit.get("confidence") if hit else None,
                    # The rule's hint applies only when its file is the screen's;
                    # a rule-level lead gave "heroes of 250 pt" for 42 pt buttons.
                    "fix_hint": (hit.get("fix_hint") if hit and hit.get("confidence") == "file" and hit.get("fix_hint")
                                 else FIX_HINTS[aname]),
                })

        if kind == "transition":
            before_path = os.path.join(cap, stem + ".before.tree.json")
            before = load_tree(before_path)
            if before is None:
                frm = cell.split(">")[0]
                for orient in (DEFAULT_ORIENTATION[frm],) + tuple(o for o in ORIENTATIONS if o != DEFAULT_ORIENTATION[frm]):
                    alt = os.path.join(cap, f"{flow}-{frm}-{orient}.tree.json")
                    if os.path.exists(alt):
                        before = load_tree(alt)
                        break
            may_remove = (flows_cfg.get(flow) or {}).get("may_remove") or []
            add("transition_stable", *checked(lambda: a_transition(before, elements, may_remove)))
            add("offscreen_elements", *checked(lambda: a_offscreen(elements, W, H, ancestry)))
            if cell.split(">")[-1] == "book":
                # The after-tree is the book pose: a grid on the hinge is caught
                # here too, not only in the book-landscape cell (field test 3, note 12).
                after_cell = "book-landscape" if W >= H else "book-portrait"
                add("interactive_in_fold", *checked(lambda: a_fold(elements, after_cell, W, H)))
        else:
            add("offscreen_elements", *checked(lambda: a_offscreen(elements, W, H, ancestry)))
            add("clipped_text", *checked(lambda: a_clipped_text(elements, W, H)))
            add("tap_target_min", *checked(lambda: a_tap_target(elements, tap_min, W, H)))
            add("bars_vertical_expected", *checked(lambda: a_bars_vertical(elements, cell, W, H, tier)))
            add("content_under_outer_camera", *checked(lambda: a_outer_camera(elements, cell, W, H)))
            add("interactive_in_fold", *checked(lambda: a_fold(elements, cell, W, H)))
            baseline = os.path.join(duolib.duo_dir(root), "baselines", stem + ".png")
            diff_out = os.path.join(cap, stem + ".diff.png")
            add("visual_diff", *a_visual_diff(shot, baseline, cell, threshold, diff_out))

        cells_out.append({
            "flow": flow, "cell": cell,
            "screenshot": _rel(root, shot) if os.path.exists(shot) else None,
            "tree": _rel(root, tree_path),
            "tree_available": available,
            "tree_source": meta["source"],
            "ancestry": ancestry,
            "window": [W, H],
            "window_source": window_source,
            "results": results,
        })

    ui = {
        "schema": 1,
        "run": run,
        "generated": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sdk_stamp": stamp,
        "sdk_tier": tier,
        "cells": cells_out,
        # False when no cell had an element tree: the run proved nothing about layout.
        "verified": any(c.get("tree_available") for c in cells_out),
        "summary": _summary(cells_out),
    }
    return ui, failures


def _rel(root: str, path: str) -> str:
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return path.replace("\\", "/")


def _summary(cells) -> dict:
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for c in cells:
        for r in c["results"]:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
    counts["cells"] = len(cells)
    counts["unverified_cells"] = sum(1 for c in cells if not c.get("skipped") and not c.get("errored") and c.get("tree_available") is False)
    counts["skipped_cells"] = sum(1 for c in cells if c.get("skipped"))
    counts["errored_cells"] = sum(1 for c in cells if c.get("errored"))
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", type=int, required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true", help="print ui.json summary as JSON")
    ap.add_argument("--include-warn", action="store_true", help="also emit warn results as agent payloads")
    args = ap.parse_args(argv)

    ui, failures = evaluate_run(args.root, args.run, args.include_warn)
    rdir = duolib.run_dir(args.root, args.run)
    duolib.write_json(os.path.join(rdir, "ui.json"), ui)
    duolib.write_json(os.path.join(rdir, "failures.json"), failures)

    if args.json:
        import json
        print(json.dumps({"run": args.run, "summary": ui["summary"], "failures": len(failures)}))
    else:
        print(f"run {args.run}  sdk {ui['sdk_tier']}  cells {ui['summary']['cells']}  "
              f"pass {ui['summary']['pass']}  warn {ui['summary']['warn']}  fail {ui['summary']['fail']}  skip {ui['summary']['skip']}")
        for c in ui["cells"]:
            if c.get("skipped"):
                print(f"  {c['flow']} / {c['cell']}: skipped ({c['results'][0].get('reason', '')})")
                continue
            if c.get("errored"):
                print(f"  {c['flow']} / {c['cell']}: flow failed ({c['results'][0].get('reason', '')})")
                continue
            bad = [r for r in c["results"] if r["status"] in ("fail", "warn")]
            if bad:
                print(f"  {c['flow']} / {c['cell']}: " + ", ".join(f"{r['assertion']}={r['status']}" for r in bad))
    unverified = ui["summary"].get("unverified_cells", 0)
    if unverified:
        print(f"WARNING: {unverified} of {ui['summary']['cells']} cells have no element tree; offscreen, clipped, tap-target, "
              "camera and fold assertions were skipped, not passed (install AXe: brew tap cameroncooke/axe && brew install axe)",
              file=sys.stderr)
    return duolib.exit_codes.UI_FAIL if ui["summary"]["fail"] else duolib.exit_codes.PASS


if __name__ == "__main__":
    sys.exit(main())
