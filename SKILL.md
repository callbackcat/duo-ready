---
name: duo-ready
description: Make an existing iOS app (UIKit, SwiftUI, React Native, Expo) ready for iPhone Duo end to end - scan the code for resizing breakages, apply fixes, build with the iOS 27.1 SDK, test every pose (closed, open, book, rotated, Split View) on the iPhone Duo simulator, gate performance, and generate the App Store screenshots that become mandatory in April 2027. Use this skill whenever the user mentions iPhone Duo, a foldable iPhone, fold/unfold, hinge, inner or outer display, vertical toolbars or tab bars, Duo screenshots, the "optimized for iPhone Duo" badge, size classes on iPhone, UIScreen.main warnings, Device Hub poses, or getting an iOS app through App Store submission after April 2027, even when they never say "Duo".
---

# duo-ready

You are helping an iOS developer make an existing app adapt to iPhone Duo and prove it, with evidence, in every pose. Apple's own "App Resizability" skill finds code patterns; this skill goes further by applying fixes, running the app in every pose on the simulator, measuring layout and performance, looping on failures, and producing the store assets. Every stage writes machine-readable output under `.duo/` (formats in `references/pipeline-contracts.md`), so you can resume, re-run only failed cells, and show the user exactly what was and wasn't verified.

**Where things live.** This skill's scripts and references sit in the skill directory (the base directory shown when the skill loads), not in the user's app. The app is the current working directory. Export the skill path once and run every script from the app root:

```bash
DUO="$HOME/.claude/skills/duo-ready"   # or wherever this SKILL.md is
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

Run `bash "$DUO/scripts/preflight.sh" --json`. It checks macOS, Xcode 27.1+, the iOS 27.1 runtime, the Duo device type, `duoctl`, `hinge`, fastlane 2.241.1+, and then boots a simulator and proves pose readback.

- Exit 0: continue.
- Exit 4: a tool is missing. Print the install hint it gives (`brew install skarol/tap/duoctl artemnovichkov/tap/hinge`, Xcode 27.1 from the developer site, `xcodebuild -downloadPlatform iOS`) and continue with stages 1 to 3 only.
- Exit 5: pose control is broken on this Xcode. Continue with stages 1 to 3; for stage 5 tell the user how to set poses in Device Hub by hand and capture with `scripts/capture.sh`.
- Not macOS at all: say so once, do stages 1 to 3, and write the plan for the rest.

### 1. Detect

Run `python3 "$DUO/scripts/detect.py"`. It writes `.duo/env.json` and scaffolds `duo.yaml` (stack, scheme, bundle id, orientation locks, test targets, store tooling). Show the user the scaffold and confirm stack and scheme. If `duo.yaml` has no flows, ask for 2 to 5 short flows that reach the screens that matter (feed, player, settings, onboarding). Grammar is in `templates/flows.yaml`; Maestro verbs so RN users can paste existing flows.

### 2. Scan

Run `python3 "$DUO/scripts/scan.py"`. It writes `.duo/scan.json` and prints a table grouped by rule. Present the findings grouped by rule with counts, severity, and whether an autofix exists. For every rule the user asks about, open the matching section in `references/rules-native.md` or `references/rules-react-native.md`: each has the reason it breaks on Duo and a before/after.

Explain the three SDK tiers when relevant: built with iOS 26 the app runs boxed; iOS 27.0 fills the display but keeps horizontal bars; iOS 27.1 goes edge to edge and moves toolbars and tab bars to the vertical trailing edge. The scan's `custom-bar-class`, `toolbar-item-no-symbol`, and `no-scene-delegate` rules exist because those three things silently prevent the 27.1 behaviour.

### 3. Fix

1. `python3 "$DUO/scripts/scan.py" --fix --dry-run` prints the unified diff of all literal autofixes. Show it.
2. On approval, create branch `duo-ready` and run `python3 "$DUO/scripts/scan.py" --fix --apply`. It refuses a dirty tree; commit or stash first.
3. For manual findings, patch each site yourself. Read the rule's section first; the fix is usually "read geometry from the view or scene, not the screen, and read it on every layout". Keep edits minimal and commit per rule.
4. Re-run the scan to confirm the count dropped. Findings marked `info` are advice, not blockers.

Prefer Apple's adaptive containers over custom layout math: `NavigationSplitView`/`UISplitViewController`, `TabView`/`UITabBarController`, `ArrangementView`/`UIArrangementViewController` for two-pane content, `ReservedRegion` queries for anything custom near the fold. The API map by job is in `references/apple-guidance.md`.

### 4. Build and SDK stamp

Run `bash "$DUO/scripts/build.sh"`. It builds for the simulator, locates the `.app`, and writes `.duo/runs/<n>/build.json` including the SDK stamp from `scripts/sdk-stamp.sh`. A stamp below 27.1 means every later measurement reflects the wrong tier; stop and fix the toolchain (wrong Xcode selected, `SDKROOT` override, old Expo build image) before continuing.

### 5. UI matrix

Run `bash "$DUO/scripts/run-matrix.sh" --run <n>`. For each flow x cell it sets the pose with `duoctl`/`hinge`, waits for the posture to read back, launches the app, runs the steps, captures the active display, dumps the element tree, and then runs `python3 "$DUO/scripts/assert.py" --run <n>`. Transitions (`closed>open`, `open>book`, `open>closed`) run mid-flow because a fold can resize the app while a screen is active.

Things that bite here, all handled by the scripts but worth knowing when reading failures:
- The simulator captures black frames for a while after boot; `capture.sh` validates and retries.
- Only the active display is lit; the other captures solid black.
- Maestro cannot tap the inner display, so RN flows in open/book cells use `duoctl tap --label`.
- Accessibility Inspector does not work on Duo inside Device Hub; trees come from XCUITest or AXe.

Assertion definitions and false-positive notes are in `references/assertions.md`. On the first green run, offer to commit `.duo/baselines/` so visual diffs work from then on.

### 6. Performance

Run `bash "$DUO/scripts/perf.sh" --run <n>`. Default mode is regression against `.duo/baselines/perf.json`; absolute thresholds apply only with `--absolute`, intended for a physical device. Simulator numbers are not device numbers; say so when presenting them. Metrics and gates are in `references/perf.md`.

### 7. Report and agent loop

Run `python3 "$DUO/scripts/report.py" --run <n>` and open `.duo/runs/<n>/duo-report.html`. Exit codes: 0 pass, 1 UI failure, 2 perf failure, 3 build failure.

For failures, run `python3 "$DUO/scripts/loop.py" --run <n>`. It prints one payload per failure: flow, cell, assertion, offending elements with frames, screenshot path, the scan rule it matched, and a `source_hint` file:line when a scan finding's file matches the element's view. Fix the cause (not the symptom; a clipped title in `book-landscape` is usually a fixed width or a centered grid, not a font size), commit with the rule id, then rerun only the failed cells with `bash "$DUO/scripts/run-matrix.sh" --run <n+1> --only-failed .duo/runs/<n>/failures.json`. Stop after `loop.max_iterations` (default 3); `loop.py` then writes `DUO-TODO.md` with what remains.

### 8. Assets and submission

When the matrix is green, run `bash "$DUO/scripts/assets.sh" --run <n>`. It picks the passing captures (outer portrait from `closed-portrait`, inner landscape from `open-landscape`, inner portrait from `open-portrait`), validates exact pixel sizes and no alpha with `scripts/assets_gate.py`, writes them under `fastlane/screenshots/<locale>/`, and drafts `FEATURING.md` with nomination text.

Tell the user plainly: fastlane deliver 2.241.1 or later uploads the outer set; the rorkai `asc` CLI also works for outer; nobody has publicly verified an inner-display upload through the API, so upload the inner set through App Store Connect's web uploader until that is confirmed. Specs, naming, and the badge are in `references/asc-duo-specs.md`.

## When the user asks a narrower question

- "Why do my toolbars not move to the side?" Check SDK stamp, then the three bar rules, then `references/apple-guidance.md#vertical-bars`.
- "Which sizes do screenshots need?" `references/asc-duo-specs.md`, and remind them of the SDK qualifier.
- "How do I test the fold in CI?" `templates/github-actions-duo.yml` and `references/simulator-control.md`.
- "Is my Expo app affected?" Yes if it reads `Dimensions.get` at module scope, locks orientation, or draws its own tab bar; run the scan with `--stack rn`.
- "Does this apply to Flutter?" The scan has no Flutter rules yet; the device facts and simulator stages still apply. Say that.

## Reporting back

End every session with: stages run and their exit codes, stages skipped and why, findings fixed (by rule) and remaining, the path to the latest report, and the next command to run. Keep it short; the report has the detail.
