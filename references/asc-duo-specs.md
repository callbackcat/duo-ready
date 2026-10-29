# App Store Connect specs for iPhone Duo

Facts for `scripts/assets.sh` and the submission step. Verified 27 Oct 2026 against the App Store Connect help pages, the asset best practices page and the developer news post. Apple can change these pages; the sources list at the end is what to re-check.

## 1. The requirement, exactly

- Today: iPhone Duo screenshots are optional.
- From **April 2027**: required for every app and game submission **for apps built with the iOS 27.1 SDK or later** (screenshot specifications page). The news post states the rule without the SDK qualifier; the spec page carries it. Quote the spec page.
- Submitting Duo screenshots now shows a badge on the product page indicating the app is optimized for iPhone Duo.
- Apple has not said apps will be removed, and has not said how App Review treats submissions without them. Do not claim otherwise.

## 2. Screenshot sizes

Pixels, no scaling needed; the simulator captures at exactly these sizes.

| Display | Portrait | Landscape |
|---|---|---|
| iPhone Duo, outer (closed) | 1398 × 2034 | 2034 × 1398 |
| iPhone Duo, inner (open) | 2007 × 2853 | 2853 × 2007 |

Both are near 2:3; a 6.9" iPhone shot (1320 × 2868, about 1:2.2) cannot be cropped into them. Rows have no fallback: Duo sizes are never scaled from another device.

Other required rows, for completeness:

| Row | Portrait | Required |
|---|---|---|
| Dynamic Island (medium), e.g. iPhone 17/16/15 | 1179 × 2556 (also 1206 × 2622) | yes, for every iPhone app |
| Face ID (large) | 1284 × 2778 (also 1242 × 2688) | only if no Dynamic Island (large) set |
| Dynamic Island (large), e.g. 16 Pro Max | 1320 × 2868 (also 1290 × 2796, 1260 × 2736) | optional |
| iPad 13" | 2064 × 2752 (also 2048 × 2732) | yes, if the app runs on iPad |

## 3. Screenshot rules

- 1 to 10 screenshots per device size. Up to three appear in search results depending on orientation.
- `.png`, `.jpg`, `.jpeg`. No alpha channel or transparency. The spec page names no color space; export sRGB. `xcrun simctl io screenshot` writes 8-bit RGBA PNGs (colour type 6, every alpha 255), so `assets.sh` flattens captures to RGB on export; the gate would otherwise reject every simulator capture (field test 5).
- One iPhone Duo placement group holds all four sizes (outer and inner, both orientations) with the same limit of ten. Reported from the ASC asset catalog by a community CLI fork; the ASC web UI shows one Duo tab. Treat the four-sizes-in-one-set detail as community-reported.
- Changing screenshots after approval needs a new version.
- Screenshots must follow App Review Guidelines 2.3.3 and 2.3.4.
- The outer-display capture includes the system status column beside the app; design captions around it.

## 4. App preview specs

| Item | Value |
|---|---|
| Device resolutions listed for Duo | 2034 × 1398 and 2853 × 2007 |
| Accepted preview resolutions | 886 × 1920 (portrait), 1920 × 886 (landscape); the same as other Face ID iPhones, not the Duo aspect ratio |
| Count | up to 3 per device size and language |
| Duration | 15 to 30 s |
| Frame rate | up to 30 fps |
| File size | up to 500 MB |
| Poster frame | default at 5 s, adjustable until approval |
| Formats | H.264 `.mov`/`.m4v`/`.mp4` (10 to 12 Mbps, up to High Profile 4.0); ProRes 422 HQ `.mov` (about 220 Mbps) |
| Audio | stereo AAC 256 kbps (or PCM for ProRes), 44.1 or 48 kHz |
| Orientation | portrait or landscape for iOS; plays in the original orientation |
| Processing | up to 24 hours |

Previews always appear before screenshots. A preview whose aspect ratio differs from the screenshots lands in "A Closer Look". Videos autoplay muted and loop, so they must work silently and loop cleanly. The spec lists no Duo fallback row and does not say which resolution maps to which display. Whether a Duo capture must be letterboxed into 886 × 1920 is unverified; treat previews as v1.1.

## 5. Asset best practices digest

Do:
- Show the app in use; lead with the strongest feature; sequence screenshots as a story.
- Keep text short and complementary; keep key elements and the focal point inside the safe area and centered; check in the ASC preview tool, which renders iPhone Duo.
- Localize text in images and videos for every supported language; design for a global audience and a 4+ rating regardless of the app's rating.
- Share screenshots and previews across orientations.

Don't:
- Include prices, discounts, URLs, copyright symbols, unverifiable claims, other platforms' logos, or Apple recognitions (Editor's Choice, App of the Day, Apple Design Award).
- Use the whole asset for accolades or calls to action.
- Show objectionable content, gore, or weapons pointed at the viewer.

## 6. Upload paths

| Path | Status (27 Oct 2026) |
|---|---|
| App Store Connect web (App Previews and Screenshots tab, Media Manager, Asset Library) | Reliable. Safe default for the inner-display set. |
| fastlane `deliver` ≥ 2.241.1 | PR #30444 added the Duo sizes (released 14 to 15 Oct 2026; one production pipeline uses 2.241.2). Earlier versions abort the whole upload on an unknown size. Enum name: `APP_IPHONE_DUO`. Read in the installed 2.241.2 source (field test 5, 29 Oct 2026): `spaceship/.../app_screenshot_set.rb` defines `APP_IPHONE_DUO` and lists it in `ALL`; `deliver/.../app_screenshot.rb` has all four Duo sizes under one "iPhone Duo" entry and `calculate_display_type` picks the type from the pixel size (`FastImage.size`), never from the file name, so inner and outer files land in the same `APP_IPHONE_DUO` set (10 per set, `upload_screenshots.rb`); uploads go through the v1 `appScreenshotSets` endpoints; `app_screenshot_validator.rb` has no alpha check, so an RGBA file is refused by Apple, not locally. |
| `asc screenshots upload --version-localization <ID> --path screenshots --device-type APP_IPHONE_DUO` (rorkai/App-Store-Connect-CLI ≥ 5.12.0) | Set creation with `APP_IPHONE_DUO` returns 201. Outer-display uploads verified live (COMPLETE, matching checksums, visible in the Duo gallery). **Inner-display uploads unverified** by anyone at this date. `asc screenshots sizes --display-type APP_IPHONE_DUO` lists the sizes. |
| App Store Connect API directly | The published OpenAPI spec and reference omit a Duo `ScreenshotDisplayType` (33 values on 29 Oct 2026, none for Duo, none that tells inner from outer); the live API accepts `APP_IPHONE_DUO` (and reportedly `IMESSAGE_APP_IPHONE_DUO`, `IPHONE_DUO` for previews). Undocumented; may change. `AppScreenshotSet` is marked deprecated since API 4.5 in favour of `AppAssetLibraryPlacement`; the Help page's single iPhone Duo row lists the outer and inner sizes together and does not say whether one set or two are expected. |
| EAS metadata | Not covered by any source; unverified. |

Rule for the skill: it exports the files and stops; it never uploads. The user drags the set into the web UI (App Previews and Screenshots > iPhone Duo) or runs their own fastlane deliver lane; say plainly that an inner upload through the API is unverified, so the web UI is the path for the inner set. Upload failures reported by the community: ITMS-90870 "Missing launch screen" when `Info.plist` lacks a launch screen key.

## 7. Framing and bezels

Apple ships a product bezel for iPhone Duo as Photoshop and PNG files: `https://devimages-cdn.apple.com/design/resources/download/Bezel-iPhone-Duo.dmg` (design resources page). No Figma or Sketch Duo templates were listed. The user downloads the DMG; `assets.sh --frames` only references a local path. Framing is optional and the framed image must still be exactly the sizes in section 2.

## 8. Featuring nomination

In App Store Connect, submit a featuring nomination. Under Helpful Details, state that the app is optimized for iPhone Duo including all device poses. `assets.sh` writes `FEATURING.md` through `scripts/featuring.py`, which builds the draft from the run's `ui.json`: one sentence per assertion that passed everywhere it was evaluated (fold, bars, clipping, tap targets, outer camera, transitions), the poses and orientations that were captured, the displays the export covered and the SDK stamp. While any cell fails, the file opens with "Not ready to submit" and the failing cells; a fixed template claimed fold-safe controls next to twelve open fold failures on the sixth field test. A fully green run reads like:

> Optimized for iPhone Duo. It adapts to the outer display when closed, the inner display when open, the partially folded (book) pose and both orientations. Nothing is laid out beyond the window edges in any pose, toolbars and tab bars follow the system's vertical placement, interactive controls stay clear of the fold in the book poses, and state and controls survive folding and unfolding. App Store screenshots cover the inner and outer displays. Built with the iOS 27.1 SDK.

Add the app's actual Duo features; never add a claim the run did not prove. Apple guide: https://developer.apple.com/help/app-store-connect/manage-featuring-nominations/nominate-your-app-for-featuring/

## 9. Preview tool and new creative assets

App Store Connect has a preview tool that shows screenshots, product page headers and search-result assets as they appear on iPhone Duo. The news post also introduces new product page header and search-result creative assets (App Store "What's New" enhancements); they are outside this skill's scope.

## 10. Sources

- Screenshot specifications: https://developer.apple.com/help/app-store-connect/reference/app-information/screenshot-specifications
- App preview specifications: https://developer.apple.com/help/app-store-connect/reference/app-information/app-preview-specifications
- Manage App Store assets: https://developer.apple.com/help/app-store-connect/manage-app-information/manage-your-app-store-assets
- Asset best practices: https://developer.apple.com/app-store/asset-best-practices/
- News, 5 Oct 2026: https://developer.apple.com/news/?id=kkphp5qo
- Prepare page (badge, nomination): https://developer.apple.com/iphone-duo/prepare/
- Design resources (bezel): https://developer.apple.com/design/resources/
- fastlane deliver Duo sizes: https://github.com/fastlane/fastlane/pull/30444
- asc CLI Duo support: https://github.com/rorkai/App-Store-Connect-CLI/pull/2926
- Sizes and API notes: https://dev.to/marck100/iphone-duo-app-store-screenshots-the-new-sizes-capturing-both-displays-and-what-the-api-says-12cn
- Production pipeline with fastlane 2.241.2: https://github.com/boardsesh/boardsesh/pull/6953
