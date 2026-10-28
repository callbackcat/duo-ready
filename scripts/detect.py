#!/usr/bin/env python3
"""duo-ready detect: inspect a repo and scaffold duo.yaml + .duo/env.json.

Usage:
  detect.py [ROOT] [--json] [--force] [--no-write]

Detects the stack (uikit | swiftui | mixed | react-native | expo | flutter |
capacitor), scheme, bundle id, orientation locks, test tooling and store
tooling. Host facts (Xcode, runtimes) are collected only when xcodebuild exists.
Never overwrites an existing duo.yaml unless --force. Standard library only.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import duolib  # noqa: E402

SKIP = {"node_modules", "Pods", ".git", "build", "DerivedData", ".build", ".duo", "android"}

DEFAULT_CELLS = ["closed-portrait", "closed-landscape", "open-landscape", "open-portrait", "book-landscape", "book-portrait"]
DEFAULT_TRANSITIONS = ["closed>open", "open>book", "open>closed"]


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return ""


def _read(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _find(root: str, patterns: list[str], maxdepth: int = 4) -> list[str]:
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        depth = os.path.relpath(dirpath, root).count(os.sep)
        dirnames[:] = [d for d in dirnames if d not in SKIP and depth < maxdepth]
        for pat in patterns:
            for fn in filenames + dirnames:
                if glob.fnmatch.fnmatch(fn, pat):
                    hits.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, "/"))
    return sorted(set(hits))


def detect_stack(root: str, pkg: dict | None) -> str:
    deps = {}
    if pkg:
        for k in ("dependencies", "devDependencies"):
            deps.update(pkg.get(k, {}) or {})
    if _find(root, ["pubspec.yaml"], 2):
        return "flutter"
    if _find(root, ["capacitor.config.*"], 2) or "@capacitor/core" in deps:
        return "capacitor"
    if "expo" in deps:
        return "expo"
    if "react-native" in deps:
        return "react-native"
    swift_files = _find(root, ["*.swift"], 6)
    uikit = swiftui = False
    for rel in swift_files[:400]:
        src = _read(os.path.join(root, rel))
        if re.search(r"\bimport SwiftUI\b|:\s*View\s*\{|\bsome View\b", src):
            swiftui = True
        if re.search(r"\bimport UIKit\b|UIViewController\b", src):
            uikit = True
    if uikit and swiftui:
        return "mixed"
    if swiftui:
        return "swiftui"
    if uikit or _find(root, ["*.xcodeproj", "*.m"], 3):
        return "uikit"
    return "unknown"


def detect_bundle_and_scheme(root: str, app_json: dict | None) -> tuple[str | None, str | None, dict]:
    bundle = scheme = None
    proj: dict = {}
    pbx = _find(root, ["project.pbxproj"], 5)
    pbx = [p for p in pbx if ".xcodeproj/" in p]
    workspaces = [w for w in _find(root, ["*.xcworkspace"], 3) if "/project.xcworkspace" not in w and not w.endswith(".xcodeproj/project.xcworkspace")]
    projects = [p for p in _find(root, ["*.xcodeproj"], 3)]
    if workspaces:
        proj["workspace"] = workspaces[0]
    if projects:
        proj["project"] = projects[0]
        scheme = os.path.splitext(os.path.basename(projects[0]))[0]
    for p in pbx:
        src = _read(os.path.join(root, p))
        m = re.search(r"PRODUCT_BUNDLE_IDENTIFIER\s*=\s*\"?([\w.\-]+)\"?;", src)
        if m and "$(" not in m.group(1):
            bundle = m.group(1)
            break
    if app_json:
        expo = app_json.get("expo", app_json)
        bundle = bundle or (expo.get("ios") or {}).get("bundleIdentifier")
        scheme = scheme or expo.get("name") or expo.get("slug")
    return bundle, scheme, proj


def detect_orientation_locks(root: str, app_json: dict | None) -> list[dict]:
    locks: list[dict] = []
    for rel in _find(root, ["Info.plist"], 5):
        if "/Pods/" in rel or "Tests" in rel:
            continue
        try:
            data = plistlib.loads(_read(os.path.join(root, rel)).encode("utf-8"))
        except Exception:
            continue
        for key in ("UISupportedInterfaceOrientations", "UISupportedInterfaceOrientations~iphone"):
            vals = data.get(key)
            if isinstance(vals, list) and vals and not any("Landscape" in v for v in vals):
                locks.append({"file": rel, "kind": "plist", "key": key, "value": vals})
    if app_json:
        expo = app_json.get("expo", app_json)
        if expo.get("orientation") in ("portrait", "landscape"):
            locks.append({"file": "app.json", "kind": "expo", "key": "orientation", "value": expo["orientation"]})
    for rel in _find(root, ["*.js", "*.jsx", "*.ts", "*.tsx"], 6):
        src = _read(os.path.join(root, rel))
        if re.search(r"ScreenOrientation\.lockAsync|lockToPortrait|lockToLandscape|Orientation\.lockTo", src):
            locks.append({"file": rel, "kind": "runtime", "key": "orientation-lock-call", "value": None})
    return locks


def detect_tests(root: str) -> list[str]:
    found = []
    for rel in _find(root, ["*.swift"], 6):
        if "UITests" in rel and "XCTest" in _read(os.path.join(root, rel)):
            found.append("xcuitest")
            break
    if _find(root, [".maestro"], 2) or _find(root, ["*.maestro.yaml", "*.maestro.yml"], 3):
        found.append("maestro")
    if _find(root, [".detoxrc*", "detox.config.*"], 2):
        found.append("detox")
    return found


def detect_store_tooling(root: str) -> list[str]:
    tools = []
    if _find(root, ["fastlane"], 2):
        tools.append("fastlane")
    if _find(root, ["eas.json"], 2):
        tools.append("eas")
    return tools


def host_facts() -> dict:
    facts: dict = {"os": platform.system(), "os_version": platform.version(), "python": platform.python_version()}
    if shutil.which("xcodebuild"):
        out = _run(["xcodebuild", "-version"])
        m = re.search(r"Xcode\s+([\d.]+)", out)
        facts["xcode"] = m.group(1) if m else None
        facts["xcode_ok"] = bool(m and tuple(int(x) for x in m.group(1).split(".")[:2]) >= (27, 1))
        runtimes = _run(["xcrun", "simctl", "list", "runtimes", "-j"])
        facts["duo_runtime"] = "iOS-27-1" in runtimes or "iOS 27.1" in runtimes
    else:
        facts["xcode"] = None
        facts["xcode_ok"] = False
        facts["duo_runtime"] = False
    for tool in ("duoctl", "hinge", "fastlane", "maestro", "xcrun", "axe", "asc"):
        facts[tool] = bool(shutil.which(tool))
    return facts


def scaffold_duo_yaml(stack: str, scheme: str | None, bundle: str | None, proj: dict, flows_hint: bool) -> dict:
    doc: dict = {
        "stack": stack,
        "scheme": scheme or "YourScheme",
        "bundle_id": bundle or "com.example.app",
    }
    if proj.get("workspace"):
        doc["workspace"] = proj["workspace"]
    elif proj.get("project"):
        doc["project"] = proj["project"]
    doc.update({
        "cells": list(DEFAULT_CELLS),
        "transitions": list(DEFAULT_TRANSITIONS),
        "flows": [
            # placeholder: a launch-only flow shows whatever screen the app restores,
            # so SKILL.md asks for real flows while this flag is present
            {"name": "launch", "steps": ["launch", "sleep 2"], "placeholder": True},
        ],
        "assert": {
            "offscreen_elements": "fail",
            "clipped_text": "fail",
            "tap_target_min": 44,
            "bars_vertical_expected": "warn",
            "content_under_outer_camera": "fail",
            "interactive_in_fold": "fail",
            "visual_diff_threshold": 0.02,
        },
        "perf": {
            "mode": "regression",
            "launch_ms": {"warn": 800, "fail": 1500},
            "fold_relayout_ms": {"fail": 250},
            "memory_delta_mb": {"warn": 30},
        },
        "loop": {"max_iterations": 3},
        "assets": {"locales": ["en-US"], "output": "fastlane/screenshots"},
    })
    return doc


def detect(root: str) -> tuple[dict, dict]:
    pkg = None
    app_json = None
    if os.path.exists(os.path.join(root, "package.json")):
        try:
            pkg = json.loads(_read(os.path.join(root, "package.json")))
        except Exception:
            pkg = None
    for name in ("app.json", "app.config.json"):
        if os.path.exists(os.path.join(root, name)):
            try:
                app_json = json.loads(_read(os.path.join(root, name)))
            except Exception:
                app_json = None
            break
    stack = detect_stack(root, pkg)
    bundle, scheme, proj = detect_bundle_and_scheme(root, app_json)
    env = {
        "schema": 1,
        "root": os.path.abspath(root).replace(os.sep, "/"),
        "stack": stack,
        "scheme": scheme,
        "bundle_id": bundle,
        "xcode_container": proj,
        "orientation_locks": detect_orientation_locks(root, app_json),
        "test_tooling": detect_tests(root),
        "store_tooling": detect_store_tooling(root),
        "expo_sdk": (pkg or {}).get("dependencies", {}).get("expo") if pkg else None,
        "host": host_facts(),
    }
    doc = scaffold_duo_yaml(stack, scheme, bundle, proj, flows_hint=True)
    return env, doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="detect.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite an existing duo.yaml")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    if not os.path.isdir(a.root):
        print(f"cannot run on this host: root not found: {a.root}", file=sys.stderr)
        return duolib.exit_codes.PREFLIGHT_FAIL
    env, doc = detect(a.root)
    yaml_path = os.path.join(a.root, "duo.yaml")
    wrote_yaml = False
    if not a.no_write:
        duolib.write_json(os.path.join(a.root, ".duo", "env.json"), env)
        if a.force or not os.path.exists(yaml_path):
            with open(yaml_path, "w", encoding="utf-8") as f:
                f.write("# duo-ready configuration. Generated by detect.py; edit freely.\n")
                f.write("# See references/pipeline-contracts.md for every key.\n")
                f.write(duolib.dump_yaml(doc) + "\n")
            wrote_yaml = True
    if a.json:
        print(json.dumps({"env": env, "duo_yaml": doc, "wrote_duo_yaml": wrote_yaml}, indent=2))
    else:
        print(f"stack: {env['stack']}   scheme: {env['scheme']}   bundle id: {env['bundle_id']}")
        if env["xcode_container"]:
            print(f"xcode: {env['xcode_container']}")
        print(f"orientation locks: {len(env['orientation_locks'])}   tests: {env['test_tooling'] or 'none'}   store: {env['store_tooling'] or 'none'}")
        h = env["host"]
        print(f"host: {h['os']}  xcode {h.get('xcode') or 'missing'} ({'ok' if h.get('xcode_ok') else 'need 27.1+'})  duo runtime {'yes' if h.get('duo_runtime') else 'no'}  duoctl {'yes' if h.get('duoctl') else 'no'}  hinge {'yes' if h.get('hinge') else 'no'}")
        if not a.no_write:
            print(f"wrote .duo/env.json{' and duo.yaml' if wrote_yaml else ' (duo.yaml exists; use --force to overwrite)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
