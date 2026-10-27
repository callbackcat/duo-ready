# React Native / Expo scan rules

Source of truth: `scripts/rules/react-native.yaml`. Apple's own App Resizability skill cannot see JavaScript, so these rules exist to cover the layer where RN apps actually break. React Native has no first-party Duo API as of 27 Oct 2026; flexbox and `useWindowDimensions()` already do the right thing, and most breakage comes from caching the window size, locking orientation, or assuming symmetric insets. Numbers are from `references/device-facts.md`.

Contents: [rn-dimensions-module-scope](#rn-dimensions-module-scope) · [rn-dimensions-no-listener](#rn-dimensions-no-listener) · [rn-platform-ispad](#rn-platform-ispad) · [rn-orientation-lock](#rn-orientation-lock) · [rn-hardcoded-breakpoint](#rn-hardcoded-breakpoint) · [rn-stylesheet-fixed-width](#rn-stylesheet-fixed-width) · [rn-safe-area-missing](#rn-safe-area-missing) · [rn-symmetric-insets](#rn-symmetric-insets) · [rn-image-cover](#rn-image-cover) · [rn-js-tab-bar](#rn-js-tab-bar) · [rn-appstate-inactive-pause](#rn-appstate-inactive-pause) · [rn-expo-hinge-for-layout](#rn-expo-hinge-for-layout) · [rn-sdk-floor](#rn-sdk-floor)

Before any of this matters: the app must be built with the iOS 27.1 SDK (Xcode 27.1). Check with `xcrun --sdk iphoneos --show-sdk-version` and `scripts/sdk-stamp.sh`; an older stamp runs letterboxed in a phone-shaped window.

---

## rn-dimensions-module-scope
**error · manual** (suggested codemod below)

`Dimensions.get('window')` at module scope runs once at launch. After the first fold the window is 951×669 pt instead of 466×678 and every style built from that width is wrong. A `Dimensions.addEventListener` does not help when the value was baked into `StyleSheet.create`.

```tsx
// before
const { width } = Dimensions.get('window');
const styles = StyleSheet.create({ card: { width: width - 32 } });
// after
function Card({ children }) {
  const { width } = useWindowDimensions();          // re-renders on fold, rotation, Split View
  return <View style={[styles.card, { width: width - 32 }]}>{children}</View>;
}
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## rn-dimensions-no-listener
**warn · manual** (file-level: indented `Dimensions.get` with no `useWindowDimensions` / listener in the file)

Inside a component `Dimensions.get` is a snapshot taken on that render; the component does not re-render when the device folds. Replace with `useWindowDimensions()`.

```tsx
// before
const { width } = Dimensions.get('window');
// after
const { width } = useWindowDimensions();
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## rn-platform-ispad
**error · manual**

`Platform.isPad` is `false` on iPhone Duo although the open inner display is wider than an iPad mini in landscape. Choose layouts from the window width.

```tsx
// before
const columns = Platform.isPad ? 3 : 2;
// after
const { width } = useWindowDimensions();
const columns = width >= 600 ? 2 : 1;
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## rn-orientation-lock
**warn · manual** (`app.json` `"orientation": "portrait"`, `expo-screen-orientation` `lockAsync`, `react-native-orientation-locker` `lockTo*`)

Orientation locks are silently ignored on the inner display, so a portrait-locked app still receives a 951×669 window there. The lock cannot protect the layout; make the layout width-driven and drop the lock (games may keep it but must fill the screen in every pose).

```json
// app.json before
{ "expo": { "orientation": "portrait" } }
// after
{ "expo": { "orientation": "default" } }
```
Ref: https://developer.apple.com/videos/play/tech-talks/111461/

## rn-hardcoded-breakpoint
**warn · manual**

`width === 414`, `width < 375` and friends encode specific iPhones. The Duo window is 466 pt closed, 951 open, about 475 in Split View, and rotation swaps the numbers. Use one semantic breakpoint.

```tsx
// before
const twoColumns = width >= 414;
// after
const twoColumns = width >= 600;          // one column closed (466), two open (951) in either rotation
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## rn-stylesheet-fixed-width
**warn · manual**

A fixed `width: 375` overflows the 466 pt outer display once insets are applied and leaves half of the 951 pt inner display empty. Use `flex: 1`, percentages, or the measured window width.

```tsx
// before
card: { width: 375 }
// after
card: { flex: 1, maxWidth: 600 }
```
Ref: https://developer.apple.com/design/human-interface-guidelines/designing-for-iphone-duo

## rn-safe-area-missing
**warn · manual** (file-level: a screen component under `screens/`, `app/` or named `*Screen` without `SafeAreaView` / `useSafeAreaInsets`)

On iPhone Duo the status column (84 pt) and the vertical bar sit on one edge and the outer camera occludes a 37×37 pt corner. A screen that ignores the safe area draws under them. Wrap the screen in `SafeAreaView` from `react-native-safe-area-context` or apply `useSafeAreaInsets()` per edge.

```tsx
// after
import { SafeAreaView } from 'react-native-safe-area-context';
export function HomeScreen() { return <SafeAreaView style={{ flex: 1 }}>…</SafeAreaView>; }
```
Ref: https://developer.apple.com/videos/play/tech-talks/111461/

## rn-symmetric-insets
**error · manual**

`paddingHorizontal: Math.max(insets.left, insets.right)` assumes both edges match. On the Duo only one edge carries the status column and bar, so the layout loses 84 pt on the wrong side. Apply each edge separately.

```tsx
// before
paddingHorizontal: Math.max(insets.left, insets.right)
// after
paddingLeft: insets.left, paddingRight: insets.right
```
Ref: https://developer.apple.com/videos/play/tech-talks/111461/

## rn-image-cover
**warn · manual**

`resizeMode="cover"` (or `contentFit="cover"`, `objectFit: 'cover'`) crops to the container. The window aspect ratio changes from 0.69 (closed) to 1.42 (open), so a hero image loses its subject. Keep the image at a fixed `aspectRatio` and place content beneath it, or pick cover/contain from the window aspect ratio.

```tsx
// before
<Image source={hero} style={{ width: '100%', height: 260 }} resizeMode="cover" />
// after
<Image source={hero} style={{ width: '100%', aspectRatio: 16 / 9 }} resizeMode="contain" />
```
Ref: https://developer.apple.com/iphone-duo/prepare/

## rn-js-tab-bar
**warn · manual**

The system moves tab bars to the vertical trailing edge in the closed and open-landscape poses. A JS-drawn tab bar (`createBottomTabNavigator`, a custom `tabBar` prop) stays at the bottom and looks out of place next to system apps. Prefer a native tab bar backed by `UITabBarController`: `createNativeBottomTabNavigator` from `@bottom-tabs/react-navigation`, or Expo Router native tabs. Verify on a real build; native-tabs Duo behaviour is reported, not yet confirmed by the maintainers.

Ref: https://developer.apple.com/design/human-interface-guidelines/designing-for-iphone-duo

## rn-appstate-inactive-pause
**warn · manual**

In Split View on the inner display your app can be visible and `inactive` at the same time. Pausing playback or network work on anything other than `background` interrupts the user while they look at the other app.

```tsx
// before
if (state !== 'active') player.pause();
// after
if (state === 'background') player.pause();
```
Ref: https://developer.apple.com/videos/play/tech-talks/111464/

## rn-expo-hinge-for-layout
**warn · manual** (file-level: `useHinge` / `getHinge` value feeding width, flex, columns, style or padding)

`expo-hinge` (Expo SDK 58) exposes the hinge angle and status (`closed`, `partiallyOpen`, `fullyOpen`) via `UIHingeInteraction`. Expo's guidance, like Apple's, is to use hinge state for interactions and effects, not layout: the window size and safe-area insets already describe the layout, and they also hold in Split View and on non-foldable devices where the hinge is `null`.

```tsx
// before
const hinge = useHinge();
const columns = hinge && hinge.angle > 90 ? 2 : 1;
// after
const { width } = useWindowDimensions();
const columns = width >= 600 ? 2 : 1;
const bend = hinge?.status === 'partiallyOpen' ? hinge.angle / 180 : 0;   // effects only
```
Ref: https://docs.expo.dev/versions/v58.0.0/sdk/hinge/

## rn-sdk-floor
**warn · manual** (file-level on `package.json`)

Expo SDK 58 is the first with `expo-hinge`, Duo-aware native tabs and an EAS build image on Xcode 27.1. `react-native-screens` shipped iPhone Duo fixes on 13 Oct 2026 (the exact first version is marked TODO-VERIFY in `scan.py`; the floor used is 4.20.0). Older versions mis-size screens on the inner display. Upgrade before measuring anything.

```sh
npx expo install expo@^58 react-native-screens@latest
```
Ref: https://docs.expo.dev/versions/v58.0.0/sdk/hinge/
