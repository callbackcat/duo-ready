import React, { useEffect, useRef } from 'react'; // duo: rn-safe-area-missing
import { AppState, Image, StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { video } from '../player';

// Intentionally broken for iPhone Duo. Tagged lines are scan fixtures.
// Every real outer-display bug on a field-test app was a height bug:
// the outer display is 678 pt tall, shorter than any current iPhone.
export function OnboardingScreen() {
  const { height } = useWindowDimensions();
  const heroHeight = height * 0.6; // duo: rn-window-height-fraction
  const ref = useRef(null);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (nextAppState) => {
      if (nextAppState !== 'active') video.pause(); // duo: rn-appstate-inactive-pause
    });
    return () => sub.remove();
  }, []);

  return (
    <View style={styles.root}>
      <View style={[styles.hero, { height: heroHeight }]}>
        <Image source={require('../art/hero.png')} height={320} /> {/* duo: rn-fixed-height */}
      </View>
      <Text adjustsFontSizeToFit numberOfLines={1} style={styles.title}> {/* duo: rn-adjusts-font-fixed-lineheight */}
        Welcome to Demo
      </Text>
      <Text style={styles.body} ref={ref}>Swipe to continue</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  hero: {
    justifyContent: 'flex-end',
  },
  art: {
    minHeight: 340, // duo: rn-fixed-height
  },
  title: {
    fontSize: 28,
    lineHeight: 34,
  },
  body: {
    fontSize: 16,
  },
});
