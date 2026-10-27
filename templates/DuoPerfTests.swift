// DuoPerfTests.swift - duo-ready performance template.
//
// Add this file to a UI test target named `DuoPerfTests`. scripts/perf.sh runs
// it once per cell (and per transition) with DUO_CELL set and the simulator
// already posed. Metrics are read from the xcresult bundle by perf.sh.
//
// Simulator numbers are not device numbers. By default the pipeline treats
// them as a regression baseline for your own project; absolute thresholds are
// for `--device` runs on real hardware.
//
// Metric identifiers perf.sh looks for (substring match, see perf.sh NAME_MAP):
//   "launch"   XCTClockMetric around XCUIApplication.launch         -> launch_ms
//   "relayout" XCTClockMetric from pose change to stable frame       -> fold_relayout_ms
//   "memory"   XCTMemoryMetric across the transition                 -> memory_delta_mb
//   "cpu"      XCTCPUMetric across the transition                    -> cpu_pct

import XCTest

final class DuoPerfTests: XCTestCase {

    private var cell: String { ProcessInfo.processInfo.environment["DUO_CELL"] ?? "unknown" }
    private var isTransition: Bool { cell.contains(">") }

    /// Cold launch in the current pose. The simulator is posed by perf.sh before the test starts.
    func testLaunch() throws {
        try XCTSkipIf(isTransition, "launch is measured per pose, not per transition")
        let options = XCTMeasureOptions()
        options.iterationCount = 5
        measure(metrics: [XCTClockMetric(), XCTMemoryMetric()], options: options) {
            let app = XCUIApplication()
            app.launch()
            _ = app.windows.firstMatch.waitForExistence(timeout: 10)
            app.terminate()
        }
    }

    /// Fold/unfold re-layout: time from the pose change to the first stable frame,
    /// plus memory and CPU across it. Needs DUO_POSE_URL (local hinge bridge, see
    /// DuoUITests.swift) because XCUITest cannot move the hinge itself.
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
