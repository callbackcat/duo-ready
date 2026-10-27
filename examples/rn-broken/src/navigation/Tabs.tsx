import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { HomeScreen } from '../screens/HomeScreen';
import { PlayerScreen } from '../screens/PlayerScreen';
import { MyTabBar } from './MyTabBar';

const Tab = createBottomTabNavigator(); // duo: rn-js-tab-bar

export function Tabs() {
  return (
    <Tab.Navigator tabBar={(props) => <MyTabBar {...props} />}> {/* duo: rn-js-tab-bar */}
      <Tab.Screen name="Home" component={HomeScreen} />
      <Tab.Screen name="Player" component={PlayerScreen} />
    </Tab.Navigator>
  );
}
