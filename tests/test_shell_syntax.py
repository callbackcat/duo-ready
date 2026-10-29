"""Shell scripts: syntax, --help, and honest refusal on a non-macOS host.

These run on Windows through Git Bash, which is why they only check what a
non-Mac can check: every script parses, prints usage with --help, and exits 4
with the contract's exact `cannot run on this host:` prefix instead of faking
a result. assets.sh is host-independent and gets a functional test.
"""
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import zlib

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS = os.path.join(ROOT, "scripts")
BASH = shutil.which("bash") or "/usr/bin/bash"

SCRIPT_NAMES = [
    "preflight.sh", "sdk-stamp.sh", "build.sh", "sim.sh", "capture.sh",
    "run-matrix.sh", "perf.sh", "assets.sh",
]
# Arguments that make each script get past argument validation.
REFUSAL_ARGS = {
    "preflight.sh": [],
    "sdk-stamp.sh": ["Fake.app"],
    "build.sh": [],
    "sim.sh": ["udid"],
    "capture.sh": ["out.png"],
    "run-matrix.sh": [],
    "perf.sh": [],
}


def run(script, *args, env=None, cwd=ROOT):
    merged = dict(os.environ)
    if env:
        merged.update(env)
    return subprocess.run(
        [BASH, os.path.join(SCRIPTS, script), *args],
        cwd=cwd, capture_output=True, text=True, timeout=60, env=merged,
    )


@pytest.mark.parametrize("script", SCRIPT_NAMES + ["common.sh"])
def test_bash_syntax(script):
    r = subprocess.run([BASH, "-n", os.path.join(SCRIPTS, script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("script", SCRIPT_NAMES)
def test_help(script):
    r = run(script, "--help")
    assert r.returncode == 0, r.stderr
    assert "Usage:" in r.stdout


@pytest.mark.skipif(platform.system() == "Darwin", reason="refusal only applies off macOS")
@pytest.mark.parametrize("script", sorted(REFUSAL_ARGS))
def test_refuses_on_non_mac(script):
    r = run(script, *REFUSAL_ARGS[script], env={"DUO_PY": "python"})
    assert r.returncode == 4, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    lines = [ln for ln in r.stderr.splitlines() if ln.startswith("cannot run on this host:")]
    assert len(lines) == 1, r.stderr


def test_assets_refuses_without_python():
    # assets.sh does not need macOS but must not pretend to work without its tools.
    r = run("assets.sh", env={"DUO_PY": "definitely-missing-python"})
    assert r.returncode == 4
    assert r.stderr.startswith("cannot run on this host:")


def _png(path, width, height):
    """Write a solid grey RGB PNG with the standard library."""
    raw = b"".join(bytes([0]) + bytes([128, 128, 128]) * width for _ in range(height))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(bytes([0x89]) + b"PNG" + bytes([0x0D, 0x0A, 0x1A, 0x0A]))
        f.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        f.write(chunk(b"IDAT", zlib.compress(raw)))
        f.write(chunk(b"IEND", b""))


def test_assets_exports_passing_cells(tmp_path):
    """Given a run with ui.json and captures, assets.sh exports the App Store set,
    writes manifest.json and FEATURING.md, and prints the upload commands."""
    proj = tmp_path / "proj"
    caps = proj / ".duo" / "runs" / "1" / "captures"
    caps.mkdir(parents=True)
    shutil.copy(os.path.join(ROOT, "templates", "duo.yaml"), proj / "duo.yaml")
    _png(caps / "feed-closed-portrait.png", 1398, 2034)
    _png(caps / "feed-open-landscape.png", 2853, 2007)
    _png(caps / "feed-book-landscape.png", 2853, 2007)
    ui = {"schema": 1, "run": 1, "cells": [
        {"flow": "feed", "cell": "closed-portrait", "screenshot": str(caps / "feed-closed-portrait.png"),
         "results": [{"assertion": "offscreen_elements", "status": "pass"}]},
        {"flow": "feed", "cell": "open-landscape", "screenshot": str(caps / "feed-open-landscape.png"),
         "results": [{"assertion": "offscreen_elements", "status": "pass"}]},
        {"flow": "feed", "cell": "book-landscape", "screenshot": str(caps / "feed-book-landscape.png"),
         "results": [{"assertion": "interactive_in_fold", "status": "fail"}]},
    ]}
    (proj / ".duo" / "runs" / "1" / "ui.json").write_text(json.dumps(ui))
    r = run("assets.sh", "--json", cwd=str(proj), env={"DUO_PY": "python", "DUO_ROOT": str(proj).replace(os.sep, "/")})
    assert r.returncode == 0, r.stdout + r.stderr
    dest = proj / "fastlane" / "screenshots" / "en-US"
    files = sorted(p.name for p in dest.glob("*.png"))
    assert files == ["00_iphone_duo_inner_feed-open-landscape.png", "01_iphone_duo_outer_feed-closed-portrait.png"]
    manifest = json.loads((dest / "manifest.json").read_text())
    assert [e["cell"] for e in manifest["screenshots"]] == ["open-landscape", "closed-portrait"]
    assert (proj / "FEATURING.md").exists()
    assert "APP_IPHONE_DUO" in r.stdout


def test_duocfg_reads_template():
    py = sys.executable
    cfg = os.path.join(ROOT, "templates", "duo.yaml")
    duocfg = os.path.join(SCRIPTS, "duocfg.py")
    r = subprocess.run([py, duocfg, "scheme", "--file", cfg], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "MyApp"
    r = subprocess.run([py, duocfg, "cells", "--file", cfg, "--list"], capture_output=True, text=True)
    assert r.stdout.split() == ["closed-portrait", "closed-landscape", "open-landscape", "open-portrait", "book-landscape", "book-portrait"]
    r = subprocess.run([py, duocfg, "perf.launch_ms.fail", "--file", cfg], capture_output=True, text=True)
    assert r.stdout.strip() == "1500"
    r = subprocess.run([py, duocfg, "missing.key", "--file", cfg], capture_output=True, text=True)
    assert r.returncode == 1
    r = subprocess.run([py, duocfg, "missing.key", "--file", cfg, "--default", "x"], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "x"


@pytest.mark.parametrize("script", SCRIPT_NAMES + ["common.sh"])
def test_no_sigpipe_pipelines(script):
    """`cmd | head -n 1` and `cmd | awk '... exit'` under `set -o pipefail` die
    with SIGPIPE (exit 141) about one run in eight (field test). Capture the
    output first, then parse it; `sed -n 1p` reads to the end."""
    text = open(os.path.join(SCRIPTS, script), encoding="utf-8").read()
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    bad = [ln for ln in code if "| head -n 1" in ln or re.search(r"\|\s*awk\s+'[^']*\bexit\b", ln)]
    assert bad == [], bad


@pytest.mark.parametrize("script", SCRIPT_NAMES + ["common.sh"])
def test_local_does_not_read_a_variable_it_assigns(script):
    """`local a="$x" b="$a"` expands $a before the assignment (unbound under set -u)."""
    text = open(os.path.join(SCRIPTS, script), encoding="utf-8").read()
    bad = []
    for ln in text.splitlines():
        m = re.match(r"\s*local\s+(.*)", ln)
        if not m:
            continue
        names = re.findall(r"(\w+)=", m.group(1))
        for name in names[:-1] if names else []:
            rest = m.group(1).split(name + "=", 1)[1]
            if re.search(r"\$\{?" + re.escape(name) + r"\b", rest):
                bad.append(ln)
    assert bad == [], bad


def test_scripts_are_executable_in_git():
    """The field test cloned the repo and got `permission denied` on every script."""
    if not shutil.which("git"):
        pytest.skip("git not available")
    r = subprocess.run(["git", "ls-files", "-s", "scripts/"], cwd=ROOT, capture_output=True, text=True)
    modes = {ln.split()[3]: ln.split()[0] for ln in r.stdout.splitlines() if ln.strip()}
    sh = {p: m for p, m in modes.items() if p.endswith(".sh")}
    assert sh, "no scripts tracked"
    assert all(m == "100755" for m in sh.values()), {p: m for p, m in sh.items() if m != "100755"}


def test_simdisplay_parses_xcode_27_1_enumerate():
    """Verified format (27 Oct 2026): `Connected Screens:` blocks with Unique ID
    and Pixel Size; the outer display is 1398 px wide, the inner 2007."""
    py = sys.executable
    fixture = os.path.join(ROOT, "tests", "fixtures", "simctl-io-enumerate-xcode27.1.txt")
    text = open(fixture, encoding="utf-8").read()
    simdisplay = os.path.join(SCRIPTS, "simdisplay.py")
    outer = subprocess.run([py, simdisplay, "--width", "1398"], input=text, capture_output=True, text=True, encoding="utf-8")
    inner = subprocess.run([py, simdisplay, "--width", "2007"], input=text, capture_output=True, text=True, encoding="utf-8")
    assert outer.returncode == 0 and inner.returncode == 0
    assert re.fullmatch(r"[0-9A-F-]{36}", outer.stdout.strip()), outer.stdout
    assert re.fullmatch(r"[0-9A-F-]{36}", inner.stdout.strip()), inner.stdout
    assert outer.stdout.strip() != inner.stdout.strip()
    listing = subprocess.run([py, simdisplay, "--json"], input=text, capture_output=True, text=True, encoding="utf-8")
    screens = json.loads(listing.stdout)
    assert {1398, 2007} <= {s["width"] for s in screens}  # the fixture also lists CarPlay/external displays
    missing = subprocess.run([py, simdisplay, "--width", "9999"], input=text, capture_output=True, text=True, encoding="utf-8")
    assert missing.returncode == 1


def test_templates_exist():
    for name in ["duo.yaml", "flows.yaml", "DuoUITests.swift", "DuoPerfTests.swift", "github-actions-duo.yml", "add-duo-test-targets.rb"]:
        assert os.path.isfile(os.path.join(ROOT, "templates", name)), name
    for name in ["tree.py", "perfparse.py"]:
        assert os.path.isfile(os.path.join(SCRIPTS, name)), name


@pytest.mark.parametrize("script", SCRIPT_NAMES + ["common.sh"])
def test_no_grep_q_pipelines(script):
    """`cmd | grep -q x` under pipefail: grep exits at the first match, the
    producer gets SIGPIPE and the pipeline reports 141 (field test 2: a running
    app was reported dead 18 times out of 20). Capture, then grep."""
    text = open(os.path.join(SCRIPTS, script), encoding="utf-8").read()
    code = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    bad = [ln for ln in code if re.search(r"\|\s*grep\s+(-[A-Za-z]*q|-q)", ln)]
    assert bad == [], bad


def test_field_test_2_contracts():
    """Things the second field test proved the scripts must do."""
    rm = open(os.path.join(SCRIPTS, "run-matrix.sh"), encoding="utf-8").read()
    perf = open(os.path.join(SCRIPTS, "perf.sh"), encoding="utf-8").read()
    sim = open(os.path.join(SCRIPTS, "sim.sh"), encoding="utf-8").read()
    pre = open(os.path.join(SCRIPTS, "preflight.sh"), encoding="utf-8").read()
    build = open(os.path.join(SCRIPTS, "build.sh"), encoding="utf-8").read()
    assert "elements --json" not in rm, "duoctl elements has no --json flag (duoctl 0.2.0)"
    assert "tree.py" in rm and "from-axe" in rm
    assert "TEST_RUNNER_DUO_CELL=" in rm and "TEST_RUNNER_DUO_CELL=" in perf, "xcodebuild forwards only TEST_RUNNER_ variables"
    assert "TEST_RUNNER_DUO_POSE_URL" in perf
    assert "-to-" in perf and "test-results metrics" in perf
    assert "perfparse.py" in perf
    assert "--udid" in rm and "--udid" in perf and "duo_select_sim" in rm and "duo_select_sim" in perf
    assert "error_cell" in rm and ".error.json" in rm
    assert 'process != "log"' in sim, "the log predicate matched its own invocation"
    assert "orientation)" in sim
    assert "brew trust" in pre and "mobile-dev-inc/tap" in pre and "get.maestro.mobile.dev" not in pre
    assert "duoctl elements" in pre and '"elements":"%s"' in pre
    assert 'build >>"$LOG"' in build, "xcodebuild output truncated the prebuild log"
    assert "LANG=" in build


def test_field_test_3_contracts():
    """Things the third field test proved the scripts must do."""
    rm = open(os.path.join(SCRIPTS, "run-matrix.sh"), encoding="utf-8").read()
    perf = open(os.path.join(SCRIPTS, "perf.sh"), encoding="utf-8").read()
    sim = open(os.path.join(SCRIPTS, "sim.sh"), encoding="utf-8").read()
    pre = open(os.path.join(SCRIPTS, "preflight.sh"), encoding="utf-8").read()
    orientation = sim[sim.index("  orientation)"):]
    orientation = orientation[:orientation.index("    esac")]
    assert 'get("orientation"' not in orientation, "the hinge's orientation label is the device's, inverted on the inner display"
    assert "sizePoints" in orientation and "activeDisplay" in orientation and "capture.sh" in orientation
    assert "did not take effect" in sim, "rotate must verify the readback"
    assert '( set -e; "$fn" "$@" )' in rm and "set +e" in rm, "errexit is off inside `( ... ) || st=$?`"
    assert rm.count('|| exit "$DUO_EXIT_UI"') >= 2, "a failed run_steps must end the cell"
    assert "MAESTRO_WARNED" not in rm and "driver duoctl:" in rm
    assert "rerun-of.json" in rm
    assert "deadline" in pre and "sleep 2" in pre, "preflight retries the elements probe after a cold boot"
    assert "nothing gated" in perf


def test_field_test_4_contracts():
    """Things the fourth field test proved the scripts must do."""
    rm = open(os.path.join(SCRIPTS, "run-matrix.sh"), encoding="utf-8").read()
    perf = open(os.path.join(SCRIPTS, "perf.sh"), encoding="utf-8").read()
    lp = open(os.path.join(SCRIPTS, "loop.py"), encoding="utf-8").read()
    maestro = rm[rm.index("run_steps_maestro()"):rm.index("run_steps()")]
    assert "grep -m 1 -E 'Assertion is false:" in maestro, "the Maestro reason must name the failing step, not the generic hint"
    assert "tail -n 1" not in maestro.split("grep -m 1")[1].split("||")[0]
    assert "--promote" in perf and "promoted from run" in perf, "a baseline run is promoted, not measured twice"
    assert ".refused.txt" in perf, "a refused perf cell must reach perf.json"
    assert "last is None or" in lp, "a loop.json without last_run (0.3.0) is not this chain"
    assert "comes up portrait after an unfold (2007" not in rm, "stale field-test-2 comment"


def test_field_test_5_contracts():
    """Things the fifth field test proved the scripts must do."""
    assets = open(os.path.join(SCRIPTS, "assets.sh"), encoding="utf-8").read()
    report = open(os.path.join(SCRIPTS, "report.py"), encoding="utf-8").read()
    assert "pngio.flatten(" in assets, "simctl captures are RGBA; the export must flatten them or the gate rejects every file"
    assert "TODO-VERIFY" not in assets, "deliver's size-based device detection was read in its 2.241.2 source"
    assert "--write-baseline records" not in report and "--promote" in report
