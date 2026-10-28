# Contributing

## Mac verification: what is done and what the third iteration needs

Two field tests have run (27 and 28 Oct 2026, Xcode 27.1 build 27A9275, Expo SDK 54 app). Verified so far: plugin install, preflight, simulator boot, pose readback at 0, 127 and 180 degrees, rotation, per-display capture at the App Store pixel sizes, the SDK stamp, the UIScene launch kill, element trees through `duoctl elements`, both XCUITest templates compiling and running, and `DuoPerfTests` metrics in the result bundle. The second test found three blockers in 0.2.0 (`duoctl elements --json`, a SIGPIPE false "killed at launch", the legacy xcresult object without measurements); 0.3.0 ships the fixes from the hand patches made during that test and has not run end to end itself. Open an issue titled "Mac verification <date>" and tick what passed, attaching `preflight.json` and the report.

Environment: macOS Tahoe 26.6+ or macOS 27, Xcode 27.1 (or 27.2 RC) with its Command Line Tools, iOS 27.1 runtime, Homebrew 7 with `brew trust` run for each third-party tap, `duoctl`, `hinge`, AXe, Maestro from the `mobile-dev-inc/tap` tap, fastlane 2.241.1+. Keep the project outside iCloud Drive.

Third iteration (still open):

- [ ] `/plugin marketplace update callbackcat` then `/plugin update duo-ready@callbackcat` lands 0.3.0; `${CLAUDE_SKILL_DIR}` ends in `0.3.0`.
- [ ] `bash scripts/preflight.sh --json` reports `"axe":true`, `"maestro":true` and `"elements":"ok"`.
- [ ] `ruby templates/add-duo-test-targets.rb` on a fresh prebuild adds both targets and the scheme's Test action is Release; `xcodebuild build-for-testing` succeeds.
- [ ] `run-matrix.sh --run <n>` unpatched: `ui.json` has `"verified": true`, every closed cell has a non-empty tree with `"ancestry": false`, transition cells carry `"window_source": "screenshot"`, and a flow with a deliberately wrong `wait` produces one `.error.json` while the other cells still complete.
- [ ] `run-matrix.sh --udid <your simulator>` runs a signed-in flow with deep link plus `wait id:` only.
- [ ] `perf.sh --run <n>` exits 0 or 2 with `launch_ms` (from `XCTApplicationLaunchMetric`, hundreds of ms, not seconds) and `launch_wall_ms` as `info`; files are `closed-to-open.metrics.json`, never a name with `>`.
- [ ] `report.py --run <n>` is under 2 MB, links the full captures, and shows the perf `reason` when perf was skipped.
- [ ] `loop.py --run <n>` exits 4 on a run without `failures.json`, 1 with failures, and prints the `--only-failed` command.
- [ ] `assets.sh --run <n>` then `fastlane deliver --skip_binary_upload --skip_metadata` uploads the outer set; try the inner set and record whether App Store Connect accepts it through the API.
- [ ] `templates/github-actions-duo.yml` on a macOS runner that carries Xcode 27.1.

Anything that failed: paste the exact error and the Xcode build number. A protocol change in `duoctl`/`hinge` shows as preflight exit 5; a cell the app refuses (portrait lock) shows as `<flow>-<cell>.skip.json`; a flow step that failed shows as `<flow>-<cell>.error.json`; neither is an assertion failure. Attach trees and captures only after replacing app names, user names and copy text; the fixtures in `tests/fixtures/axe/` show the expected level of anonymisation.

## Adding a rule

1. Add the entry to `scripts/rules/native.yaml` or `scripts/rules/react-native.yaml` (id, lang, severity, pattern, autofix, fix_hint, apple_ref, doc).
2. Add a positive site tagged `// duo: <rule-id>` to the matching fixture under `examples/`, and a negative case that must not match.
3. Add the section to `references/rules-*.md` with why it breaks on Duo and a before/after.
4. `python -m pytest tests/ -q`.

## Facts

Every number in `references/` carries a "Verified <date>" line and a source URL. If Apple's page changed (the weekly watch workflow opens an issue), update the number, the date and anything in `scripts/` that embeds it (`assert.py` geometry table, `assets_gate.py` sizes).
