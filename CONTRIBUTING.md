# Contributing

## Verification on a Mac

The pipeline has run end to end on a production Expo SDK 54 app (macOS 27.0.1, Xcode 27.1 build 27A9275, iOS 27.1 runtime, duoctl 0.2.0, hinge 0.3.0, AXe, Maestro, Claude Code 2.1.212): preflight on cold and booted simulators, pose readback at 0, 127 and 180 degrees, rotation on both displays, captures at all three Duo sizes, element trees through `duoctl elements`, the two XCUITest targets added by `add-duo-test-targets.rb`, the matrix on a clean and on a signed-in simulator, error cells for failed flow steps, perf through `xcresulttool get test-results metrics` with a promoted baseline, the report, the loop (fix, rerun only the failed cells, green), and the screenshot export with its size and alpha gate.

Not yet exercised on a real project: a native UIKit or SwiftUI app end to end (the XCUITest tree source and the native rules on a real codebase), Split View cells, and `templates/github-actions-duo.yml` on a macOS runner with Xcode 27.1. If you run any of these, open an issue titled "Mac verification <date>" with what passed and what did not.

Environment: macOS Tahoe 26.6+ or macOS 27, Xcode 27.1 (or 27.2 RC) with its Command Line Tools, iOS 27.1 runtime, Homebrew 7 with `brew trust` run for each third-party tap, `duoctl`, `hinge`, AXe, Maestro from the `mobile-dev-inc/tap` tap. Keep the project outside iCloud Drive.

Reporting a failure: paste the exact error and the Xcode build number. A protocol change in `duoctl`/`hinge` shows as preflight exit 5; a cell the app refuses (portrait lock) shows as `<flow>-<cell>.skip.json`; a flow step that failed shows as `<flow>-<cell>.error.json`; neither is an assertion failure. Attach trees and captures only after replacing the app name, user names and every piece of copy; the fixtures in `tests/fixtures/axe/` show the expected level of anonymisation (testIDs kept, text replaced by numbered placeholders).

## Adding a rule

1. Add the entry to `scripts/rules/native.yaml` or `scripts/rules/react-native.yaml` (id, lang, severity, pattern, autofix, fix_hint, apple_ref, doc).
2. Add a positive site tagged `// duo: <rule-id>` to the matching fixture under `examples/`, and a negative case that must not match.
3. Add the section to `references/rules-*.md` with why it breaks on Duo and a before/after.
4. `python -m pytest tests/ -q`.

## Facts

Every number in `references/` carries a "Verified <date>" line and a source URL. If Apple's page changed (the weekly watch workflow opens an issue), update the number, the date and anything in `scripts/` that embeds it (`assert.py` geometry table, `assets_gate.py` sizes).
