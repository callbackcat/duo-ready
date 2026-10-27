# Layout assertions

Specification for `scripts/assert.py`. Inputs per cell: the element tree `<flow>-<cell>.tree.json`, the screenshot `<flow>-<cell>.png`, the cell name, the SDK stamp from `build.json`, and thresholds from `duo.yaml` (`assert:` block). Output: the `results` array in `ui.json` (formats in `pipeline-contracts.md`). Geometry constants come from `device-facts.md` and are repeated here so the code and the doc cannot drift silently.

## Tree fields used

`id`, `type`, `label`, `frame` `[x, y, w, h]` in points with origin at the app window's top-left, `interactive` (bool), `text`, `truncated` (bool), optional `parent` (id) and `scrollable` (bool). Elements with `type` in `window`, `other` with no label and no children are treated as containers.

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
Any element whose frame is not fully inside the window rectangle, after clamping tiny overshoots (≤ 1 pt). Containers and scrollable content children with `scrollable` ancestors are exempt (scrolled-off rows are normal). Report the offending `id`s and frames. False positives: lazily sized collection cells during animation; capture only after the wait-for-posture rule and a 500 ms settle. Typical cause: hardcoded widths from `UIScreen.main.bounds` or `Dimensions.get` captured at launch.

### clipped_text
An element with `text` is clipped when `truncated` is true, or its `text` ends with an ellipsis character, while its width is smaller than the parent's available width minus 16 pt. Multi-line labels with `numberOfLines` set are not visible in the tree, so warn, never fail, unless `duo.yaml` says fail. Typical cause: fixed widths or a layout computed for 375 pt.

### tap_target_min
Interactive elements (buttons, links, toggles, cells with actions) with width or height below `tap_target_min` (default 44 pt). Exempt system bar items and elements inside the trailing vertical bar column. Report the element and the measured size.

### bars_vertical_expected
Applies only with a 27.1 or later stamp and only in cells that expect vertical bars: `closed-portrait`, `closed-landscape`, `open-landscape`, `book-landscape`, `split-view-*`. Detection: a group of two or more bar-type elements (`button`, `tab`) whose frames sit inside the trailing 84 pt column and are stacked vertically, or any element with `type` in `tabBar`, `toolbar`, `navigationBar` whose width is about 84 pt and height exceeds its width. Pass when found. Fail when the tree contains bar-type elements laid out horizontally at the top or bottom edge instead (custom `UIToolbar`/`UITabBar`/JS tab bar), warn when no bars are found at all (the screen may legitimately have none). `open-portrait` and `book-portrait` expect horizontal bars and are skipped.

### content_under_outer_camera
Closed cells only. Fail when any non-background, non-container element intersects the 37 × 37 pt occlusion in the top-trailing corner (inside the 84 pt status column). Background images that ignore the safe area are allowed to pass under it, so exempt elements with `type` `image` that span the full window width. Typical cause: `ignoresSafeArea()` on a card stage or a hero view that also holds controls.

### interactive_in_fold
Book cells only. Fail when an interactive element's frame intersects the fold band: x 455..495 in `book-landscape`, y 455..495 in `book-portrait`. Elements with a `scrollable` ancestor are exempt, since scrolling content may cross the fold. Report the ids. Typical cause: a grid centered on the content area (the two sides of the fold are 455 pt and 372 pt, so centering lands a column on the hinge) or a fixed-position control at the window center. Suggested fix: `ReservedRegion` query, `ArrangementView`, or an even column count centered on the division frame.

### visual_diff
Compares the capture with `.duo/baselines/<flow>-<cell>.png` using `scripts/diff.py`: fraction of pixels whose max channel delta exceeds 32, after excluding the status column (84 pt × 3 px on the trailing edge in vertical-bar cells, the top 82 pt in `open-portrait`/`book-portrait`) so the clock and signal glyphs do not count. Status: pass below `visual_diff_threshold` (default 0.02), warn up to 3× the threshold, fail above. Skipped when no baseline exists; the first green run writes baselines. Size mismatch between capture and baseline is a fail with a clear message (usually a stamp or pose mismatch).

### transition_stable
For each transition in `duo.yaml` (`closed>open`, `open>book`, `open>closed`) the runner captures before and after the mid-flow pose change. Fail when an element id that was interactive before the change is missing after it (excluding ids inside bars, which legitimately move to overflow), or when the after-cell has any assertion failure the before-cell did not have. Warn when more than 30% of ids changed, which usually means a full re-navigation rather than a re-layout. Typical cause: a pushed compact screen kept after unfolding, or state reset on size change.

## matched_rule and source_hint

For every failure, look up `.duo/scan.json`. If a finding's file stem (`PlayerView` from `Sources/PlayerView.swift`) is a case-insensitive substring of the failing element's `id`, `label`, or the flow's screen name, set `matched_rule` to that finding's rule and `source_hint` to `file:line`. If several match, prefer rules associated with the assertion:

| Assertion | Preferred rules |
|---|---|
| offscreen_elements, clipped_text | screen-main-bounds, hardcoded-size, layout-once, rn-dimensions-module-scope, rn-stylesheet-fixed-width |
| bars_vertical_expected | custom-bar-class, rn-js-tab-bar, toolbar-item-no-symbol |
| content_under_outer_camera | symmetric-safe-area, rn-safe-area-missing, fill-media |
| interactive_in_fold | centered-grid-odd-columns, cached-reserved-regions |
| transition_stable | layout-once, orientation-layout, rn-orientation-lock |

Otherwise both fields are null; the payload still carries the assertion's generic `fix_hint`.

## Known gaps

- Split View cells depend on scripting Split View in the simulator, which is unverified; `assert.py` must accept their geometry but the runner may skip them.
- Trees from AXe list only labelled elements, so `offscreen_elements` is weaker for React Native screens without `accessibilityLabel`/`testID`. Say so in the report when the tree source is AXe.
- The clock region exclusion in `visual_diff` is a fixed rectangle; apps that draw their own status area will see small diffs.
