import type { Device, MapData, Position, PresenceEvent, Session } from '../types';

const API_BASE = 'https://api.voicechatbox.com';

interface ApiResponse<T> {
  data: T;
  error?: string;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  token?: string,
): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      const errorBody = await response.text();
      return { data: null as unknown as T, error: `HTTP ${response.status}: ${errorBody}` };
    }

    const data = await response.json();
    return { data };
  } catch (error) {
    return { data: null as unknown as T, error: String(error) };
  }
}

export const api = {
  createSession: (name: string, token?: string) =>
    request<Session>('POST', '/api/sessions', { name }, token),

  getMap: (sessionId: string, token?: string) =>
    request<MapData>('GET', `/api/map/${sessionId}`, undefined, token),

  getDevices: (sessionId: string, token?: string) =>
    request<Device[]>('GET', `/api/devices/${sessionId}`, undefined, token),

  getPresence: (sessionId: string, token?: string) =>
    request<PresenceEvent[]>('GET', `/api/presence/${sessionId}`, undefined, token),

  tagPosition: (sessionId: string, position: Position, token?: string) =>
    request<{ status: string }>('POST', '/api/positions', {
      session_id: sessionId,
      ...position,
    }, token),
};
