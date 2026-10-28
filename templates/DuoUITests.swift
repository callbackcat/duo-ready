// DuoUITests.swift - duo-ready XCUITest tour template.
//
// Add this file to a UI test target named `DuoUITests` (File > New > Target >
// UI Testing Bundle, or templates/add-duo-test-targets.rb without Xcode).
// scripts/run-matrix.sh runs it once per flow x cell. xcodebuild forwards only
// TEST_RUNNER_-prefixed variables to a UI test runner, where they arrive
// without the prefix; the shell sets TEST_RUNNER_DUO_FLOW and so on, and the
// test reads:
//
//   DUO_FLOW      flow name (for attachment names)
//   DUO_CELL      cell name, e.g. "book-landscape"
//   DUO_STEPS     steps joined by U+001F (the flows.yaml grammar)
//   DUO_TREE_OUT  path where the element tree JSON should be written
//   DUO_POSE_URL  optional: base URL of a local pose bridge (see below)
//
// What it does: launches the app, interprets the steps, emits an os_signpost
// at every stop, waits for a stable frame, then writes the accessibility
// element tree in the references/pipeline-contracts.md format both to
// DUO_TREE_OUT (via the simulator's shared filesystem) and as an XCTAttachment.
//
// Pose changes: XCUITest has no API for the hinge, and the simulator ignores
// XCUIDevice.shared.orientation on iPhone Duo. The shell sets the pose with
// duoctl/hinge before launching the test. For a `pose` step inside a flow,
// the test calls a tiny local HTTP bridge (`GET <DUO_POSE_URL>/hinge?state=book`)
// if DUO_POSE_URL is set; tosbaha/duo-fold-control ships such a server
// (tools/duo-hinge-server.py). Without it the step is skipped with a message.

import XCTest
import os.signpost

final class DuoUITests: XCTestCase {

    private let log = OSLog(subsystem: "duo-ready", category: "flow")
    private var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = true
        app = XCUIApplication()
    }

    func testFlow() throws {
        let env = ProcessInfo.processInfo.environment
        let flow = env["DUO_FLOW"] ?? "flow"
        let cell = env["DUO_CELL"] ?? "unknown"
        let steps = (env["DUO_STEPS"] ?? "launch").split(separator: "\u{1F}").map(String.init)

        let signpostID = OSSignpostID(log: log)
        os_signpost(.begin, log: log, name: "duo.flow", signpostID: signpostID, "%{public}s %{public}s", flow, cell)

        for (index, step) in steps.enumerated() {
            run(step: step)
            os_signpost(.event, log: log, name: "duo.stop", "%{public}s step %d", flow, index)
        }

        waitForStableFrame()
        let tree = elementTree()
        attachTree(tree, name: "\(flow)-\(cell).tree.json")
        if let out = env["DUO_TREE_OUT"] {
            writeTree(tree, to: out)
        }
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = "\(flow)-\(cell).xctest.png"   // informational: XCUIScreen.main is the cover display on Duo
        shot.lifetime = .keepAlways
        add(shot)

        os_signpost(.end, log: log, name: "duo.flow", signpostID: signpostID)
    }

    // MARK: - Step interpreter (flows.yaml grammar)

    private func run(step: String) {
        let trimmed = step.trimmingCharacters(in: .whitespaces)
        let verb = String(trimmed.split(separator: " ", maxSplits: 1).first ?? "")
        var arg = trimmed.dropFirst(verb.count).trimmingCharacters(in: .whitespaces)
        if arg.hasPrefix("\"") && arg.hasSuffix("\"") && arg.count >= 2 {
            arg = String(arg.dropFirst().dropLast())
        }
        switch verb {
        case "launch":
            app.launch()
        case "tap":
            let element = find(arg)
            XCTAssertTrue(element.waitForExistence(timeout: 10), "tap: '\(arg)' not found")
            element.tap()
        case "wait":
            XCTAssertTrue(find(arg).waitForExistence(timeout: 10), "wait: '\(arg)' not found")
        case "scroll":
            let n = Int(arg) ?? 1
            let scrollable = app.scrollViews.firstMatch.exists ? app.scrollViews.firstMatch
                : (app.tables.firstMatch.exists ? app.tables.firstMatch : app.collectionViews.firstMatch)
            for _ in 0..<n { scrollable.swipeUp() }
        case "deeplink":
            if let url = URL(string: arg) {
                app.open(url)
            }
        case "pose":
            changePose(arg)
        case "rotate":
            // Silent no-op on iPhone Duo; left here so flows stay portable to other devices.
            XCUIDevice.shared.orientation = (arg == "landscape") ? .landscapeLeft : .portrait
        case "sleep":
            Thread.sleep(forTimeInterval: Double(arg) ?? 1)
        default:
            XCTFail("unknown step: \(step)")
        }
    }

    private func find(_ key: String) -> XCUIElement {
        let byId = app.descendants(matching: .any).matching(identifier: key).firstMatch
        if byId.exists { return byId }
        let pred = NSPredicate(format: "label == %@ OR title == %@ OR value == %@", key, key, key)
        return app.descendants(matching: .any).matching(pred).firstMatch
    }

    private func changePose(_ pose: String) {
        guard let base = ProcessInfo.processInfo.environment["DUO_POSE_URL"],
              let url = URL(string: "\(base)/hinge?state=\(pose)") else {
            print("duo: pose step '\(pose)' skipped: set DUO_POSE_URL to a local hinge bridge (tosbaha/duo-fold-control) to fold mid-test")
            return
        }
        let done = expectation(description: "pose")
        URLSession.shared.dataTask(with: url) { _, response, _ in
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            XCTAssertEqual(code, 200, "pose bridge returned \(code)")
            done.fulfill()
        }.resume()
        wait(for: [done], timeout: 10)
        Thread.sleep(forTimeInterval: 2.5)   // active display switches 1-2.5 s after the angle
        waitForStableFrame()
    }

    // MARK: - Stable frame

    /// Polls the window frame until it stops changing, so captures and trees
    /// are taken after the resize animation rather than during it.
    private func waitForStableFrame(timeout: TimeInterval = 5) {
        let window = app.windows.firstMatch
        var last = window.frame
        let deadline = Date().addingTimeInterval(timeout)
        var stable = 0
        while Date() < deadline && stable < 3 {
            Thread.sleep(forTimeInterval: 0.2)
            let now = window.frame
            stable = (now == last) ? stable + 1 : 0
            last = now
        }
    }

    // MARK: - Element tree (references/pipeline-contracts.md)

    private struct Node: Encodable {
        let id: String
        let type: String
        let label: String
        let frame: [Double]
        let interactive: Bool
        let text: String
        let truncated: Bool
    }

    private func elementTree() -> Data {
        let window = app.windows.firstMatch.frame
        let interactiveTypes: Set<XCUIElement.ElementType> = [.button, .link, .textField, .secureTextField, .switch, .slider, .tab, .tabBar, .segmentedControl, .cell, .toggle, .stepper, .picker]
        var nodes: [Node] = []
        let query = app.descendants(matching: .any)
        let count = min(query.count, 400)
        for i in 0..<count {
            let e = query.element(boundBy: i)
            guard e.exists, e.frame.width > 0, e.frame.height > 0 else { continue }
            let f = e.frame
            let text = (e.value as? String) ?? e.label
            nodes.append(Node(
                id: e.identifier.isEmpty ? e.label : e.identifier,
                type: typeName(e.elementType),
                label: e.label,
                frame: [f.minX - window.minX, f.minY - window.minY, f.width, f.height],
                interactive: interactiveTypes.contains(e.elementType) && e.isHittable,
                text: text,
                truncated: text.hasSuffix("…") || text.hasSuffix("...")
            ))
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let payload: [String: Any] = [
            "elements": nodes.map { n -> [String: Any] in
                ["id": n.id, "type": n.type, "label": n.label, "frame": n.frame, "interactive": n.interactive, "text": n.text, "truncated": n.truncated]
            },
            "window": [window.minX, window.minY, window.width, window.height],
            "source": "XCUITest",
        ]
        return (try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys])) ?? Data()
    }

    private func typeName(_ t: XCUIElement.ElementType) -> String {
        switch t {
        case .button: return "button"
        case .staticText: return "text"
        case .textField, .secureTextField, .textView: return "textField"
        case .image: return "image"
        case .tabBar: return "tabBar"
        case .tab: return "tab"
        case .toolbar: return "toolbar"
        case .navigationBar: return "navigationBar"
        case .cell: return "cell"
        case .switch, .toggle: return "switch"
        case .link: return "link"
        case .scrollView, .table, .collectionView: return "scroll"
        case .sheet: return "sheet"
        default: return "other"
        }
    }

    private func attachTree(_ data: Data, name: String) {
        let attachment = XCTAttachment(data: data, uniformTypeIdentifier: "public.json")
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func writeTree(_ data: Data, to path: String) {
        // The simulator shares the host filesystem, so an absolute host path works.
        do {
            try data.write(to: URL(fileURLWithPath: path))
        } catch {
            print("duo: could not write tree to \(path): \(error)")
        }
    }
}
