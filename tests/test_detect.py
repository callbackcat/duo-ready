import json
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import detect  # noqa: E402
import duolib  # noqa: E402

UIKIT = os.path.join(ROOT, "examples", "uikit-broken")
RN = os.path.join(ROOT, "examples", "rn-broken")


def test_detect_uikit_fixture():
    env, doc = detect.detect(UIKIT)
    assert env["stack"] == "mixed"  # UIKit controllers plus a SwiftUI view
    assert env["bundle_id"] == "com.example.duobroken"
    assert env["scheme"] == "DuoBroken"
    assert env["xcode_container"]["project"] == "DuoBroken.xcodeproj"
    locks = [l for l in env["orientation_locks"] if l["kind"] == "plist"]
    assert len(locks) == 1 and locks[0]["file"] == "Info.plist"
    assert env["test_tooling"] == []
    assert env["store_tooling"] == []
    assert doc["stack"] == "mixed" and doc["bundle_id"] == "com.example.duobroken"
    assert doc["cells"] == detect.DEFAULT_CELLS
    assert doc["perf"]["launch_ms"] == {"warn": 800, "fail": 1500}


def test_detect_rn_fixture():
    env, doc = detect.detect(RN)
    assert env["stack"] == "expo"
    assert env["bundle_id"] == "com.example.duobrokenrn"
    assert env["scheme"] == "DuoBrokenRN"
    kinds = {l["kind"] for l in env["orientation_locks"]}
    assert {"expo", "runtime"} <= kinds
    assert env["expo_sdk"] == "~52.0.0"


def test_host_facts_present_without_xcode():
    env, _ = detect.detect(RN)
    h = env["host"]
    assert "xcode_ok" in h and "duoctl" in h and "hinge" in h
    if not shutil.which("xcodebuild"):
        assert h["xcode_ok"] is False and h["duo_runtime"] is False


def test_cli_writes_env_and_yaml_once(tmp_path):
    work = tmp_path / "proj"
    shutil.copytree(RN, work)
    assert detect.main([str(work)]) == 0
    env = json.loads((work / ".duo" / "env.json").read_text(encoding="utf-8"))
    assert env["stack"] == "expo"
    y = work / "duo.yaml"
    first = y.read_text(encoding="utf-8")
    parsed = duolib.load_yaml(str(y))
    assert parsed["bundle_id"] == "com.example.duobrokenrn"
    assert parsed["flows"][0]["name"] == "launch"
    y.write_text(first + "\n# user edit\n", encoding="utf-8")
    assert detect.main([str(work)]) == 0
    assert "# user edit" in y.read_text(encoding="utf-8")  # not overwritten
    assert detect.main([str(work), "--force"]) == 0
    assert "# user edit" not in y.read_text(encoding="utf-8")
