#!/usr/bin/env python3
"""duo-ready scan: static rules for iPhone Duo resizing breakages.

Usage:
  scan.py [ROOT] [--rules FILE ...] [--stack native|rn|all] [--json] [--out PATH]
  scan.py [ROOT] --fix --dry-run            # print unified diffs for autofixable rules
  scan.py [ROOT] --fix --apply [--force] [--commit]

Walks ROOT (default .), applies the rule catalogs in scripts/rules/, writes
.duo/scan.json (see references/pipeline-contracts.md) and prints a table grouped
by rule. Findings are not failures: exit 0. Exit 4 only when inputs are missing.

Standard library only; runs on macOS, Linux and Windows.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import json
import os
import plistlib
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import duolib  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
RULES_DIR = os.path.join(HERE, "rules")
SKIP_DIRS = {"node_modules", "Pods", ".build", "DerivedData", ".git", "build", ".duo",
             ".expo", "android", "Carthage", "vendor", ".next", "dist", "__pycache__"}
EXT_LANG = {
    ".swift": "swift", ".m": "objc", ".mm": "objc", ".h": "objc",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".ts": "ts", ".tsx": "ts",
    ".json": "json", ".plist": "plist",
}
SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}
# Test files never run on a device: Dimensions.get in a Jest test is not a
# layout bug (field test false positive).
TEST_FILE_RE = re.compile(r"(?:^|/)(?:__tests__|__mocks__|__snapshots__)/|\.(?:test|spec)\.[jt]sx?$")
SCHEMA = 1

# ---------------------------------------------------------------------------
# Lexer: blank comments and string contents, preserving positions
# ---------------------------------------------------------------------------


def strip_code(text: str, lang: str) -> str:
    """Return text with comments and string-literal contents replaced by spaces.

    Newlines and column positions are preserved so line/column numbers computed
    on the stripped text are valid for the original.
    """
    if lang in ("json", "plist"):
        return text
    out = list(text)
    n = len(text)
    i = 0

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif lang in ("swift", "objc") and text.startswith('"""', i):
            j = text.find('"""', i + 3)
            j = n if j < 0 else j + 3
            blank(i + 3, max(i + 3, j - 3))
            i = j
        elif c in ('"', "'", "`"):
            if c == "'" and lang in ("swift", "objc"):
                # Swift has no single-quoted strings; ObjC char literal 'a'
                i += 1
                continue
            if c == "`" and lang not in ("js", "ts"):
                i += 1
                continue
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == c:
                    break
                if text[j] == "\n" and c != "`":
                    break  # unterminated; stop at EOL
                j += 1
            blank(i + 1, min(j, n))
            i = min(j, n) + 1
        else:
            i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def load_rules(paths: list[str] | None = None, stack: str = "all") -> list[dict]:
    if not paths:
        paths = []
        if stack in ("all", "native"):
            paths.append(os.path.join(RULES_DIR, "native.yaml"))
        if stack in ("all", "rn"):
            paths.append(os.path.join(RULES_DIR, "react-native.yaml"))
    rules: list[dict] = []
    for p in paths:
        if not os.path.exists(p):
            print(f"cannot run on this host: rules file not found: {p}", file=sys.stderr)
            sys.exit(duolib.exit_codes.PREFLIGHT_FAIL)
        for r in duolib.load_yaml(p) or []:
            langs = r.get("lang", [])
            r["lang"] = [langs] if isinstance(langs, str) else list(langs)
            r.setdefault("kind", "line")
            r.setdefault("severity", "warn")
            r.setdefault("autofix", False)
            r.setdefault("raw", False)
            if "pattern" in r and r["pattern"] is not None:
                flags = re.M if r["kind"] == "multiline" else 0
                r["_re"] = re.compile(r["pattern"], flags)
            if r.get("exclude"):
                r["_exclude"] = re.compile(r["exclude"])
            if r.get("fix_exclude"):
                # still reported as a finding, but never rewritten by --fix
                r["_fix_exclude"] = re.compile(r["fix_exclude"])
            rules.append(r)
    return rules


def finding(rule: dict, path: str, line: int, col: int, match: str) -> dict:
    return {
        "rule": rule["id"],
        "severity": rule["severity"],
        # a site that fix_exclude protects is reported but counted as manual
        "autofix": bool(rule.get("autofix")) and not (rule.get("_fix_exclude") is not None and rule["_fix_exclude"].search(match)),
        "file": path.replace(os.sep, "/"),
        "line": line,
        "column": col,
        "match": match.strip()[:160],
        "fix_hint": rule.get("fix_hint", ""),
        "apple_ref": rule.get("apple_ref", ""),
        "doc": rule.get("doc", ""),
    }


# ---------------------------------------------------------------------------
# File-level checks (kind: file)
# ---------------------------------------------------------------------------

_GEOMETRY_RE = re.compile(r"\b(?:bounds|frame)\s*\.\s*(?:width|height|size|midX|midY|maxX|maxY)\b|\bbounds\b|\.frame\b")
_LAYOUT_HOOK_RE = re.compile(r"viewDidLayoutSubviews|layoutSubviews|viewWillTransition|onGeometryChange|GeometryReader|updateConstraints")
_FUNC_RE = re.compile(r"\bfunc\s+(?:viewDidLoad|viewIsAppearing)\b|^\s*(?:override\s+|required\s+|convenience\s+|public\s+|private\s+)*init\s*\(", re.M)


def _brace_body(text: str, start: int) -> tuple[int, int] | None:
    """Return (open, close) offsets of the first {...} block at or after start."""
    o = text.find("{", start)
    if o < 0:
        return None
    depth = 0
    for k in range(o, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return o, k
    return None


def check_layout_once(rule: dict, path: str, raw: str, stripped: str) -> list[dict]:
    if _LAYOUT_HOOK_RE.search(stripped):
        return []
    out = []
    for m in _FUNC_RE.finditer(stripped):
        body = _brace_body(stripped, m.end())
        if not body:
            continue
        o, c = body
        seg = stripped[o:c]
        g = _GEOMETRY_RE.search(seg)
        if g:
            abs_pos = o + g.start()
            line = stripped.count("\n", 0, abs_pos) + 1
            col = abs_pos - (stripped.rfind("\n", 0, abs_pos) + 1) + 1
            out.append(finding(rule, path, line, col, raw.splitlines()[line - 1]))
            break
    return out


def _plist_load(raw: str) -> dict | None:
    try:
        return plistlib.loads(raw.encode("utf-8"))
    except Exception:
        return None


def _line_of(raw: str, needle: str) -> int:
    for i, ln in enumerate(raw.splitlines(), 1):
        if needle in ln:
            return i
    return 1


def check_fixed_orientation_plist(rule: dict, path: str, raw: str, stripped: str) -> list[dict]:
    if os.path.basename(path) != "Info.plist":
        return []
    data = _plist_load(raw)
    if not data:
        return []
    out = []
    for key in ("UISupportedInterfaceOrientations", "UISupportedInterfaceOrientations~iphone"):
        vals = data.get(key)
        if isinstance(vals, list) and vals and not any("Landscape" in v for v in vals):
            out.append(finding(rule, path, _line_of(raw, key), 1, f"{key} = {vals}"))
    return out


def check_rn_dimensions_no_listener(rule: dict, path: str, raw: str, stripped: str) -> list[dict]:
    if re.search(r"useWindowDimensions|Dimensions\.addEventListener|useDimensions\(", stripped):
        return []
    out = []
    for i, ln in enumerate(stripped.splitlines(), 1):
        if re.search(r"Dimensions\.get\(", ln) and ln[:1].isspace():
            out.append(finding(rule, path, i, ln.find("Dimensions") + 1, raw.splitlines()[i - 1]))
    return out


_SCREEN_FILE_RE = re.compile(r"(?:^|[\\/])(?:screens|app|\(tabs\))[\\/].+\.[jt]sx?$|Screen\.[jt]sx?$")


def check_rn_safe_area_missing(rule: dict, path: str, raw: str, stripped: str) -> list[dict]:
    if not _SCREEN_FILE_RE.search(path) or "_layout." in os.path.basename(path):
        return []
    if not re.search(r"\breturn\s*\(?\s*<", stripped):
        return []  # not a component file
    if re.search(r"SafeAreaView|useSafeAreaInsets|useSafeAreaFrame|SafeAreaProvider|edges=|contentInsetAdjustmentBehavior", stripped):
        return []
    # Route wrappers, redirects and navigator roots draw nothing of their own,
    # and a screen rendered inside a scaffold/layout component inherits its
    # insets (field test: all 7 findings on a real Expo app were one of these).
    if re.search(r"<\s*(?:Redirect|Slot)\b|<\s*(?:Stack|Tabs|Drawer)\s*(?:>|screenOptions|initialRouteName)", stripped):
        return []
    if not re.search(r"\bstyle\s*=|StyleSheet\.create\(", stripped):
        return []
    if re.search(r"<\s*\w*(?:Scaffold|Layout|Shell|Chrome|Frame)\b", stripped):
        return []
    return [finding(rule, path, 1, 1, os.path.basename(path))]


_LINEHEIGHT_RE = re.compile(r"\blineHeight\s*:")


def check_rn_adjusts_font_fixed_lineheight(rule: dict, path: str, raw: str, stripped: str) -> list[dict]:
    """adjustsFontSizeToFit together with a fixed lineHeight on the same Text.

    On the new architecture (React Native 0.81) the fit search ignores
    minimumFontScale and stops only when the text fits its frame; a fixed
    lineHeight keeps the line box from shrinking, so on the 678 pt outer
    display the search ends at the 4 pt floor and the text vanishes (field
    test bugs F3 and F5).
    """
    if "adjustsFontSizeToFit" not in stripped or not _LINEHEIGHT_RE.search(stripped):
        return []
    out = []
    raw_lines = raw.splitlines()
    for i, ln in enumerate(stripped.splitlines(), 1):
        if "adjustsFontSizeToFit" not in ln:
            continue
        m = re.search(r"style=\{\s*styles\.(\w+)", ln)
        if m:
            block = re.search(r"\b" + re.escape(m.group(1)) + r"\s*:\s*\{([^}]*)\}", stripped)
            if block and not _LINEHEIGHT_RE.search(block.group(1)):
                continue  # that style has no fixed lineHeight
        out.append(finding(rule, path, i, ln.find("adjustsFontSizeToFit") + 1, raw_lines[i - 1]))
    return out


_APPSTATE_RE = re.compile(r"(?<![.\w])(?:state|nextAppState|appState|status|next)\s*!==?\s*['\"]active['\"]"
                          r"|(?<![.\w])(?:state|nextAppState|appState|status|next)\s*===?\s*['\"]inactive['\"]")
_RESUME_RE = re.compile(r"!==?\s*['\"]active['\"]\s*\)\s*\{?\s*return\b")


def check_rn_appstate_inactive_pause(rule: dict, path: str, raw: str, stripped: str) -> list[dict]:
    """Pausing on anything but background. Only in files that read AppState,
    never on a property (`action.status`), and not on resume handlers of the
    form `if (state !== 'active') return;` (field test: 4 of 5 findings)."""
    if "AppState" not in stripped:
        return []
    out = []
    stripped_lines = stripped.splitlines()
    for i, ln in enumerate(raw.splitlines(), 1):
        m = _APPSTATE_RE.search(ln)
        if not m or _RESUME_RE.search(ln):
            continue
        # strip_code keeps offsets: the identifier must survive in the code view
        # (a comment that quotes the pattern is not a finding)
        code_ln = stripped_lines[i - 1] if i <= len(stripped_lines) else ""
        ident = re.match(r"\w+", m.group(0)).group(0)
        if not code_ln[m.start():].startswith(ident):
            continue
        out.append(finding(rule, path, i, m.start() + 1, ln))
    return out


def check_rn_expo_hinge_for_layout(rule: dict, path: str, raw: str, stripped: str) -> list[dict]:
    if not re.search(r"expo-hinge|useHinge\(|getHinge\(", raw):
        return []
    out = []
    for i, ln in enumerate(stripped.splitlines(), 1):
        if re.search(r"\bhinge\b", ln, re.I) and re.search(r"\b(?:width|height|flex|flexDirection|columns|numColumns|style|layout|padding|margin)\b", ln) \
                and not re.search(r"useHinge\(|getHinge\(|import", ln):
            out.append(finding(rule, path, i, 1, raw.splitlines()[i - 1]))
    return out


# Conservative floors. react-native-screens shipped iPhone Duo fixes on 13 Oct 2026;
# the exact first version is TODO-VERIFY on npm. 4.20.0 is used as the floor.
_EXPO_FLOOR = 58
_SCREENS_FLOOR = (4, 20, 0)


def _semver(spec: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", spec or "")
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def check_rn_sdk_floor(rule: dict, path: str, raw: str, stripped: str) -> list[dict]:
    if os.path.basename(path) != "package.json":
        return []
    try:
        pkg = json.loads(raw)
    except Exception:
        return []
    deps = {}
    for k in ("dependencies", "devDependencies"):
        deps.update(pkg.get(k, {}) or {})
    out = []
    expo = deps.get("expo")
    if expo:
        v = _semver(expo)
        if v and v[0] < _EXPO_FLOOR:
            out.append(finding(rule, path, _line_of(raw, '"expo"'), 1, f"expo {expo} < {_EXPO_FLOOR}"))
    screens = deps.get("react-native-screens")
    if screens:
        v = _semver(screens)
        if v and v < _SCREENS_FLOOR:
            out.append(finding(rule, path, _line_of(raw, '"react-native-screens"'), 1,
                               f"react-native-screens {screens} < {'.'.join(map(str, _SCREENS_FLOOR))} (TODO-VERIFY floor)"))
    return out


FILE_CHECKS = {
    "rn_adjusts_font_fixed_lineheight": check_rn_adjusts_font_fixed_lineheight,
    "rn_appstate_inactive_pause": check_rn_appstate_inactive_pause,
    "layout_once": check_layout_once,
    "fixed_orientation_plist": check_fixed_orientation_plist,
    "rn_dimensions_no_listener": check_rn_dimensions_no_listener,
    "rn_safe_area_missing": check_rn_safe_area_missing,
    "rn_expo_hinge_for_layout": check_rn_expo_hinge_for_layout,
    "rn_sdk_floor": check_rn_sdk_floor,
}


# ---------------------------------------------------------------------------
# Project-level checks (kind: project)
# ---------------------------------------------------------------------------

_SCENE_RE = re.compile(r"UIWindowSceneDelegate|UISceneDelegate|:\s*App\s*\{|\bApp\s*\{\s*$|UIApplicationSceneManifest|RCTAppDelegate", re.M)


def check_no_scene_delegate(rule: dict, root: str, files: list[tuple[str, str]]) -> list[dict]:
    """One finding per Info.plist whose subtree has neither a scene manifest nor a scene delegate."""
    plists = [p for p, lang in files if lang == "plist" and os.path.basename(p) == "Info.plist"]
    out = []
    for plist in plists:
        base = os.path.dirname(plist)
        raw = _read(os.path.join(root, plist))
        data = _plist_load(raw) or {}
        if "UIApplicationSceneManifest" in data or "NSExtension" in data:
            continue
        if "CFBundlePackageType" in data and data.get("CFBundlePackageType") not in ("APPL", "$(PRODUCT_BUNDLE_PACKAGE_TYPE)"):
            continue
        # sources in the same subtree, excluding nested targets with their own Info.plist
        nested = [os.path.dirname(p) for p in plists if p != plist and os.path.dirname(p).startswith(base + "/" if base else "")]
        has_scene = False
        for p, lang in files:
            if lang not in ("swift", "objc"):
                continue
            if base and not p.startswith(base + "/"):
                continue
            if any(p.startswith(nd + "/") for nd in nested):
                continue
            if _SCENE_RE.search(_read(os.path.join(root, p))):
                has_scene = True
                break
        if not has_scene:
            out.append(finding(rule, plist, _line_of(raw, "<dict>"), 1, "no UIApplicationSceneManifest and no UIWindowSceneDelegate"))
    return out


_EXPO_SCENE_RE = re.compile(r"UIApplicationSceneManifest|UIWindowSceneDelegate|withSceneLifecycle")


def is_expo_project(root: str) -> bool:
    app_json = os.path.join(root, "app.json")
    if os.path.exists(app_json):
        try:
            if "expo" in (json.loads(_read(app_json)) or {}):
                return True
        except ValueError:
            pass
    return any(os.path.exists(os.path.join(root, n)) for n in ("app.config.js", "app.config.ts", "app.config.mjs"))


def expo_generated_dirs(root: str) -> set[str]:
    """ios/ and android/ of an Expo managed project when git ignores them.

    `expo prebuild` regenerates them, so a finding there cannot be committed
    and the fix belongs in app.json or a config plugin (field test: 4 of 26
    findings pointed at generated files).
    """
    if not is_expo_project(root):
        return set()
    gi = os.path.join(root, ".gitignore")
    if not os.path.exists(gi):
        return set()
    lines = {ln.strip().strip("/") for ln in _read(gi).splitlines()}
    return {d for d in ("ios", "android") if d in lines}


def _expo_config_plugins(root: str) -> list[str] | None:
    """Names/paths of the config plugins app.json registers, None when the
    config is code (app.config.*) and cannot be parsed here."""
    app_json = os.path.join(root, "app.json")
    if not os.path.exists(app_json):
        return None
    try:
        expo = (json.loads(_read(app_json)) or {}).get("expo") or {}
    except ValueError:
        return None
    out = []
    for entry in expo.get("plugins") or []:
        name = entry[0] if isinstance(entry, list) and entry else entry
        if isinstance(name, str):
            out.append(name)
    return out


def check_expo_no_scene_lifecycle(rule: dict, root: str, files: list[tuple[str, str]]) -> list[dict]:
    """Expo managed project where no registered config plugin adds the UIScene
    life cycle. Reported against app.json because ios/ is generated; a committed
    ios/ (bare workflow) is covered by the native no-scene-delegate rule.
    """
    if not is_expo_project(root):
        return []
    if "ios" not in expo_generated_dirs(root) and os.path.isdir(os.path.join(root, "ios")):
        return []
    plugins = _expo_config_plugins(root)
    if plugins is None:
        # app.config.ts/js: settle for a textual search of the config and plugins
        for p, lang in files:
            if lang in ("js", "ts") and not p.startswith("Fixed/") and _EXPO_SCENE_RE.search(_read(os.path.join(root, p))):
                return []
    else:
        for name in plugins:
            if re.search(r"scene", name, re.I):
                return []
            if name.startswith("."):
                for cand in (name, name + ".js", name + ".ts", name + ".mjs", os.path.join(name, "index.js")):
                    full = os.path.join(root, cand)
                    if os.path.isfile(full) and _EXPO_SCENE_RE.search(_read(full)):
                        return []
    cfg = next((n for n in ("app.json", "app.config.ts", "app.config.js", "app.config.mjs") if os.path.exists(os.path.join(root, n))), "app.json")
    raw = _read(os.path.join(root, cfg))
    line = _line_of(raw, '"expo"') if '"expo"' in raw else 1
    return [finding(rule, cfg, line, 1, "no config plugin adds UIApplicationSceneManifest and a SceneDelegate (launch blocker on the iOS 27 SDK)")]


PROJECT_CHECKS = {"no_scene_delegate": check_no_scene_delegate, "expo_no_scene_lifecycle": check_expo_no_scene_lifecycle}

# ---------------------------------------------------------------------------
# Walking and matching
# ---------------------------------------------------------------------------


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def walk(root: str) -> list[tuple[str, str]]:
    out = []
    generated = expo_generated_dirs(root)
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        skip = SKIP_DIRS | (generated if os.path.abspath(dirpath) == root_abs else set())
        dirnames[:] = sorted(d for d in dirnames if d not in skip and not d.endswith((".xcodeproj", ".xcworkspace", ".xcassets")))
        for fn in sorted(filenames):
            ext = os.path.splitext(fn)[1].lower()
            lang = EXT_LANG.get(ext)
            if not lang:
                continue
            if lang == "json" and fn not in ("app.json", "app.config.json", "package.json"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/")
            if lang in ("js", "ts") and TEST_FILE_RE.search(rel):
                continue
            out.append((rel, lang))
    return out


def scan_file(rules: list[dict], root: str, rel: str, lang: str) -> list[dict]:
    raw = _read(os.path.join(root, rel))
    if not raw:
        return []
    stripped = strip_code(raw, lang)
    raw_lines = raw.splitlines()
    stripped_lines = stripped.splitlines()
    out: list[dict] = []
    for rule in rules:
        if lang not in rule["lang"]:
            continue
        kind = rule["kind"]
        if kind == "file":
            fn = FILE_CHECKS.get(rule.get("check", ""))
            if fn:
                out.extend(fn(rule, rel, raw, stripped))
            continue
        if kind == "project":
            continue
        rx = rule.get("_re")
        if rx is None:
            continue
        subject_text = raw if rule["raw"] else stripped
        if kind == "multiline":
            for m in rx.finditer(subject_text):
                if "_exclude" in rule and rule["_exclude"].search(m.group(0)):
                    continue
                line = subject_text.count("\n", 0, m.start()) + 1
                col = m.start() - (subject_text.rfind("\n", 0, m.start()) + 1) + 1
                out.append(finding(rule, rel, line, col, raw_lines[line - 1] if line - 1 < len(raw_lines) else m.group(0)))
            continue
        subject_lines = raw_lines if rule["raw"] else stripped_lines
        for i, ln in enumerate(subject_lines):
            m = rx.search(ln)
            if not m:
                continue
            if "_exclude" in rule and rule["_exclude"].search(ln if rule["raw"] else raw_lines[i]):
                continue
            out.append(finding(rule, rel, i + 1, m.start() + 1, raw_lines[i]))
    return out


def scan(root: str, rules: list[dict]) -> list[dict]:
    files = walk(root)
    findings: list[dict] = []
    for rel, lang in files:
        findings.extend(scan_file(rules, root, rel, lang))
    for rule in rules:
        if rule["kind"] == "project":
            fn = PROJECT_CHECKS.get(rule.get("check", ""))
            if fn:
                findings.extend(fn(rule, root, files))
    findings.sort(key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), f["rule"], f["file"], f["line"]))
    return findings


def summarize(findings: list[dict]) -> dict:
    s = {"error": 0, "warn": 0, "info": 0, "autofixable": 0}
    for f in findings:
        s[f["severity"]] = s.get(f["severity"], 0) + 1
        if f["autofix"]:
            s["autofixable"] += 1
    return s


def build_report(root: str, findings: list[dict], stack: str) -> dict:
    return {
        "schema": SCHEMA,
        "generated": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "root": os.path.abspath(root).replace(os.sep, "/"),
        "stack": stack,
        "findings": findings,
        "summary": summarize(findings),
    }


def print_table(findings: list[dict]) -> None:
    if not findings:
        print("duo scan: no findings")
        return
    by_rule: dict[str, list[dict]] = {}
    for f in findings:
        by_rule.setdefault(f["rule"], []).append(f)
    s = summarize(findings)
    print(f"duo scan: {len(findings)} findings  (error {s['error']}, warn {s['warn']}, info {s['info']}; autofixable {s['autofixable']})")
    print()
    for rule_id, items in by_rule.items():
        head = items[0]
        tag = "autofix" if head["autofix"] else "manual"
        print(f"[{head['severity']:5}] {rule_id}  ({len(items)} site{'s' if len(items) != 1 else ''}, {tag})")
        print(f"        {head['fix_hint']}")
        for f in items:
            print(f"        {f['file']}:{f['line']}  {f['match']}")
        print()


# ---------------------------------------------------------------------------
# Fix
# ---------------------------------------------------------------------------


def _git(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True)


def git_dirty(root: str) -> bool | None:
    r = _git(root, "status", "--porcelain")
    if r.returncode != 0:
        return None
    return bool(r.stdout.strip())


def _rewrite_text(rule: dict, raw: str, lang: str) -> str:
    """Apply one rule's literal replacement to file text; returns the text unchanged if nothing matched."""
    stripped = strip_code(raw, lang)
    new_lines = []
    for raw_ln, st_ln in zip(raw.splitlines(keepends=True), stripped.splitlines(keepends=True)):
        subject = raw_ln if rule["raw"] else st_ln
        if (
            rule["_re"].search(subject)
            and not ("_exclude" in rule and rule["_exclude"].search(raw_ln))
            and not ("_fix_exclude" in rule and rule["_fix_exclude"].search(raw_ln))
        ):
            # replace matched spans using positions from the subject line
            pieces, last = [], 0
            for m in rule["_re"].finditer(subject):
                pieces.append(raw_ln[last:m.start()])
                pieces.append(rule["replace"])
                last = m.end()
            pieces.append(raw_ln[last:])
            new_lines.append("".join(pieces))
        else:
            new_lines.append(raw_ln)
    return "".join(new_lines)


def compute_fixes(root: str, rules: list[dict], findings: list[dict]) -> dict[str, dict[str, tuple[str, str]]]:
    """Return {rule_id: {rel_path: (old_text, new_text)}} for autofixable rules.

    Each entry is computed against the file as it is on disk now, so the dry-run
    diff is per rule. apply_fixes re-reads the file before every rule so that two
    rules touching the same file compose instead of overwriting each other.
    """
    by_id = {r["id"]: r for r in rules}
    plan: dict[str, dict[str, tuple[str, str]]] = {}
    files_by_rule: dict[str, set[str]] = {}
    for f in findings:
        rule = by_id.get(f["rule"])
        if rule and rule.get("autofix") and rule.get("replace") and rule.get("_re"):
            files_by_rule.setdefault(rule["id"], set()).add(f["file"])
    for rule_id, files in files_by_rule.items():
        rule = by_id[rule_id]
        for rel in sorted(files):
            raw = _read(os.path.join(root, rel))
            lang = EXT_LANG.get(os.path.splitext(rel)[1].lower(), "swift")
            new = _rewrite_text(rule, raw, lang)
            if new != raw:
                plan.setdefault(rule_id, {})[rel] = (raw, new)
    return plan


def unified(plan: dict[str, dict[str, tuple[str, str]]]) -> str:
    out = []
    for rule_id, files in plan.items():
        for rel, (old, new) in files.items():
            out.append("".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True),
                                                    fromfile=f"a/{rel}", tofile=f"b/{rel}", n=1)))
            out.append(f"# rule: {rule_id}\n")
    return "".join(out)


def apply_fixes(root: str, plan: dict[str, dict[str, tuple[str, str]]], commit: bool, rules: list[dict] | None = None) -> int:
    """Write the fixes rule by rule, re-reading each file first so rules compose.

    `plan` says which files each rule touches; the rewrite itself is recomputed
    from the current on-disk text when `rules` is given (the normal path).
    """
    by_id = {r["id"]: r for r in (rules or [])}
    sites = 0
    for rule_id, files in plan.items():
        changed = []
        rule_sites = 0
        for rel, (old, planned_new) in files.items():
            path = os.path.join(root, rel)
            current = _read(path)
            rule = by_id.get(rule_id)
            if rule is not None:
                lang = EXT_LANG.get(os.path.splitext(rel)[1].lower(), "swift")
                new = _rewrite_text(rule, current, lang)
            else:
                new = planned_new if current == old else current
            if new == current:
                continue
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new)
            changed.append(rel)
            n = sum(1 for a, b in zip(current.splitlines(), new.splitlines()) if a != b)
            rule_sites += n
            sites += n
        if commit and changed:
            _git(root, "add", "--", *changed)
            _git(root, "commit", "-q", "-m", f"duo: fix {rule_id} ({rule_sites} sites)")
    return sites


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="scan.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--rules", action="append", help="rule file(s); default: both catalogs")
    ap.add_argument("--stack", choices=["native", "rn", "all"], default="all")
    ap.add_argument("--json", action="store_true", help="print scan.json to stdout instead of the table")
    ap.add_argument("--out", help="where to write scan.json (default ROOT/.duo/scan.json)")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--fix", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="apply even if the git tree is dirty")
    ap.add_argument("--commit", action="store_true", help="one commit per rule after --apply")
    a = ap.parse_args(argv)

    root = a.root
    if not os.path.isdir(root):
        print(f"cannot run on this host: root not found: {root}", file=sys.stderr)
        return duolib.exit_codes.PREFLIGHT_FAIL
    rules = load_rules(a.rules, a.stack)
    findings = scan(root, rules)
    report = build_report(root, findings, a.stack)

    if a.fix:
        plan = compute_fixes(root, rules, findings)
        if not plan:
            print("duo fix: nothing autofixable")
            return 0
        if a.apply:
            dirty = git_dirty(root)
            if dirty and not a.force:
                print("duo fix: git tree is dirty; commit or stash first, or pass --force", file=sys.stderr)
                return duolib.exit_codes.PREFLIGHT_FAIL
            n = apply_fixes(root, plan, a.commit, rules)
            print(f"duo fix: applied {n} site(s) across {sum(len(v) for v in plan.values())} file(s) for rules: {', '.join(plan)}")
        else:
            sys.stdout.write(unified(plan))
        return 0

    if not a.no_write:
        out = a.out or os.path.join(root, ".duo", "scan.json")
        duolib.write_json(out, report)
    if a.json:
        print(json.dumps(report, indent=2))
    else:
        print_table(findings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
