# duo-ready — project spec

An open-source agent skill + CLI pipeline that takes an existing iOS app (native or cross-platform), makes it adaptive for iPhone Duo, verifies it with UI and performance tests across every pose, and produces App Store-ready assets. Designed to be run by a coding agent (Claude Code, Cursor, Codex) or standalone from the terminal and CI.

Status: spec, 23 Oct 2026; revised 27 Oct 2026 after verifying Apple's pages and the simulator tooling. Implementation is skill-first (SKILL.md + scripts); the CLI described in §5 wraps the same scripts later.

### Revision 27 Oct 2026: what changed after verification

| Spec said (23 Oct) | Verified | Consequence |
|---|---|---|
| Poses: closed, book, tent | The simulator models hinge angle (0 to 180 degrees) plus rotation. Apple's names: closed, partially folded ("book", about 127 degrees), open/fully open (180). Tabletop and standing are physical placements with the same hinge state. Split View is a distinct window size. | Matrix is `{closed, open, book} x {portrait, landscape}` plus `split-view-left/right`. "Tent" dropped. |
| Open question: can simctl set poses? | No public API; `simctl`, `devicectl` and `XCUIDevice.orientation` are silent no-ops. `hinge` and `duoctl` (MIT) send the Device Hub vendor HID event and read the angle back. | Resolved: depend on both; preflight proves readback and exits 5 when the private protocol changes. |
| Screenshots required April 2027 | Required from April 2027 for apps built with the iOS 27.1 SDK or later. Optional now; submitting earns the "optimized for iPhone Duo" badge. | Wording everywhere carries the SDK qualifier. |
| Sizes from the ASC page | Outer 1398x2034 / 2034x1398; inner 2007x2853 / 2853x2007 px. Previews 886x1920 / 1920x886. One Duo set holds all four sizes, max 10. | Hardcoded in `references/asc-duo-specs.md` and `scripts/assets_gate.py`. |
| Window sizes unknown | 27.1 SDK: closed 466x678 pt, open 951x669 (default landscape) / 669x951. Fold region 40 pt at x 455 to 495. Outer camera 37x37. Status column 84 pt. 27.0 SDK: 386x678 / 871x669. 26 SDK: boxed 375x667. | `references/device-facts.md`; `scripts/sdk-stamp.sh` checks the binary's SDK. |
| Size-class advice | Outer: compact width. Inner: regular in both dimensions. The inner display ignores `UISupportedInterfaceOrientations`. A 6.9" iPhone in landscape is regular width with compact height. | New rules `regular-width-assumes-regular-height`, orientation lock flagged as ignored. |
| fastlane/EAS unknown | fastlane deliver 2.241.1+ knows Duo sizes (`APP_IPHONE_DUO`). rorkai `asc` CLI uploads outer sets; inner upload unverified by anyone. Apple's OpenAPI spec omits the enum. | Assets stage requires deliver 2.241.1+ or `asc`; inner upload documented as unverified. |
| Maestro for RN flows | Maestro misreports inner-display geometry and taps land on the cover screen (issue 3617). | RN runner: Maestro for closed cells only; open/book via `duoctl tap --label`. |
| Rules = Apple's list | iOS 27.1 adds reserved regions, arrangement views, hinge API, vertical-bar controls; custom `UIToolbar`/`UINavigationBar`/`UITabBar` never get vertical bars; UIScene lifecycle is mandatory (TN3187). | New rules: `custom-bar-class`, `toolbar-item-no-symbol`, `custom-overflow-menu`, `no-scene-delegate`, `symmetric-safe-area`, plus RN `rn-js-tab-bar`, `rn-appstate-inactive-pause`, `rn-expo-hinge-for-layout`, `rn-sdk-floor`. |
| Simulator quirks unknown | Screenshots can be black for minutes after boot; the active display switches 1 to 2.5 s after the angle; accessibility tools cannot read Duo content inside Device Hub. | `capture.sh` validates non-black frames; wait-for-posture before capture; element trees come from XCUITest or AXe. |

---

## 1. Context

### What Apple announced (verified 23 Oct 2026)

- iPhone Duo ships 23 Oct 2026. Two displays: 7.6" inner, 5.4" outer. Poses: closed (outer display), open / "book", "tent".
- Xcode 27.1 adds Duo support: a Duo simulator, Device Hub pose/orientation preview, and a resizable iOS simulator.
- Apps built with the iOS 26 SDK or earlier still run but don't adapt — they're centered in the inner display with empty space. iOS 27 SDK fills most of the inner display. iOS 27.1 SDK goes edge-to-edge, and toolbars/tab bars move to a vertical placement below the status bar.
- **The only hard rule:** from April 2027, every App Store submission must include iPhone Duo screenshots. Apple has not said apps will be removed; it has not said how App Review will treat submissions missing them.
- Submitting Duo screenshots now earns an "optimized for iPhone Duo" badge on the product page.
- Apple's Xcode coding assistant responds to "get my app ready for iPhone Duo" and scans for known breakage patterns. `xcrun agent skills export` exports that as a skill for third-party agents.

Sources: developer.apple.com/news/?id=kkphp5qo · developer.apple.com/iphone-duo/prepare/

### What Apple's guidance covers (the baseline we must exceed)

Common breakages Apple lists, with the prescribed fixes:

| Pattern | Fix |
|---|---|
| `UIScreen.main.bounds` for sizing / window creation | `UIWindow(windowScene:)`, `view.bounds`, `window.bounds`; SwiftUI `GeometryReader` / `onGeometryChange` |
| Layout computed once at launch | Recompute in `viewDidLayoutSubviews()` / `layoutSubviews()`; use `viewWillTransition(to:with:)` |
| Stored `UIScreen` reference | `view.window?.windowScene?.screen` |
| `UIScreen.main.scale` | `traitCollection.displayScale` / `@Environment(\.displayScale)` |
| `UIDevice.current.orientation`, `statusBarOrientation`, `interfaceOrientation` driving layout | Compare `bounds.width > bounds.height` |
| `userInterfaceIdiom == .phone / .pad` | Size classes or available-space logic |
| `horizontalSizeClass == .regular` ⇒ "is iPad" | Don't assume; iPhone can now report regular width |
| Hardcoded dimensions (`height == 844`, lists of known iPhone sizes) | Remove |
| `.scaleAspectFill` / `.aspectRatio(contentMode: .fill)` on key media | Choose fill/fit by size class or aspect ratio; set focal point |
| Toolbars/tab bars not adapted to vertical placement (iOS 27.1 SDK) | Verify content adapts |
| Not tested in all poses or during fold/unfold mid-session | Test transitions during active use |

Apple's guidance is Swift/UIKit/SwiftUI only and stops at "suggest fixes". It does not run tests, does not measure performance, does not produce store assets, and does not cover React Native, Expo, Flutter or Capacitor.

### Why this project

- Every iOS developer with a live app has to do this work between now and April 2027. The audience is the entire iOS ecosystem, and the deadline creates urgency.
- Apple ships the scan, not the pipeline. The gap is: *apply* fixes safely, *prove* they work in every pose, *catch regressions* in CI, and *generate the mandatory assets*.
- Cross-platform developers (RN/Expo/Flutter) are the ones most exposed — their layout code is JS/Dart, Apple's scan can't see it, and their frameworks cache window dimensions in ways that break on fold.
- A tool with a real pipeline is what ecosystem DevRel teams (Expo, RevenueCat, Supabase, Vercel) amplify. Shelf life is ~6 months, which is fine — adoption lands before April.

### Non-goals

- Not a replacement for Apple's assistant — a strict superset that wraps and extends it.
- Not a generic iOS test framework. Only what the Duo transition needs.
- Not marketing "your app will be removed". It won't be. The pitch is "Duo-ready build and store page in an afternoon".

---

## 2. Core concepts

### Pose × orientation matrix

Every check runs over a matrix. Default:

```
poses:        [closed, open, book]          # hinge 0°, 180°, ~127°
orientations: [portrait, landscape]
extra cells:  [split-view-left, split-view-right]
transitions:  [closed>open, open>book, open>closed]   # executed mid-flow
```

A "cell" is one (pose, orientation) tuple, named `<pose>-<orientation>`. Transitions are tested while a flow is active, not just at launch, because a fold can resize the app mid-session.

### Flows

A flow is a short, declarative navigation script that reaches a screen worth checking. The user writes them; the pipeline executes them in every cell. Format matches Maestro so RN/Flutter users get it for free and native users get an XCUITest translation.

```yaml
flows:
  - name: onboarding
    steps: [launch, tap "Get started", wait "Welcome"]
  - name: feed
    steps: [launch, wait "Feed", scroll 5]
  - name: player
    steps: [launch, tap "Library", tap first cell, wait "Now playing"]
```

### Layout assertions

Automated, framework-independent, from the accessibility tree + screenshot:

- No element bounds outside the screen bounds (minus safe area).
- No text truncated where the element has room to grow (heuristic: `…` present and sibling width < container width).
- Tap targets ≥ 44 pt.
- Tab bar / toolbar present and positioned correctly for the SDK and pose (vertical under iOS 27.1 when expected).
- Safe-area respected (no content under the status bar on the right edge / camera region on the outer display).
- Visual diff vs committed baseline per cell, with a per-flow threshold.

### Performance gates

Collected with XCTest metrics and `xctrace`:

| Metric | Default | Notes |
|---|---|---|
| Cold launch per pose | warn 800 ms, fail 1500 ms | `XCTClockMetric` on `XCUIApplication.launch` |
| Scroll hitch rate | fail > 5 hitches/s | `XCTOSSignpostMetric.scrollDecelerationMetric` / xctrace Animation Hitches |
| Fold/unfold re-layout | fail > 250 ms | time from size-change signpost to first stable frame |
| Memory delta across transitions | warn > 30 MB | `XCTMemoryMetric` before/after transition |
| CPU during transition | warn > 80 % for > 500 ms | `XCTCPUMetric` |

**Simulator caveat:** simulator numbers are not device numbers. In v1, perf gates are *regression* gates against the project's own baseline, not absolute thresholds. The `--device` flag runs the same stage on hardware for real baselines.

### Agent loop

Failures are turned into structured payloads an agent can act on without re-reading the whole project:

```json
{
  "flow": "feed", "pose": "book", "orientation": "landscape",
  "assertion": "offscreen_elements",
  "elements": [{"id": "FeedHeader", "frame": [0, 0, 1180, 88], "screen": [0, 0, 1024, 1366]}],
  "screenshot": ".duo/runs/42/feed-book-landscape.png",
  "matched_rule": "hardcoded-width",
  "source_hint": "src/components/FeedHeader.tsx:14"
}
```

The agent patches, the pipeline reruns only the failed cells, up to `loop.max_iterations`. Each fix is its own commit with the rule name in the message so the PR is reviewable.

### Config

One file, `duo.yaml`, generated by `detect` and owned by the user. See §4.

---

## 3. Pipeline

```
duo-ready run
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────┐
│ 0 detect │→│ 1 scan   │→│ 2 fix    │→│ 3 build  │→│ 4 UI tests │→│ 5 perf   │→│ 6 report │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └───────────┘ └──────────┘ └────┬─────┘
                                ▲                                                     │ fail
                                └────────── 7 agent loop: failure → cause → patch ─────┘
                                                                                      │ pass
                                                                                      ▼
                                                                              ┌──────────────┐
                                                                              │ 8 assets +   │
                                                                              │ submit config│
                                                                              └──────────────┘
```

### Stage 0 — detect

Inputs: repo root. Outputs: `duo.yaml` scaffold, `.duo/env.json`.

- Project type: UIKit, SwiftUI, mixed, React Native (bare / Expo managed / Expo prebuild), Flutter, Capacitor.
- Xcode version, iOS SDK, deployment target, scheme, bundle id.
- Existing test targets (XCUITest, Detox, Maestro).
- Orientation locks (`Info.plist` `UISupportedInterfaceOrientations`, Expo `app.json` `orientation`, `react-native-orientation-locker`).
- Store tooling present (fastlane, EAS).

### Stage 1 — scan

Static rules. Each rule has: id, language, pattern (regex or AST query), severity, auto-fixable flag, Apple reference.

Native (superset of Apple's list):

| id | pattern | auto-fix |
|---|---|---|
| `screen-main-bounds` | `UIScreen.main.bounds` | yes |
| `screen-main-scale` | `UIScreen.main.scale` | yes |
| `window-frame-init` | `UIWindow(frame:)` | yes |
| `stored-uiscreen` | property of type `UIScreen` | manual |
| `orientation-layout` | `UIDevice.current.orientation`, `statusBarOrientation`, `interfaceOrientation` in layout code | manual, with suggested replacement |
| `idiom-check` | `userInterfaceIdiom == .phone/.pad` | manual |
| `regular-means-ipad` | `horizontalSizeClass == .regular` used to pick an "iPad" branch | manual |
| `hardcoded-size` | numeric comparisons against known device dimensions | yes (remove) |
| `fill-media` | `.scaleAspectFill`, `contentMode: .fill` on images/video | flag |
| `layout-once` | geometry read in `viewDidLoad` / `init` only, no `viewDidLayoutSubviews` | manual |
| `fixed-orientation-plist` | `UISupportedInterfaceOrientations` missing landscape | flag |

React Native / Expo:

| id | pattern | auto-fix |
|---|---|---|
| `rn-dimensions-module-scope` | `Dimensions.get('window'|'screen')` at module top level | yes → `useWindowDimensions` |
| `rn-dimensions-no-listener` | `Dimensions.get` inside component without `useWindowDimensions` or change listener | yes |
| `rn-platform-ispad` | `Platform.isPad` driving layout | manual |
| `rn-orientation-lock` | `expo-screen-orientation` lock, `orientation: "portrait"` in `app.json`, orientation-locker | flag |
| `rn-hardcoded-breakpoint` | `width < 375`, `=== 414`, etc. | manual |
| `rn-stylesheet-fixed-width` | `width: <number>` on root/full-width containers | flag |
| `rn-safe-area-missing` | screens without `SafeAreaView` / `useSafeAreaInsets` | flag |
| `rn-image-cover` | `resizeMode="cover"` on hero/full-bleed images | flag |

Flutter: `MediaQuery.of(context).size` cached in state, `OrientationBuilder` misuse, `kIsPad`-style checks, fixed `SizedBox` roots. Capacitor: viewport meta, CSS `100vh`, media queries by fixed px.

Output: `.duo/scan.json` + console table.

### Stage 2 — fix

- Apply auto-fixable rules as codemods (SwiftSyntax for Swift, jscodeshift/ts-morph for JS/TS, dart `analyzer` for Flutter).
- One commit per rule id on branch `duo-ready`, message `duo: fix <rule-id> (<n> sites)`.
- Non-auto-fixable findings become agent tasks with file, line, pattern and Apple's recommended replacement.
- `--dry-run` prints the diff without committing.

### Stage 3 — build

- Native: `xcodebuild -scheme <s> -sdk iphonesimulator -destination 'platform=iOS Simulator,name=iPhone Duo'`.
- RN/Expo: `npx expo prebuild --platform ios` (if managed) then the same.
- Flutter: `flutter build ios --simulator` then boot in the Duo sim.
- Requires Xcode 27.1 / iOS 27.1 SDK; fail fast with install instructions if missing.
- Output: `.app` path, build log, SDK used (so the report can state which toolbar behaviour applies).

### Stage 4 — UI tests

- For each flow × pose × orientation: boot sim in pose, launch app, run steps, capture screenshot + accessibility tree, run assertions.
- Transitions: run flow to the final step, trigger pose change, wait for stable frame, capture again, assert.
- Runners: XCUITest (native), Maestro (RN/Flutter). Both emit the same JSON.
- Baselines: `.duo/baselines/<flow>-<pose>-<orientation>.png`, committed after first green run. Visual diff via `odiff`.
- Output: `.duo/runs/<n>/ui.json`, screenshots.

**Resolved (27 Oct 2026):** neither `simctl` nor XCUITest exposes pose switching. `duoctl` and `hinge` send the same vendor HID event Device Hub sends and read the hinge angle back from CoreMotion. `scripts/sim.sh` wraps them; `scripts/preflight.sh` proves the readback works before any pose stage runs and exits 5 otherwise. Maestro cannot drive the inner display (issue 3617), so RN flows use Maestro only in closed cells.

### Stage 5 — performance

- XCTest performance tests generated per flow; metrics from §2.
- `xcrun xctrace record --template 'Animation Hitches'` for scroll flows.
- Baseline stored per cell; gates compare to baseline (regression) by default, to absolute thresholds with `--absolute` (intended for `--device`).
- Output: `.duo/runs/<n>/perf.json`.

### Stage 6 — report

- Single self-contained `duo-report.html`: matrix grid of screenshots per flow, diff overlays, assertion failures with highlighted elements, perf table with sparklines vs baseline, scan findings, SDK/toolbar note.
- Exit codes: 0 pass, 1 UI fail, 2 perf fail, 3 build fail. CI-friendly.
- `--json` for machine consumers.

### Stage 7 — agent loop

- Reads failures from stage 4/5 JSON, emits payloads (§2), waits for patch, reruns failed cells only.
- Adapters: Claude Code (SKILL.md + hooks), Cursor rules, plain `duo-ready loop --agent <cmd>` that pipes payloads to any command.
- Cap at `loop.max_iterations` (default 3); after that, leaves a `DUO-TODO.md` with remaining failures.

### Stage 8 — assets and submission

- From passing runs, generate store screenshots at Apple's Duo specs per pose (dimensions from App Store Connect spec page; keep in `specs/asc-duo.json`, update when Apple changes).
- Optional device frames and captions from `assets.yaml`.
- Write to `fastlane/screenshots/<locale>/` (deliver 2.241.1 or later knows the Duo sizes) or upload with `asc screenshots upload --device-type APP_IPHONE_DUO`; inner-display API upload is unverified, so the skill recommends the App Store Connect web uploader for that set until confirmed.
- Draft `FEATURING.md`: nomination text stating the app is optimized for iPhone Duo in all poses.

---

## 4. Configuration — `duo.yaml`

```yaml
stack: react-native            # uikit | swiftui | react-native | expo | flutter | capacitor
scheme: MyApp
bundle_id: com.example.myapp

poses: [closed, book, tent]
orientations: [portrait, landscape]
transitions: [closed→book, book→closed, book→tent]

flows:
  - name: onboarding
    steps: [launch, tap "Get started", wait "Welcome"]
  - name: feed
    steps: [launch, wait "Feed", scroll 5]

assert:
  offscreen_elements: fail
  clipped_text: fail
  tap_target_min: 44
  visual_diff_threshold: 0.02     # fraction of pixels

perf:
  mode: regression                # regression | absolute
  launch_ms:        { warn: 800,  fail: 1500 }
  hitch_rate:       { fail: 5 }
  fold_relayout_ms: { fail: 250 }
  memory_delta_mb:  { warn: 30 }

loop:
  max_iterations: 3

assets:
  locales: [en-US]
  frames: true
  output: fastlane/screenshots
```

---

## 5. Repository layout

```
duo-ready/
├── SKILL.md                  # agent-facing instructions (Claude Code / Cursor / Codex)
├── README.md                 # human-facing; demo video; install
├── LICENSE                   # MIT
├── bin/duo-ready             # CLI entry (node or swift)
├── src/
│   ├── detect/
│   ├── scan/rules/{swift,rn,flutter,capacitor}/
│   ├── fix/codemods/
│   ├── build/
│   ├── ui/{xcuitest,maestro}/
│   ├── perf/
│   ├── report/
│   ├── loop/adapters/{claude-code,cursor,generic}/
│   └── assets/
├── specs/asc-duo.json        # Apple's screenshot specs, versioned
├── templates/{duo.yaml,flows.yaml,assets.yaml,github-actions.yml}
├── examples/
│   ├── uikit-sample/         # intentionally broken → fixed
│   └── expo-sample/
└── docs/
    ├── rules.md              # every scan rule with before/after
    ├── simulator-vs-device.md
    └── ci.md
```

### SKILL.md outline

1. When to use (user mentions iPhone Duo, foldable, April 2027 screenshots, size classes on iPhone).
2. Preconditions check (Xcode 27.1, macOS, free disk).
3. Run `duo-ready detect` → confirm `duo.yaml` with the user, ask for 2–5 flows if none.
4. Run `scan` → present findings grouped by rule → run `fix --dry-run` → confirm → `fix`.
5. `build` → `ui` → `perf` → open report.
6. For each failure payload: read `source_hint`, patch minimally, commit with rule id, rerun failed cells.
7. When green: `assets` → show where screenshots landed → offer featuring nomination text.
8. Never claim apps are removed for non-compliance; state the actual April 2027 rule.

---

## 6. Environment

- **MacBook only is sufficient** for every stage. Apple Silicon strongly preferred.
- macOS 27 (optional, for iPhone Mirroring resize tests), Xcode 27.1, iOS 27.1 runtime, ~40 GB free.
- A physical iPhone Duo is optional. It adds real perf numbers, hinge/tent behaviour, outer-display camera-region rendering, touch latency. Design `--device` from day one so contributors with hardware can submit baselines.
- CI: GitHub Actions `macos-latest` once it carries Xcode 27.1; ship a self-hosted-Mac workflow variant for the interim.

---

## 7. Build plan

**Week 1 — spine.** Install Xcode 27.1. Run Apple's assistant and `xcrun agent skills export` on a real app; read Apple's exported skill. Verify pose control from CLI (the open question). Implement detect, scan (native rules), fix (3–4 codemods), build. Run on one real app end-to-end.

**Week 2 — proof.** Stage 4 with pose switching (or resizable-sim proxy), screenshots, bounds + clipping assertions, baselines, diff. First `duo-report.html`.

**Week 3 — gates.** Perf stage with XCTest metrics, regression baselines, exit codes, GitHub Actions template. `docs/rules.md` with before/after for every rule.

**Week 4 — agent + RN + launch.** Agent loop with Claude Code adapter. RN/Expo rule set and codemods. `examples/expo-sample`. README with a timed demo video on a real app (clone → green report → assets). Launch post; tag one ecosystem account once.

**v1.1 (early Dec).** Stage 8 assets + fastlane/EAS wiring. Flutter rules. `--device` perf.

---

## 8. Launch and distribution

- Launch post: a 60–90 s screen recording of the full run on a real app with the elapsed time on screen, plus one surprising number (e.g. "found 23 Duo breakages in a 2-year-old Expo app, fixed 17 automatically").
- Post Tue–Thu, 14:00–16:00 UK. Tag the framework's company account once; never ask for a share.
- Follow-ups: PR a link into Expo docs / awesome-react-native; guest post on a moderated outlet with the data from the first 50 runs; talk proposal "What N apps got wrong on iPhone Duo" for spring 2027 conferences.
- Ask DevRel contacts who engage for a short written note once the project has users — maintainers and DevRel write these routinely.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| `duoctl`/`hinge` rely on a private HID protocol that an Xcode update can break | Preflight verifies angle readback and exits 5; pose stages degrade to manual Device Hub instructions, never a fake pass; pin brew versions |
| Apple extends its assistant to cover the whole pipeline | Our value is cross-platform + CI + assets; stay ahead on RN/Flutter |
| Hosted CI lacks Xcode 27.1 for months | Self-hosted workflow variant; document |
| Screenshot specs change | Versioned `specs/asc-duo.json`; CI job that diffs the spec page |
| Shelf life ends April 2027 | Fine — adoption and relationships land before then; position as the first of a series of agent-pipeline tools |

---

## 10. One-line summary

duo-ready: scan → fix → build → test every pose → gate perf → report → fix with an agent → generate the screenshots Apple requires from April 2027. Runs on a MacBook with Xcode 27.1; no iPhone Duo needed.
