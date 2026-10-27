# Contributing

## First task for anyone with a Mac: run the verification checklist

The repository was authored without Xcode. These items are the gap between "tested on Windows" and "verified on hardware the skill targets". Open an issue titled "Mac verification <date>" and tick what passed, attaching `preflight.json` and the report.

Environment: macOS Tahoe 26.6+, Xcode 27.1 (or 27.2 RC), iOS 27.1 runtime, `brew install skarol/tap/duoctl artemnovichkov/tap/hinge`, fastlane 2.241.1+.

- [ ] `bash scripts/preflight.sh --json` exits 0; note the Xcode build, duoctl and hinge versions it printed.
- [ ] `bash scripts/sim.sh ensure` boots an iPhone Duo simulator closed.
- [ ] `bash scripts/sim.sh pose open && bash scripts/sim.sh wait-posture open` reads back 180 degrees within 5 s; same for `book` (127) and `closed` (0).
- [ ] `bash scripts/capture.sh out.png --cell open-landscape` produces a non-black 2853x2007 or 2007x2853 PNG (note which orientation the inner capture comes out in).
- [ ] `bash scripts/sdk-stamp.sh <App.app>` reports 27.1 for an app built with Xcode 27.1 and 27.0 when built with `SDKROOT` pointed at the 27.0 SDK.
- [ ] `templates/DuoUITests.swift` and `templates/DuoPerfTests.swift` compile in a fresh UI test target.
- [ ] Full run on a real app: `build.sh`, `run-matrix.sh --run 1`, `perf.sh --run 1`, `report.py --run 1`; attach the report.
- [ ] `assets.sh --run 1` then `fastlane deliver --skip_binary_upload --skip_metadata` uploads the outer set; try the inner set and record whether App Store Connect accepts it through the API.
- [ ] `templates/github-actions-duo.yml` on a macOS runner that carries Xcode 27.1.

Anything that failed: paste the exact error and the Xcode build number. A protocol change in `duoctl`/`hinge` shows as preflight exit 5.

## Adding a rule

1. Add the entry to `scripts/rules/native.yaml` or `scripts/rules/react-native.yaml` (id, lang, severity, pattern, autofix, fix_hint, apple_ref, doc).
2. Add a positive site tagged `// duo: <rule-id>` to the matching fixture under `examples/`, and a negative case that must not match.
3. Add the section to `references/rules-*.md` with why it breaks on Duo and a before/after.
4. `python -m pytest tests/ -q`.

## Facts

Every number in `references/` carries a "Verified <date>" line and a source URL. If Apple's page changed (the weekly watch workflow opens an issue), update the number, the date and anything in `scripts/` that embeds it (`assert.py` geometry table, `assets_gate.py` sizes).
