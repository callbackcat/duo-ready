# Contributing

## Mac verification: what is done and what the second iteration needs

The first field test (27 Oct 2026, Xcode 27.1 build 27A9275, Expo SDK 54 app) verified preflight, simulator boot, pose readback at 0, 127 and 180 degrees, rotation, per-display capture at the App Store pixel sizes, the SDK stamp and the UIScene launch kill. It could not verify the measuring half: AXe was not installed (every element tree empty) and the app had no `DuoPerfTests` target. Open an issue titled "Mac verification <date>" and tick what passed, attaching `preflight.json` and the report.

Environment: macOS Tahoe 26.6+ or macOS 27, Xcode 27.1 (or 27.2 RC) with its Command Line Tools, iOS 27.1 runtime, `brew install skarol/tap/duoctl artemnovichkov/tap/hinge`, `brew tap cameroncooke/axe && brew install axe`, Maestro, fastlane 2.241.1+. Keep the project outside iCloud Drive.

Second iteration (still open):

- [ ] `bash scripts/preflight.sh --json` reports `"axe":true` and `"maestro":true`.
- [ ] The app has a `SceneDelegate` (Expo: a config plugin, see `references/rules-react-native.md#expo-no-scene-lifecycle`) and `bash scripts/sim.sh launch <bundle id>` keeps it alive past 3 s.
- [ ] `templates/DuoUITests.swift` and `templates/DuoPerfTests.swift` compile in UI test targets named `DuoUITests` and `DuoPerfTests`.
- [ ] `run-matrix.sh --run <n>` with real flows (deep links plus accessibility ids), then `ui.json` has `"verified": true` and at least one non-empty tree per cell; attach the trees of one closed and one open cell so the assertion heuristics can be tuned.
- [ ] `perf.sh --run <n>` exits 0 or 2 with metrics in `perf.json` (not 4); attach one `.xcresult` JSON so the metric parser can be verified against a real bundle.
- [ ] `report.py --run <n>` exits 0 on a verified green run.
- [ ] `assets.sh --run <n>` then `fastlane deliver --skip_binary_upload --skip_metadata` uploads the outer set; try the inner set and record whether App Store Connect accepts it through the API.
- [ ] `templates/github-actions-duo.yml` on a macOS runner that carries Xcode 27.1.

Anything that failed: paste the exact error and the Xcode build number. A protocol change in `duoctl`/`hinge` shows as preflight exit 5; a cell the app refuses (portrait lock) shows as `<flow>-<cell>.skip.json`, not as a failure.

## Adding a rule

1. Add the entry to `scripts/rules/native.yaml` or `scripts/rules/react-native.yaml` (id, lang, severity, pattern, autofix, fix_hint, apple_ref, doc).
2. Add a positive site tagged `// duo: <rule-id>` to the matching fixture under `examples/`, and a negative case that must not match.
3. Add the section to `references/rules-*.md` with why it breaks on Duo and a before/after.
4. `python -m pytest tests/ -q`.

## Facts

Every number in `references/` carries a "Verified <date>" line and a source URL. If Apple's page changed (the weekly watch workflow opens an issue), update the number, the date and anything in `scripts/` that embeds it (`assert.py` geometry table, `assets_gate.py` sizes).
