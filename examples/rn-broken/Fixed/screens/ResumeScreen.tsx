import React, { useEffect, useState } from 'react';
import { AppState, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { refresh } from '../api';

// Clean: resumes on `active` instead of pausing on `inactive`, caps width with
// maxWidth (the recommended pattern), and lets the hero shrink.
export function ResumeScreen() {
  const [count, setCount] = useState(0);

  useEffect(() => {
    const sub = AppState.addEventListener('change', (state) => {
      if (state !== 'active') return;
      refresh().then(setCount);
    });
    return () => sub.remove();
  }, []);

  return (
    <SafeAreaView style={styles.root}>
      <View style={styles.card}>
        <Text style={styles.title} numberOfLines={2}>Resumed {count} times</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  card: { maxWidth: 600, alignSelf: 'center', width: '100%', flexShrink: 1 },
  title: { fontSize: 28, lineHeight: 34 },
});
