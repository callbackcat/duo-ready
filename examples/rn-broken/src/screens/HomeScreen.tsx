// duo: rn-safe-area-missing
import React from 'react';
import { Dimensions, FlatList, View } from 'react-native';
import { Card } from '../components/Card';

// Intentionally broken for iPhone Duo. No SafeAreaView, snapshot dimensions, device breakpoint.
export function HomeScreen({ items }: { items: string[] }) {
  const { width } = Dimensions.get('window'); // duo: rn-dimensions-no-listener
  const twoColumns = width >= 414; // duo: rn-hardcoded-breakpoint
  return (
    <View style={{ flex: 1 }}>
      <FlatList
        key={twoColumns ? 'two' : 'one'}
        numColumns={twoColumns ? 2 : 1}
        data={items}
        renderItem={({ item }) => <Card uri={item} />}
      />
    </View>
  );
}
