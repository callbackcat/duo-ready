# Performance gates

Specification for `scripts/perf.sh`, `templates/DuoPerfTests.swift` and the `perf:` block of `duo.yaml`. Output format: `perf.json` in `pipeline-contracts.md`.

## Why gates at all

A fold resizes the app mid-session. Apps that recompute layout on every size change, reload data on trait changes, or rebuild view hierarchies when the size class flips will stutter exactly when the device is being opened, which is the moment people judge the app. The gates catch regressions introduced while fixing layout, not absolute device performance.

## Metrics (v1)

| Metric | Cells | How measured | Default gate |
|---|---|---|---|
| `launch_ms` | every pose cell | `XCTClockMetric` around `XCUIApplication.launch()` in `measure(metrics:)`, 5 iterations, median | warn 800, fail 1500 (absolute); regression: fail at +20% over baseline |
| `fold_relayout_ms` | every transition (`closed>open`, `open>book`, `open>closed`) | time from the pose command's confirmed angle to the first stable frame. The app under test emits `os_signpost` begin on `viewWillTransition(to:with:)` / `onGeometryChange` and end when `viewDidLayoutSubviews` runs twice with the same bounds; the template reads them through `XCTOSSignpostMetric`. Fallback when the app has no signposts: wall clock from confirmed angle to the first capture whose diff against the previous frame is under 0.5%. | fail 250 |
| `memory_delta_mb` | every transition | `XCTMemoryMetric` physical footprint before and after the transition | warn 30 |
| `cpu_transition` | every transition | `XCTCPUMetric` during the 500 ms after the pose change | warn above 80% for over 500 ms |
| `hitch_rate` | scroll flows | `xcrun xctrace record --template 'Animation Hitches'` then `xctrace export`; hitches per second during the scroll steps | fail 5 (v1.1, not in v1) |

Every row carries `flow`, `cell`, `metric`, `value`, `baseline`, `status`.

## Regression versus absolute mode

`perf.mode: regression` (default): each value is compared with the project's own baseline for the same flow, cell and metric. Status is `fail` when the value exceeds the baseline by the metric's regression margin (20% for `launch_ms` and `fold_relayout_ms`, the `warn` absolute for memory), `warn` at half the margin, and `pass` otherwise. A missing baseline yields `pass` with `baseline: null` and the value becomes the new baseline on a green run.

`perf.mode: absolute` (or `--absolute`): values are compared with the `warn`/`fail` numbers in `duo.yaml`. Intended for physical devices.

The simulator shares the Mac's CPU, has no thermal envelope, renders through a different pipeline and reports memory differently, so absolute simulator numbers mean nothing; only deltas against the same machine's earlier runs do. The report prints the host model and Xcode version next to every perf table for that reason.

## Baselines

`.duo/baselines/perf.json`:

```json
{ "schema": 1, "host": "Mac16,1", "xcode": "27.1", "sdk_stamp": "27.1",
  "metrics": { "feed/closed-portrait/launch_ms": 590, "feed/closed>open/fold_relayout_ms": 180 } }
```

Keys are `<flow>/<cell>/<metric>`. `perf.sh --write-baseline` overwrites after a green run; the file is committed. A baseline recorded on a different host model or Xcode version is used but flagged in the report, because the comparison is weaker.

## Test template

`templates/DuoPerfTests.swift` generates one test per flow: launch measurement in each pose (pose set through the same local bridge the UI tests use, see `simulator-control.md` section 9), then the transition measurement block:

```swift
let options = XCTMeasureOptions(); options.iterationCount = 3
measure(metrics: [XCTClockMetric(), XCTMemoryMetric(application: app), XCTCPUMetric(application: app)], options: options) {
    DuoBridge.pose("open")                 // confirmed by readback before returning
    XCTAssertTrue(app.staticTexts[stopLabel].waitForExistence(timeout: 5))
}
```

Results come out of the `.xcresult` bundle with `xcrun xcresulttool get --format json`; `perf.sh` maps metric names to the rows above.

## Device mode (later)

`--device <udid>` will run the same XCTest bundle on hardware through `xcodebuild test -destination 'platform=iOS,id=<udid>'`, where poses are physical and the tests prompt the operator ("fold to book, then press continue") between measurements. Absolute mode becomes meaningful there, and contributors with hardware can submit baselines tagged with the device model. Nothing in v1 depends on it; `perf.sh` exits 4 with "device mode not implemented" if the flag is passed.
