import json
import os
import sys

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS)
import duolib  # noqa: E402
import loop  # noqa: E402
import pngio  # noqa: E402
import report  # noqa: E402


def seed(root, run=1, with_ui=True, with_perf=True, ui_fail=True, perf_fail=False):
    rdir = os.path.join(root, ".duo", "runs", str(run))
    cap = os.path.join(rdir, "captures")
    os.makedirs(cap, exist_ok=True)
    shot = os.path.join(cap, "feed-book-landscape.png")
    pngio.write(shot, 30, 21, 3, pngio.solid(30, 21, (200, 200, 200)))
    duolib.write_json(os.path.join(rdir, "build.json"), {"sdk_stamp": "27.1", "scheme": "DemoApp", "skipped": ["perf: xctrace not installed"]})
    if with_ui:
        duolib.write_json(os.path.join(rdir, "ui.json"), {
            "schema": 1, "run": run, "sdk_stamp": "27.1", "sdk_tier": "27.1",
            "cells": [
                {"flow": "feed", "cell": "book-landscape", "screenshot": ".duo/runs/%d/captures/feed-book-landscape.png" % run,
                 "tree": "x", "window": [951, 669],
                 "results": [{"assertion": "offscreen_elements", "status": "pass"},
                             {"assertion": "interactive_in_fold", "status": "fail" if ui_fail else "pass",
                              "elements": [{"id": "PlayButton", "frame": [440, 300, 60, 44]}]}]},
                {"flow": "feed", "cell": "closed-portrait", "screenshot": None, "tree": "y", "window": [466, 678],
                 "results": [{"assertion": "offscreen_elements", "status": "pass"}, {"assertion": "visual_diff", "status": "skip", "reason": "no baseline"}]},
            ],
            "summary": {},
        })
        failures = [{
            "flow": "feed", "cell": "book-landscape", "assertion": "interactive_in_fold", "status": "fail",
            "elements": [{"id": "PlayButton", "frame": [440, 300, 60, 44]}],
            "screenshot": ".duo/runs/%d/captures/feed-book-landscape.png" % run,
            "matched_rule": "centered-grid-odd-columns", "source_hint": "Sources/PlayerView.swift:88",
            "fix_hint": "Keep interactive elements out of the fold.",
        }] if ui_fail else []
        duolib.write_json(os.path.join(rdir, "failures.json"), failures)
    if with_perf:
        duolib.write_json(os.path.join(rdir, "perf.json"), {"schema": 1, "run": run, "mode": "regression", "metrics": [
            {"flow": "feed", "cell": "closed-portrait", "metric": "launch_ms", "value": 612, "baseline": 590, "status": "pass"},
            {"flow": "feed", "cell": "closed>open", "metric": "fold_relayout_ms", "value": 310, "baseline": None, "status": "fail" if perf_fail else "pass"},
        ]})
    duolib.write_json(os.path.join(root, ".duo", "scan.json"), {"findings": [
        {"rule": "screen-main-bounds", "severity": "error", "autofix": True, "file": "Sources/App.swift", "line": 4},
        {"rule": "screen-main-bounds", "severity": "error", "autofix": True, "file": "Sources/B.swift", "line": 9},
        {"rule": "fill-media", "severity": "warn", "autofix": False, "file": "Sources/Hero.swift", "line": 12},
    ]})
    with open(os.path.join(root, "duo.yaml"), "w") as fh:
        fh.write("scheme: DemoApp\ncells: [closed-portrait, book-landscape]\ntransitions: [\"closed>open\"]\nloop:\n  max_iterations: 2\n")
    return rdir


def test_report_sections_and_exit_codes(tmp_path, capsys):
    root = str(tmp_path)
    rdir = seed(root)
    code = report.main(["--run", "1", "--root", root, "--json"])
    assert code == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["overall"] == "fail" and summary["failures"] == 1
    html_path = os.path.join(rdir, "duo-report.html")
    assert os.path.exists(html_path)
    text = open(html_path, encoding="utf-8").read()
    for needle in ("Pose matrix", "Failures", "Performance", "Scan findings", "Unverified or skipped stages",
                   "April 2027", "iOS 27.1 SDK or later", "data:image/png;base64,", "<svg", "<rect", "PlayButton",
                   "centered-grid-odd-columns", "fold_relayout_ms", "screen-main-bounds", "xctrace not installed",
                   "DemoApp", "closed-portrait", "book-landscape"):
        assert needle in text, needle
    assert "<link" not in text and "<script src" not in text  # self-contained
    assert "visual diff: no baselines" in text


def test_report_perf_fail_exit_2_and_skipped_stages(tmp_path):
    root = str(tmp_path)
    seed(root, run=2, ui_fail=False, perf_fail=True)
    assert report.main(["--run", "2", "--root", root]) == 2
    seed(root, run=3, with_ui=False, with_perf=False)
    # nothing measured is not a pass: exit 1 so a CI gate cannot read it as green
    assert report.main(["--run", "3", "--root", root]) == 1
    text = open(os.path.join(root, ".duo", "runs", "3", "duo-report.html"), encoding="utf-8").read()
    assert "no ui.json" in text and "no perf.json" in text


def test_loop_iterations_cap_and_todo(tmp_path, capsys):
    root = str(tmp_path)
    seed(root)
    # iteration 1: payloads emitted, exit 1
    assert loop.main(["--run", "1", "--root", root]) == 1
    out = capsys.readouterr()
    payload = json.loads(out.out.strip().splitlines()[0])
    assert payload["assertion"] == "interactive_in_fold"
    assert "--flows feed --cells book-landscape" in out.err
    # iteration 2 (cap from duo.yaml is 2)
    assert loop.main(["--run", "1", "--root", root, "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["iteration"] == 2 and data["rerun"] == "--flows feed --cells book-landscape"
    # iteration 3: cap reached -> DUO-TODO.md
    assert loop.main(["--run", "1", "--root", root]) == 0
    todo = os.path.join(root, "DUO-TODO.md")
    assert os.path.exists(todo)
    body = open(todo, encoding="utf-8").read()
    assert "interactive_in_fold" in body and "Keep interactive elements out of the fold." in body and "PlayerView.swift:88" in body
    assert "April 2027" in body and "iOS 27.1 SDK or later" in body
    capsys.readouterr()
    # mark-fixed records the commit format
    assert loop.main(["--mark-fixed", "screen-main-bounds", "--sites", "3", "--root", root]) == 0
    assert capsys.readouterr().out.strip() == "duo: fix screen-main-bounds (3 sites)"
    state = duolib.load_json(os.path.join(root, ".duo", "loop.json"))
    assert state["history"][0]["message"] == "duo: fix screen-main-bounds (3 sites)"
    # no failures -> done, counter reset
    duolib.write_json(os.path.join(root, ".duo", "runs", "1", "failures.json"), [])
    assert loop.main(["--run", "1", "--root", root]) == 0
    assert duolib.load_json(os.path.join(root, ".duo", "loop.json"))["iterations"] == 0


def test_loop_agent_command(tmp_path):
    root = str(tmp_path)
    seed(root)
    sink = os.path.join(root, "sink.txt")
    cmd = f'"{sys.executable}" -c "import sys;open(r\'{sink}\',\'w\').write(sys.stdin.read())"'
    assert loop.main(["--run", "1", "--root", root, "--agent", cmd]) == 1
    assert "interactive_in_fold" in open(sink, encoding="utf-8").read()


def test_report_and_loop_refuse_unverified_run(tmp_path, capsys):
    """Field test, run 9: 25 green cells with empty element trees. A ui.json
    whose cells had no tree is 'unverified', exit 1, and loop does not say done."""
    root = str(tmp_path)
    rdir = seed(root, run=4, ui_fail=False)
    ui_path = os.path.join(rdir, "ui.json")
    ui = duolib.load_json(ui_path)
    ui["verified"] = False
    for c in ui["cells"]:
        c["tree_available"] = False
    duolib.write_json(ui_path, ui)
    assert report.main(["--run", "4", "--root", root, "--json"]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["overall"] == "unverified"
    text = open(os.path.join(rdir, "duo-report.html"), encoding="utf-8").read()
    assert "skipped, not passed" in text and "AXe" in text
    assert loop.main(["--run", "4", "--root", root, "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "unverified" and out["failures"] == 0


def test_loop_without_failures_json_is_not_done(tmp_path, capsys):
    root = str(tmp_path)
    rdir = seed(root, run=5, ui_fail=False)
    os.remove(os.path.join(rdir, "failures.json"))
    assert loop.main(["--run", "5", "--root", root, "--json"]) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "no_assertions" and out["failures"] is None


def test_report_perf_without_metrics_is_skip(tmp_path, capsys):
    root = str(tmp_path)
    rdir = seed(root, run=6, ui_fail=False)
    duolib.write_json(os.path.join(rdir, "perf.json"), {"schema": 1, "run": 6, "mode": "regression", "metrics": [],
                                                        "status": "skip", "reason": "no metrics collected"})
    assert report.main(["--run", "6", "--root", root, "--json"]) == 0  # UI verified, perf merely absent
    summary = json.loads(capsys.readouterr().out)
    assert summary["overall"] == "pass"
    text = open(os.path.join(rdir, "duo-report.html"), encoding="utf-8").read()
    assert "DuoPerfTests target missing" in text
