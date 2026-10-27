import React, { useEffect } from 'react';
import { AppState, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useHinge } from 'expo-hinge';
import { player } from '../player';

// Intentionally broken for iPhone Duo. Tagged lines are scan fixtures.
export function PlayerScreen() {
  const insets = useSafeAreaInsets();
  const hinge = useHinge();
  const columns = hinge && hinge.angle > 90 ? 2 : 1; // duo: rn-expo-hinge-for-layout

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state !== 'active') player.pause(); // duo: rn-appstate-inactive-pause
    });
    return () => sub.remove();
  }, []);

  return (
    <View style={{ flex: 1, paddingHorizontal: Math.max(insets.left, insets.right) }}> {/* duo: rn-symmetric-insets */}
      <View style={{ flex: columns }} />
    </View>
  );
}
