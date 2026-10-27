# Driving the iPhone Duo simulator from scripts

Cookbook for `scripts/sim.sh`, `capture.sh` and `run-matrix.sh`. Verified 27 Oct 2026 on community reports for Xcode 27.1 (27A9275) and 27.2 RC with the iOS 27.1 runtime. Nothing here is a public Apple API except `simctl` and `devicectl`; the pose tools reuse the private HID event Device Hub sends, so pin their versions and expect an Xcode update to break them.

## Contents

1. [Requirements](#1-requirements)
2. [Create and boot](#2-create-and-boot)
3. [Pose tools: duoctl and hinge](#3-pose-tools-duoctl-and-hinge)
4. [Pose names and angles](#4-pose-names-and-angles)
5. [Wait-for-posture rule](#5-wait-for-posture-rule)
6. [Rotation](#6-rotation)
7. [Screenshots per display](#7-screenshots-per-display)
8. [Touch and element trees on the inner display](#8-touch-and-element-trees-on-the-inner-display)
9. [XCUITest bridge pattern](#9-xcuitest-bridge-pattern)
10. [Maestro limitations](#10-maestro-limitations)
11. [Device Hub manual fallback](#11-device-hub-manual-fallback)
12. [CI boot recipe](#12-ci-boot-recipe)
13. [Known issues](#13-known-issues)
14. [Sources](#14-sources)

## 1. Requirements

- macOS Tahoe 26.6 or later, Xcode 27.1 or later, iOS 27.1 simulator runtime (`xcodebuild -downloadPlatform iOS` installs it).
- The iOS 27.1 runtime supports only the `iPhone Duo` device type (model `iPhone19,4`); creating another iPhone on it fails with "Incompatible device". Test other phones on 27.0.
- Homebrew for `duoctl` and `hinge`. Both compile a small helper with Xcode's clang on first run and cache it under `~/.cache/<tool>`.
- Optional: AXe for `duoctl --label`, `--id` and `elements`.

`scripts/preflight.sh` checks all of this and exits 4 with the missing tool named.

## 2. Create and boot

```bash
UDID=$(xcrun simctl create ci-duo "iPhone Duo" com.apple.CoreSimulator.SimRuntime.iOS-27-1)
xcrun simctl boot "$UDID"
xcrun simctl bootstatus "$UDID" -b      # blocks until booted
xcrun simctl install "$UDID" build/MyApp.app
xcrun simctl launch "$UDID" com.example.myapp
```

The device boots closed, on the outer display. Boot with `simctl`, not through Device Hub: quitting Device Hub shuts down the simulators it booted. Initial launch can take minutes (Xcode 27.1 known issue 187708500), and screenshots may be black for a few minutes after boot (27.2 RC known issue 187146039).

## 3. Pose tools: duoctl and hinge

| | duoctl (skarol) | hinge (artemnovichkov) |
|---|---|---|
| Install | `brew install skarol/tap/duoctl`; agent skill `npx skills add skarol/duoctl` | `brew install artemnovichkov/tap/hinge`; `npx skills add artemnovichkov/hinge`; Claude plugin `/plugin marketplace add artemnovichkov/hinge` |
| License | MIT | MIT |
| Mechanism | helper spawned with `xcrun simctl spawn` sends vendor HID events (usage page 0xFF61, usage 0x5B); touches cloned onto the active display's touchscreen | same HID event through the simulator `IOHIDEventSystem`; angle read back from private `CMAngleManager` |
| Readback | `duoctl state` (JSON: angle, active screen, orientation, size) | `hinge get`, `hinge posture [--json]` |
| Select device | `-d <udid|name>` or `DUOCTL_UDID`; never guesses with several Duos | `-d`/`--device`, `HINGE_DEVICE`, else the only booted Duo |
| Verified on | Xcode 27.1 + iOS 27.1 | Xcode 27.1 and 27.2 + iOS 27.1 |

Commands:

| Job | duoctl | hinge |
|---|---|---|
| Close (0°) | `duoctl close` | `hinge close` |
| Open flat (180°) | `duoctl open [--duration s]` | `hinge open` |
| Half (90°) | `duoctl half` | `hinge half` |
| Any angle | `duoctl hinge 127 [--duration s]` | `hinge 127` / `hinge set 127` |
| Animate | `--duration` on any fold | `hinge sweep 180 0 2` |
| Rotate | `duoctl rotate portrait|landscape|portrait-upside-down|landscape-flipped` (interface orientations) | `hinge rotate left|right`, `hinge orient portrait|landscape-left|landscape-right|portrait-upside-down` (device orientations) |
| Screenshot of the lit display | `duoctl screenshot out.png` | `hinge screenshot out.png [--json]` |
| Tap | `duoctl tap x y`, `duoctl tap --label L`, `--id I` | none |
| Long press / swipe | `duoctl long-press x y`, `duoctl swipe x1 y1 x2 y2` | none |
| Element list | `duoctl elements` (needs AXe) | none |
| Confirm angle | checks state after every change, errors otherwise | waits for CoreMotion up to `--timeout` (default 2 s) |

`scripts/sim.sh` prefers `duoctl` (it also taps) and falls back to `hinge` for pose changes. Pin both in the README; if either stops confirming angles, assume the protocol changed, exit 5 and stop the pose stages.

A third implementation, `tosbaha/duo-fold-control`, sends the event from the host over CoreSimulator XPC and ships an XCTest bridge (section 9). It documents the mechanism in detail: `dtuhidd` builds the vendor event, `locationd` reads `hinge-slider-control` as degrees, SpringBoard moves the scene between displays.

## 4. Pose names and angles

| Cell pose | Angle | Hinge status | Lit display | Window (27.1 SDK) |
|---|---|---|---|---|
| `closed` | 0° | `closed` | outer | 466 × 678 pt portrait |
| `book` | 127° (Device Hub "Book") | `partiallyOpen` | inner, fold active | 951 × 669 pt |
| `open` | 180° | `fullyOpen` | inner, fold inactive | 951 × 669 pt |

Use 127°, not the tools' `half` (90°), so measurements match Device Hub's Book button. Only the fold region's active state differs between `book` and `open`; the window size is identical. Tabletop and standing are not separate simulator states.

The path matters: jumping 0° to 90° can move the app to the inner display while a slow sweep may leave it on the outer one. Set the final angle in one step for cells; use `sweep`/`--duration` only for transition timing tests.

## 5. Wait-for-posture rule

The lit display changes 1 to 2.5 s after the angle. Never capture or tap right after a pose command:

```bash
duoctl hinge 127
until duoctl state | grep -q '"inner"'; do sleep 0.25; done   # field names: check duoctl state output
sleep 1
```

Prefer an app-level signal: wait for a label or accessibility id that only exists on the target screen. Treat a pose as confirmed only when the readback reports it. A simulator can stop following the hinge while still reporting angles; shut it down and boot again.

## 6. Rotation

Only the HID orientation event works. `xcrun devicectl device orientation set` and `XCUIDevice.shared.orientation` report success without rotating the Duo simulator. `duoctl rotate` tries orientations until the active screen reports the requested rotation; `hinge orient` names device orientations, so `landscape-left` versus `landscape-right` matters. The default unfolded orientation of the inner display is landscape, and the inner panel is mounted a quarter turn from the outer one, so captures in landscape poses come out rotated.

## 7. Screenshots per display

Both displays exist at once; only one is lit, the other captures solid black.

```bash
xcrun simctl io "$UDID" enumerate        # lists displays with UUIDs and widths
xcrun simctl io "$UDID" screenshot --display="$OUTER_UUID" closed.png
xcrun simctl io "$UDID" screenshot --display="$INNER_UUID" open.png
```

Pick the display by width: 1398 is the outer, 2007 the inner. UUIDs change every boot, and index names (`--display=1`/`3`, `primary`/`primary-1`) differ between Xcode builds, so never hardcode them. Output is already at App Store pixel size (outer 1398 × 2034, inner 2007 × 2853). Captures include the status column on the outer display. `duoctl screenshot` and `hinge screenshot` capture the lit display without enumerating.

Validate every PNG: a black or empty frame is still a valid file. `scripts/capture.sh` rejects images with under 0.5% non-black pixels and retries after a short wait, because the simulator returns black for minutes after boot.

Do not use `xcrun simctl io screenConfig` to switch or power displays: it can turn a display off without opening the device and has crashed the system shell.

## 8. Touch and element trees on the inner display

Each display has its own touchscreen. AXe, XcodeBuildMCP, RocketSim and Maestro inject touches into the outer (cover) touchscreen only, so taps aimed at the open inner display land on the cover. Use `duoctl tap` (coordinates in interface points of the lit display, converted for the current rotation) or XCUITest running inside the app.

Element frames for `scripts/assert.py` come from:
- XCUITest: `app.descendants(matching: .any)` with `frame`, `identifier`, `label`, `elementType`, `isHittable`; the template dumps them to `<flow>-<cell>.tree.json`.
- AXe via `duoctl elements`: labelled elements with frames.

Accessibility Inspector, VoiceOver and similar tools cannot read Duo content inside Device Hub (27.2 RC known issue 187148389); the in-app tree is the only reliable source.

## 9. XCUITest bridge pattern

XCTest has no hinge API. Pattern from `tosbaha/duo-fold-control`: a host-side HTTP server wraps the pose tool, and the test calls it with the simulator's own `SIMULATOR_UDID`.

```
host:  duo-hinge-server.py --port 8765   # GET /hinge?state=closed|half|flat&udid=...  GET /ping
test:  DuoFold.set(.closed) / .half / .flat / DuoFold.set(degrees: 127)
       DuoDisplay / attachScreenshot("name", of: .inner)   // XCUIScreen.main always returns the cover
```

`templates/DuoUITests.swift` does the same against `scripts/sim.sh pose <cell>` through a local server. Set the pose in `setUp()` when a test depends on it; state persists between tests and runs. The call returns before the display animation ends, so wait for a UI label, not a fixed sleep. `http://127.0.0.1` needs no App Transport Security exception.

## 10. Maestro limitations

Open issue mobile-dev-inc/maestro#3617: no `setFoldPosture`/`setSplitScreen`; `setOrientation` only rotates; the inner-screen view hierarchy is reported shifted and truncated (#3623); taps go to the cover screen; the device profile reports enhanced multitasking as false, so Split View may not be scriptable at all. One production pipeline (boardsesh PR #6953) works around it with deep links, id waits and `simctl` inner captures while Maestro drives only the closed pose.

Rule for the RN runner: Maestro for `closed-*` cells; `open-*`/`book-*` via deep links plus `duoctl tap --label` or XCUITest. Flows that must run on the inner display should expose deep links and accessibility ids.

## 11. Device Hub manual fallback

Device Hub (Xcode 27.1) has buttons Closed, Book, Open and Rotate Right; holding Option over them shows a slider for any hinge angle. Use this when preflight exits 5. Device Hub's slider does not move when `duoctl`/`hinge` change the angle. Drag the app by the home indicator to either side to test Split View; whether Split View can be scripted is unverified.

## 12. CI boot recipe

```bash
sudo xcode-select -s /Applications/Xcode_27.1.app
xcodebuild -downloadPlatform iOS            # retry; downloads can fail on hosted runners
brew install skarol/tap/duoctl artemnovichkov/tap/hinge
UDID=$(xcrun simctl create ci-duo "iPhone Duo" com.apple.CoreSimulator.SimRuntime.iOS-27-1)
xcrun simctl boot "$UDID" && xcrun simctl bootstatus "$UDID" -b
export DUOCTL_UDID="$UDID" HINGE_DEVICE="$UDID"
sleep 120                                   # black-frame window after boot
duoctl open && duoctl rotate portrait && duoctl screenshot open-portrait.png
```

Hosted `macos-latest` did not carry Xcode 27.1 at verification time; `templates/github-actions-duo.yml` ships a self-hosted variant. Selecting Xcode 27 and installing the 27.1 runtime on hosted CI is unproven.

## 13. Known issues

From the Xcode 27.1 and 27.2 RC release notes unless marked community:

- Initial Simulator launch can take several minutes (187708500).
- StandBy unavailable in the Duo runtime (187708663).
- Most app extensions cannot run or be debugged in the Duo runtime (187708767).
- Screenshots and recordings may be black for up to a few minutes after boot (187146039).
- Accessibility tools cannot convey Duo screen content inside Device Hub (187148389).
- Modifier keys may stop working after switching displays; click the visible screen (189465196).
- Fixed in 27.2: `CameraCaptureAccessory` could use both displays without an active capture session (190155353).
- Community: hinge sometimes stops responding, reboot the simulator; display switch lag 1 to 2.5 s; pose tools do not update Device Hub's slider; a `UIView` built against 27.1 reports zero default layout margins on the Duo runtime; black frames after boot.

## 14. Sources

- Xcode 27.1 release notes: https://developer.apple.com/documentation/xcode-release-notes/xcode-27_1-release-notes
- Xcode 27.2 RC release notes: https://developer.apple.com/documentation/xcode-release-notes/xcode-27_2-release-notes
- Tech Talk 111461 (Device Hub testing steps): https://developer.apple.com/videos/play/tech-talks/111461/
- duoctl: https://github.com/skarol/duoctl
- hinge: https://github.com/artemnovichkov/hinge
- duo-fold-control: https://github.com/tosbaha/duo-fold-control
- agent-device fold command: https://github.com/callstack/agent-device/pull/2717
- Maestro issue: https://github.com/mobile-dev-inc/maestro/issues/3617
- Command-line testing guide: https://fitsduo.com/guides/command-line-testing
- Worked example with measurements: https://blakecrosley.com/blog/prepare-your-app-for-iphone-duo
- boardsesh Duo screenshot CI: https://github.com/boardsesh/boardsesh/pull/6953
