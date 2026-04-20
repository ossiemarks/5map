import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Dimensions,
} from 'react-native';
import { useStore } from '../store';
import { useMap } from '../hooks/useMap';
import { HeatmapOverlay } from '../components/HeatmapOverlay';
import { PositionMarker } from '../components/PositionMarker';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const CANVAS_SIZE = SCREEN_WIDTH - 32;

export function MapScreen() {
  const currentSession = useStore((s) => s.currentSession);
  const sessionId = currentSession?.session_id ?? null;
  const { mapData, positions, tagPosition } = useMap(sessionId);
  const [tagLabel, setTagLabel] = useState<string>('');

  const handleTagPosition = useCallback(() => {
    const centerX = CANVAS_SIZE / 2;
    const centerY = CANVAS_SIZE / 2;
    const label = `P${positions.length + 1}`;
    tagPosition(centerX, centerY, label);
  }, [positions.length, tagPosition]);

  const isEmpty = positions.length < 3 && !mapData;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Signal Heatmap</Text>
        <View style={styles.counter}>
          <Text style={styles.counterText}>
            {positions.length} position{positions.length !== 1 ? 's' : ''} tagged
          </Text>
        </View>
      </View>

      <View style={styles.canvasContainer}>
        {isEmpty ? (
          <View style={styles.emptyState}>
            <Text style={styles.emptyIcon}>📡</Text>
            <Text style={styles.emptyText}>
              No data yet — tag at least 3 positions
            </Text>
          </View>
        ) : (
          <View style={styles.canvas}>
            {mapData && (
              <HeatmapOverlay
                heatmap={mapData.heatmap}
                gridBounds={mapData.grid_bounds}
                canvasSize={CANVAS_SIZE}
              />
            )}
            {positions.map((pos, index) => (
              <PositionMarker
                key={`pos-${index}`}
                x={pos.x}
                y={pos.y}
                label={pos.label}
              />
            ))}
          </View>
        )}
      </View>

      <TouchableOpacity
        style={styles.tagButton}
        onPress={handleTagPosition}
        activeOpacity={0.7}
      >
        <Text style={styles.tagButtonText}>Tag Position</Text>
      </TouchableOpacity>

      {currentSession && (
        <Text style={styles.sessionInfo}>
          Session: {currentSession.name}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0e17',
    padding: 16,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  title: {
    fontSize: 22,
    fontWeight: '700',
    color: '#e8eaed',
  },
  counter: {
    backgroundColor: '#131a2b',
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 12,
  },
  counterText: {
    fontSize: 13,
    color: '#00d4ff',
    fontWeight: '600',
  },
  canvasContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  canvas: {
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
    backgroundColor: '#131a2b',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#1e2a42',
    overflow: 'hidden',
    position: 'relative',
  },
  emptyState: {
    width: CANVAS_SIZE,
    height: CANVAS_SIZE,
    backgroundColor: '#131a2b',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#1e2a42',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 16,
  },
  emptyText: {
    fontSize: 15,
    color: '#6b7280',
    textAlign: 'center',
    lineHeight: 22,
  },
  tagButton: {
    backgroundColor: '#00d4ff',
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: 'center',
    marginTop: 16,
  },
  tagButtonText: {
    fontSize: 16,
    fontWeight: '700',
    color: '#0a0e17',
  },
  sessionInfo: {
    fontSize: 12,
    color: '#6b7280',
    textAlign: 'center',
    marginTop: 8,
  },
});
