# Apple guidance for iPhone Duo, condensed by job

Digest of the HIG page "Designing for iPhone Duo", the technology overview "Preparing your app for iPhone Duo", the prepare page, and Tech Talks 111461 (Prepare), 111462 (Raise the bar), 111463 (Strike a pose), 111464 (Multiple displays and scenes), 111466 (Design). Paraphrased; API names are exact. Verified 27 Oct 2026. Numbers live in `device-facts.md`.

## Contents

1. [The one rule](#1-the-one-rule)
2. [Build and SDK tiers](#2-build-and-sdk-tiers)
3. [Resizing and size classes](#3-resizing-and-size-classes)
4. [Screen access](#4-screen-access)
5. [Safe areas and asymmetry](#5-safe-areas-and-asymmetry)
6. [Vertical bars](#6-vertical-bars)
7. [Reserved regions](#7-reserved-regions)
8. [Arrangement views](#8-arrangement-views)
9. [Hinge, Split View, scenes, accessories](#9-hinge-split-view-scenes-accessories)
10. [Camera direction](#10-camera-direction)
11. [Games](#11-games)
12. [UIScene lifecycle](#12-uiscene-lifecycle)
13. [Design patterns for the inner display](#13-design-patterns-for-the-inner-display)
14. [Apple's own checklist](#14-apples-own-checklist)
15. [App Resizability skill](#15-app-resizability-skill)
16. [Sources](#16-sources)

## 1. The one rule

Do not design a layout per pose. Build the app to resize: a compact-width layout for the outer display and a regular-width layout for the inner display cover every pose. Use size classes, layout margins and safe area insets; avoid fixed widths and anything tied to a specific display. Standard system containers adapt on their own; custom code is what breaks.

Keep functionality and element state the same across displays and poses. Show an extra level of hierarchy on the inner display when it makes sense (Mail shows list and message side by side when open), but never tie a feature to one pose.

## 2. Build and SDK tiers

| Built with | Behaviour on iPhone Duo |
|---|---|
| iOS 26 SDK or earlier | Runs, centered in a phone-sized box with empty space when open; sits left of the status bar and camera when closed. |
| iOS 27 SDK | Fills most of the inner display but stops short of the status bar on the right edge. |
| iOS 27.1 SDK or later | Edge to edge. Navigation bars, toolbars and tab bars lay out vertically under the status bar. |

Xcode 27.1 is required for the full experience. Before shipping with the 27.1 SDK, check that content adapts to vertical bars. Apps built with older SDKs still run without recompiling.

## 3. Resizing and size classes

| Job | SwiftUI | UIKit |
|---|---|---|
| Read size class | `@Environment(\.horizontalSizeClass)`, `@Environment(\.verticalSizeClass)` | `traitCollection.horizontalSizeClass`, `.verticalSizeClass` (use automatic trait tracking) |
| Size-dependent layout | `GeometryReader`, `onGeometryChange` | `layoutSubviews`, `viewDidLayoutSubviews`; `viewWillTransition(to:with:)` for work that must run on size change |
| Wider than tall? | compare the `GeometryReader` size | compare `view.bounds` or `superview.bounds` |

Size classes per cell: outer portrait is compact width, regular height; outer landscape is compact in both; the inner display is regular in both dimensions in every pose.

Remove from layout code:
- `UIDevice.current.orientation`, `statusBarOrientation`, `interfaceOrientation` and `windowScene.effectiveGeometry.interfaceOrientation`. The inner display does not honor supported interface orientations.
- `userInterfaceIdiom == .phone` or `.pad` as a layout switch. Use size classes or available space.
- `horizontalSizeClass == .regular` meaning "iPad". iPhone Duo reports regular width. (A 6.9" iPhone in landscape is regular width with compact height; check both.)
- Comparisons against known device sizes such as `bounds.height == 844` and lists of iPhone sizes.
- Size read once at launch, in `init`, `viewDidLoad` or `viewIsAppearing`, and never again.

Full-bleed media using `.scaleAspectFill` or `.aspectRatio(contentMode: .fill)` can crop important content when the aspect ratio changes. Choose fill or fit by size class or aspect ratio, or set a focal point.

Adopt Auto Layout in UIKit. Prefer `NavigationSplitView` / `UISplitViewController`, `TabView` / `UITabBarController`, `NavigationStack` / `UINavigationController`, `List`, `ScrollView` and arrangement views, all of which adapt to the outer display, the open or folded inner display and camera occlusions.

## 4. Screen access

`UIScreen.main` is ambiguous on a two-display device and will be deprecated.

| Job | SwiftUI | UIKit |
|---|---|---|
| Bounds for layout | `GeometryReader`, scene geometry | `view.bounds`, `window.bounds` |
| Display scale | `@Environment(\.displayScale)` | `traitCollection.displayScale` |
| Create a window | n/a | `UIWindow(windowScene:)`, never `UIWindow(frame: UIScreen.main.bounds)` |
| Need the screen object | n/a | `view.window?.windowScene?.screen`, never a stored `UIScreen` |

```swift
let screen = window?.windowScene?.screen
```

## 5. Safe areas and asymmetry

Foreground content (anything interactive) stays inside the safe area. Background content (artwork, hero images) may extend past it. Because controls sit along one edge, safe areas and layout margins are asymmetric: never assume opposite edges are equal, including in Split View where the other app's bars sit on the far edge.

| Job | SwiftUI | UIKit |
|---|---|---|
| Inset by default | content is inside the safe area already; `.ignoresSafeArea()` for backgrounds | `view.bounds.inset(by: view.safeAreaInsets)` for foreground; `backgroundView.frame = view.bounds` for background |
| Per-edge width | read each inset | `let width = view.bounds.inset(by: view.safeAreaInsets).width` |

On the outer display most content needs an offset so it is not hidden behind the side controls; safe area insets provide it. Immersive, non-scrolling visuals can stay centered full width if no interactive element sits under the controls. A mixed approach works: full-width background or header with inset, scrollable foreground.

Concentric corners: `ConcentricRectangle` (SwiftUI) and `UICornerConfiguration` (UIKit), iOS 26 APIs updated for the device.

## 6. Vertical bars

Navigation, toolbar and tab bar controls share one vertical region on the trailing edge when the device is closed, and on the inner display in landscape. Inner portrait keeps horizontal bars. In Split View each app places its bars on its outer edge. Bars stay on the same hardware side in right-to-left languages.

**Opt in.** Rebuild with the 27.1 SDK and use the system containers. Content from custom `UIToolbar`, `UINavigationBar` or `UITabBar` instances is ignored.

```swift
NavigationStack {
    ContentView()
        .toolbar {
            ToolbarItem(placement: .bottomBar) { ... }
        }
}
```

**Ordering.** Top of the column: primary navigation (Back, Close), then prominent actions (Done). Remaining items keep their groups; the system inserts a vertical spacer between top-bar and bottom-bar items. Tab bars stay bottom-aligned.

| Job | SwiftUI | UIKit |
|---|---|---|
| Custom Back/Close | `ToolbarItem(placement: .cancellationAction)` | `navigationItem.leadingItemGroups`; `leftItemsSupplementBackButton = false` |
| Prominent action | `ToolbarItem(placement: .topBarPinnedTrailing)` | `navigationItem.pinnedTrailingGroup` |
| Group items | `ToolbarItemGroup` | `UIBarButtonItemGroup` |

**Item axis.** Vertical bars have fixed width and flexible height. Items with a symbol move vertically; title-only items and custom views stay horizontal. Always give an item both a symbol and a title: vertical uses the symbol, horizontal prefers the symbol, the overflow menu uses both. Do not add manual spacing; flexible spacers are zero-size vertically.

| Behavior | Use | SwiftUI | UIKit |
|---|---|---|---|
| `.verticalPreferred` | custom view that has a vertical form | `.axisBehavior(.verticalPreferred)` on the `ToolbarItem` | `item.axisBehavior = .verticalPreferred` |
| `.horizontalOnly` | item that toggles between symbol and text | `.axisBehavior(.horizontalOnly)` | `item.axisBehavior = .horizontalOnly` |

Use badges instead of inline counts: `.badge(7)` / `item.badge = .count(7)`. The system Edit button and keyboard accessory bars stay horizontal.

**Overflow and priority.** Items overflow bottom to top by default. Assign visibility priorities, groups first, then items. Keep frequent actions (Compose, New Note) and badged items visible longest. Consolidate custom overflow menus into the system one and reserve the ellipsis for it.

| Job | SwiftUI | UIKit |
|---|---|---|
| Priority | `.visibilityPriority(.high)` | `item.visibilityPriority = .high` |
| Overflow items | `ToolbarOverflowMenu { Button("Scan") {...} }` | `navigationItem.additionalOverflowItems = UIDeferredMenuElement { ... }` |

**Compression.** Default: toolbar items overflow first, which suits navigation-focused apps. Task-oriented views can compress the tab bar instead.

| SwiftUI | UIKit |
|---|---|
| `.toolbarVerticalCompressionBehavior(.prefersToolbarItems)` | `navigationItem.verticalBarCompressionBehavior = .prefersBarItems` |
| `ToolbarVerticalCompressionBehavior` | `UIVerticalBarCompressionBehavior` |

**Detect and adapt custom views.** Read the edge; it is nil or unspecified when bars are horizontal. Vertical bars have no scroll-edge effect by default but get a background under Reduce Transparency.

```swift
@Environment(\.toolbarVerticalEdge) var edge     // SwiftUI
switch traitCollection.verticalBarEdge { ... }     // UIKit
```

Extend hero or background images under a vertical bar with `backgroundExtensionEffect()` (SwiftUI) or `UIBackgroundExtensionView` (UIKit).

**Opt out** for single-page bottom-heavy layouts (Calculator) and sheets with one control.

```swift
NavigationStack { ContentView() }.toolbarVerticalBehavior(.disabled)   // SwiftUI
override var preferredVerticalBarBehavior: UIVerticalBarBehavior { .disabled }  // UIKit
```

**Sheets, inspectors, split views.** Outer display: sheet bars are vertical by default; a text-only Done keeps the rail reserved but empty, so add a symbol or disable the vertical bar. Inner display: sheet bars are horizontal for centered or leading placement and vertical for trailing; set `presentationPlacement(_:)` (SwiftUI) or `preferredPlacement` (UIKit). Partially folded, sheets slide off the fold. Inspectors keep horizontal bars. In split views only the detail column participates in the vertical bar.

Locate controls near the content they affect: list controls stay above the list column rather than moving to the side. Do not override default bar placement without a reason.

## 7. Reserved regions

Regions of the display that content avoids or components adapt to, like window controls on iPad.

| Region | Kind | Present |
|---|---|---|
| Outer front camera | occlusion | always; expands into the Dynamic Island for Live Activities |
| Inner front camera | occlusion | only while the camera is active; UI moves aside |
| Fold | division | active when partially folded, inactive when flat; zero width when flat |

System components (alerts, context menus, sheets, popovers, split views) move or rebalance automatically. Custom views query regions and read each `frame`:

```swift
// SwiftUI
GeometryReader { proxy in
    let regions = proxy.reservedRegions(kind: .division)              // active only
    let all = proxy.reservedRegions(kind: .division, options: .includeInactive)
    let frames = regions.map(\.frame)
}
// UIKit
let regions = view.reservedRegions(kind: .division)
```

Types: `ReservedRegion` (SwiftUI, full signature `reservedRegions(kind:options:layoutDirectionBehavior:)` on `GeometryProxy`) and `UIView.ReservedRegion` (UIKit, `reservedRegions(kind:options:)`). Kinds `.division` and `.occlusion`.

Guidance: prefer containers that adapt (Notes' split view); in grids prefer an even number of columns and center on the division frame, not the content area; move only what is needed when folding, avoid rearranging; keep interactive elements out of the hinge, scrollable content may cross it. Regions are empty for the first few layout passes: read them in every layout pass, never cache.

Displacement patterns from the talk: move related elements together; alerts go to the trailing side when folded like a book; in tabletop, the top region suits distant viewing and the bottom suits touch controls; search follows the view it searches.

## 8. Arrangement views

A layout container for a primary and a secondary view that reacts to size classes, aspect ratio and active division regions. iOS 27.1.

| | SwiftUI | UIKit |
|---|---|---|
| Container | `ArrangementView { primary } secondary: { secondary }` | `UIArrangementViewController`, `setViewController(_:for: .primary/.secondary)` |
| Split style | `.arrangementViewStyle(.split)`, `.split.axes(.horizontal)` | `updateArrangement(.split.axes(.horizontal))` (`UISplitArrangement`) |
| Overlay style | `.arrangementViewStyle(.overlay)` | overlay arrangement |
| Overlay state | `@Environment(\.overlayArrangementZIndex)` | `state(for: .primary)?.zIndex` |

Split: side by side when wider than tall, stacked when taller; both views visible; limiting axes shows only the primary view when the axis cannot split. Overlay: primary on top of secondary when no division is active; when partially folded the primary moves to the trailing or bottom region and the secondary to the leading or top region.

```swift
NavigationStack {
    ArrangementView { PlayerView() } secondary: { UpNextView() }
        .arrangementViewStyle(.split.axes(.horizontal))
}
```

Choose split for an `HStack`/`VStack` relationship, overlay for a `ZStack` one. Keep navigation containers around, not inside, an arrangement view. Do not place an arrangement view inside a `NavigationSplitView`, `List` or `ScrollView`.

## 9. Hinge, Split View, scenes, accessories

Hinge data is for interactions and effects, not layout. Layout uses size classes, reserved regions and arrangements.

| | SwiftUI | UIKit |
|---|---|---|
| Hinge updates | `.onHingeChange { previous, context in ... }`; `context.hinge?.status` (`.closed`, `.partiallyOpen`, `.fullyOpen`), `.angle` | `UIHingeInteraction` |
| Scene accessory | `.sceneAccessory { CameraCaptureAccessory(isEnabled:) { ... }.onAvailabilityChange { } }` | `CameraCaptureAccessory` |
| New scene | `UIWindowSceneActivationAction` (hides when new windows are unavailable) | same |

```swift
.onHingeChange { _, context in
    if let hinge = context.hinge, hinge.status == .partiallyOpen {
        pitchBend = calculatePitchBend(angle: hinge.angle)
    } else { pitchBend = 0 }
}
```

Split View: every app participates. Two apps share the inner display 50/50, or a pinned video sits above an app. Handle both through size classes and scene geometry; the app can be visible yet inactive, so pause on background, not on inactive. Multiple scenes: iPhone Duo is the first iPhone with multiple instances of an app's UI; new windows open only on the inner display. Scene accessories show content on the other display while the main UI stays put; `CameraCaptureAccessory` needs the app full screen on the inner display with an active capture session (teleprompter example).

## 10. Camera direction

Each display has a front camera, so opening, closing or rotating can flip which way the camera in use points. Use the direction-based selection guide ("Choosing a camera by the direction it faces", AVFoundation) and register a capture accessory to show capture UI on the outer display while the rear camera is active ("Registering a camera capture accessory on iPhone Duo"). Tech Talk 111465 covers the full camera experience.

## 11. Games

Playable in every pose. Lock to portrait or landscape if needed but fill the screen as the pose changes. Keep text and control sizes consistent while resizing. Prefer changing the aspect ratio over letterboxing; if boxing is unavoidable, fill the padding with artwork.

## 12. UIScene lifecycle

The UIKit scene-based lifecycle becomes mandatory with the SDK after iOS 26 (TN3187). Apps without `UIApplicationSceneManifest` and a scene delegate must migrate before building with the 27.1 SDK. Window creation must use `UIWindow(windowScene:)`.

## 13. Design patterns for the inner display

- Split views: expand on the inner display, collapse to one pane on the outer, exactly like regular vs compact on other iPhones.
- Reflow: a vertically stacked layout becomes two columns when width allows (Music).
- Sidebar: present the tab bar as a sidebar on the inner display for information-dense apps (Health): `.defaultTabBarPlacement(.sidebar)` (SwiftUI), `tabBarController.sidebar.preferredPlacement = .sidebar` (UIKit).
- Keep controls' relative positions similar across poses so people do not relearn the app.

## 14. Apple's own checklist

Walk every view, sheet and popover in each pose and rotation; drag the app to both sides in Split View. Look for: views that do not resize; bars not presented vertically; sheets or popovers positioned awkwardly after folding; elements sitting in the fold; content under the outer camera; keyboard hiding the rail. Common issues named by Apple: `UIScreen.main` use; size read once; orientation-based layout; idiom checks; regular width assumed to be iPad; hardcoded dimensions; fill-mode media cropping; bars not adapted to vertical placement.

## 15. App Resizability skill

In Xcode 27.1 ask the coding assistant "get my app ready for iPhone Duo". The App Resizability skill (formerly Modernize Your UIKit App) scans for the patterns above; Apple says it finds most issues, not all. Export it for other agents with `xcrun agent skills export [--output-dir DIR] [--replace-existing]`; if the command is missing, point `xcode-select` or `DEVELOPER_DIR` at Xcode 27. Treat its output as the baseline this skill must exceed.

## 16. Sources

Verified 27 Oct 2026.

- HIG, Designing for iPhone Duo: https://developer.apple.com/design/human-interface-guidelines/designing-for-iphone-duo
- Technology overview, Preparing your app for iPhone Duo: https://developer.apple.com/documentation/technologyoverviews/preparing-your-app-for-iphone-duo
- Prepare page: https://developer.apple.com/iphone-duo/prepare/
- Developer news, 5 Oct 2026: https://developer.apple.com/news/?id=kkphp5qo
- Tech Talk 111461, Prepare your app for iPhone Duo: https://developer.apple.com/videos/play/tech-talks/111461/
- Tech Talk 111462, Raise the bar with iPhone Duo: https://developer.apple.com/videos/play/tech-talks/111462/
- Tech Talk 111463, Strike a pose with adaptive layouts: https://developer.apple.com/videos/play/tech-talks/111463/
- Tech Talk 111464, Leverage multiple displays and scenes: https://developer.apple.com/videos/play/tech-talks/111464/
- Tech Talk 111466, Design for iPhone Duo: https://developer.apple.com/videos/play/tech-talks/111466/
- Design resources (bezel): https://developer.apple.com/design/resources/
- Agent skills export (community write-up): https://sarunw.com/posts/export-xcode-agent-skills/
