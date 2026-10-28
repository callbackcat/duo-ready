# Layout assertions

Specification for `scripts/assert.py`. Inputs per cell: the element tree `<flow>-<cell>.tree.json`, the screenshot `<flow>-<cell>.png`, the cell name, the SDK stamp from `build.json`, and thresholds from `duo.yaml` (`assert:` block). Output: the `results` array in `ui.json` (formats in `pipeline-contracts.md`). Geometry constants come from `device-facts.md` and are repeated here so the code and the doc cannot drift silently.

## Tree fields used

`id`, `type`, `label`, `frame` `[x, y, w, h]` in points with origin at the app window's top-left, `interactive` (bool), `text`, `truncated` (bool), optional `parent` (id) and `scrollable` (bool). The tree's `source` and `ancestry` fields say where it came from and whether parents are known.

An element is interactive when the flag says so or its type is one of `Button`, `TextField`, `SecureTextField`, `Switch`, `Slider`, `Link`, `Tab`, `Cell`, `SegmentedControl`, `Stepper`, `PageIndicator`, `SearchField`, `TabBar` items (case-insensitive; AXe capitalises, XCUITest does not). Containers are dropped before any assertion: the `Application` root, and `Group`, `Other`, `Window`, `ScrollView`, `Table`, `CollectionView`, `NavigationBar` and similar whose frame covers 90% or more of the window or of the window rotated (AXe reports the root unrotated in landscape, so a 669 x 951 frame in a 951 x 669 cell is the root, not an overflow). A `Slider` that is 32 pt or thinner and spans 40% or more of the window along its axis is a `UIScrollView` indicator (AXe reports it as adjustable, with a localised label); it is not a tap target and not a control on the fold.

The window size comes from the geometry table below, except when the capture's pixel size says the display came up in the other orientation (2007 x 2853 after an unfold); then the window is taken from the capture and the cell carries `window_source: screenshot`.

## Cell geometry (iOS 27.1 SDK, points)

| Cell | Window | Safe content area | Vertical bar | Fold (division) | Outer camera |
|---|---|---|---|---|---|
| closed-portrait | 466 × 678 | x 0..382 | trailing column, 84 wide | none | 37 × 37 at the top-trailing corner of the status column |
| closed-landscape | 678 × 466 | x 0..594 | trailing column, 84 wide | none | 37 × 37 top-trailing |
| open-landscape | 951 × 669 | x 0..867 | trailing column, 84 wide | x 455..495 (inactive) | none |
| open-portrait | 669 × 951 | y 82..951 | none (horizontal bars; status area 134 × 82 at the top) | y 455..495 (inactive) | none |
| book-landscape | 951 × 669 | x 0..867 | trailing column, 84 wide | x 455..495 **active** | none |
| book-portrait | 669 × 951 | y 82..951 | none | y 455..495 **active** | none |
| split-view-left/right | about 475 × 669 | depends | on the app's outer edge | none | none |

With a 27.0 stamp the windows are 386 × 678 and 871 × 669, there are no vertical bars and no reserved regions; `assert.py` must switch tables on the stamp and mark `bars_vertical_expected` as `skipped` for anything below 27.1.

## Statuses

`pass`, `warn`, `fail`, `skipped`. `duo.yaml` maps each assertion to `fail`, `warn` or `off`; `off` yields `skipped`. A cell fails when any assertion is `fail`; the run exits 1.

## Assertions

### offscreen_elements
Any element whose frame is not fully inside the window rectangle, after clamping tiny overshoots (≤ 1 pt). Containers and scrollable content children with `scrollable` ancestors are exempt (scrolled-off rows are normal). Report the offending `id`s and frames. Horizontal overflow is a `fail`. Vertical-only overflow is a `fail` with an XCUITest tree (ancestry known) and a `warn` with an AXe tree, because a flat tree cannot tell a row scrolled below the fold of a list from a clipped one; the `reason` says so and the capture decides. False positives: lazily sized collection cells during animation; capture only after the wait-for-posture rule and a 500 ms settle. Typical cause: hardcoded widths from `UIScreen.main.bounds` or `Dimensions.get` captured at launch.

### clipped_text
An element with `text` is clipped when `truncated` is true, or its `text` ends with an ellipsis character, while its width is smaller than the parent's available width minus 16 pt. Multi-line labels with `numberOfLines` set are not visible in the tree, so warn, never fail, unless `duo.yaml` says fail. Typical cause: fixed widths or a layout computed for 375 pt.

### tap_target_min
Interactive elements (buttons, links, toggles, cells with actions) with width or height below `tap_target_min` (default 44 pt). Exempt system bar items and elements inside the trailing vertical bar column. Report the element and the measured size. 42 x 42 pt icon buttons are the common real finding (second field test); they are 2 pt short and the fix is padding, not a threshold change. The system scroll indicator is exempt (above). React Native `hitSlop` is invisible to the tree, so a 40 pt button with `hitSlop={8}` is reported although it is 56 pt to the touch; say so when it comes up rather than silently accepting it.

### bars_vertical_expected
Applies only with a 27.1 or later stamp and only in cells that expect vertical bars: `closed-portrait`, `closed-landscape`, `open-landscape`, `book-landscape`, `split-view-*`. Detection: a group of two or more bar-type elements (`button`, `tab`) whose frames sit inside the trailing 84 pt column and are stacked vertically, or any element with `type` in `tabBar`, `toolbar`, `navigationBar` whose width is about 84 pt and height exceeds its width. Pass when found. Fail when the tree contains bar-type elements laid out horizontally at the top or bottom edge instead (custom `UIToolbar`/`UITabBar`/JS tab bar), warn when no bars are found at all (the screen may legitimately have none). `open-portrait` and `book-portrait` expect horizontal bars and are skipped. The assertion is also skipped, not warned, when the tree has no bar-typed element and no bar-shaped group: two or more interactive elements inside the window along the bottom band, spread over at least half of its width, or two or more inside the window in the trailing column. Controls below the window bottom of a scrolled screen are content, not a bar (third field test: a task field, two 42 pt buttons and a scroll indicator). A screen without bars (an onboarding page, a full-screen hero) is not a finding.

### content_under_outer_camera
Closed cells only. Fail when any non-background, non-container element intersects the 37 × 37 pt occlusion in the top-trailing corner (inside the 84 pt status column). Background images that ignore the safe area are allowed to pass under it, so exempt elements with `type` `image` that span the full window width. Typical cause: `ignoresSafeArea()` on a card stage or a hero view that also holds controls.

### interactive_in_fold
Book cells only. Fail when an interactive element's frame intersects the fold band: x 455..495 in `book-landscape`, y 455..495 in `book-portrait`. Elements with a `scrollable` ancestor are exempt, since scrolling content may cross the fold. Report the ids. Typical cause: a grid centered on the content area (the two sides of the fold are 455 pt and 372 pt, so centering lands a column on the hinge) or a fixed-position control at the window center. Suggested fix: `ReservedRegion` query, `ArrangementView`, or an even column count centered on the division frame.

### visual_diff
Compares the capture with `.duo/baselines/<flow>-<cell>.png` using `scripts/diff.py`: fraction of pixels whose max channel delta exceeds 32, after excluding the status column (84 pt × 3 px on the trailing edge in vertical-bar cells, the top 82 pt in `open-portrait`/`book-portrait`) so the clock and signal glyphs do not count. Status: pass below `visual_diff_threshold` (default 0.02), warn up to 3× the threshold, fail above. Skipped when no baseline exists; the first green run writes baselines. Size mismatch between capture and baseline is a fail with a clear message (usually a stamp or pose mismatch).

### transition_stable
For each transition in `duo.yaml` (`closed>open`, `open>book`, `open>closed`) the runner captures before and after the mid-flow pose change. Fail when an element id that was interactive before the change is missing after it (excluding ids inside bars, which legitimately move to overflow), or when the after-cell has any assertion failure the before-cell did not have. Warn when more than 30% of ids changed, which usually means a full re-navigation rather than a re-layout. Typical cause: a pushed compact screen kept after unfolding, or state reset on size change. Transition cells also run `offscreen_elements`, and `interactive_in_fold` when the pose after the change is book, so a grid on the hinge is caught right after `open>book` as well as in the `book-landscape` cell.

## matched_rule and source_hint

For every failure, look up `.duo/scan.json`, restricted to the rules that can cause that assertion:

| Assertion | Rules considered |
|---|---|
| offscreen_elements | screen-main-bounds, hardcoded-size, layout-once, rn-dimensions-module-scope, rn-stylesheet-fixed-width, rn-fixed-height, rn-window-height-fraction, window-frame-init, stored-uiscreen |
| clipped_text | hardcoded-size, rn-stylesheet-fixed-width, rn-adjusts-font-fixed-lineheight, rn-hardcoded-breakpoint, layout-once |
| tap_target_min | hardcoded-size, rn-fixed-height |
| bars_vertical_expected | custom-bar-class, rn-js-tab-bar, toolbar-item-no-symbol, custom-overflow-menu |
| content_under_outer_camera | symmetric-safe-area, rn-safe-area-missing, fill-media, rn-symmetric-insets, rn-image-cover |
| interactive_in_fold | centered-grid-odd-columns, cached-reserved-regions, rn-expo-hinge-for-layout |
| transition_stable | layout-once, orientation-layout, rn-orientation-lock, rn-dimensions-no-listener, fixed-orientation-plist |
| visual_diff, flow | none |

Among those, a finding whose file stem (`PlayerView` from `Sources/PlayerView.swift`) is a case-insensitive substring of the failing element's `id` or `label` wins with `source_confidence: file`; otherwise `matched_rule` names the most severe considered rule with `source_confidence: rule` and `source_hint` stays null (a rule-level match is a lead, not a file to open; the third field test saw an onboarding video blamed for den buttons). With no considered rule at all both fields are null; the payload still carries the assertion's generic `fix_hint`. The second field test showed why the restriction matters: the root element's id was the app name, which is a substring of every file named after the app, so one unrelated provider file was blamed for all 19 failures.

## Known gaps

- Split View cells depend on scripting Split View in the simulator, which is unverified; `assert.py` must accept their geometry but the runner may skip them.
- Trees from AXe list only labelled elements, so `offscreen_elements` is weaker for React Native screens without `accessibilityLabel`/`testID`; they also carry no ancestry, so vertical overflow is a warn. The report says so when any cell's tree came from AXe.
- The assertions see geometry, not design: centred controls and odd-column grids that straddle the fold in `book-landscape` only fail when an interactive element intersects the 40 pt band; a layout that merely looks wrong around the hinge needs a human look at the capture.
- The clock region exclusion in `visual_diff` is a fixed rectangle; apps that draw their own status area will see small diffs.
- `hitSlop` and other touch-area extensions are invisible to the tree; `tap_target_min` measures the drawn frame.
- `window_source: screenshot` means the capture's size disagreed with the cell's nominal size. With the orientation readback of 0.3.1 it should appear only on transition cells; on a static cell it means the rotation did not happen and the cell's name is wrong.
