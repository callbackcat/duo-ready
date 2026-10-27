# Native scan rules (Swift / Objective-C / Info.plist)

Source of truth: `scripts/rules/native.yaml`. Each section's anchor is the rule id, which `scan.json` findings carry in `doc`. Severity: **error** breaks layout on iPhone Duo; **warn** degrades it; **info** is worth a look. Verified against Apple guidance 27 Oct 2026 (see `references/device-facts.md` for the numbers quoted here).

Contents: [screen-main-bounds](#screen-main-bounds) · [screen-main-scale](#screen-main-scale) · [window-frame-init](#window-frame-init) · [stored-uiscreen](#stored-uiscreen) · [orientation-layout](#orientation-layout) · [idiom-check](#idiom-check) · [regular-means-ipad](#regular-means-ipad) · [regular-width-assumes-regular-height](#regular-width-assumes-regular-height) · [hardcoded-size](#hardcoded-size) · [fill-media](#fill-media) · [layout-once](#layout-once) · [fixed-orientation-plist](#fixed-orientation-plist) · [custom-bar-class](#custom-bar-class) · [toolbar-item-no-symbol](#toolbar-item-no-symbol) · [custom-overflow-menu](#custom-overflow-menu) · [no-scene-delegate](#no-scene-delegate) · [symmetric-safe-area](#symmetric-safe-area) · [centered-grid-odd-columns](#centered-grid-odd-columns) · [cached-reserved-regions](#cached-reserved-regions)

---

## screen-main-bounds
**error · autofix** (`UIScreen.main.bounds` → `view.bounds`; review each site)

iPhone Duo has two screens. `UIScreen.main` is ambiguous, is being deprecated, and never reflects the window the app is actually in: the closed pose gives a 466×678 pt window on the outer display, the open pose 951×669 on the inner one, and Split View narrows it further.

```swift
// before
let width = UIScreen.main.bounds.width
// after (UIKit)
let width = view.bounds.width            // or window.bounds, or the scene's coordinate space
// after (SwiftUI)
GeometryReader { proxy in … proxy.size.width … }   // or .onGeometryChange(for:of:action:)
```
The autofix assumes the call site lives in a view or view controller. In an app delegate or a model object, size from the scene instead. Ref: https://developer.apple.com/iphone-duo/prepare/

Autofix note: `--fix` rewrites `UIScreen.main.bounds` to `view.bounds` only where a view is plausibly in scope. It never touches `UIWindow(frame: UIScreen.main.bounds)`; that site belongs to `window-frame-init` and needs `UIWindow(windowScene:)`, which is a manual change.

## screen-main-scale
**error · autofix** (`UIScreen.main.scale` → `traitCollection.displayScale`)

Both Duo displays are 3×, but the scale must come from the display the view is on, not from a global.

```swift
// before
let px = points * UIScreen.main.scale
// after
let px = points * traitCollection.displayScale       // SwiftUI: @Environment(\.displayScale)
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## window-frame-init
**error · manual**

A window created from a frame is not attached to a scene, so it cannot follow the app between displays or resize on fold. Create it from the window scene in the scene delegate (see also [no-scene-delegate](#no-scene-delegate)).

```swift
// before
let window = UIWindow(frame: UIScreen.main.bounds)
// after
func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
    guard let windowScene = scene as? UIWindowScene else { return }
    let window = UIWindow(windowScene: windowScene)
    …
}
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## stored-uiscreen
**warn · manual**

A stored `UIScreen` keeps pointing at whichever display the app launched on. Resolve it when you need it.

```swift
// before
var screen: UIScreen = UIScreen.main
// after
var screen: UIScreen? { view.window?.windowScene?.screen }
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## orientation-layout
**error · manual**

Orientation no longer predicts shape: the closed pose is wider-than-tall in "portrait" terms on a 5.4-inch outer display, the inner display ignores supported orientations, and Split View changes width without any rotation. Apple's list of offenders is `UIDevice.current.orientation`, `statusBarOrientation` and `interfaceOrientation` (including `windowScene.effectiveGeometry.interfaceOrientation`).

```swift
// before
if UIDevice.current.orientation.isLandscape { useTwoColumns() }
// after
if view.bounds.width > view.bounds.height { useTwoColumns() }     // or size classes
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## idiom-check
**error · manual**

`userInterfaceIdiom` is `.phone` on iPhone Duo even though the inner display is regular in both dimensions, so an idiom check sends Duo down the cramped phone path.

```swift
// before
let columns = UIDevice.current.userInterfaceIdiom == .pad ? 3 : 1
// after
let columns = traitCollection.horizontalSizeClass == .regular ? 2 : 1
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## regular-means-ipad
**error · manual**

Code that derives an `isPad` flag from `horizontalSizeClass == .regular` now classifies iPhone Duo's inner display as an iPad and may enable iPad-only chrome, pointer assumptions or navigation. Branch on the size class itself and keep the decision local.

```swift
// before
let isPad = horizontalSizeClass == .regular
if isPad { showSidebar() }
// after
if horizontalSizeClass == .regular { showSidebar() }   // true on iPad and on the Duo inner display; that is the point
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## regular-width-assumes-regular-height
**info · manual**

A 6.9-inch iPhone in landscape is regular width with **compact** height. A two-pane layout that keys on width alone therefore also fires there, where vertical room is 400 pt. Check the vertical class (or the height) when the layout needs both.

```swift
// before
if horizontalSizeClass == .regular { twoPane() }
// after
if horizontalSizeClass == .regular && verticalSizeClass == .regular { twoPane() }
```
Ref: https://developer.apple.com/videos/play/tech-talks/111461/

## hardcoded-size
**error · manual**

Comparisons against known iPhone dimensions (`height == 844`, lists like `[320, 375, 414]`) do not contain 466×678 or 951×669 and never will contain the next device. Remove them and size relative to the container.

```swift
// before
if view.bounds.height == 844 { compact = true }
// after
compact = view.bounds.height < 700
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## fill-media
**warn · manual**

`.scaleAspectFill` / `.aspectRatio(contentMode: .fill)` crops full-bleed media. Going from the closed to the open pose roughly doubles the width and changes the aspect ratio from 0.69 to 1.42, so the subject is cut off. Choose fill or fit from the size class or aspect ratio, or set a focal point.

```swift
// before
imageView.contentMode = .scaleAspectFill
// after
imageView.contentMode = traitCollection.horizontalSizeClass == .regular ? .scaleAspectFit : .scaleAspectFill
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## layout-once
**warn · manual** (file-level: geometry read in `viewDidLoad` / `viewIsAppearing` / `init` with no layout hook in the file)

Geometry captured at load time is wrong after the first fold. Compute size-dependent layout in `viewDidLayoutSubviews()` / `layoutSubviews()` and use `viewWillTransition(to:with:)` for work that must run on size changes.

```swift
// before
override func viewDidLoad() { super.viewDidLoad(); cardWidth = view.bounds.width / 2 }
// after
override func viewDidLayoutSubviews() { super.viewDidLayoutSubviews(); cardWidth = view.bounds.inset(by: view.safeAreaInsets).width / 2 }
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## fixed-orientation-plist
**warn · manual** (file-level: `UISupportedInterfaceOrientations` without a landscape value)

The inner display does not honor supported interface orientations: a portrait-only app still receives a 951×669 landscape window when the device opens. The lock does not protect the layout; a resizable layout does. Add landscape (games may keep a lock but must fill the screen in every pose).

```xml
<key>UISupportedInterfaceOrientations</key>
<array>
    <string>UIInterfaceOrientationPortrait</string>
    <string>UIInterfaceOrientationLandscapeLeft</string>
    <string>UIInterfaceOrientationLandscapeRight</string>
</array>
```
Ref: https://developer.apple.com/videos/play/tech-talks/111461/

## custom-bar-class
**error · manual**

Only bars owned by `UINavigationController` and `UITabBarController` (and SwiftUI `.toolbar` inside `NavigationStack` / `NavigationSplitView` / `TabView`) move to the vertical trailing edge on iPhone Duo. Items in a hand-built `UIToolbar`, `UINavigationBar` or `UITabBar` are ignored and stay horizontal, eating vertical space on the 678 pt-tall outer display.

```swift
// before
let toolbar = UIToolbar(); toolbar.items = [share, more]; view.addSubview(toolbar)
// after
toolbarItems = [share, more]; navigationController?.setToolbarHidden(false, animated: false)
```
Ref: https://developer.apple.com/documentation/technologyoverviews/preparing-your-app-for-iphone-duo

## toolbar-item-no-symbol
**warn · manual**

An item with a title and no symbol is never shown vertically; the system keeps a horizontal rail for it (and a sheet with a single "Done" ends up with an empty vertical rail). Give every item both a symbol and a title so the system can pick icon-only (vertical), icon or title (horizontal) or both (overflow menu).

```swift
// before
ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
navigationItem.rightBarButtonItem = UIBarButtonItem(title: "Done", style: .done, target: self, action: #selector(done))
// after
ToolbarItem(placement: .confirmationAction) { Button("Done", systemImage: "checkmark") { dismiss() } }
navigationItem.rightBarButtonItem = UIBarButtonItem(title: "Done", image: UIImage(systemName: "checkmark"), target: self, action: #selector(done))
```
Text that carries information (a cart total) may stay horizontal on purpose: mark it `.axisBehavior(.horizontalOnly)`. Ref: https://developer.apple.com/videos/play/tech-talks/111462/

## custom-overflow-menu
**warn · manual**

iPhone Duo compresses bar items into a system overflow menu that uses the ellipsis. A second, app-owned ellipsis menu confuses people and may itself be compressed. Move those actions into the system menu and reserve the ellipsis for it.

```swift
// before
Menu { Button("Share") {} } label: { Image(systemName: "ellipsis.circle") }
// after
.toolbar { ToolbarOverflowMenu { Button("Share", systemImage: "square.and.arrow.up") {} } }
// UIKit
navigationItem.additionalOverflowItems = UIDeferredMenuElement { provider in provider(self.overflowItems) }
```
Set `visibilityPriority` on the items that must stay visible longest. Ref: https://developer.apple.com/design/human-interface-guidelines/designing-for-iphone-duo

## no-scene-delegate
**error · manual** (project-level: an `Info.plist` without `UIApplicationSceneManifest` and no `UIWindowSceneDelegate` in its sources)

Apps built with the iOS 27 SDK or later must use the UIScene life cycle (TN3187). Without scenes the window is not attached to a display and cannot move between the outer and inner display or participate in Split View and multiple windows. SwiftUI `App` lifecycle already satisfies this.

Steps: add `UIApplicationSceneManifest` to Info.plist with a `UIWindowSceneSessionRoleApplication` configuration naming your `SceneDelegate`; move window creation into `scene(_:willConnectTo:options:)`; implement `application(_:configurationForConnecting:options:)`. Ref: https://developer.apple.com/documentation/technotes/tn3187-migrating-to-the-uikit-scene-based-life-cycle

## symmetric-safe-area
**error · manual**

The Duo safe area is asymmetric: in the closed pose an 84 pt status column and the vertical bar sit on the trailing edge only, and in Split View the bar sits on the app's outer edge. Taking the larger inset for both sides wastes 84 pt on the wrong edge.

```swift
// before
let side = max(view.safeAreaInsets.left, view.safeAreaInsets.right)
content.frame = view.bounds.insetBy(dx: side, dy: 0)
// after
content.frame = view.bounds.inset(by: view.safeAreaInsets)
```
Ref: https://developer.apple.com/videos/play/tech-talks/111461/

## centered-grid-odd-columns
**info · manual**

When the device is partially folded the fold is a 40 pt division at x 455–495 of the 951 pt window. A grid with an odd column count centered on the content area puts its middle column across the fold. Prefer an even count, or center on the division frame from `reservedRegions(kind: .division)`.

```swift
// before
let columns = Array(repeating: GridItem(.flexible()), count: 3)
// after
let columns = Array(repeating: GridItem(.flexible()), count: horizontalSizeClass == .regular ? 4 : 2)
```
Ref: https://developer.apple.com/design/human-interface-guidelines/designing-for-iphone-duo

## cached-reserved-regions
**info · manual**

Reserved regions are empty for the first few layout passes and change as the device folds (the fold is inactive at 180° and active when partially open). A cached array is stale almost immediately; read regions inside the layout pass.

```swift
// before
.onAppear { self.regions = proxy.reservedRegions(kind: .division) }
// after
GeometryReader { proxy in
    let regions = proxy.reservedRegions(kind: .division)   // re-evaluated on every layout
    …
}
```
Ref: https://developer.apple.com/videos/play/tech-talks/111463/
