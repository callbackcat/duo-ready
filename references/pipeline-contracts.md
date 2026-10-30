# Pipeline contracts

Machine-readable formats shared by every script. Scripts read and write only these; the agent loop and the report depend on them being stable.

## Working directory

```
.duo/
├── env.json            # detect output: host + project facts
├── scan.json           # scan output
├── baselines/          # <flow>-<cell>.png, committed after the first green run
└── runs/<n>/
    ├── build.json      # app path, sdk stamp, scheme, configuration, derived_data, scene_manifest
    ├── captures/       # <flow>-<cell>.png and <flow>-<cell>.tree.json; <flow>-<cell>.skip.json for cells the app refused;
    │                   # <flow>-<cell>.error.json for cells whose flow step failed
    ├── thumbs/         # report thumbnails (240 px matrix, 720 px failures); the report links the full captures
    ├── perf/           # <cell>.metrics.json (xcresulttool test-results metrics), <cell>.xcresult, <cell>.log; ">" spelled "-to-"
    ├── ui.json         # assertion results
    ├── perf.json
    ├── failures.json   # agent payloads (ui + perf failures merged)
    └── duo-report.html
```

`duo.yaml` lives at the project root and is owned by the user.

## Cell names

`<pose>-<orientation>` with pose in `closed | open | book` and orientation in `portrait | landscape`, plus `split-view-left` and `split-view-right`. Transitions are written `closed>open`, `open>book`, `open>closed`.

Cell geometry (points, iOS 27.1 SDK) is in `references/device-facts.md`; `scripts/assert.py` carries the same table.

Transition captures are files, so the `>` is spelled `-to-` on disk: `<flow>-<from>-to-<to>.png`, with the element tree before the pose change in `<flow>-<from>-to-<to>.before.tree.json` and the tree after it in `<flow>-<from>-to-<to>.tree.json`. `ui.json` reports the cell as `closed>open`.

## duo.yaml

```yaml
stack: uikit                  # uikit | swiftui | mixed | react-native | expo | flutter | capacitor
scheme: MyApp
bundle_id: com.example.myapp
workspace: MyApp.xcworkspace  # or project: MyApp.xcodeproj
derived_data: ~/Library/Developer/Xcode/DerivedData/duo-ready-MyApp   # optional; default outside the project (iCloud breaks codesign)
xcodebuild_args: [IPHONEOS_DEPLOYMENT_TARGET=15.0]                  # optional; Xcode 27.1 refuses targets below iOS 15
cells: [closed-portrait, closed-landscape, open-landscape, open-portrait, book-landscape, book-portrait]
transitions: ["closed>open", "open>book", "open>closed"]
flows:
  - name: feed
    steps: [launch, wait "Feed", scroll 5]
  # detect.py scaffolds `- name: launch, steps: [launch, sleep 2], placeholder: true`;
  # SKILL.md asks for real flows while that flag is present
assert:
  offscreen_elements: fail    # fail | warn | off
  clipped_text: fail
  tap_target_min: 44
  bars_vertical_expected: warn
  content_under_outer_camera: fail
  interactive_in_fold: fail
  visual_diff_threshold: 0.02
perf:
  mode: regression            # regression | absolute
  launch_ms: { warn: 800, fail: 1500 }
  fold_relayout_ms: { fail: 250 }
  memory_delta_mb: { warn: 30 }
loop:
  max_iterations: 3
assets:
  locales: [en-US]
  output: fastlane/screenshots
```

## flows.yaml step grammar

One step per list item, Maestro-compatible verbs so RN users can reuse their flows:

```
launch
reset                           # clear app state (reinstall; Maestro clearState)
tap "<accessibility label>"     # tap id:<testID> for an identifier
wait "<label>"                  # waits up to 10 s; wait id:<testID> for an identifier (Maestro matches a
                                # bare string as text only, so ids must be written as id:)
scroll <n>                      # n swipes up in the main scroll view
deeplink <url>
pose <closed|open|book>         # mid-flow transition
rotate <portrait|landscape>
sleep <seconds>
```

Native runner translates to XCUITest (template in `templates/DuoUITests.swift`; the shell passes `TEST_RUNNER_DUO_FLOW`, `TEST_RUNNER_DUO_CELL`, `TEST_RUNNER_DUO_STEPS`, `TEST_RUNNER_DUO_TREE_OUT`, which xcodebuild delivers to the runner without the prefix); RN runner uses Maestro for closed cells and `duoctl tap --label` for open/book cells (Maestro misreports inner-display geometry, issue mobile-dev-inc/maestro#3617). `--driver duoctl` forces the duoctl interpreter for closed cells too (deeplink, wait, sleep; no taps on the outer display). `--udid <udid>` (or `DUOCTL_UDID`) drives an already booted simulator instead of the protected `duo-ready` one, for flows behind a sign-in.

A step that fails ends the cell, not the matrix: the runner writes `<flow>-<cell>.error.json` (`{"flow","cell","error":true,"reason"}`), `assert.py` records the cell with `errored: true` and one result `{"assertion":"flow","status":"fail","reason":...}`, and `failures.json` carries it with `assertion: "flow"`. This holds for every driver: Maestro cells, duoctl cells and native cells alike (0.3.0 let a failed `wait` in a duoctl cell pass; fixed in 0.3.1). Tool, build and pose failures (exit 3, 4, 5) still stop the run. `--only-failed` also writes `<run>/rerun-of.json` (`{"from": <run>, "failures": <path>}`), which `loop.py` uses to count iterations per rerun chain, and every run writes `<run>/matrix-args.json` (`{"udid": <udid or null when the default simulator was used>, "driver": <driver or null>, "skip_transitions": bool}`), which `loop.py` appends to the rerun command; `.duo/loop.json` records `last_run`, and a state without that key (written before 0.3.1) starts a new chain instead of inheriting its count.

## scan.json

```json
{
  "schema": 1,
  "generated": "2026-10-27T10:00:00Z",
  "stack": "uikit",
  "findings": [
    {
      "rule": "screen-main-bounds",
      "severity": "error",
      "autofix": true,
      "file": "Sources/FeedViewController.swift",
      "line": 42,
      "column": 18,
      "match": "UIScreen.main.bounds",
      "fix_hint": "Use view.bounds, window.bounds, or GeometryReader.",
      "apple_ref": "https://developer.apple.com/iphone-duo/prepare/"
    }
  ],
  "summary": { "error": 3, "warn": 5, "info": 2, "autofixable": 4 }
}
```

## Rule definition (scripts/rules/*.yaml)

```yaml
- id: screen-main-bounds
  lang: swift                 # swift | objc | js | ts | json | plist
  severity: error             # error | warn | info
  pattern: 'UIScreen\.main\.bounds'
  exclude: '^\s*//'           # optional; lines matching are skipped
  autofix: true
  replace: 'view.bounds'      # optional; literal replacement for autofix
  fix_hint: Use view.bounds, window.bounds, or SwiftUI GeometryReader / onGeometryChange.
  apple_ref: https://developer.apple.com/iphone-duo/prepare/
  doc: references/rules-native.md#screen-main-bounds
```

Patterns are Python regexes applied per line unless `multiline: true`. Comments and string literals are skipped by a lightweight lexer in `scan.py`.

## ui.json

```json
{
  "schema": 1,
  "run": 3,
  "sdk_stamp": "27.1",
  "verified": true,
  "cells": [
    {
      "flow": "feed", "cell": "book-landscape",
      "screenshot": ".duo/runs/3/captures/feed-book-landscape.png",
      "tree": ".duo/runs/3/captures/feed-book-landscape.tree.json",
      "tree_available": true,
      "results": [
        { "assertion": "offscreen_elements", "status": "pass" },
        { "assertion": "interactive_in_fold", "status": "fail",
          "elements": [{ "id": "PlayButton", "frame": [440, 300, 60, 44] }] },
        { "assertion": "visual_diff", "status": "warn", "diff": 0.031, "threshold": 0.02 }
      ]
    },
    {
      "flow": "feed", "cell": "closed-landscape", "screenshot": null, "tree": null,
      "skipped": true, "tree_available": false,
      "results": [{ "assertion": "cell", "status": "skip", "reason": "the app in front refused to rotate to landscape" }]
    }
  ],
  "summary": { "pass": 7, "warn": 1, "fail": 1, "skip": 2, "cells": 2, "unverified_cells": 0, "skipped_cells": 1 }
}
```

Element tree format (`*.tree.json`): `{"elements":[{"id":"PlayButton","type":"button","label":"Play","frame":[x,y,w,h],"interactive":true,"text":"...","truncated":false}], "source": "duoctl elements"|"xcuitest", "ancestry": false|true}` in points, origin top-left of the app window. `source` names the producer; `ancestry` is true only when elements carry `parent`/`scrollable` (XCUITest). AXe trees (`duoctl elements`, normalised by `scripts/tree.py`) are flat, list types capitalised (`Button`, `TextField`, `StaticText`, `Group`, `Application`), and report the root `Application` unrotated; `assert.py` marks interactivity by type, drops containers, and downgrades vertical-only overflow to `warn` when `ancestry` is false. Each cell in `ui.json` carries `tree_source`, `ancestry`, `window` and `window_source` (`cell` from the geometry table, or `screenshot` when the capture's pixel size says the display came up in the other orientation, as the inner display does right after an unfold).

When `duoctl elements` fails (AXe missing) or the DuoUITests attachment is absent, `run-matrix.sh` writes `{"source": "unavailable", "elements": []}` instead. `assert.py` then reports every tree-based assertion as `skip` with the reason, sets `tree_available: false` on the cell, and `verified` is true only when at least one cell had a tree. An empty tree is never a pass (first field test: 25 vacuous greens).

`<flow>-<cell>.skip.json` (`{"flow","cell","reason"}`) is written when the app refuses the cell, typically a portrait-locked app on the outer display (`sim.sh rotate` exit 6). The cell appears in `ui.json` with `skipped: true` and one `skip` result.

## build.json

```json
{ "schema": 1, "run": 3, "stack": "expo", "scheme": "MyApp", "configuration": "Release",
  "app": "/Users/me/Library/Developer/Xcode/DerivedData/duo-ready-MyApp/Build/Products/Release-iphonesimulator/MyApp.app",
  "bundle_id": "com.example.myapp", "sdk_stamp": "27.1", "log": ".duo/runs/3/build.log",
  "derived_data": "/Users/me/Library/Developer/Xcode/DerivedData/duo-ready-MyApp", "scene_manifest": true }
```

`scene_manifest: false` on a UIKit or React Native app built with SDK 27 means the app will be killed about 2 s after launch; `sim.sh launch` exits 3 when it sees "UIScene life cycle is required" in the system log.

## perf.json

```json
{ "schema": 1, "run": 3, "mode": "regression",
  "metrics": [
    { "flow": "*", "cell": "closed-portrait", "metric": "launch_ms", "value": 612.0, "unit": "ms", "baseline": 590, "status": "pass" },
    { "flow": "*", "cell": "closed-portrait", "metric": "launch_wall_ms", "value": 5810.0, "unit": "ms", "baseline": null, "status": "info" },
    { "flow": "*", "cell": "closed-portrait", "metric": "memory_peak_mb", "value": 50.9, "unit": "MB", "baseline": null, "status": "info" },
    { "flow": "*", "cell": "closed>open", "metric": "fold_relayout_ms", "value": 310.0, "unit": "ms", "baseline": null, "status": "baseline" },
    { "flow": "*", "cell": "open>book", "metric": "fold_relayout_ms", "value": null, "unit": "ms", "baseline": null, "status": "skip",
      "reason": "DuoPerfTests skipped testFoldRelayout: TEST_RUNNER_DUO_POSE_URL is not set (the skill ships no hinge bridge), so fold_relayout_ms and memory_delta_mb were not measured" }
  ],
  "status": "baseline", "gated": 0,
  "reason": "no .duo/baselines/perf.json: every gated metric is a candidate baseline, nothing was gated" }
```

Metric names come from the test name plus the XCTest metric identifier (`scripts/perfparse.py`): `launch_ms` is `XCTApplicationLaunchMetric` in `testLaunch`, `launch_wall_ms` the `XCTClockMetric` around the whole launch block (XCUITest setup included, so seconds; reported, never gated), `fold_relayout_ms` the clock metric in `testFoldRelayout`, `memory_delta_mb`/`memory_peak_mb` the memory metrics, `cpu_s` CPU time. Gated metrics are `launch_ms`, `fold_relayout_ms` and `memory_delta_mb` across a transition; the rest are `info`, including `memory_delta_mb` from `testLaunch`. Row statuses: `pass`, `warn`, `fail`, `info`, `baseline` (no baseline yet; the value becomes one on `--write-baseline`), `skip` (the cell ran and measured nothing, or the app refused its orientation, recorded by `perf.sh` as `<cell>.refused.txt`; `reason` says why). The document carries `status`: `fail`, `pass`, or `baseline` when no gated metric had a baseline to compare with (exit 0, but `perf.sh` says `nothing gated` and the report lists it as skipped), and `gated`, the number of rows that were compared. Source files are `<cell>.metrics.json` from `xcrun xcresulttool get test-results metrics --path <cell>.xcresult` (`>` spelled `-to-` on disk), with the legacy `<cell>.json` root object as a fallback for older toolchains.

With no `DuoPerfTests` target there is nothing to measure: `perf.sh` exits 4, writes `"metrics": [], "status": "skip", "reason": "..."`, and never writes a baseline. The `reason` distinguishes a missing target from a result bundle that carried no measurements although the log shows `measured [` lines. The report shows perf as skipped with that reason.

## failures.json (agent payload)

```json
[
  {
    "flow": "feed", "cell": "book-landscape", "assertion": "interactive_in_fold",
    "elements": [{ "id": "PlayButton", "frame": [440, 300, 60, 44] }],
    "screenshot": ".duo/runs/3/captures/feed-book-landscape.png",
    "matched_rule": "centered-grid-odd-columns",
    "source_hint": "Sources/PlayerView.swift:88",
    "source_confidence": "file",
    "fix_hint": "Keep interactive elements out of x 455–495 in book poses; use ReservedRegion or ArrangementView."
  },
  { "flow": "checkout", "cell": "open-landscape", "assertion": "flow", "elements": [], "screenshot": null,
    "reason": "step timed out: wait \"Pay\" (not in the element tree after 10 s)", "matched_rule": null, "source_hint": null,
    "fix_hint": "The flow did not reach its screen in this cell; fix the step or the app, this is not a layout result." }
]
```

`matched_rule` is only ever a rule that can cause that assertion (table in `assertions.md`). `source_confidence` is `file` when the finding's file stem matches the failing element's id or label, `rule` when only the rule type matches (a lead to check, not a diagnosis). Otherwise both are null. The second field test matched an unrelated provider file for every failure because the root element's id was the app name; that match is gone.

## Exit codes

`0` pass · `1` UI assertion failure or a flow step that failed, or nothing verified (`report.py` with no `ui.json`, or `verified: false`); for `loop.py`, payloads printed and another iteration expected · `2` perf failure · `3` build failure, or the app dies at launch · `4` preflight failure (missing tool, wrong Xcode, no `DuoPerfTests` target, no metrics); for `loop.py`, nothing to loop on (no `failures.json`, or an unverified run) · `5` pose control unavailable (private protocol changed) · `6` the app refused the cell (`sim.sh rotate` on a portrait-locked app, printed as `duo: refused:`; `run-matrix.sh` and `perf.sh` turn this into a skipped cell and continue).

Every script supports `--help` and `--json` (including on the exit-4 path), and prints a one-line `cannot run on this host: <reason>` with exit 4 when a required tool is missing. Scripts never fake a pass for a stage that didn't run, and a run that measured nothing is reported as `unverified` or `skip`, never as `pass`.
