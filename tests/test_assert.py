import importlib
import json
import os
import sys

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPTS)
import duolib  # noqa: E402
import pngio  # noqa: E402

asrt = importlib.import_module("assert")


def el(id_, x, y, w, h, interactive=False, type_="view", text=None, truncated=None):
    d = {"id": id_, "type": type_, "frame": [x, y, w, h], "interactive": interactive}
    if text is not None:
        d["text"] = text
    if truncated is not None:
        d["truncated"] = truncated
    return d


def write_capture(root, run, flow, cell, elements, png=True, size=(40, 60), color=(255, 255, 255)):
    cap = os.path.join(root, ".duo", "runs", str(run), "captures")
    os.makedirs(cap, exist_ok=True)
    duolib.write_json(os.path.join(cap, f"{flow}-{cell}.tree.json"), {"elements": elements})
    if png:
        pngio.write(os.path.join(cap, f"{flow}-{cell}.png"), size[0], size[1], 3, pngio.solid(size[0], size[1], color))


def results_for(ui, flow, cell):
    for c in ui["cells"]:
        if c["flow"] == flow and c["cell"] == cell:
            return {r["assertion"]: r for r in c["results"]}
    raise AssertionError(f"cell {flow}/{cell} missing")


def write_build(root, run, stamp="27.1"):
    duolib.write_json(os.path.join(root, ".duo", "runs", str(run), "build.json"), {"sdk_stamp": stamp, "scheme": "Demo"})


def test_sdk_tier():
    assert asrt.sdk_tier("27.1") == "27.1"
    assert asrt.sdk_tier("27.2") == "27.1"
    assert asrt.sdk_tier("27.0") == "27.0"
    assert asrt.sdk_tier("26.0") == "26"
    assert asrt.sdk_tier(None) == "27.1"


def test_parse_capture_name():
    assert asrt.parse_capture_name("feed-book-landscape") == ("feed", "book-landscape", "cell")
    assert asrt.parse_capture_name("my-flow-closed-portrait") == ("my-flow", "closed-portrait", "cell")
    assert asrt.parse_capture_name("feed-closed-to-open") == ("feed", "closed>open", "transition")
    assert asrt.parse_capture_name("feed-split-view-left") == ("feed", "split-view-left", "cell")
    assert asrt.parse_capture_name("garbage") is None


def test_clean_cell_passes(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    elements = [
        el("Root", 0, 0, 466, 678, type_="view"),
        el("FeedList", 0, 0, 382, 678, type_="scroll"),
        el("OkButton", 20, 500, 120, 48, interactive=True, type_="button"),
        el("ComposeItem", 400, 100, 44, 44, interactive=True, type_="button"),
        el("SearchItem", 400, 160, 44, 44, interactive=True, type_="button"),
    ]
    write_capture(root, 1, "feed", "closed-portrait", elements)
    ui, failures = asrt.evaluate_run(root, 1)
    r = results_for(ui, "feed", "closed-portrait")
    assert r["offscreen_elements"]["status"] == "pass"
    assert r["clipped_text"]["status"] == "pass"
    assert r["tap_target_min"]["status"] == "pass"
    assert r["bars_vertical_expected"]["status"] == "pass"
    assert r["content_under_outer_camera"]["status"] == "pass"
    assert r["interactive_in_fold"]["status"] == "skip"
    assert r["visual_diff"]["status"] == "skip"
    assert failures == []


def test_offscreen_and_tap_target_fail(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    elements = [
        el("FeedHeader", 0, 0, 1180, 88, type_="view"),
        el("TinyButton", 10, 100, 30, 30, interactive=True, type_="button"),
    ]
    write_capture(root, 1, "feed", "open-landscape", elements)
    ui, failures = asrt.evaluate_run(root, 1)
    r = results_for(ui, "feed", "open-landscape")
    assert r["offscreen_elements"]["status"] == "fail"
    assert r["offscreen_elements"]["elements"][0]["id"] == "FeedHeader"
    assert r["tap_target_min"]["status"] == "fail"
    names = {f["assertion"] for f in failures}
    assert {"offscreen_elements", "tap_target_min"} <= names
    for f in failures:
        assert f["fix_hint"]


def test_offscreen_uses_sdk_tier_geometry(tmp_path):
    root = str(tmp_path)
    write_build(root, 1, stamp="27.0")
    # 900 wide is inside 951 (27.1) but outside 871 (27.0)
    write_capture(root, 1, "feed", "open-landscape", [el("Wide", 0, 0, 900, 100)])
    ui, _ = asrt.evaluate_run(root, 1)
    assert ui["sdk_tier"] == "27.0"
    assert results_for(ui, "feed", "open-landscape")["offscreen_elements"]["status"] == "fail"
    assert results_for(ui, "feed", "open-landscape")["bars_vertical_expected"]["status"] == "skip"


def test_clipped_text(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    elements = [
        el("Card", 0, 0, 400, 200, type_="view"),
        el("TitleLabel", 16, 16, 200, 20, type_="label", text="A long title that is cut…"),
        el("FullLabel", 16, 60, 384, 20, type_="label", text="Fills the card…"),
        el("FlaggedLabel", 16, 100, 100, 20, type_="label", text="short", truncated=True),
    ]
    write_capture(root, 1, "feed", "open-portrait", elements)
    ui, _ = asrt.evaluate_run(root, 1)
    r = results_for(ui, "feed", "open-portrait")["clipped_text"]
    assert r["status"] == "fail"
    ids = {e["id"] for e in r["elements"]}
    assert ids == {"TitleLabel", "FlaggedLabel"}


def test_bars_vertical_missing_is_warn_by_default(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    elements = [el("Tab1", 0, 630, 100, 48, interactive=True), el("Tab2", 120, 630, 100, 48, interactive=True)]
    write_capture(root, 1, "feed", "closed-portrait", elements)
    ui, failures = asrt.evaluate_run(root, 1)
    assert results_for(ui, "feed", "closed-portrait")["bars_vertical_expected"]["status"] == "warn"
    assert all(f["assertion"] != "bars_vertical_expected" for f in failures)
    _, failures_w = asrt.evaluate_run(root, 1, include_warn=True)
    assert any(f["assertion"] == "bars_vertical_expected" for f in failures_w)


def test_outer_camera_and_background_exempt(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    elements = [
        el("HeroImage", 0, 0, 466, 300, type_="image"),
        el("CloseButton", 420, 12, 44, 44, interactive=True, type_="button"),
    ]
    write_capture(root, 1, "player", "closed-portrait", elements)
    ui, _ = asrt.evaluate_run(root, 1)
    r = results_for(ui, "player", "closed-portrait")["content_under_outer_camera"]
    assert r["status"] == "fail"
    assert [e["id"] for e in r["elements"]] == ["CloseButton"]


def test_interactive_in_fold_both_orientations(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    write_capture(root, 1, "player", "book-landscape", [
        el("PlayButton", 440, 300, 60, 44, interactive=True, type_="button"),
        el("Feed", 0, 0, 951, 669, type_="scroll", interactive=True),
        el("Left", 100, 300, 60, 44, interactive=True, type_="button"),
    ])
    write_capture(root, 1, "player", "book-portrait", [
        el("Mid", 100, 460, 100, 44, interactive=True, type_="button"),
        el("Top", 100, 10, 100, 44, interactive=True, type_="button"),
    ])
    write_capture(root, 1, "player", "open-landscape", [el("PlayButton", 440, 300, 60, 44, interactive=True)])
    ui, _ = asrt.evaluate_run(root, 1)
    land = results_for(ui, "player", "book-landscape")["interactive_in_fold"]
    port = results_for(ui, "player", "book-portrait")["interactive_in_fold"]
    assert land["status"] == "fail" and [e["id"] for e in land["elements"]] == ["PlayButton"]
    assert port["status"] == "fail" and [e["id"] for e in port["elements"]] == ["Mid"]
    assert results_for(ui, "player", "open-landscape")["interactive_in_fold"]["status"] == "skip"


def test_source_hint_from_scan(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    duolib.write_json(os.path.join(root, ".duo", "scan.json"), {"findings": [
        {"rule": "hardcoded-size", "severity": "warn", "file": "Sources/PlayerView.swift", "line": 88, "fix_hint": "Remove hardcoded dimensions."},
        {"rule": "screen-main-bounds", "severity": "error", "file": "Sources/AppDelegate.swift", "line": 10, "fix_hint": "x"},
    ]})
    write_capture(root, 1, "player", "book-landscape", [el("PlayButton", 440, 300, 60, 44, interactive=True)])
    _, failures = asrt.evaluate_run(root, 1)
    f = [x for x in failures if x["assertion"] == "interactive_in_fold"][0]
    assert f["matched_rule"] == "hardcoded-size"
    assert f["source_hint"] == "Sources/PlayerView.swift:88"
    assert f["fix_hint"] == "Remove hardcoded dimensions."


def test_visual_diff_thresholds(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    base_dir = os.path.join(root, ".duo", "baselines")
    os.makedirs(base_dir)
    w, h = 40, 60  # split-view cells have no ignore regions
    pngio.write(os.path.join(base_dir, "feed-split-view-left.png"), w, h, 3, pngio.solid(w, h, (255, 255, 255)))
    rows = pngio.solid(w, h, (255, 255, 255))
    pngio.fill_rect(rows, 0, 50, 2, 1, (0, 0, 0))  # 2 of 2400 px = 0.00083
    cap = os.path.join(root, ".duo", "runs", "1", "captures")
    os.makedirs(cap)
    duolib.write_json(os.path.join(cap, "feed-split-view-left.tree.json"), {"elements": []})
    pngio.write(os.path.join(cap, "feed-split-view-left.png"), w, h, 3, rows)
    # pass: under the default 0.02 threshold
    ui, _ = asrt.evaluate_run(root, 1)
    assert results_for(ui, "feed", "split-view-left")["visual_diff"]["status"] == "pass"
    # warn: between threshold and 2x; use threshold 0.0005 via duo.yaml
    with open(os.path.join(root, "duo.yaml"), "w") as fh:
        fh.write("assert:\n  visual_diff_threshold: 0.0005\n")
    ui, _ = asrt.evaluate_run(root, 1)
    r = results_for(ui, "feed", "split-view-left")["visual_diff"]
    assert r["status"] == "warn" and r["diff"] > 0.0005
    assert os.path.exists(os.path.join(cap, "feed-split-view-left.diff.png"))
    # fail: > 2x
    with open(os.path.join(root, "duo.yaml"), "w") as fh:
        fh.write("assert:\n  visual_diff_threshold: 0.0001\n")
    ui, failures = asrt.evaluate_run(root, 1)
    assert results_for(ui, "feed", "split-view-left")["visual_diff"]["status"] == "fail"
    assert any(f["assertion"] == "visual_diff" for f in failures)


def test_visual_diff_ignores_status_band(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    base_dir = os.path.join(root, ".duo", "baselines")
    os.makedirs(base_dir)
    w, h = 30, 300  # open-portrait: top 246 px ignored
    pngio.write(os.path.join(base_dir, "feed-open-portrait.png"), w, h, 3, pngio.solid(w, h, (255, 255, 255)))
    rows = pngio.solid(w, h, (255, 255, 255))
    pngio.fill_rect(rows, 0, 0, w, 246, (0, 0, 0))  # whole ignored band changed
    cap = os.path.join(root, ".duo", "runs", "1", "captures")
    os.makedirs(cap)
    duolib.write_json(os.path.join(cap, "feed-open-portrait.tree.json"), {"elements": []})
    pngio.write(os.path.join(cap, "feed-open-portrait.png"), w, h, 3, rows)
    ui, _ = asrt.evaluate_run(root, 1)
    assert results_for(ui, "feed", "open-portrait")["visual_diff"]["status"] == "pass"


def test_transition_stable(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    cap = os.path.join(root, ".duo", "runs", "1", "captures")
    os.makedirs(cap)
    before = [el("Title", 0, 0, 100, 20), el("PlayButton", 0, 40, 60, 44, interactive=True), el("Toast", 0, 100, 60, 20)]
    after = [el("Title", 0, 0, 100, 20)]
    duolib.write_json(os.path.join(cap, "player-closed-to-open.before.tree.json"), {"elements": before})
    duolib.write_json(os.path.join(cap, "player-closed-to-open.tree.json"), {"elements": after})
    with open(os.path.join(root, "duo.yaml"), "w") as fh:
        fh.write("flows:\n  - name: player\n    steps: [launch]\n    may_remove: [Toast]\n")
    ui, failures = asrt.evaluate_run(root, 1)
    r = results_for(ui, "player", "closed>open")["transition_stable"]
    assert r["status"] == "fail"
    assert r["missing"] == ["PlayButton"]
    # fallback to the from-pose capture when no .before tree exists
    os.remove(os.path.join(cap, "player-closed-to-open.before.tree.json"))
    duolib.write_json(os.path.join(cap, "player-closed-portrait.tree.json"), {"elements": [el("Title", 0, 0, 100, 20)]})
    ui, _ = asrt.evaluate_run(root, 1)
    assert results_for(ui, "player", "closed>open")["transition_stable"]["status"] == "pass"


def test_severity_off_and_warn(tmp_path):
    root = str(tmp_path)
    write_build(root, 1)
    with open(os.path.join(root, "duo.yaml"), "w") as fh:
        fh.write("assert:\n  offscreen_elements: off\n  tap_target: warn\n")
    write_capture(root, 1, "feed", "open-landscape", [el("Wide", 0, 0, 2000, 10, interactive=True)])
    ui, failures = asrt.evaluate_run(root, 1)
    r = results_for(ui, "feed", "open-landscape")
    assert r["offscreen_elements"]["status"] == "skip"
    assert r["tap_target_min"]["status"] == "warn"
    assert failures == []


def test_cli_writes_files_and_exit_code(tmp_path, capsys):
    root = str(tmp_path)
    write_build(root, 2)
    write_capture(root, 2, "feed", "open-landscape", [el("Wide", 0, 0, 2000, 10)])
    code = asrt.main(["--run", "2", "--root", root, "--json"])
    assert code == 1
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["failures"] == 1
    assert os.path.exists(os.path.join(root, ".duo", "runs", "2", "ui.json"))
    assert os.path.exists(os.path.join(root, ".duo", "runs", "2", "failures.json"))
    write_capture(root, 3, "feed", "open-landscape", [el("Ok", 0, 0, 100, 100)])
    write_build(root, 3)
    assert asrt.main(["--run", "3", "--root", root]) == 0
