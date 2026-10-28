# Performance gates

Specification for `scripts/perf.sh`, `templates/DuoPerfTests.swift` and the `perf:` block of `duo.yaml`. Output format: `perf.json` in `pipeline-contracts.md`.

## Why gates at all

A fold resizes the app mid-session. Apps that recompute layout on every size change, reload data on trait changes, or rebuild view hierarchies when the size class flips will stutter exactly when the device is being opened, which is the moment people judge the app. The gates catch regressions introduced while fixing layout, not absolute device performance.

## Metrics (v1)

| Metric | Cells | How measured | Default gate |
|---|---|---|---|
| `launch_ms` | every pose cell | `XCTApplicationLaunchMetric` in `measure(metrics:)` around `XCUIApplication.launch()`, 5 iterations, median. This is the app's own launch (0.6 s for a small native app, 2.3 s for a Release Expo app, on the simulator). The `XCTClockMetric` around the same block is reported as `launch_wall_ms` and includes XCUITest setup, wait and terminate (about 5.8 s), so it is `info`, never gated; the first version of the template gated that number by mistake | warn 800, fail 1500 (absolute); regression: fail at +20% over baseline |
| `fold_relayout_ms` | every transition (`closed>open`, `open>book`, `open>closed`) | time from the pose command's confirmed angle to the first stable frame. The app under test emits `os_signpost` begin on `viewWillTransition(to:with:)` / `onGeometryChange` and end when `viewDidLayoutSubviews` runs twice with the same bounds; the template reads them through `XCTOSSignpostMetric`. Fallback when the app has no signposts: wall clock from confirmed angle to the first capture whose diff against the previous frame is under 0.5%. | fail 250 |
| `memory_delta_mb` | every transition (`testFoldRelayout`) | `XCTMemoryMetric` physical footprint before and after the transition (`Memory.physical`); `Memory.physical_peak` is reported as `memory_peak_mb`, info only. The same metric in `testLaunch` is the launch-to-terminate delta, about zero at 735% RSD (third field test), and is reported as info, never gated | warn 30 |
| `cpu_transition` | every transition | `XCTCPUMetric` during the 500 ms after the pose change | warn above 80% for over 500 ms |
| `hitch_rate` | scroll flows | `xcrun xctrace record --template 'Animation Hitches'` then `xctrace export`; hitches per second during the scroll steps | fail 5 (v1.1, not in v1) |

Every row carries `flow`, `cell`, `metric`, `value`, `unit`, `baseline`, `status`. `scripts/perfparse.py` names metrics from the test name plus the XCTest identifier (`com.apple.dt.XCTMetric_ApplicationLaunch-AppLaunch.duration`, `..._Clock.time.monotonic`, `..._Memory.physical`, `..._Memory.physical_peak`, `..._CPU.time`) and converts seconds to milliseconds and kB to MB.

## Regression versus absolute mode

`perf.mode: regression` (default): each value is compared with the project's own baseline for the same flow, cell and metric. Status is `fail` when the value exceeds the baseline by the metric's regression margin (20% for `launch_ms` and `fold_relayout_ms`, the `warn` absolute for memory), `warn` at half the margin, and `pass` otherwise. A missing baseline yields `status: baseline` with `baseline: null` on every gated metric and `status: baseline` on the document; `perf.sh` then prints `baseline recorded, nothing gated` instead of `pass`, and the report lists perf under skipped stages until `--write-baseline` records one.

`perf.mode: absolute` (or `--absolute`): values are compared with the `warn`/`fail` numbers in `duo.yaml`. Intended for physical devices.

The simulator shares the Mac's CPU, has no thermal envelope, renders through a different pipeline and reports memory differently, so absolute simulator numbers mean nothing; only deltas against the same machine's earlier runs do. The report prints the host model and Xcode version next to every perf table for that reason.

## Baselines

`.duo/baselines/perf.json` is a copy of a run's `perf.json` (`perf.sh --write-baseline`); `perfparse.py` reads its `metrics` list and matches rows on flow, cell and metric:

```json
{ "schema": 1, "run": 3, "mode": "regression",
  "metrics": [ { "flow": "*", "cell": "closed-portrait", "metric": "launch_ms", "value": 2265.0, "unit": "ms", "baseline": null, "status": "baseline" } ] }
```

`--write-baseline` overwrites after a run whose numbers look sane; the file is committed. A baseline recorded on a different host model or Xcode version is used but flagged in the report, because the comparison is weaker.

## Test template

`templates/DuoPerfTests.swift` has two tests: `testLaunch` runs in pose cells (the shell poses the simulator first and passes the cell as `TEST_RUNNER_DUO_CELL`, which the runner sees as `DUO_CELL`), `testFoldRelayout` in transition cells and only when `TEST_RUNNER_DUO_POSE_URL` points at a local hinge bridge (`simulator-control.md` section 9); otherwise it is skipped with a message, and the transition cells appear in `perf.json` as `status: skip` rows with that reason, so a missing `fold_relayout_ms` is explained rather than absent. The transition block:

```swift
let options = XCTMeasureOptions(); options.iterationCount = 3
measure(metrics: [XCTClockMetric(), XCTMemoryMetric(application: app), XCTCPUMetric(application: app)], options: options) {
    DuoBridge.pose("open")                 // confirmed by readback before returning
    XCTAssertTrue(app.staticTexts[stopLabel].waitForExistence(timeout: 5))
}
```

Results come out of the `.xcresult` bundle with `xcrun xcresulttool get test-results metrics --path <bundle>` (Xcode 27.1; the legacy `get --legacy --format json` root object has no measurements). `perf.sh` writes `<cell>.metrics.json` per cell, with `>` spelled `-to-` in file names, and `perfparse.py` maps the identifiers to the rows above. Expect 8 to 10 minutes for six pose cells (five launches each plus XCUITest setup). The target is added with `templates/add-duo-test-targets.rb`; the scheme's Test action must be Release for a React Native or Expo app.

## Device mode (later)

`--device <udid>` will run the same XCTest bundle on hardware through `xcodebuild test -destination 'platform=iOS,id=<udid>'`, where poses are physical and the tests prompt the operator ("fold to book, then press continue") between measurements. Absolute mode becomes meaningful there, and contributors with hardware can submit baselines tagged with the device model. Nothing in v1 depends on it; `perf.sh` exits 4 with "device mode not implemented" if the flag is passed.
