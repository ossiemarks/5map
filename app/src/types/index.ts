export interface RssiReading {
  mac: string;
  rssi_dbm: number;
  channel: number;
  bandwidth: string;
}

export interface Position {
  x: number;
  y: number;
  label: string;
  rssi_snapshot?: RssiReading[];
}

export interface SensorObservation {
  mac: string;
  rssi_dbm: number;
  noise_dbm: number | null;
  channel: number;
  bandwidth: string;
  frame_type: string;
  ssid: string | null;
  is_randomized_mac: boolean;
  count: number;
}

export interface Device {
  mac_address: string;
  device_type: 'phone' | 'laptop' | 'iot' | 'ap' | 'unknown';
  vendor: string | null;
  zone: string | null;
  rssi_dbm: number;
  risk_score: number;
  first_seen: string;
  last_seen: string;
  is_randomized_mac: boolean;
}

export interface PresenceEvent {
  event_id: string;
  session_id: string;
  timestamp: string;
  event_type: 'empty' | 'stationary' | 'moving' | 'entry' | 'exit';
  zone: string;
  confidence: number;
  device_count: number;
}

export interface HeatmapPoint {
  x: number;
  y: number;
  value: number;
}

export interface Wall {
  start: [number, number];
  end: [number, number];
  confidence: number;
}

export interface MapData {
  session_id: string;
  heatmap: number[][];
  walls: Wall[];
  grid_bounds: {
    x_min: number;
    x_max: number;
    y_min: number;
    y_max: number;
  };
  positions: Position[];
  confidence: number;
  updated_at: string;
}

export interface Session {
  session_id: string;
  name: string;
  created_at: string;
  status: 'active' | 'completed';
  position_count: number;
  device_count: number;
}

export interface WebSocketMessage {
  type: 'map_update' | 'device_update' | 'presence_event' | 'error';
  session_id: string;
  data: MapData | Device | PresenceEvent | { message: string };
}
