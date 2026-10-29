# Contributing

## Mac verification: what is done and what the fifth iteration needs

Four field tests have run (27 and 28 Oct 2026, Xcode 27.1 build 27A9275, Expo SDK 54 app). The fourth ran 0.3.1 unpatched and proved the two 0.3.1 fixes on the device: `sim.sh rotate portrait` really rotates the inner display (2007 x 2853 capture, `orientation` reads `portrait`), the inner portrait cells have a 669 x 951 window with `window_source: cell` and their own trees, and a failed `wait` in an open cell is an error cell with no capture. Also verified: cold preflight `elements: ok` (24 s), one `driver duoctl:` line on a signed-in simulator, perf `status: baseline` with transition skip rows and then `gated: 5` after a baseline, a 1.3 MB report with JPEG thumbnails, the den's scroll indicator gone from the assertions, the wardrobe grid caught in `open>book`, and a new real finding only a true portrait cell could reach (a hero button across the horizontal fold in `book-portrait`). It left three things, fixed in 0.3.2 and not yet run on a Mac: a `.duo/loop.json` written by 0.3.0 has no `last_run`, so a fresh run printed "cap 3 reached" instead of `1/3`; the Maestro reason carried Maestro's generic "Element selector may be incorrect" bullet instead of the `Assertion is false:` line; `--write-baseline` measured every cell a second time (19 minutes for the perf step), so `perf.sh --promote` now copies the run's file. Open an issue titled "Mac verification <date>" and tick what passed, attaching `preflight.json` and the report.

Environment: macOS Tahoe 26.6+ or macOS 27, Xcode 27.1 (or 27.2 RC) with its Command Line Tools, iOS 27.1 runtime, Homebrew 7 with `brew trust` run for each third-party tap, `duoctl`, `hinge`, AXe, Maestro from the `mobile-dev-inc/tap` tap, fastlane 2.241.1+. Keep the project outside iCloud Drive.

Fifth iteration (still open):

- [ ] `/plugin marketplace update callbackcat` then `/plugin update duo-ready@callbackcat` lands 0.3.2; `${CLAUDE_SKILL_DIR}` ends in `0.3.2`.
- [ ] `loop.py --run <n>` on a fresh run, with the project's existing `.duo/loop.json` (written by 0.3.0 or 0.3.1, counter at 3), prints the payloads and `iteration 1/3`, and `.duo/loop.json` gains `last_run`.
- [ ] The broken Maestro flow's reason reads `maestro flow <f> failed: Assertion is false: id: <selector> is visible`, not the "Element selector may be incorrect" bullet.
- [ ] `perf.sh --promote --run <n>` right after a `baseline recorded, nothing gated` run writes `.duo/baselines/perf.json` in about a second; the next `perf.sh --run <n>` prints `perf: pass` with `gated` > 0. Two perf runs in all, not three.
- [ ] The refused `closed-landscape` cell is a `skip` row in `perf.json` (reason "refused the landscape orientation") and in the report's perf table.
- [ ] `DUO-TODO.md` (reach the cap on purpose with `--max-iterations 1` twice): a rule-level lead reads "lead only", never "at `None`", and the `tap_target_min` fix text is the 44 pt hint, not the rule's hero-height hint.
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
