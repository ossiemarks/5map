import { useCallback, useEffect } from 'react';
import { useStore } from '../store';
import { api } from '../services/api';
import { storage } from '../services/storage';
import type { Position } from '../types';

export function useMap(sessionId: string | null) {
  const mapData = useStore((s) => s.mapData);
  const positions = useStore((s) => s.positions);
  const setMapData = useStore((s) => s.setMapData);
  const addPosition = useStore((s) => s.addPosition);

  useEffect(() => {
    if (!sessionId) return;

    (async () => {
      // Try cache first
      const cached = await storage.getMap(sessionId);
      if (cached) setMapData(cached);

      // Fetch fresh
      const { data, error } = await api.getMap(sessionId);
      if (data && !error) {
        setMapData(data);
        storage.setMap(sessionId, data);
      }
    })();
  }, [sessionId]);

  const tagPosition = useCallback(
    async (x: number, y: number, label: string) => {
      if (!sessionId) return;
      const pos: Position = { x, y, label };
      addPosition(pos);
      await api.tagPosition(sessionId, pos);
    },
    [sessionId],
  );

  return { mapData, positions, tagPosition };
}
