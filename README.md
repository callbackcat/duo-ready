<p align="center">
  <img src="assets/iphone-duo.svg" width="160" alt="iPhone Duo">
</p>

<h1 align="center">duo-ready</h1>

<p align="center">Get an existing iOS app ready for iPhone Duo, and prove it works in every pose.</p>

## What this skill is for

iPhone Duo is Apple's foldable iPhone: a 5.4" outer display when closed and a 7.6" inner display when open. Apps that assume one screen size, lock orientation, or read `UIScreen.main` look wrong on it, and from April 2027 every App Store submission built with the iOS 27.1 SDK must include Duo screenshots.

duo-ready is a Claude Code skill (plus plain scripts you can run by hand) that takes your app through the whole job:

- finds the code patterns that break on a foldable, in Swift, UIKit, SwiftUI, React Native and Expo projects, and fixes the ones that can be fixed automatically;
- builds the app with the iOS 27.1 SDK and runs it on the iPhone Duo simulator in every pose: closed, open, partially folded, rotated, and mid-flow fold transitions;
- checks each screen for clipped or offscreen content, tap targets, bars in the right place, and nothing interactive sitting in the fold;
- measures launch time, fold re-layout time and memory across transitions;
- turns every failure into a small payload a coding agent can act on, then re-runs only the failed cells;
- exports the screenshots at Apple's exact Duo sizes, ready for App Store Connect.

Runs on a Mac with Xcode 27.1. No iPhone Duo hardware needed.

## Pipeline

```
          your app repo
               |
  0 preflight  |  Xcode 27.1? iOS 27.1 runtime? duoctl + hinge? pose readback works?
               v
  1 detect  ---> duo.yaml (stack, scheme, flows)
               |
  2 scan    ---> .duo/scan.json  (32 rules, grouped by rule id)
               |
  3 fix     ---> one commit per rule on branch duo-ready
               |
  4 build   ---> .app + SDK stamp (26 / 27.0 / 27.1 tier)
               |
  5 matrix  ---> for each flow x pose:  pose -> launch -> steps -> capture -> element tree
               |     closed-portrait  closed-landscape  open-landscape  open-portrait
               |     book-landscape   book-portrait     closed>open     open>book ...
               v
  6 assert  ---> ui.json   (offscreen, clipped, tap targets, bars, camera, fold, visual diff)
  7 perf    ---> perf.json (launch, fold re-layout, memory, CPU; regression vs baseline)
               |
  8 report  ---> duo-report.html        exit 0 pass / 1 UI / 2 perf / 3 build
               |
         fail? |  9 loop: failures.json -> agent patches -> rerun failed cells (max 3)
               v
  10 assets ---> fastlane/screenshots/<locale>/  1398x2034  2007x2853  (+ FEATURING.md)
```

## The rule, stated exactly

From **April 2027**, every App Store submission of an app **built with the iOS 27.1 SDK or later** must include iPhone Duo screenshots. They are optional today, and submitting them now puts an "optimized for iPhone Duo" badge on the product page. Apple has not said apps will be removed. Sources: [developer news](https://developer.apple.com/news/?id=kkphp5qo), [screenshot specifications](https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications).

## Install

Get the skill folder onto the Mac (clone the repo, or unzip the archive you were given), then copy or symlink it where Claude Code looks for skills:

```bash
git clone <repo-url> ~/duo-ready        # or: unzip duo-ready-skill.zip -d ~/
ln -s ~/duo-ready ~/.claude/skills/duo-ready
```

Claude Code picks it up at the next session (`/reload-skills` if the session is already open). Nothing else is installed on the Mac by the skill itself.

Mac tooling the simulator stages need (one-time):

```bash
# Xcode 27.1 or later from https://developer.apple.com/download/ (macOS Tahoe 26.6+)
sudo xcode-select -s /Applications/Xcode.app
xcodebuild -downloadPlatform iOS                  # iOS 27.1 runtime with the iPhone Duo device type
brew install skarol/tap/duoctl artemnovichkov/tap/hinge
gem install fastlane -v '>= 2.241.1'              # optional, only for screenshot upload
```

`duoctl` and `hinge` are MIT tools that send the same private HID event Xcode's Device Hub sends to fold the simulator. Apple has no public API for this. `scripts/preflight.sh` proves the angle reads back before any pose stage runs and exits with code 5 when an Xcode update breaks the protocol; nothing is ever faked.

## Quick start on a Mac (10 minutes)

```bash
DUO=~/.claude/skills/duo-ready
cd /path/to/your/app
bash "$DUO/scripts/preflight.sh" --json          # must exit 0; exit 4 = missing tool, 5 = pose control broken
python3 "$DUO/scripts/detect.py"                 # writes duo.yaml; edit flows and scheme if needed
python3 "$DUO/scripts/scan.py"                   # findings grouped by rule
```

Then open Claude Code in the app folder and say: "get my app ready for iPhone Duo". The skill runs the remaining stages and reports what it could and could not verify. To run them by hand, follow the commands under Use.

First time on a Mac? Please also run the checklist in `CONTRIBUTING.md` and send back `preflight.json` and `.duo/runs/1/duo-report.html`; that is the verification this project still lacks.

## Use

Run from the app's root, with `DUO` pointing at the skill folder:

```bash
bash "$DUO/scripts/preflight.sh"            # Xcode 27.1, runtime, duoctl/hinge, pose readback
python3 "$DUO/scripts/detect.py"            # writes .duo/env.json and scaffolds duo.yaml
python3 "$DUO/scripts/scan.py"              # findings grouped by rule -> .duo/scan.json
python3 "$DUO/scripts/scan.py" --fix --dry-run
python3 "$DUO/scripts/scan.py" --fix --apply
bash "$DUO/scripts/build.sh"                # .app + SDK stamp -> .duo/runs/1/build.json
bash "$DUO/scripts/run-matrix.sh" --run 1   # every flow x pose, captures, element trees, assertions
bash "$DUO/scripts/perf.sh" --run 1
python3 "$DUO/scripts/report.py" --run 1    # .duo/runs/1/duo-report.html, exit 0/1/2
python3 "$DUO/scripts/loop.py" --run 1      # agent payloads for each failure
bash "$DUO/scripts/assets.sh" --run 1       # fastlane/screenshots/<locale>/ + FEATURING.md
```

With Claude Code, say "get my app ready for iPhone Duo" and the skill runs these in order, asks before branching or applying fixes, and reports which stages ran.

## What it checks

Static rules (`references/rules-native.md`, `references/rules-react-native.md`): Apple's published breakage list (`UIScreen.main`, orientation-driven layout, idiom checks, hardcoded device sizes, fill media, layout computed once) plus what the iOS 27.1 SDK added: custom `UIToolbar`/`UINavigationBar`/`UITabBar` that never get vertical bars, title-only toolbar items, custom overflow menus, missing scene lifecycle, symmetric safe-area math, odd-column grids across the fold. React Native and Expo: module-scope `Dimensions.get`, orientation locks (ignored on the inner display), symmetric insets, JS-drawn tab bars, `AppState` pausing in Split View, `useHinge` driving layout, SDK floors.

Runtime assertions per cell (`references/assertions.md`): offscreen elements, clipped text, 44 pt tap targets, vertical bars where the pose expects them, content under the outer camera, interactive elements in the fold region, visual diff against baselines, stability across mid-flow fold transitions.

Performance (`references/perf.md`): cold launch per pose, fold re-layout time, memory delta across transitions, CPU during transitions. Regression mode against your own baseline by default; simulator numbers are not device numbers.

## Device facts in one table

| | Outer display (closed) | Inner display (open / book) |
|---|---|---|
| Pixels | 1398 × 2034 | 2007 × 2853 |
| Points (iOS 27.1 SDK) | 466 × 678 | 951 × 669 (landscape default) |
| Size classes | compact W / regular H (portrait) | regular / regular |
| Bars | vertical, trailing edge | vertical in landscape, horizontal in portrait |
| Fold region | n/a | 40 pt at x 455 to 495 (landscape), active only when partially folded |

Full numbers, SDK tiers and simulator quirks: `references/device-facts.md`.

## Verification status

This repository was authored on a Windows machine without Xcode. What has been verified and where:

| Part | Status |
|---|---|
| Rule engine (19 native + 13 React Native rules), fixtures, autofix dry-run | Tested with pytest on Windows (87 tests in total across the suite) |
| YAML subset loader, detect, assertions, visual diff, report, loop, assets gate | Tested with pytest on Windows using synthetic trees and PNGs |
| Shell scripts | `bash -n` syntax checked; `--help` and the non-macOS refusal path tested |
| Preflight on Xcode 27.1, pose readback through `duoctl`/`hinge`, non-black capture, XCUITest templates compiling, full run on a real app, fastlane upload | **Not yet run on a Mac.** Tracked as the first contributor task; checklist in `CONTRIBUTING.md` |

If you run it on a Mac, open an issue with the output of `bash scripts/preflight.sh --json` and `.duo/runs/1/duo-report.html`.

## Facts that are still unverified publicly

- Uploading the **inner-display** screenshot set through the App Store Connect API (`APP_IPHONE_DUO`). Outer uploads are confirmed; use the web uploader for the inner set until someone confirms.
- fastlane deliver's exact filename convention for Duo screenshots (support landed in 2.241.1).
- Split View on the simulator from scripts.

## Layout

```
SKILL.md              agent-facing workflow
references/           device facts, Apple guidance digest, rules, simulator cookbook, ASC specs, assertions, perf
scripts/              preflight, detect, scan, sdk-stamp, build, sim, capture, run-matrix, assert, diff, perf, report, loop, assets
templates/            duo.yaml, flows.yaml, XCUITest tour, perf tests, GitHub Actions
examples/             intentionally broken UIKit and React Native fixtures used by the tests
tests/                pytest suite (runs on any OS)
evals/                skill eval cases for `claude plugin eval`
```

## Related projects

- [hinge](https://github.com/artemnovichkov/hinge) and [duoctl](https://github.com/skarol/duoctl): simulator fold control; duo-ready depends on them.
- [iphone-duo-skills](https://github.com/mirzaaghazadeh/iphone-duo-skills): documentation skills for Duo APIs, no pipeline.
- [FoldReady](https://github.com/guillaume-flambard/foldready): Swift static scanner with a paid review.
- Apple's App Resizability skill: `xcrun agent skills export` from Xcode 27.1; duo-ready's scan is a superset and adds the runtime stages.

## License

MIT.
