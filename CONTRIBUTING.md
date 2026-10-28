# Contributing

## Mac verification: what is done and what the fourth iteration needs

Three field tests have run (27 and 28 Oct 2026, Xcode 27.1 build 27A9275, Expo SDK 54 app). The third ran 0.3.0 unpatched end to end: preflight with the `elements` probe, `add-duo-test-targets.rb` producing targets identical to hand-made ones, the matrix on a clean simulator and on a signed-in one with `--udid`, perf through `xcresulttool get test-results metrics`, report and loop; both real layout issues the second test had missed were caught. It also found that `sim.sh rotate` trusted the hinge's orientation label (inverted on the inner display, so no inner portrait cell was portrait) and that a failed flow step in a duoctl cell was ignored (bash errexit off inside `||`). 0.3.1 fixes both and has not run on a Mac itself. Open an issue titled "Mac verification <date>" and tick what passed, attaching `preflight.json` and the report.

Environment: macOS Tahoe 26.6+ or macOS 27, Xcode 27.1 (or 27.2 RC) with its Command Line Tools, iOS 27.1 runtime, Homebrew 7 with `brew trust` run for each third-party tap, `duoctl`, `hinge`, AXe, Maestro from the `mobile-dev-inc/tap` tap, fastlane 2.241.1+. Keep the project outside iCloud Drive.

Fourth iteration (still open):

- [ ] `/plugin marketplace update callbackcat` then `/plugin update duo-ready@callbackcat` lands 0.3.1; `${CLAUDE_SKILL_DIR}` ends in `0.3.1`.
- [ ] `bash scripts/preflight.sh --json` on a cold (shut down) simulator reports `"elements":"ok"` (the probe now retries for 30 s).
- [ ] `bash scripts/sim.sh orientation` on the open pose prints the window's orientation (`landscape` for a 2853 x 2007 capture), and `sim.sh rotate portrait` really rotates: the next capture is 2007 x 2853.
- [ ] `run-matrix.sh --run <n>`: `open-portrait` and `book-portrait` cells have a 669 x 951 window with `"window_source": "cell"`; `window_source: screenshot` appears on transition cells only (when the capture size differs from the nominal one).
- [ ] A flow with a deliberately wrong `wait` produces `.error.json` in an open or book cell too, not only in the Maestro closed cell; the Maestro reason names the failing selector.
- [ ] `run-matrix.sh --udid <sim> --driver duoctl` prints one `driver duoctl` line and no "maestro not installed" warning.
- [ ] `perf.sh --run <n>` on a project without a baseline prints `baseline recorded, nothing gated`, `perf.json` has `"status": "baseline"` and three `skip` rows for the transitions with a reason; `--write-baseline` then a second run gates `launch_ms`.
- [ ] `report.py --run <n>` is under 2 MB (JPEG thumbnails), lists perf under skipped stages when nothing was gated, and shows the transition skip rows.
- [ ] `loop.py --run <n>` on a fresh run starts at `1/3` and suggests an unused run number.
- [ ] The den's scroll indicator (`Slider`) no longer fails `tap_target_min` or `interactive_in_fold`; `bars_vertical_expected` skips on the den instead of warning.
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
