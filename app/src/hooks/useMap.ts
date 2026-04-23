import { useCallback, useEffect, useRef } from 'react';
import { useStore } from '../store';
import { api } from '../services/api';
import { storage } from '../services/storage';
import { idwInterpolate } from '../utils/idw';
import type { MapData, Position } from '../types';

export function useMap(sessionId: string | null) {
  const mapData = useStore((s) => s.mapData);
  const positions = useStore((s) => s.positions);
  const roomWidth = useStore((s) => s.roomWidth);
  const roomHeight = useStore((s) => s.roomHeight);
  const setMapData = useStore((s) => s.setMapData);
  const addPosition = useStore((s) => s.addPosition);
  const idwMapRef = useRef<MapData | null>(null);

  useEffect(() => {
    if (!sessionId) return;
    (async () => {
      const cached = await storage.getMap(sessionId);
      if (cached) setMapData(cached);
      const { data, error } = await api.getMap(sessionId);
      if (data && !error) {
        setMapData(data);
        storage.setMap(sessionId, data);
      }
    })();
  }, [sessionId]);

  const generateIdwPreview = useCallback(
    (allPositions: Array<Position>) => {
      const tagged = allPositions
        .filter((p) => p.rssi_snapshot && p.rssi_snapshot.length > 0)
        .map((p) => ({
          x: p.x,
          y: p.y,
          rssiMean:
            p.rssi_snapshot!.reduce((sum, r) => sum + r.rssi_dbm, 0) /
            p.rssi_snapshot!.length,
        }));

      if (tagged.length < 3) return null;

      const heatmap = idwInterpolate(tagged, 30, {
        xMin: 0,
        xMax: roomWidth,
        yMin: 0,
        yMax: roomHeight,
      });

      const preview: MapData = {
        session_id: sessionId || '',
        heatmap,
        walls: [],
        grid_bounds: { x_min: 0, x_max: roomWidth, y_min: 0, y_max: roomHeight },
        positions: allPositions,
        confidence: 0.5,
        updated_at: new Date().toISOString(),
      };
      idwMapRef.current = preview;
      return preview;
    },
    [roomWidth, roomHeight, sessionId],
  );

  const tagPosition = useCallback(
    async (x: number, y: number, label: string) => {
      if (!sessionId) return;
      const pos: Position = { x, y, label };
      addPosition(pos);

      // Fire API call (includes RSSI snapshot fetch + POST)
      api.tagPosition(sessionId, pos);

      // Generate IDW preview locally
      const allPos = [...positions, pos];
      const preview = generateIdwPreview(allPos);
      if (preview) setMapData(preview);
    },
    [sessionId, positions, generateIdwPreview],
  );

  return { mapData, positions, tagPosition, roomWidth, roomHeight };
}
