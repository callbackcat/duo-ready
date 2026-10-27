# Pipeline contracts

Machine-readable formats shared by every script. Scripts read and write only these; the agent loop and the report depend on them being stable.

## Working directory

```
.duo/
├── env.json            # detect output: host + project facts
├── scan.json           # scan output
├── baselines/          # <flow>-<cell>.png, committed after the first green run
└── runs/<n>/
    ├── build.json      # app path, sdk stamp, scheme
    ├── captures/       # <flow>-<cell>.png and <flow>-<cell>.tree.json
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
cells: [closed-portrait, closed-landscape, open-landscape, open-portrait, book-landscape, book-portrait]
transitions: ["closed>open", "open>book", "open>closed"]
flows:
  - name: feed
    steps: [launch, wait "Feed", scroll 5]
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
tap "<accessibility label or id>"
wait "<label or id>"            # waits up to 10 s for the element
scroll <n>                      # n swipes up in the main scroll view
deeplink <url>
pose <closed|open|book>         # mid-flow transition
rotate <portrait|landscape>
sleep <seconds>
```

Native runner translates to XCUITest (template in `templates/DuoUITests.swift`); RN runner uses Maestro for closed cells and `duoctl tap --label` for open/book cells (Maestro misreports inner-display geometry, issue mobile-dev-inc/maestro#3617).

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
  "cells": [
    {
      "flow": "feed", "cell": "book-landscape",
      "screenshot": ".duo/runs/3/captures/feed-book-landscape.png",
      "tree": ".duo/runs/3/captures/feed-book-landscape.tree.json",
      "results": [
        { "assertion": "offscreen_elements", "status": "pass" },
        { "assertion": "interactive_in_fold", "status": "fail",
          "elements": [{ "id": "PlayButton", "frame": [440, 300, 60, 44] }] },
        { "assertion": "visual_diff", "status": "warn", "diff": 0.031, "threshold": 0.02 }
      ]
    }
  ]
}
```

Element tree format (`*.tree.json`): `{"elements":[{"id":"PlayButton","type":"button","label":"Play","frame":[x,y,w,h],"interactive":true,"text":"...","truncated":false}]}` in points, origin top-left of the app window.

## perf.json

```json
{ "schema": 1, "run": 3, "mode": "regression",
  "metrics": [
    { "flow": "feed", "cell": "closed-portrait", "metric": "launch_ms", "value": 612, "baseline": 590, "status": "pass" },
    { "flow": "feed", "cell": "closed>open", "metric": "fold_relayout_ms", "value": 310, "baseline": null, "status": "fail" }
  ] }
```

## failures.json (agent payload)

```json
[
  {
    "flow": "feed", "cell": "book-landscape", "assertion": "interactive_in_fold",
    "elements": [{ "id": "PlayButton", "frame": [440, 300, 60, 44] }],
    "screenshot": ".duo/runs/3/captures/feed-book-landscape.png",
    "matched_rule": "centered-grid-odd-columns",
    "source_hint": "Sources/PlayerView.swift:88",
    "fix_hint": "Keep interactive elements out of x 455–495 in book poses; use ReservedRegion or ArrangementView."
  }
]
```

`source_hint` is set when a scan finding's file name shares a stem with the failing screen's view id (`PlayButton` → `PlayerView.swift`). Otherwise null.

## Exit codes

`0` pass · `1` UI assertion failure · `2` perf failure · `3` build failure · `4` preflight failure (missing tool, wrong Xcode) · `5` pose control unavailable (private protocol changed).

Every script supports `--help` and `--json`, and prints a one-line `cannot run on this host: <reason>` with exit 4 when a required tool is missing. Scripts never fake a pass for a stage that didn't run.
