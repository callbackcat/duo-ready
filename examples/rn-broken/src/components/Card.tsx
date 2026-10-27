import React from 'react';
import { Dimensions, Image, Platform, StyleSheet, View } from 'react-native';

// Intentionally broken for iPhone Duo. Tagged lines are scan fixtures.
const { width } = Dimensions.get('window'); // duo: rn-dimensions-module-scope

const columns = Platform.isPad ? 3 : 2; // duo: rn-platform-ispad

export function Card({ uri }: { uri: string }) {
  return (
    <View style={[styles.card, { width: width / columns - 16 }]}>
      <Image source={{ uri }} style={styles.hero} resizeMode="cover" /> {/* duo: rn-image-cover */}
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    width: 375, // duo: rn-stylesheet-fixed-width
    padding: 8,
  },
  hero: {
    height: 180,
  },
});
