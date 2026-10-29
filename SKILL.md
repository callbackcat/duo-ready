---
name: duo-ready
description: Make an existing iOS app (UIKit, SwiftUI, React Native, Expo) ready for iPhone Duo end to end - scan the code for resizing breakages, apply fixes, build with the iOS 27.1 SDK, test every pose (closed, open, book, rotated, Split View) on the iPhone Duo simulator, gate performance, and generate the App Store screenshots that become mandatory in April 2027. Use this skill whenever the user mentions iPhone Duo, a foldable iPhone, fold/unfold, hinge, inner or outer display, vertical toolbars or tab bars, Duo screenshots, the "optimized for iPhone Duo" badge, size classes on iPhone, UIScreen.main warnings, Device Hub poses, or getting an iOS app through App Store submission after April 2027, even when they never say "Duo".
---

# duo-ready

You are helping an iOS developer make an existing app adapt to iPhone Duo and prove it, with evidence, in every pose. Apple's own "App Resizability" skill finds code patterns; this skill goes further by applying fixes, running the app in every pose on the simulator, measuring layout and performance, looping on failures, and producing the store assets. Every stage writes machine-readable output under `.duo/` (formats in `references/pipeline-contracts.md`), so you can resume, re-run only failed cells, and show the user exactly what was and wasn't verified.

**Where things live.** This skill's scripts and references sit in the skill directory, not in the user's app. That directory is `${CLAUDE_SKILL_DIR}` (the folder holding this SKILL.md: the plugin cache `~/.claude/plugins/cache/callbackcat/duo-ready/<version>` when installed as a plugin, or `~/.claude/skills/duo-ready` when copied by hand). Installed as a plugin the skill is listed as `duo-ready:duo-ready`. The app is the current working directory. Export the skill path once and run every script from the app root:

```bash
DUO="${CLAUDE_SKILL_DIR}"   # the directory that contains this SKILL.md
cd /path/to/the/app
bash "$DUO/scripts/preflight.sh"
```

All commands below assume `$DUO` is set. Reference paths such as `references/device-facts.md` are relative to the skill directory too.

Facts you need before touching code are in `references/device-facts.md`. Read it once per session; the numbers there (window sizes per SDK, fold region, size classes per pose) are what the assertions use.

## Ground rules

- **Never claim apps will be removed.** The rule is: from April 2027, every App Store submission of an app built with the iOS 27.1 SDK or later must include iPhone Duo screenshots. Submitting them now earns the "optimized for iPhone Duo" badge. Say exactly that.
- **Never fake a stage.** Simulator and store stages need macOS, Xcode 27.1, the iOS 27.1 runtime, and the `duoctl`/`hinge` tools. If any is missing, run what you can (detect, scan, fix, plan) and list the skipped stages by name in your summary.
- **Pose control is a private protocol.** `duoctl` and `hinge` send the same HID event Device Hub sends. `scripts/preflight.sh` proves the angle reads back before any pose stage; exit code 5 means the protocol changed and poses must be set by hand in Device Hub (`references/simulator-control.md`).
- **One commit per rule** on branch `duo-ready`, message `duo: fix <rule-id> (<n> sites)`, so the PR is reviewable rule by rule.
- **Confirm before destructive steps**: creating the branch, applying autofixes, overwriting baselines, writing into `fastlane/`.

## Workflow

Work through the stages in order. Each stage says which reference to open and what to show the user.

### 0. Preconditions

Run `bash "$DUO/scripts/preflight.sh" --json`. It checks macOS, Xcode 27.1+, the iOS 27.1 runtime, the Duo device type, `duoctl`, `hinge`, fastlane 2.241.1+, Maestro and AXe, and then boots a simulator and proves pose readback.

- Exit 0: continue. Read the `warnings` and `elements` fields. `elements` is `ok` only when one real `duoctl elements` call returned a list; `failed` means every tree in stage 5 will be unavailable and the run can only report "unverified", so fix that first (AXe: `brew tap cameroncooke/axe && brew trust cameroncooke/axe && brew install axe`). Without Maestro (`brew tap mobile-dev-inc/tap && brew trust mobile-dev-inc/tap && brew install mobile-dev-inc/tap/maestro`; not the unrelated `maestro` cask, and the curl installer is refused by agent sandboxes) React Native closed-pose flows fall back to launch, deep link, wait and sleep. Install both before a run that is meant to prove anything. Homebrew 7 refuses third-party taps until `brew trust` has been run for them; every hint the scripts print includes that step.
- Exit 4: a tool is missing. Print the install hint it gives (`brew tap skarol/tap artemnovichkov/tap && brew trust skarol/tap artemnovichkov/tap && brew install skarol/tap/duoctl artemnovichkov/tap/hinge`, Xcode 27.1 from the developer site, `xcodebuild -downloadPlatform iOS`) and continue with stages 1 to 3 only. On macOS 27 Homebrew needs the Command Line Tools for Xcode 27 first (Software Update or `xcode-select --install`); that download alone took 13 minutes on the first field test.
- Exit 5: pose control is broken on this Xcode. Continue with stages 1 to 3; for stage 5 tell the user how to set poses in Device Hub by hand and capture with `scripts/capture.sh`.
- Not macOS at all: say so once, do stages 1 to 3, and write the plan for the rest.

### 1. Detect

Run `python3 "$DUO/scripts/detect.py"`. It writes `.duo/env.json` and scaffolds `duo.yaml` (stack, scheme, bundle id, orientation locks, test targets, store tooling). Show the user the scaffold and confirm stack and scheme. If `duo.yaml` has no flows, or only the scaffolded `launch` flow marked `placeholder: true`, ask for 2 to 5 short flows that reach the screens that matter (feed, player, settings, onboarding). A launch-only flow captures whatever screen the app restores, which on the first field test was the same onboarding screen in every cell. Grammar is in `templates/flows.yaml`; Maestro verbs so RN users can paste existing flows. Flows that must run on the inner display should use deep links and accessibility ids, because `duoctl tap` only reaches the lit inner display. Write `wait id:<testID>` for ids (Maestro matches a bare string as text, not as an id) and start flows that need a fresh state with `reset`; it uninstalls and reinstalls the app, so it never belongs in a flow that will run on a signed-in simulator (next paragraph).

Flows behind a sign-in cannot be driven by the runner (nothing types a password). Run them on the developer's own signed-in simulator with `--udid <udid>` on `run-matrix.sh` and `perf.sh`, with deep links and waits only (no `reset`, no taps), and say in the summary that those cells ran on a shared simulator. Never ask for credentials.

### 2. Scan

Run `python3 "$DUO/scripts/scan.py"`. It writes `.duo/scan.json` and prints a table grouped by rule. Present the findings grouped by rule with counts, severity, and whether an autofix exists. For every rule the user asks about, open the matching section in `references/rules-native.md` or `references/rules-react-native.md`: each has the reason it breaks on Duo and a before/after.

Explain the three SDK tiers when relevant: built with iOS 26 the app runs boxed; iOS 27.0 fills the display but keeps horizontal bars; iOS 27.1 goes edge to edge and moves toolbars and tab bars to the vertical trailing edge. The scan's `custom-bar-class`, `toolbar-item-no-symbol`, and `no-scene-delegate` rules exist because those three things silently prevent the 27.1 behaviour.

Two findings are launch blockers, not layout advice, and must be fixed before stage 4: `no-scene-delegate` and `expo-no-scene-lifecycle`. An app built with the iOS 27 SDK and no UIScene life cycle is killed by UIKit about 2 s after launch (verified 27 Oct 2026 on Expo SDK 54 / React Native 0.81, whose templates ship without one). For Expo the fix is a config plugin plus a `SceneDelegate`; the recipe is in `references/rules-react-native.md#expo-no-scene-lifecycle`. The scan skips a gitignored `ios/` in Expo projects because `expo prebuild` regenerates it; findings there belong in `app.json` or a plugin.

The outer display is 678 pt tall, shorter than any current iPhone. On the first field test every real outer-display bug was a height bug (a fixed hero, a 60 percent window-height block, `adjustsFontSizeToFit` with a fixed `lineHeight` shrinking a title to 4 pt). The `rn-fixed-height`, `rn-window-height-fraction` and `rn-adjusts-font-fixed-lineheight` rules cover those; read screens with the 678 pt height in mind even where no rule fires.

### 3. Fix

1. `python3 "$DUO/scripts/scan.py" --fix --dry-run` prints the unified diff of all literal autofixes. Show it.
2. On approval, create branch `duo-ready` and run `python3 "$DUO/scripts/scan.py" --fix --apply`. It refuses a dirty tree; commit or stash first.
3. For manual findings, patch each site yourself. Read the rule's section first; the fix is usually "read geometry from the view or scene, not the screen, and read it on every layout". Keep edits minimal and commit per rule.
4. Re-run the scan to confirm the count dropped. Findings marked `info` are advice, not blockers.

Prefer Apple's adaptive containers over custom layout math: `NavigationSplitView`/`UISplitViewController`, `TabView`/`UITabBarController`, `ArrangementView`/`UIArrangementViewController` for two-pane content, `ReservedRegion` queries for anything custom near the fold. The API map by job is in `references/apple-guidance.md`.

### 4. Build and SDK stamp

Run `bash "$DUO/scripts/build.sh"`. It builds for the simulator, locates the `.app`, and writes `.duo/runs/<n>/build.json` including the SDK stamp from `scripts/sdk-stamp.sh`. A stamp below 27.1 means every later measurement reflects the wrong tier; stop and fix the toolchain (wrong Xcode selected, `SDKROOT` override, old Expo build image) before continuing.

What the script decides for you, and when to override it:
- React Native and Expo build `Release` by default, because a Debug build loads its JavaScript from Metro, which nothing here starts. `--configuration Debug` only if you also run Metro.
- DerivedData goes to `~/Library/Developer/Xcode/DerivedData/duo-ready-<scheme>`, never inside the project. A project under iCloud Drive (Desktop, Documents) makes codesign fail on Finder attributes and took 37 minutes instead of 4 on the field test. Override with `DUO_DERIVED_DATA` or `derived_data:` in `duo.yaml`.
- Xcode 27.1 refuses deployment targets below iOS 15, which old CocoaPods resource bundles still declare. The build log hint says so; pass `DUO_XCODEBUILD_SETTINGS=IPHONEOS_DEPLOYMENT_TARGET=15.0` or add `xcodebuild_args:` to `duo.yaml`, or raise the floor in the Podfile `post_install`.
- Expo: `ios/` is generated once; after changing `app.json` or a config plugin run `build.sh --prebuild`.
- The script warns when `Info.plist` has no `UIApplicationSceneManifest`. For a UIKit or React Native app built with SDK 27 that is the launch blocker from stage 2; `sim.sh launch` confirms it by reading the kill from the system log and exits 3.

A first build on a fresh Mac takes 10 to 15 minutes (Pods, Hermes); a rebuild 3 to 5. Build plus matrix on a prepared Mac is 15 to 25 minutes, not hours; perf adds 8 to 10 minutes (five launches per cell). When it takes longer, the time is going into tool installs or a wrong DerivedData location, not into the skill's stages.

Add the two UI test targets before stage 5, not after: `ruby "$DUO/templates/add-duo-test-targets.rb" ios/<App>.xcodeproj <App> "$DUO/templates"` creates `DuoUITests` and `DuoPerfTests` from the templates, adds them to the scheme's Test action and sets that action to Release (with Homebrew CocoaPods use its Ruby: `GEM_HOME=/opt/homebrew/Cellar/cocoapods/<ver>/libexec /opt/homebrew/opt/ruby/bin/ruby ...`). Expo regenerates `ios/` on prebuild, so rerun it after `build.sh --prebuild`. Then `xcodebuild build-for-testing` once with the same scheme, configuration and DerivedData as `build.json`.

### 5. UI matrix

Run `bash "$DUO/scripts/run-matrix.sh" --run <n>`. For each flow x cell it sets the pose with `duoctl`/`hinge`, waits for the posture to read back, launches the app, runs the steps, rotates, captures the active display, dumps the element tree, and then runs `python3 "$DUO/scripts/assert.py" --run <n>`. Transitions (`closed>open`, `open>book`, `open>closed`) run mid-flow because a fold can resize the app while a screen is active.

Things that bite here, all handled by the scripts but worth knowing when reading failures:
- The simulator captures black frames for a while after boot; `capture.sh` validates and retries.
- Only the active display is lit; the other captures solid black.
- Rotation happens after the app is in front, because SpringBoard on the outer display is portrait only. A portrait-locked app refuses the landscape cells; `sim.sh rotate` prints `duo: refused:` (exit 6) and the matrix writes `<flow>-<cell>.skip.json` and moves on. The report lists those cells as skipped, never as passed. If the lock is intentional, drop the landscape cells from `duo.yaml`.
- A flow step that fails (a `wait` that times out, a Maestro assertion) ends that cell only: the matrix writes `<flow>-<cell>.error.json`, `assert.py` reports it as a failed `flow` assertion, and the other cells still produce evidence. Exit 1 from the matrix therefore means "something failed", and `failures.json` says whether it was a layout assertion or a flow. A Maestro reason carries the assertion line (`Assertion is false: id: <id> is visible`), so the payload names the selector that did not appear.
- Orientation is read from the window size `duoctl state` reports for the lit display, never from the hinge's orientation label: on the inner display that label is the device's and says portrait for a 951 x 669 landscape window (0.3.0 believed it and photographed every inner portrait cell in landscape, under the portrait name). `sim.sh rotate` waits until the readback agrees, and a rotation that does not take effect is an error cell, not a pass. After an unfold the inner display keeps whatever rotation it had last; transition captures record the orientation read back, and `assert.py` sizes the window from the capture (`window_source: screenshot`) when it differs from the cell's nominal size.
- Maestro cannot tap the inner display, so RN flows in open/book cells use `duoctl tap --label`; `duoctl tap` in turn cannot touch the outer display. Deep links may show an "Open in <App>?" prompt the first time; the runner waits, but a flow that needs the prompt answered must say so.
- Accessibility Inspector does not work on Duo inside Device Hub; trees come from XCUITest or AXe. When `duoctl elements` fails the tree file carries `source: unavailable`, `assert.py` marks the layout assertions `skip` and `ui.json` gets `verified: false`. The first field test produced 25 green cells this way before the fix; a green matrix is only evidence when `verified` is true.
- AXe trees (`duoctl elements`, every React Native and Expo cell) are flat: no parent, no scroll information, every static text twice, the root `Application` reported unrotated in landscape. `scripts/tree.py` normalises them and `assert.py` drops containers, so a `fail` there is real; vertical overflow is a `warn` because a flat tree cannot tell a scrolled-off row from a clipped one. The native `DuoUITests` tree has ancestry and fails it. Read the warns with the capture next to them.

Assertion definitions and false-positive notes are in `references/assertions.md`. On the first green run, offer to commit `.duo/baselines/` so visual diffs work from then on.

### 6. Performance

Run `bash "$DUO/scripts/perf.sh" --run <n>`. It needs the `DuoPerfTests` target from stage 4 (`templates/add-duo-test-targets.rb`); without one xcodebuild reports "no test bundles available", there is nothing to measure, and the script exits 4 with `perf.json` marked `status: skip` and a `reason` that says whether the target is missing or the result bundle had no measurements. The cell name reaches the test as `TEST_RUNNER_DUO_CELL` (xcodebuild forwards nothing else to a UI test runner); `launch_ms` is `XCTApplicationLaunchMetric`, the app's own launch, and `launch_wall_ms` the whole measured block including XCUITest setup, reported but not gated. Metrics are read with `xcrun xcresulttool get test-results metrics` and parsed by `scripts/perfparse.py`; transition files are spelled `closed-to-open` on disk. Default mode is regression against `.duo/baselines/perf.json`; absolute thresholds apply only with `--absolute`, intended for a physical device. A project without a baseline gates nothing: `perf.sh` prints `baseline recorded, nothing gated`, `perf.json` carries `status: baseline`, and the report lists perf under skipped stages; once the numbers look sane run `perf.sh --promote --run <n>`, which copies that file to the baseline without measuring again (`--write-baseline` measures first, a second 6 minute run), and never call the baseline run a pass. A cell the app refuses to rotate (portrait lock) is a `skip` row with the refusal as its reason. Transition cells measure `fold_relayout_ms` only with a hinge bridge (`DUO_POSE_URL`); without one they appear as `skip` rows with the reason. `memory_delta_mb` from `testLaunch` is the launch-to-terminate delta, about zero, reported as info and gated only across a transition. Simulator numbers are not device numbers (a Release Expo app launches in about 2.3 s there); say so when presenting them. Metrics and gates are in `references/perf.md`.

### 7. Report and agent loop

Run `python3 "$DUO/scripts/report.py" --run <n>` and open `.duo/runs/<n>/duo-report.html`. Exit codes: 0 pass, 1 UI failure, 2 perf failure, 3 build failure. A run that verified nothing (no `ui.json`, or `verified: false` because no cell had an element tree) also exits 1 with overall `unverified`, so a CI gate cannot read it as green; say which stage produced no evidence and what to install.

For failures, run `python3 "$DUO/scripts/loop.py" --run <n>`. Exit 1 means payloads were printed and another iteration is expected; exit 4 means there is nothing to loop on (`failures.json` missing because the matrix never reached the assertions, or the run is unverified) and it never says "loop complete" in that case. It prints one payload per failure: flow, cell, assertion, offending elements with frames, screenshot path, and when a scan finding can cause that assertion, `matched_rule`, `source_hint` file:line and `source_confidence` (`file` when the screen's name matches the file, `rule` when only the rule type does; the latter is a lead, not a diagnosis). Fix the cause (not the symptom; a clipped title in `book-landscape` is usually a fixed width or a centered grid, not a font size), commit with the rule id, then rerun only the failed pairs with the exact command `loop.py` prints: `bash "$DUO/scripts/run-matrix.sh" --run <next free n> --only-failed .duo/runs/<n>/failures.json`. The iteration counter belongs to that rerun chain: a fresh matrix run that is not an `--only-failed` rerun of the last looped run starts at 1 again, and so does a `.duo/loop.json` written before 0.3.1 (no `last_run`). The payload's `fix_hint` is the scan rule's only on a file-level match; a rule-level lead keeps the assertion's own hint. Stop after `loop.max_iterations` (default 3); `loop.py` then writes `DUO-TODO.md` with what remains.

The report embeds JPEG thumbnails (made with `sips` on macOS) and links the full captures under `.duo/runs/<n>/captures/`, so it stays around 1 MB for 36 cells and can be attached to an issue.

### 8. Assets and submission

When the matrix is green, run `bash "$DUO/scripts/assets.sh" --run <n>`. It picks the passing captures (outer portrait from `closed-portrait`, inner landscape from `open-landscape`, inner portrait from `open-portrait`), validates exact pixel sizes and no alpha with `scripts/assets_gate.py`, writes them under `fastlane/screenshots/<locale>/`, and drafts `FEATURING.md` with nomination text.

Tell the user plainly: fastlane deliver 2.241.1 or later uploads the outer set; the rorkai `asc` CLI also works for outer; nobody has publicly verified an inner-display upload through the API, so upload the inner set through App Store Connect's web uploader until that is confirmed. Specs, naming, and the badge are in `references/asc-duo-specs.md`.

## When the user asks a narrower question

- "Why do my toolbars not move to the side?" Check SDK stamp, then the three bar rules, then `references/apple-guidance.md#vertical-bars`.
- "Which sizes do screenshots need?" `references/asc-duo-specs.md`, and remind them of the SDK qualifier.
- "How do I test the fold in CI?" `templates/github-actions-duo.yml` and `references/simulator-control.md`.
- "Is my Expo app affected?" Yes if it reads `Dimensions.get` at module scope, locks orientation, or draws its own tab bar; run the scan with `--stack rn`. On Expo SDK 54 or React Native 0.81 it is also killed at launch when built with the iOS 27 SDK until a scene life cycle is added (`expo-no-scene-lifecycle`).
- "Why did the run take hours?" It should not. Look at the build log location (iCloud Drive), whether the Command Line Tools and AXe were installed mid-run, and whether `build.sh` re-ran `expo prebuild`; build plus matrix take 15 to 25 minutes, perf 8 to 10 more.
- "The matrix passes but the app looks wrong on the hinge." The assertions see geometry, not design. Check by eye in `book-landscape`: controls centred on the window land on the fold, and a grid with an odd column count does too; the fix is an even column count or `ReservedRegion`. Buttons of 42 pt fail `tap_target_min` by 2 pt and are a real finding, not noise.
- "Does this apply to Flutter?" The scan has no Flutter rules yet; the device facts and simulator stages still apply. Say that.

## Reporting back

End every session with: stages run and their exit codes, stages skipped and why, findings fixed (by rule) and remaining, the path to the latest report, and the next command to run. Keep it short; the report has the detail.
