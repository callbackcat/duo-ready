# Contributing

## Mac verification: what is done and what the sixth iteration needs

Five field tests have run (27 to 29 Oct 2026, Xcode 27.1 build 27A9275, Expo SDK 54 app). The fifth ran 0.3.2 unpatched over the changed paths only and proved the three 0.3.2 fixes: a fresh run printed `iteration 1/3` and the payloads (with `last_run` already present in `loop.json`, so the "no `last_run`" branch itself is still unproven), the broken Maestro flow's reason is `Assertion is false: id: duo-no-such-id is visible` character for character, and `perf.sh --promote` took 51 ms, cutting the perf step from 19 to 12 minutes with the refused cell as a skip row. It was also the first run to reach `assets.sh` on a real app, and the gate rejected all six of its own exports: `simctl io screenshot` writes RGBA PNGs and the export copied them as they were. 0.3.3 flattens captures to RGB on export (`pngio.flatten`), the report's baseline hint names `--promote`, and the fastlane naming question is closed from the 2.241.2 source (device type from pixel size, inner and outer in one `APP_IPHONE_DUO` set). No upload was made: the app is live and the project has no App Store Connect key. The fourth ran 0.3.1 unpatched and proved the two 0.3.1 fixes on the device: `sim.sh rotate portrait` really rotates the inner display (2007 x 2853 capture, `orientation` reads `portrait`), the inner portrait cells have a 669 x 951 window with `window_source: cell` and their own trees, and a failed `wait` in an open cell is an error cell with no capture. Also verified: cold preflight `elements: ok` (24 s), one `driver duoctl:` line on a signed-in simulator, perf `status: baseline` with transition skip rows and then `gated: 5` after a baseline, a 1.3 MB report with JPEG thumbnails, the den's scroll indicator gone from the assertions, the wardrobe grid caught in `open>book`, and a new real finding only a true portrait cell could reach (a hero button across the horizontal fold in `book-portrait`). It left three things, fixed in 0.3.2 and not yet run on a Mac: a `.duo/loop.json` written by 0.3.0 has no `last_run`, so a fresh run printed "cap 3 reached" instead of `1/3`; the Maestro reason carried Maestro's generic "Element selector may be incorrect" bullet instead of the `Assertion is false:` line; `--write-baseline` measured every cell a second time (19 minutes for the perf step), so `perf.sh --promote` now copies the run's file. Open an issue titled "Mac verification <date>" and tick what passed, attaching `preflight.json` and the report.

Environment: macOS Tahoe 26.6+ or macOS 27, Xcode 27.1 (or 27.2 RC) with its Command Line Tools, iOS 27.1 runtime, Homebrew 7 with `brew trust` run for each third-party tap, `duoctl`, `hinge`, AXe, Maestro from the `mobile-dev-inc/tap` tap, fastlane 2.241.1+. Keep the project outside iCloud Drive.

Sixth iteration (still open):

- [ ] `/plugin marketplace update callbackcat` then `/plugin update duo-ready@callbackcat` lands 0.3.3; `${CLAUDE_SKILL_DIR}` ends in `0.3.3`.
- [ ] `assets.sh --run <n>` on an existing run exports RGB PNGs (`00_iphone_duo_inner_...png` is colour type 2, `file` says "8-bit/color RGB"), prints "(6 flattened from RGBA to RGB)", passes the gate, writes `FEATURING.md` and prints the upload commands. Note the time per inner capture.
- [ ] `loop.py --run <n>` on a fresh run after deleting the `last_run` key from `.duo/loop.json` (counter left at 3) prints `iteration 1/3`.
- [ ] `report.py` on a baseline run names `perf.sh --promote` in the skipped stages.
- [ ] With the app owner's approval and an App Store Connect API key: `fastlane deliver --skip_binary_upload --skip_metadata` with the outer files only, then the inner files, and record whether App Store Connect accepts the inner set through the API.
- [ ] `templates/github-actions-duo.yml` on a macOS runner that carries Xcode 27.1.

Anything that failed: paste the exact error and the Xcode build number. A protocol change in `duoctl`/`hinge` shows as preflight exit 5; a cell the app refuses (portrait lock) shows as `<flow>-<cell>.skip.json`; a flow step that failed shows as `<flow>-<cell>.error.json`; neither is an assertion failure. Attach trees and captures only after replacing app names, user names and copy text; the fixtures in `tests/fixtures/axe/` show the expected level of anonymisation.

## Adding a rule

1. Add the entry to `scripts/rules/native.yaml` or `scripts/rules/react-native.yaml` (id, lang, severity, pattern, autofix, fix_hint, apple_ref, doc).
2. Add a positive site tagged `// duo: <rule-id>` to the matching fixture under `examples/`, and a negative case that must not match.
3. Add the section to `references/rules-*.md` with why it breaks on Duo and a before/after.
4. `python -m pytest tests/ -q`.

## Facts

Every number in `references/` carries a "Verified <date>" line and a source URL. If Apple's page changed (the weekly watch workflow opens an issue), update the number, the date and anything in `scripts/` that embeds it (`assert.py` geometry table, `assets_gate.py` sizes).
