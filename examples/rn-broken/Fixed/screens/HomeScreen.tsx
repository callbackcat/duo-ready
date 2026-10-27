import React, { useEffect } from 'react';
import { AppState, FlatList, Image, View, useWindowDimensions } from 'react-native';
import { SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import { createNativeBottomTabNavigator } from '@bottom-tabs/react-navigation';
import { useHinge } from 'expo-hinge';
import { player } from '../player';

// The same screen written the way the Duo guidance recommends.
// scan.py must report zero findings for this directory.
const Tab = createNativeBottomTabNavigator();

export function HomeScreen({ items }: { items: string[] }) {
  const { width } = useWindowDimensions();
  const insets = useSafeAreaInsets();
  const hinge = useHinge();
  const twoColumns = width >= 600;
  const bend = hinge && hinge.status === 'partiallyOpen' ? hinge.angle / 180 : 0;

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'background') player.pause();
    });
    return () => sub.remove();
  }, []);

  return (
    <SafeAreaView style={{ flex: 1, paddingLeft: insets.left, paddingRight: insets.right }}>
      <Image source={{ uri: items[0] }} style={{ width: '100%', aspectRatio: 16 / 9, opacity: 1 - bend }} resizeMode="contain" />
      <FlatList
        key={twoColumns ? 'two' : 'one'}
        numColumns={twoColumns ? 2 : 1}
        data={items}
        renderItem={({ item }) => <View style={{ flex: 1, padding: 8 }} />}
      />
    </SafeAreaView>
  );
}
