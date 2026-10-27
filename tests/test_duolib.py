import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import duolib  # noqa: E402

SAMPLE = """
# duo.yaml sample
stack: react-native
scheme: MyApp
bundle_id: com.example.myapp
cells: [closed-portrait, "open-landscape", book-portrait]
transitions: ["closed>open", "open>book"]
flows:
  - name: onboarding
    steps: [launch, tap "Get started", wait "Welcome"]
  - name: feed
    steps:
      - launch
      - wait "Feed"
      - scroll 5
assert:
  offscreen_elements: fail   # trailing comment
  tap_target_min: 44
  visual_diff_threshold: 0.02
perf:
  mode: regression
  launch_ms: { warn: 800, fail: 1500 }
loop:
  max_iterations: 3
empty:
flag: true
url: https://developer.apple.com/iphone-duo/prepare/
"""


def test_parse_sample():
    doc = duolib.parse_yaml(SAMPLE)
    assert doc["stack"] == "react-native"
    assert doc["cells"] == ["closed-portrait", "open-landscape", "book-portrait"]
    assert doc["transitions"] == ["closed>open", "open>book"]
    assert doc["flows"][0] == {"name": "onboarding", "steps": ["launch", 'tap "Get started"', 'wait "Welcome"']}
    assert doc["flows"][1]["steps"] == ["launch", 'wait "Feed"', "scroll 5"]
    assert doc["assert"]["offscreen_elements"] == "fail"
    assert doc["assert"]["tap_target_min"] == 44
    assert doc["assert"]["visual_diff_threshold"] == 0.02
    assert doc["perf"]["launch_ms"] == {"warn": 800, "fail": 1500}
    assert doc["loop"]["max_iterations"] == 3
    assert doc["empty"] is None
    assert doc["flag"] is True
    assert doc["url"] == "https://developer.apple.com/iphone-duo/prepare/"


def test_rule_list_of_maps():
    text = """
- id: screen-main-bounds
  lang: swift
  severity: error
  pattern: 'UIScreen\\.main\\.bounds'
  autofix: true
  fix_hint: Use view.bounds, window.bounds, or GeometryReader.
- id: second
  lang: js
  severity: warn
  pattern: "Dimensions\\\\.get\\\\('window'\\\\)"
  autofix: false
"""
    rules = duolib.parse_yaml(text)
    assert len(rules) == 2
    assert rules[0]["pattern"] == r"UIScreen\.main\.bounds"
    assert rules[0]["autofix"] is True
    assert rules[1]["pattern"] == r"Dimensions\.get\('window'\)"
    assert rules[1]["severity"] == "warn"


def test_tabs_rejected():
    with pytest.raises(duolib.YAMLError):
        duolib.parse_yaml("a:\n\tb: 1\n")


def test_roundtrip_dump():
    doc = {
        "stack": "uikit",
        "cells": ["closed-portrait", "open-landscape"],
        "flows": [{"name": "feed", "steps": ["launch", 'wait "Feed"']}],
        "assert": {"tap_target_min": 44, "visual_diff_threshold": 0.02},
        "perf": {"mode": "regression", "launch_ms": {"warn": 800, "fail": 1500}},
    }
    text = duolib.dump_yaml(doc)
    back = duolib.parse_yaml(text)
    assert back == doc


def test_exit_codes_contract():
    assert duolib.exit_codes.PASS == 0
    assert duolib.exit_codes.UI_FAIL == 1
    assert duolib.exit_codes.PERF_FAIL == 2
    assert duolib.exit_codes.BUILD_FAIL == 3
    assert duolib.exit_codes.PREFLIGHT_FAIL == 4
    assert duolib.exit_codes.POSE_UNAVAILABLE == 5
