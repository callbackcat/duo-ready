"""perfparse.py against the `xcresulttool get test-results metrics` shape seen on
Xcode 27.1 (field test 2: the legacy root object carried no measurements, this
form does)."""
import json
import os
import shutil
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import duolib  # noqa: E402
import perfparse  # noqa: E402

FIXTURE = os.path.join(ROOT, "tests", "fixtures", "xcresult-test-results-metrics.json")


def _seed(tmp_path, name="closed-to-open.metrics.json"):
    perf = tmp_path / "perf"
    perf.mkdir()
    shutil.copy(FIXTURE, perf / name)
    return str(perf)


def test_metric_names_by_test_and_identifier():
    assert perfparse.metric_name("DuoPerfTests/testLaunch()", "com.apple.dt.XCTMetric_ApplicationLaunch-AppLaunch.duration") == "launch_ms"
    assert perfparse.metric_name("DuoPerfTests/testLaunch()", "com.apple.dt.XCTMetric_Clock.time.monotonic") == "launch_wall_ms"
    assert perfparse.metric_name("DuoPerfTests/testFoldRelayout()", "com.apple.dt.XCTMetric_Clock.time.monotonic") == "fold_relayout_ms"
    assert perfparse.metric_name("x/testLaunch()", "com.apple.dt.XCTMetric_Memory.physical_peak") == "memory_peak_mb"
    assert perfparse.metric_name("x/testLaunch()", "com.apple.dt.XCTMetric_Memory.physical") == "memory_delta_mb"
    assert perfparse.metric_name("x/testFoldRelayout()", "com.apple.dt.XCTMetric_CPU.time") == "cpu_s"


def test_parse_and_gate_regression(tmp_path):
    perf_dir = _seed(tmp_path)
    doc, code = perfparse.build(11, perf_dir, None, "regression", {})
    assert code == 0 and "status" not in doc
    rows = {(m["cell"], m["metric"]): m for m in doc["metrics"]}
    assert ("closed>open", "launch_ms") in rows  # the `-to-` file name becomes the contract cell name
    assert rows[("closed>open", "launch_ms")]["value"] == 611.0 and rows[("closed>open", "launch_ms")]["unit"] == "ms"
    assert rows[("closed>open", "launch_wall_ms")]["status"] == "info"       # XCUITest automation time, not gated
    assert abs(rows[("closed>open", "memory_peak_mb")]["value"] - 50.87) < 0.05
    assert rows[("closed>open", "memory_peak_mb")]["status"] == "info"
    assert rows[("closed>open", "fold_relayout_ms")]["value"] == 180.0
    assert rows[("closed>open", "fold_relayout_ms")]["status"] == "baseline"  # no baseline yet


def test_absolute_mode_and_baseline_fail(tmp_path):
    perf_dir = _seed(tmp_path)
    cfg = {"launch_ms": {"warn": 500, "fail": 600}, "fold_relayout_ms": {"fail": 250}}
    doc, code = perfparse.build(1, perf_dir, None, "absolute", cfg)
    rows = {m["metric"]: m["status"] for m in doc["metrics"]}
    assert rows["launch_ms"] == "fail" and rows["fold_relayout_ms"] == "pass" and code == 2
    base = tmp_path / "baseline.json"
    duolib.write_json(str(base), {"metrics": [{"flow": "*", "cell": "closed>open", "metric": "launch_ms", "value": 400}]})
    doc, code = perfparse.build(1, perf_dir, str(base), "regression", {})
    assert {m["metric"]: m["status"] for m in doc["metrics"]}["launch_ms"] == "fail" and code == 2


def test_no_metrics_is_exit_4_and_blames_the_right_thing(tmp_path):
    perf = tmp_path / "perf"
    perf.mkdir()
    (perf / "closed-portrait.json").write_text(json.dumps({"_type": {"_name": "ActionsInvocationRecord"}, "actions": []}))
    doc, code = perfparse.build(1, str(perf), None, "regression", {})
    assert code == 4 and doc["status"] == "skip" and "DuoPerfTests target missing" in doc["reason"]
    (perf / "closed-portrait.log").write_text("Test Case '-[DuoPerfTests testLaunch]' measured [Clock Monotonic Time, s] average: 5.8\n")
    doc, code = perfparse.build(1, str(perf), None, "regression", {}, log_dir=str(perf))
    assert code == 4 and "xcresulttool" in doc["reason"] and "DuoPerfTests target missing" not in doc["reason"]


def test_legacy_walk_fallback(tmp_path):
    perf = tmp_path / "perf"
    perf.mkdir()
    legacy = {"tests": [{"testIdentifier": "DuoPerfTests/testLaunch()", "metrics": [
        {"identifier": "com.apple.dt.XCTMetric_ApplicationLaunch-AppLaunch.duration", "unitOfMeasurement": "s",
         "measurements": {"_values": [{"_value": "0.5"}, {"_value": "0.7"}, {"_value": "0.6"}]}}]}]}
    (perf / "open-landscape.json").write_text(json.dumps(legacy))
    doc, code = perfparse.build(1, str(perf), None, "regression", {})
    assert code == 0 and doc["metrics"][0]["metric"] == "launch_ms" and doc["metrics"][0]["value"] == 600.0


def test_cli(tmp_path):
    perf_dir = _seed(tmp_path, "open-landscape.metrics.json")
    out = tmp_path / "perf.json"
    assert perfparse.main(["--run", "3", "--perf-dir", perf_dir, "--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["run"] == 3 and any(m["cell"] == "open-landscape" for m in doc["metrics"])
