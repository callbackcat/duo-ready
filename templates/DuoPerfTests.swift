// DuoPerfTests.swift - duo-ready performance template.
//
// Add this file to a UI test target named `DuoPerfTests` (templates/add-duo-test-targets.rb
// does it without opening Xcode). scripts/perf.sh runs it once per cell (and
// per transition) with the simulator already posed and the cell name passed
// as TEST_RUNNER_DUO_CELL. xcodebuild forwards only TEST_RUNNER_-prefixed
// variables to a UI test runner, where they arrive without the prefix
// (verified 28 Oct 2026: a plain DUO_CELL never reached the test). Metrics are
// read from the xcresult bundle by scripts/perfparse.py.
//
// Simulator numbers are not device numbers. By default the pipeline treats
// them as a regression baseline for your own project; absolute thresholds are
// for `--device` runs on real hardware.
//
// Metric identifiers perfparse.py looks for (by test name + metric identifier):
//   testLaunch        XCTApplicationLaunchMetric  -> launch_ms        (app launch itself)
//                     XCTClockMetric              -> launch_wall_ms   (whole measure block incl. XCUITest setup; reported, not gated)
//                     XCTMemoryMetric             -> memory_peak_mb / memory_delta_mb
//   testFoldRelayout  XCTClockMetric              -> fold_relayout_ms
//                     XCTMemoryMetric, XCTCPUMetric -> memory_delta_mb, cpu_s

import XCTest

final class DuoPerfTests: XCTestCase {

    private var cell: String { ProcessInfo.processInfo.environment["DUO_CELL"] ?? "unknown" }
    private var isTransition: Bool { cell.contains(">") }

    /// Cold launch in the current pose. The simulator is posed by perf.sh before the test starts.
    func testLaunch() throws {
        try XCTSkipIf(isTransition, "launch is measured per pose, not per transition")
        let options = XCTMeasureOptions()
        options.iterationCount = 5
        let app = XCUIApplication()
        measure(metrics: [XCTApplicationLaunchMetric(), XCTClockMetric(), XCTMemoryMetric()], options: options) {
            app.launch()
            _ = app.windows.firstMatch.waitForExistence(timeout: 10)
            app.terminate()
        }
    }

    /// Fold/unfold re-layout: time from the pose change to the first stable frame,
    /// plus memory and CPU across it. Needs DUO_POSE_URL (local hinge bridge, see
    /// DuoUITests.swift) because XCUITest cannot move the hinge itself; perf.sh
    /// passes TEST_RUNNER_DUO_POSE_URL through when DUO_POSE_URL is set.
    func testFoldRelayout() throws {
        try XCTSkipUnless(isTransition, "relayout is measured on transitions such as closed>open")
        guard let base = ProcessInfo.processInfo.environment["DUO_POSE_URL"] else {
            throw XCTSkip("set DUO_POSE_URL to a local hinge bridge to measure fold re-layout")
        }
        let parts = cell.split(separator: ">").map(String.init)
        let from = parts.first ?? "closed", to = parts.last ?? "open"

        let app = XCUIApplication()
        app.launch()
        _ = app.windows.firstMatch.waitForExistence(timeout: 10)

        let options = XCTMeasureOptions()
        options.iterationCount = 3
        measure(metrics: [XCTClockMetric(), XCTMemoryMetric(application: app), XCTCPUMetric(application: app)], options: options) {
            setPose(to, bridge: base)
            waitForStableFrame(app)
            stopMeasuring()
            setPose(from, bridge: base)   // reset outside the measured region
            waitForStableFrame(app)
        }
    }

    private func setPose(_ pose: String, bridge: String) {
        guard let url = URL(string: "\(bridge)/hinge?state=\(pose)") else { return }
        let done = expectation(description: "pose \(pose)")
        URLSession.shared.dataTask(with: url) { _, _, _ in done.fulfill() }.resume()
        wait(for: [done], timeout: 10)
    }

    private func waitForStableFrame(_ app: XCUIApplication, timeout: TimeInterval = 5) {
        let window = app.windows.firstMatch
        var last = window.frame
        let deadline = Date().addingTimeInterval(timeout)
        var stable = 0
        while Date() < deadline && stable < 3 {
            Thread.sleep(forTimeInterval: 0.1)
            let now = window.frame
            stable = (now == last) ? stable + 1 : 0
            last = now
        }
    }
}
