import React, { useEffect, useRef } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StatusBar } from 'expo-status-bar';
import { StyleSheet, View, Text } from 'react-native';

import MapScreen from './src/screens/MapScreen';
import DevicesScreen from './src/screens/DevicesScreen';
import PresenceScreen from './src/screens/PresenceScreen';
import SettingsScreen from './src/screens/SettingsScreen';
import { WebSocketClient } from './src/services/websocket';
import { useStore, handleWebSocketMessage } from './src/store';

const Tab = createBottomTabNavigator();

const THEME = {
  dark: true,
  colors: {
    primary: '#00d4ff',
    background: '#0a0e17',
    card: '#131a2b',
    text: '#e8eaed',
    border: '#1e2d4a',
    notification: '#ff4757',
  },
};

function TabIcon({ label, focused }: { label: string; focused: boolean }) {
  const icons: Record<string, string> = {
    Map: '🗺',
    Devices: '📱',
    Presence: '👤',
    Settings: '⚙',
  };
  return (
    <Text style={{ fontSize: 20, opacity: focused ? 1 : 0.5 }}>
      {icons[label] || '?'}
    </Text>
  );
}

export default function App() {
  const wsRef = useRef<WebSocketClient | null>(null);
  const setWsConnected = useStore((s) => s.setWsConnected);
  const currentSession = useStore((s) => s.currentSession);

  useEffect(() => {
    const ws = new WebSocketClient(
      'mvp-token',
      handleWebSocketMessage,
      setWsConnected,
    );
    ws.connect();
    wsRef.current = ws;

    return () => {
      ws.disconnect();
    };
  }, []);

  useEffect(() => {
    if (currentSession && wsRef.current) {
      wsRef.current.subscribe(currentSession.session_id);
    }
  }, [currentSession]);

  return (
    <View style={styles.container}>
      <StatusBar style="light" />
      <NavigationContainer theme={THEME}>
        <Tab.Navigator
          screenOptions={({ route }) => ({
            tabBarIcon: ({ focused }) => (
              <TabIcon label={route.name} focused={focused} />
            ),
            tabBarStyle: { backgroundColor: '#131a2b', borderTopColor: '#1e2d4a' },
            tabBarActiveTintColor: '#00d4ff',
            tabBarInactiveTintColor: '#5a6987',
            headerStyle: { backgroundColor: '#131a2b' },
            headerTintColor: '#e8eaed',
          })}
        >
          <Tab.Screen name="Map" component={MapScreen} />
          <Tab.Screen name="Devices" component={DevicesScreen} />
          <Tab.Screen name="Presence" component={PresenceScreen} />
          <Tab.Screen name="Settings" component={SettingsScreen} />
        </Tab.Navigator>
      </NavigationContainer>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0e17',
  },
});
