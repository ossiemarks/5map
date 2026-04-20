import { create } from 'zustand';
import type { Device, MapData, PresenceEvent, Session, WebSocketMessage } from '../types';

interface MapSlice {
  mapData: MapData | null;
  positions: Array<{ x: number; y: number; label: string }>;
  setMapData: (data: MapData) => void;
  addPosition: (pos: { x: number; y: number; label: string }) => void;
  clearMap: () => void;
}

interface DevicesSlice {
  devices: Device[];
  setDevices: (devices: Device[]) => void;
  updateDevice: (device: Device) => void;
  clearDevices: () => void;
}

interface PresenceSlice {
  events: PresenceEvent[];
  setEvents: (events: PresenceEvent[]) => void;
  addEvent: (event: PresenceEvent) => void;
  clearEvents: () => void;
}

interface SessionSlice {
  currentSession: Session | null;
  sessions: Session[];
  setCurrentSession: (session: Session | null) => void;
  setSessions: (sessions: Session[]) => void;
}

interface ConnectionSlice {
  wsConnected: boolean;
  setWsConnected: (connected: boolean) => void;
}

export type AppState = MapSlice & DevicesSlice & PresenceSlice & SessionSlice & ConnectionSlice;

export const useStore = create<AppState>((set) => ({
  // Map slice
  mapData: null,
  positions: [],
  setMapData: (data) => set({ mapData: data }),
  addPosition: (pos) => set((state) => ({ positions: [...state.positions, pos] })),
  clearMap: () => set({ mapData: null, positions: [] }),

  // Devices slice
  devices: [],
  setDevices: (devices) => set({ devices }),
  updateDevice: (device) =>
    set((state) => {
      const idx = state.devices.findIndex((d) => d.mac_address === device.mac_address);
      if (idx >= 0) {
        const updated = [...state.devices];
        updated[idx] = device;
        return { devices: updated };
      }
      return { devices: [...state.devices, device] };
    }),
  clearDevices: () => set({ devices: [] }),

  // Presence slice
  events: [],
  setEvents: (events) => set({ events }),
  addEvent: (event) =>
    set((state) => ({
      events: [event, ...state.events].slice(0, 500), // keep last 500
    })),
  clearEvents: () => set({ events: [] }),

  // Session slice
  currentSession: null,
  sessions: [],
  setCurrentSession: (session) => set({ currentSession: session }),
  setSessions: (sessions) => set({ sessions }),

  // Connection slice
  wsConnected: false,
  setWsConnected: (connected) => set({ wsConnected: connected }),
}));

export function handleWebSocketMessage(message: WebSocketMessage): void {
  const store = useStore.getState();

  switch (message.type) {
    case 'map_update':
      store.setMapData(message.data as MapData);
      break;
    case 'device_update':
      store.updateDevice(message.data as Device);
      break;
    case 'presence_event':
      store.addEvent(message.data as PresenceEvent);
      break;
  }
}
