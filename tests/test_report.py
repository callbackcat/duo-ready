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
    # the hint is the exact command, into the next run, only the failed pairs
    assert 'run-matrix.sh" --run 2 --only-failed .duo/runs/1/failures.json' in out.err
    # iteration 2 (cap from duo.yaml is 2)
    assert loop.main(["--run", "1", "--root", root, "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["iteration"] == 2 and data["rerun"] == "--flows feed --cells book-landscape"
    assert data["rerun_command"].endswith("--run 2 --only-failed .duo/runs/1/failures.json")
    # iteration 3: cap reached -> DUO-TODO.md
    assert loop.main(["--run", "1", "--root", root]) == 0
    todo = os.path.join(root, "DUO-TODO.md")
    assert os.path.exists(todo)
    body = open(todo, encoding="utf-8").read()
    assert "interactive_in_fold" in body and "Keep interactive elements out of the fold." in body and "PlayerView.swift:88" in body
    assert "--only-failed .duo/runs/1/failures.json" in body
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
    assert loop.main(["--run", "4", "--root", root, "--json"]) == 4  # nothing to loop on, not "failures remain"
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "unverified" and out["failures"] == 0


def test_loop_without_failures_json_is_not_done(tmp_path, capsys):
    root = str(tmp_path)
    rdir = seed(root, run=5, ui_fail=False)
    os.remove(os.path.join(rdir, "failures.json"))
    assert loop.main(["--run", "5", "--root", root, "--json"]) == 4
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
    assert "no metrics collected" in text  # the perf.json reason is shown verbatim


def test_report_embeds_thumbnails_not_full_captures(tmp_path):
    """Field test 2: 56 MB report from full captures embedded twice. The report
    embeds a thumbnail, links the PNG on disk, and stays small."""
    root = str(tmp_path)
    rdir = seed(root, run=7)
    cap = os.path.join(rdir, "captures")
    big = os.path.join(cap, "feed-book-landscape.png")
    w, h = 2853, 2007  # an inner-display landscape capture
    pngio.write(big, w, h, 3, pngio.solid(w, h, (200, 200, 200)))
    ui = duolib.load_json(os.path.join(rdir, "ui.json"))
    for c in ui["cells"]:
        c["screenshot"] = os.path.relpath(big, root)
    duolib.write_json(os.path.join(rdir, "ui.json"), ui)
    failures = duolib.load_json(os.path.join(rdir, "failures.json"))
    for f in failures:
        f["screenshot"] = os.path.relpath(big, root)
    duolib.write_json(os.path.join(rdir, "failures.json"), failures)
    report.main(["--run", "7", "--root", root, "--json"])
    html_path = os.path.join(rdir, "duo-report.html")
    assert os.path.getsize(html_path) < 400_000, os.path.getsize(html_path)
    text = open(html_path, encoding="utf-8").read()
    assert 'href="captures/feed-book-landscape.png"' in text
    thumbs = sorted(os.listdir(os.path.join(rdir, "thumbs")))
    assert thumbs == ["feed-book-landscape.240.png", "feed-book-landscape.720.png"]
    assert pngio.info(os.path.join(rdir, "thumbs", "feed-book-landscape.720.png"))["width"] == 720
    # the overlay keeps full-capture coordinates so frames line up on the thumbnail
    assert f'viewBox="0 0 {w} {h}"' in text


def test_report_perf_reason_and_errored_cells(tmp_path, capsys):
    root = str(tmp_path)
    rdir = seed(root, run=8, ui_fail=False)
    duolib.write_json(os.path.join(rdir, "perf.json"), {"schema": 1, "run": 8, "mode": "regression", "metrics": [],
                                                        "status": "skip", "reason": "xcresulttool returned no measurements although the log shows measured values"})
    ui = duolib.load_json(os.path.join(rdir, "ui.json"))
    ui["cells"].append({"flow": "checkout", "cell": "open-landscape", "errored": True, "screenshot": None, "ancestry": False,
                        "results": [{"assertion": "flow", "status": "fail", "reason": "step timed out: wait \"Pay\""}]})
    duolib.write_json(os.path.join(rdir, "ui.json"), ui)
    assert report.main(["--run", "8", "--root", root, "--json"]) == 1
    summary = json.loads(capsys.readouterr().out)
    text = open(os.path.join(rdir, "duo-report.html"), encoding="utf-8").read()
    assert "xcresulttool returned no measurements" in text
    assert "stopped on a flow step" in text and "checkout/open-landscape" in text
    assert "vertical overflow is reported as warn" in text
    assert any("captures exist" not in s for s in summary["skipped"])


def test_report_names_captures_without_assertions(tmp_path, capsys):
    """run-matrix stopped before assert.py but captures exist: say so, with the command."""
    root = str(tmp_path)
    rdir = seed(root, run=9, with_ui=False, with_perf=False)
    cap = os.path.join(rdir, "captures")
    os.makedirs(cap, exist_ok=True)
    pngio.write(os.path.join(cap, "feed-closed-portrait.png"), 4, 4, 3, pngio.solid(4, 4))
    report.main(["--run", "9", "--root", root, "--json"])
    summary = json.loads(capsys.readouterr().out)
    assert any("assert.py did not run" in s and "--run 9" in s for s in summary["skipped"])


def test_loop_counter_is_per_rerun_chain_and_next_free_run(tmp_path, capsys):
    """Field test 3, note 14: the counter was project state ("3/3" inherited
    from the previous day) and the suggested run number already existed."""
    root = str(tmp_path)
    seed(root, run=11)
    assert loop.main(["--run", "11", "--root", root, "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["iteration"] == 1
    # an --only-failed rerun of 11 continues the chain
    seed(root, run=12)
    duolib.write_json(os.path.join(root, ".duo", "runs", "12", "rerun-of.json"), {"from": 11})
    assert loop.main(["--run", "12", "--root", root, "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["iteration"] == 2
    # a fresh run (not a rerun of 12) starts a new chain at 1
    seed(root, run=13)
    os.makedirs(os.path.join(root, ".duo", "runs", "14"))  # taken by hand
    assert loop.main(["--run", "13", "--root", root, "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["iteration"] == 1
    assert data["rerun_command"].endswith("--run 15 --only-failed .duo/runs/13/failures.json")
    assert loop.next_run(root, 13) == 15 and loop.next_run(root, 20) == 21


def test_report_lists_ungated_perf_and_skip_rows(tmp_path):
    """Field test 3, notes 10 and 13: perf "passed" with nothing compared and
    the report did not say so."""
    root = str(tmp_path)
    rdir = seed(root, ui_fail=False)
    duolib.write_json(os.path.join(rdir, "perf.json"), {"schema": 1, "run": 1, "mode": "regression", "status": "baseline", "gated": 0, "metrics": [
        {"flow": "*", "cell": "closed-portrait", "metric": "launch_ms", "value": 2265.0, "baseline": None, "status": "baseline"},
        {"flow": "*", "cell": "open>book", "metric": "fold_relayout_ms", "value": None, "baseline": None, "status": "skip",
         "reason": "DuoPerfTests skipped testFoldRelayout: TEST_RUNNER_DUO_POSE_URL is not set"},
    ]})
    out, summary = report.build_report(root, 1)
    assert any("nothing was gated" in s for s in summary["skipped"])
    assert any("open>book" in s and "DUO_POSE_URL" in s for s in summary["skipped"])
    assert 'perf <span class="badge baseline">baseline</span>' in out
    assert "DUO_POSE_URL" in out and "None" not in out.split("Performance")[1].split("Scan findings")[0]


def test_loop_state_from_0_3_0_does_not_inherit_its_counter(tmp_path, capsys):
    """Field test 4, note 11: a loop.json written by 0.3.0 has no last_run; on a
    fresh run loop.py printed "iteration cap 3 reached" and never a payload."""
    root = str(tmp_path)
    seed(root, run=15)
    duolib.write_json(os.path.join(root, ".duo", "loop.json"), {"iterations": 3, "max_iterations": 3, "history": []})
    assert loop.main(["--run", "15", "--root", root, "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["iteration"] == 1 and data["action"] == "patch"
    assert duolib.load_json(os.path.join(root, ".duo", "loop.json"))["last_run"] == 15
    assert not os.path.exists(os.path.join(root, "DUO-TODO.md"))


def test_todo_names_a_rule_level_lead_without_a_file(tmp_path):
    """Field test 4, note 11: DUO-TODO.md read "(scan rule rn-fixed-height at None)"."""
    root = str(tmp_path)
    failures = [{"flow": "feed", "cell": "closed-portrait", "assertion": "tap_target_min", "status": "fail",
                 "elements": [{"id": "mic", "frame": [342, 692, 42, 42]}], "matched_rule": "rn-fixed-height",
                 "source_hint": None, "source_confidence": "rule",
                 "fix_hint": "Keep interactive elements at least 44 x 44 pt in every pose"}]
    path = loop.write_todo(root, 15, failures, {"iterations": 0, "max_iterations": 3, "history": []})
    text = open(path, encoding="utf-8").read()
    assert "at `None`" not in text and "lead only" in text and "rn-fixed-height" in text
    assert "44 x 44 pt" in text


def test_report_baseline_wording_depends_on_the_baseline_file(tmp_path):
    """Field test 6: the report said "no baseline in .duo/baselines/perf.json"
    next to a baseline that had just been promoted, and printed `<n>`."""
    root = str(tmp_path)
    rdir = seed(root, ui_fail=False)
    duolib.write_json(os.path.join(rdir, "perf.json"), {"schema": 1, "run": 1, "mode": "regression", "status": "baseline", "gated": 0, "metrics": [
        {"flow": "*", "cell": "closed-portrait", "metric": "launch_ms", "value": 2265.0, "baseline": None, "status": "baseline"}]})
    _, summary = report.build_report(root, 1)
    line = [s for s in summary["skipped"] if "nothing was gated" in s][0]
    assert "no baseline in .duo/baselines/perf.json" in line and "perf.sh --promote --run 1" in line and "<n>" not in line
    duolib.write_json(os.path.join(root, ".duo", "baselines", "perf.json"), {"metrics": []})
    _, summary = report.build_report(root, 1)
    line = [s for s in summary["skipped"] if "nothing was gated" in s][0]
    assert "no baseline in" not in line and "written before .duo/baselines/perf.json existed" in line and "perf.sh --run 1" in line
