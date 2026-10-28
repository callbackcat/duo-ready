"""tree.py: the AXe (`duoctl elements`) normaliser, on raw output recorded on the
second field test (anonymised: app and screen names replaced, geometry kept)."""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import tree  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures", "axe")


def _load(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


def test_from_axe_maps_fields_and_marks_interactive_by_type():
    raw = _load("duoctl-elements-feed-closed-portrait.json")
    doc = tree.from_axe(raw, udid="X")
    assert doc["source"] == "duoctl elements" and doc["ancestry"] is False and doc["udid"] == "X"
    by_id = {e["id"]: e for e in doc["elements"]}
    assert by_id["home-profile"]["type"] == "Button" and by_id["home-profile"]["interactive"] is True
    assert by_id["Add a task"]["type"] == "TextField" and by_id["Add a task"]["interactive"] is True
    assert by_id["Demo"]["type"] == "Application" and by_id["Demo"]["interactive"] is False
    assert by_id["home-profile"]["frame"] == [318.0, 6.0, 40.0, 40.0]


def test_from_axe_drops_duplicate_static_texts():
    raw = _load("duoctl-elements-feed-closed-portrait.json")
    dup = sum(1 for e in raw if e["type"] == "StaticText" and e["label"] == "TASKS")
    assert dup == 2  # AXe lists every StaticText twice
    doc = tree.from_axe(raw)
    assert sum(1 for e in doc["elements"] if e["id"] == "TASKS") == 1


def test_from_axe_accepts_list_frames_and_dict_wrapper():
    doc = tree.from_axe({"elements": [{"type": "button", "label": "Go", "frame": [1, 2, 44, 44]}]})
    assert doc["elements"][0]["frame"] == [1.0, 2.0, 44.0, 44.0] and doc["elements"][0]["interactive"]


def test_cli_writes_tree(tmp_path):
    out = tmp_path / "x.tree.json"
    r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "tree.py"), "from-axe",
                        os.path.join(FIX, "duoctl-elements-feed-closed-portrait.json"), str(out), "--udid", "U", "--driver", "run-matrix"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["driver"] == "run-matrix" and len(doc["elements"]) > 10
