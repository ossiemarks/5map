import { useEffect } from 'react';
import { useStore } from '../store';
import { api } from '../services/api';
import { storage } from '../services/storage';

export function useDevices(sessionId: string | null) {
  const devices = useStore((s) => s.devices);
  const setDevices = useStore((s) => s.setDevices);

  useEffect(() => {
    if (!sessionId) return;

    (async () => {
      const cached = await storage.getDevices(sessionId);
      if (cached) setDevices(cached);

      const { data, error } = await api.getDevices(sessionId);
      if (data && !error) {
        setDevices(data);
        storage.setDevices(sessionId, data);
      }
    })();
  }, [sessionId]);

  const sortedDevices = [...devices].sort((a, b) => a.rssi_dbm - b.rssi_dbm);
  const rogueDevices = devices.filter((d) => d.risk_score >= 0.6);

  return { devices: sortedDevices, rogueDevices, totalCount: devices.length };
}
