import AsyncStorage from '@react-native-async-storage/async-storage';
import type { Device, MapData, PresenceEvent, Session } from '../types';

const KEYS = {
  SESSIONS: '5map:sessions',
  MAP: (id: string) => `5map:map:${id}`,
  DEVICES: (id: string) => `5map:devices:${id}`,
  PRESENCE: (id: string) => `5map:presence:${id}`,
  SETTINGS: '5map:settings',
};

async function getJSON<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

async function setJSON(key: string, value: unknown): Promise<void> {
  try {
    await AsyncStorage.setItem(key, JSON.stringify(value));
  } catch {
    // storage full or unavailable
  }
}

export const storage = {
  getSessions: () => getJSON<Session[]>(KEYS.SESSIONS),
  setSessions: (sessions: Session[]) => setJSON(KEYS.SESSIONS, sessions),

  getMap: (sessionId: string) => getJSON<MapData>(KEYS.MAP(sessionId)),
  setMap: (sessionId: string, map: MapData) => setJSON(KEYS.MAP(sessionId), map),

  getDevices: (sessionId: string) => getJSON<Device[]>(KEYS.DEVICES(sessionId)),
  setDevices: (sessionId: string, devices: Device[]) => setJSON(KEYS.DEVICES(sessionId), devices),

  getPresence: (sessionId: string) => getJSON<PresenceEvent[]>(KEYS.PRESENCE(sessionId)),
  setPresence: (sessionId: string, events: PresenceEvent[]) => setJSON(KEYS.PRESENCE(sessionId), events),

  getSettings: () => getJSON<Record<string, string>>(KEYS.SETTINGS),
  setSettings: (settings: Record<string, string>) => setJSON(KEYS.SETTINGS, settings),

  clear: () => AsyncStorage.clear(),
};
