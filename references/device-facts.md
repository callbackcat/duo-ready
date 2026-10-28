# iPhone Duo device facts

Verified 27 Oct 2026 against Apple's pages and the iOS 27.1 simulator (community measurements marked *sim*). Use these numbers in assertions, screenshot gates and layout advice. Re-verify whenever Xcode or the ASC spec page changes.

## Displays

| Display | Diagonal | Pixels (portrait) | Pixels (landscape) | Scale | Notes |
|---|---|---|---|---|---|
| Outer (closed) | 5.4" | 1398 × 2034 | 2034 × 1398 | 3× | Wider and shorter than other iPhones. Front camera in the corner, always visible. |
| Inner (open) | 7.6" | 2007 × 2853 | 2853 × 2007 | 3× | Folds in the middle. Front camera hidden until active. |

Sources: App Store Connect screenshot specifications; Apple design resources bezel.

## App window in points, by SDK the binary was built with (*sim*)

| SDK stamp | Closed | Closed, turned | Open (default landscape) | Open, turned | Behaviour |
|---|---|---|---|---|---|
| iOS 26 or earlier | 375 × 667 boxed | 667 × 375 | 375 × 667 boxed in the inner display | same | Runs, centered with empty space; closed pose sits left of status bar and camera. Compact height throughout. |
| iOS 27.0 | 386 × 678 | 678 × 386 | 871 × 669 | 669 × 871 | Fills most of the display but avoids the status bar on the right edge. No vertical bars, no reserved regions. |
| iOS 27.1+ | **466 × 678** | **678 × 466** | **951 × 669** | **669 × 951** | Edge to edge. Toolbars and tab bars move to the vertical trailing edge. Reserved regions reported. |

Check the stamp with `scripts/sdk-stamp.sh` (reads the `sdk` value of the `LC_BUILD_VERSION` load command via `otool -l`). A 27.0 stamp invalidates every later measurement.

Two consequences of building with the 27.x SDK, verified on the simulator 27 Oct 2026:
- UIKit kills an app that has no UIScene life cycle about 2 s after launch ("UIScene life cycle is required for apps built with this SDK", TN3187). Expo SDK 54 and React Native 0.81 templates ship without one; SwiftUI `App` apps are fine. The scan rules `no-scene-delegate` and `expo-no-scene-lifecycle` are launch blockers.
- Xcode 27.1 refuses deployment targets below iOS 15, which old CocoaPods resource bundles still declare (`IPHONEOS_DEPLOYMENT_TARGET=15.0` or a Podfile `post_install` fixes it).

The outer window is 678 pt tall, shorter than any current iPhone (the 6.1" class is 852 pt). Screens that size a hero or block from a fixed height or a large fraction of the window height run out of room there before they run out of width.

## Size classes (iOS 27.1 SDK)

| Cell | Horizontal | Vertical | Bars |
|---|---|---|---|
| closed-portrait | compact | regular | vertical, trailing edge |
| closed-landscape | compact | compact | vertical, trailing edge |
| open-landscape | regular | regular | vertical, trailing edge |
| open-portrait | regular | regular | **horizontal** (only pose with horizontal bars) |
| book-landscape | regular | regular | vertical, trailing edge; fold active |
| book-portrait | regular | regular | horizontal; fold active |
| split-view-left/right | compact or regular depending on width | regular | vertical, on the app's **outer** edge |

Facts that break assumptions:
- The outer display behaves like other iPhones. The inner display is regular in **both** dimensions.
- The inner display **does not honor `UISupportedInterfaceOrientations`**. Orientation locks are ignored there.
- A 6.9" iPhone in landscape is regular width with **compact height**. "Regular width means Duo inner display" is wrong; check height too.
- `userInterfaceIdiom` is `.phone` on iPhone Duo. `Platform.isPad` is false in React Native.

## Poses and hinge angles

| Name (Apple) | Hinge angle | Active display | Simulator control |
|---|---|---|---|
| Closed | 0° | outer | `duoctl close` / `hinge close` |
| Partially folded ("book") | ~127° (Device Hub "Book" button); `duoctl half` and `hinge half` use 90° | inner, fold region active | `duoctl hinge 127` / `hinge 127` |
| Open / fully open / flat | 180° | inner, fold region inactive | `duoctl open` / `hinge open` |
| Tabletop, standing, tent | same hinge states as above; physical placement only | — | not modelled by the simulator beyond angle + rotation |

`hinge.status` / `UIHingeInteraction` report `closed`, `partiallyOpen`, `fullyOpen` (plus `unknown`). The window size is identical for open and book; only the fold region's active state changes. The active display switches 1–2.5 s after the angle changes (*sim*).

Rotation: `duoctl rotate portrait|landscape|portrait-upside-down|landscape-flipped`, `hinge orient ...`. `xcrun devicectl device orientation set` and `XCUIDevice.shared.orientation` report success without rotating the Duo simulator.

## Reserved regions (iOS 27.1 SDK, points, *sim*)

| Region | Kind | Cell | Frame | Active when |
|---|---|---|---|---|
| Fold | division | open-/book-landscape (951 wide) | x 455–495, full height (40 pt wide; 20 pt margin each side) | device partially folded |
| Fold | division | open-/book-portrait (669 wide) | y 455–495, full width | device partially folded |
| Outer front camera | occlusion | closed-* | 37 × 37, top-trailing corner inside the status column | always |
| Inner front camera | occlusion | open-*, book-* | 58 × 37 | only while the camera is active |
| Status column | system | closed-portrait | 84 × 170 at the trailing edge | always |
| Status column | system | open-landscape | 84 × 120 at the trailing edge | always |
| Status area | system | open-portrait | 134 × 82 at the top | always |

Content width in open-landscape is roughly 867 pt; the two sides of the fold are 455 pt and 372 pt because the vertical bar takes the trailing edge. A grid centered on the content area puts a column across the fold; center on the division frame instead.

Regions are empty for the first few layout passes. Read them on every layout, never cache them.

## Simulator identity and commands

- Device type: `iPhone Duo` (`com.apple.CoreSimulator.SimDeviceType.iPhone-Duo`, model `iPhone19,4`). Runtime: `com.apple.CoreSimulator.SimRuntime.iOS-27-1`. The 27.1 runtime supports only the Duo device type; test other iPhones on 27.0.
- Create and boot: `xcrun simctl create ci-duo "iPhone Duo" com.apple.CoreSimulator.SimRuntime.iOS-27-1`, `xcrun simctl boot <UDID>`, `xcrun simctl bootstatus <UDID> -b`. Boots closed.
- Displays: `xcrun simctl io <UDID> enumerate` lists both with UUIDs that change every boot. Pick by width (1398 outer, 2007 inner). Capture: `xcrun simctl io <UDID> screenshot --display=<UUID> out.png`. The inactive display captures solid black; landscape poses capture rotated.
- Never use `simctl io screenConfig` to switch displays; it can turn a display off and crash the shell.

## Known simulator issues (Xcode 27.1 / 27.2 RC release notes)

- Screenshots and recordings may be black for up to a few minutes after boot (187146039). Validate every capture.
- VoiceOver, Accessibility Inspector and other accessibility tools cannot read Duo content inside Device Hub (187148389). Get element trees from XCUITest inside the app or from AXe (`duoctl elements`).
- StandBy and most app extensions are unavailable in the Duo runtime (187708663, 187708767).
- Initial Simulator launch can take several minutes (187708500).
- Modifier keys may stop working after switching displays; click the visible screen (189465196).
- Quitting Device Hub shuts down the simulators it booted; boot with `simctl` for automation.
- SpringBoard on the outer display is portrait only, and a portrait-locked app refuses `duoctl rotate` there (verified 27 Oct 2026); landscape cells of such an app are skipped, not failed.

## App Store

- Duo screenshots are optional today. From **April 2027 they are required for every submission of an app built with the iOS 27.1 SDK or later**. Submitting them now earns the "optimized for iPhone Duo" badge on the product page. Apple has not said apps will be removed.
- Dates: announcement 9 Sep 2026; developer news 5 Oct 2026; device on sale 23 Oct 2026 with iOS 27.1; iOS 27.2 shipped 26 Oct 2026.

## Sources

- https://developer.apple.com/design/human-interface-guidelines/designing-for-iphone-duo
- https://developer.apple.com/documentation/technologyoverviews/preparing-your-app-for-iphone-duo
- https://developer.apple.com/iphone-duo/prepare/
- https://developer.apple.com/news/?id=kkphp5qo
- https://developer.apple.com/videos/play/tech-talks/111461/ (Prepare), 111462 (Raise the bar), 111463 (Strike a pose), 111464 (Multiple displays), 111466 (Design)
- https://developer.apple.com/documentation/xcode-release-notes/xcode-27_1-release-notes and xcode-27_2-release-notes
- https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications
- *sim* measurements: https://blakecrosley.com/blog/prepare-your-app-for-iphone-duo, https://github.com/tosbaha/duo-fold-control, https://fitsduo.com/guides/command-line-testing
