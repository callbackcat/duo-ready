import React, { useReducer } from 'react';
import { StyleSheet, Text, View, useWindowDimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

// Clean: `status !== 'active'` here is a reducer field, not AppState, and the
// hero takes 40 percent of the window, which leaves room on the 678 pt display.
type Action = { status: 'active' | 'done' };

function reducer(count: number, action: Action) {
  if (action.status !== 'active') return count;
  return count + 1;
}

export function LocalState() {
  const { height } = useWindowDimensions();
  const [count, dispatch] = useReducer(reducer, 0);
  return (
    <SafeAreaView style={styles.root}>
      <View style={{ height: height * 0.4 }} />
      <Text onPress={() => dispatch({ status: 'active' })}>{count}</Text>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({ root: { flex: 1 } });
