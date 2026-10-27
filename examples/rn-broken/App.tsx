import React, { useEffect } from 'react';
import * as ScreenOrientation from 'expo-screen-orientation';
import { Tabs } from './src/navigation/Tabs';

// Intentionally broken for iPhone Duo. Tagged lines are scan fixtures.
export default function App() {
  useEffect(() => {
    ScreenOrientation.lockAsync(ScreenOrientation.OrientationLock.PORTRAIT_UP); // duo: rn-orientation-lock
  }, []);
  return <Tabs />;
}
