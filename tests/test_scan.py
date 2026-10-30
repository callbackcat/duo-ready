"""Rule-engine tests. Every rule must fire on its tagged fixture line and stay
silent on the Fixed/ negatives. Runs on Windows, macOS and Linux."""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import scan  # noqa: E402

UIKIT = os.path.join(ROOT, "examples", "uikit-broken")
RN = os.path.join(ROOT, "examples", "rn-broken")
TAG_RE = re.compile(r"duo:\s*([a-z0-9-]+)")

# Expected findings in files that cannot carry comments (JSON): (relative file, rule, line-containing)
JSON_EXPECTED = {
    RN: [
        ("app.json", "rn-orientation-lock", '"orientation"'),
        ("app.json", "expo-no-scene-lifecycle", '"expo"'),
        ("package.json", "rn-sdk-floor", '"expo"'),
        ("package.json", "rn-sdk-floor", '"react-native-screens"'),
    ],
}


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _tagged(root):
    """Return {(rel, line): {rule ids}} from `duo: <rule>` tags in fixture files, excluding Fixed/."""
    tags = {}
    for rel, lang in scan.walk(root):
        if rel.startswith("Fixed/") or lang == "json":
            continue
        for i, ln in enumerate(_read(os.path.join(root, rel)).splitlines(), 1):
            ids = set(TAG_RE.findall(ln))
            if ids:
                tags[(rel, i)] = ids
    return tags


def _line_containing(root, rel, needle):
    for i, ln in enumerate(_read(os.path.join(root, rel)).splitlines(), 1):
        if needle in ln:
            return i
    raise AssertionError(f"{needle} not in {rel}")


@pytest.fixture(scope="module")
def rules():
    return scan.load_rules()


@pytest.fixture(scope="module")
def uikit_findings(rules):
    return scan.scan(UIKIT, rules)


@pytest.fixture(scope="module")
def rn_findings(rules):
    return scan.scan(RN, rules)


def test_catalogs_load(rules):
    ids = [r["id"] for r in rules]
    assert len(ids) == len(set(ids)), "duplicate rule ids"
    assert len(scan.load_rules(stack="native")) == 19
    assert len(scan.load_rules(stack="rn")) == 17
    for r in rules:
        assert r["severity"] in ("error", "warn", "info"), r["id"]
        assert r.get("fix_hint") and r.get("apple_ref") and r.get("doc"), r["id"]
        assert r["doc"].split("#")[1] == r["id"], r["id"]
        if r["kind"] in ("file", "project"):
            assert r.get("check") in (scan.FILE_CHECKS | scan.PROJECT_CHECKS), r["id"]
        else:
            assert "_re" in r, r["id"]


def _expected_and_actual(root, findings):
    expected = {}
    for (rel, line), ids in _tagged(root).items():
        for rid in ids:
            expected.setdefault(rid, set()).add((rel, line))
    for rel, rid, needle in JSON_EXPECTED.get(root, []):
        expected.setdefault(rid, set()).add((rel, _line_containing(root, rel, needle)))
    actual = {}
    for f in findings:
        actual.setdefault(f["rule"], set()).add((f["file"], f["line"]))
    return expected, actual


@pytest.mark.parametrize("root_name", ["uikit", "rn"])
def test_every_tagged_site_is_found(root_name, uikit_findings, rn_findings):
    root, findings = (UIKIT, uikit_findings) if root_name == "uikit" else (RN, rn_findings)
    expected, actual = _expected_and_actual(root, findings)
    missing = {rid: sites - actual.get(rid, set()) for rid, sites in expected.items()}
    missing = {k: v for k, v in missing.items() if v}
    assert not missing, f"tagged sites not reported: {missing}"


@pytest.mark.parametrize("root_name", ["uikit", "rn"])
def test_no_untagged_findings(root_name, uikit_findings, rn_findings):
    """Precision: every finding must sit on a tagged line (or be an expected JSON finding)."""
    root, findings = (UIKIT, uikit_findings) if root_name == "uikit" else (RN, rn_findings)
    expected, actual = _expected_and_actual(root, findings)
    extra = {rid: sites - expected.get(rid, set()) for rid, sites in actual.items()}
    extra = {k: v for k, v in extra.items() if v}
    assert not extra, f"findings on untagged lines (false positives): {extra}"


def test_every_rule_has_a_positive_fixture(rules, uikit_findings, rn_findings):
    fired = {f["rule"] for f in uikit_findings} | {f["rule"] for f in rn_findings}
    silent = [r["id"] for r in rules if r["id"] not in fired]
    assert not silent, f"rules with no positive fixture: {silent}"


@pytest.mark.parametrize("fixed", [os.path.join(UIKIT, "Fixed"), os.path.join(RN, "Fixed")])
def test_fixed_fixtures_are_clean(rules, fixed):
    findings = scan.scan(fixed, rules)
    assert findings == [], [(f["rule"], f["file"], f["line"], f["match"]) for f in findings]


def test_lexer_strips_comments_and_strings():
    src = 'let a = UIScreen.main.bounds // UIScreen.main.bounds in comment\nlet s = "UIScreen.main.bounds"\n/* UIScreen.main.bounds\n */ let b = 1\n'
    out = scan.strip_code(src, "swift")
    assert out.count("UIScreen.main.bounds") == 1
    assert len(out) == len(src)
    assert out.count("\n") == src.count("\n")
    js = "const x = `UIScreen ${y}`; // c\nconst z = 'Dimensions.get';\n"
    outjs = scan.strip_code(js, "js")
    assert "Dimensions" not in outjs and "UIScreen" not in outjs
    assert len(outjs) == len(js)


def test_scan_json_schema(tmp_path, rules):
    out = tmp_path / "scan.json"
    rc = scan.main([UIKIT, "--out", str(out)])
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == 1
    assert set(doc["summary"]) == {"error", "warn", "info", "autofixable"}
    f = doc["findings"][0]
    assert set(f) >= {"rule", "severity", "autofix", "file", "line", "column", "match", "fix_hint", "apple_ref"}
    assert "\\" not in f["file"]
    sev = [scan.SEVERITY_ORDER[x["severity"]] for x in doc["findings"]]
    assert sev == sorted(sev)


def test_autofix_dry_run_diff(tmp_path, rules):
    work = tmp_path / "proj"
    shutil.copytree(UIKIT, work)
    findings = scan.scan(str(work), rules)
    plan = scan.compute_fixes(str(work), rules, findings)
    assert set(plan) == {"screen-main-bounds", "screen-main-scale"}
    diff = scan.unified(plan)
    # UIWindow(frame: UIScreen.main.bounds) is reported but never rewritten to view.bounds:
    # an AppDelegate has no `view`, and window-frame-init already prescribes UIWindow(windowScene:)
    assert "UIWindow(frame: view.bounds)" not in diff
    assert "-        return UIScreen.main.bounds.width / 2" in diff
    assert "+        return view.bounds.width / 2" in diff
    assert "traitCollection.displayScale" in diff
    # dry run does not touch files
    assert "UIScreen.main.scale" in _read(str(work / "FeedViewController.swift"))


def test_autofix_apply_refuses_dirty_tree_and_applies_with_force(tmp_path, rules):
    if not shutil.which("git"):
        pytest.skip("git not available")
    work = tmp_path / "proj"
    shutil.copytree(UIKIT, work)
    subprocess.run(["git", "init", "-q"], cwd=work, check=True)
    rc = scan.main([str(work), "--fix", "--apply", "--no-write"])
    assert rc == 4  # dirty (untracked) tree refused
    rc = scan.main([str(work), "--fix", "--apply", "--force", "--no-write"])
    assert rc == 0
    src = _read(str(work / "FeedViewController.swift"))
    assert "UIScreen.main.scale" not in src and "traitCollection.displayScale" in src
    # the UIWindow(frame:) site is deliberately left for the manual window-frame-init fix
    assert "UIWindow(frame: UIScreen.main.bounds)" in _read(str(work / "AppDelegate.swift"))
    assert "UIScreen.main.bounds" not in _read(str(work / "FeedViewController.swift"))


def test_cli_table_and_stack_filter(capsys):
    rc = scan.main([RN, "--stack", "native", "--no-write"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "rn-" not in out
    rc = scan.main([RN, "--stack", "rn", "--no-write"])
    out = capsys.readouterr().out
    assert "rn-dimensions-module-scope" in out and "findings" in out


def _write(root, rel, text):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)


def test_expo_generated_ios_is_skipped_only_when_gitignored(tmp_path, rules):
    """expo prebuild regenerates ios/; findings there cannot be committed, so a
    managed project's ignored ios/ is not scanned (field test: 4 of 26 findings)."""
    root = str(tmp_path)
    _write(root, "app.json", '{"expo": {"name": "x", "orientation": "default", "plugins": ["./plugins/withScene.js"]}}')
    _write(root, "plugins/withScene.js", "// UIApplicationSceneManifest\n")
    _write(root, "ios/App/AppDelegate.swift", "let w = UIWindow(frame: UIScreen.main.bounds)\n")
    _write(root, ".gitignore", "node_modules/\nios/\nandroid/\n")
    assert scan.scan(root, rules) == []
    os.remove(os.path.join(root, ".gitignore"))
    found = {f["rule"] for f in scan.scan(root, rules)}
    assert "screen-main-bounds" in found


def test_expo_scene_lifecycle_needs_a_registered_plugin(tmp_path, rules):
    root = str(tmp_path)
    _write(root, "app.json", '{"expo": {"name": "x", "orientation": "default"}}')
    _write(root, "plugins/withScene.js", "// UIApplicationSceneManifest, but not registered in app.json\n")
    found = [f for f in scan.scan(root, rules) if f["rule"] == "expo-no-scene-lifecycle"]
    assert len(found) == 1 and found[0]["severity"] == "error" and found[0]["file"] == "app.json"
    _write(root, "app.json", '{"expo": {"name": "x", "orientation": "default", "plugins": [["./plugins/withScene", {}]]}}')
    assert [f for f in scan.scan(root, rules) if f["rule"] == "expo-no-scene-lifecycle"] == []


def test_expo_scene_plugin_name_is_not_trusted(tmp_path, rules):
    """A registered local plugin named withScene*.js that does not add the scene
    manifest is still a finding (field test 2); a package name is all
    there is to go on for node_modules plugins."""
    root = str(tmp_path)
    _write(root, "app.json", '{"expo": {"name": "x", "orientation": "default", "plugins": ["./plugins/withSceneLifecycle.js"]}}')
    _write(root, "plugins/withSceneLifecycle.js", "// placeholder, does nothing yet\nmodule.exports = (c) => c;\n")
    assert len([f for f in scan.scan(root, rules) if f["rule"] == "expo-no-scene-lifecycle"]) == 1
    _write(root, "plugins/withSceneLifecycle.js", "// adds UIApplicationSceneManifest\n")
    assert [f for f in scan.scan(root, rules) if f["rule"] == "expo-no-scene-lifecycle"] == []
    _write(root, "app.json", '{"expo": {"name": "x", "orientation": "default", "plugins": ["expo-scene-lifecycle"]}}')
    assert [f for f in scan.scan(root, rules) if f["rule"] == "expo-no-scene-lifecycle"] == []


def test_rn_adjusts_font_checks_every_style_in_an_array(tmp_path, rules):
    root = str(tmp_path)
    _write(root, "package.json", '{"dependencies": {"react-native": "0.81.0"}}')
    src = (
        "import { StyleSheet, Text } from 'react-native';\n"
        "export function A() { return <Text adjustsFontSizeToFit numberOfLines={1} style={[styles.base, styles.title]}>a</Text>; }\n"
        "export function B() { return <Text adjustsFontSizeToFit numberOfLines={1} style={[styles.base, styles.plain]}>b</Text>; }\n"
        "const styles = StyleSheet.create({ base: { color: 'red' }, title: { fontSize: 20, lineHeight: 24 }, plain: { fontSize: 20 } });\n"
    )
    _write(root, "src/Hero.tsx", src)
    found = [f for f in scan.scan(root, rules) if f["rule"] == "rn-adjusts-font-fixed-lineheight"]
    assert [f["line"] for f in found] == [2]


def test_test_files_are_not_scanned(tmp_path, rules):
    root = str(tmp_path)
    _write(root, "src/__tests__/a.test.tsx", "const { width } = Dimensions.get('window');\n")
    _write(root, "src/b.spec.ts", "const { width } = Dimensions.get('window');\n")
    _write(root, "src/c.ts", "const { width } = Dimensions.get('window');\n")
    files = [f["file"] for f in scan.scan(root, rules) if f["rule"] == "rn-dimensions-module-scope"]
    assert files == ["src/c.ts"]
