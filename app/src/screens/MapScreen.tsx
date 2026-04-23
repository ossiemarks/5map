import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  TouchableOpacity,
  StyleSheet,
  Dimensions,
  TextInput,
  Alert,
} from 'react-native';
import Svg, { Circle, Line, Text as SvgText } from 'react-native-svg';
import { useStore } from '../store';
import { useMap } from '../hooks/useMap';
import HeatmapOverlay from '../components/HeatmapOverlay';

const { width: SCREEN_WIDTH } = Dimensions.get('window');
const CANVAS_PADDING = 32;
const CANVAS_SIZE = SCREEN_WIDTH - CANVAS_PADDING;

export function MapScreen() {
  const currentSession = useStore((s) => s.currentSession);
  const setRoomDimensions = useStore((s) => s.setRoomDimensions);
  const sessionId = currentSession?.session_id ?? null;
  const { mapData, positions, tagPosition, roomWidth, roomHeight } = useMap(sessionId);

  const [widthInput, setWidthInput] = useState(String(roomWidth));
  const [heightInput, setHeightInput] = useState(String(roomHeight));
  const [showSetup, setShowSetup] = useState(positions.length === 0);

  const canvasHeight = CANVAS_SIZE * (roomHeight / roomWidth);

  const handleSetDimensions = useCallback(() => {
    const w = parseFloat(widthInput);
    const h = parseFloat(heightInput);
    if (isNaN(w) || isNaN(h) || w <= 0 || h <= 0) {
      Alert.alert('Invalid dimensions', 'Enter positive numbers for width and height.');
      return;
    }
    setRoomDimensions(w, h);
    setShowSetup(false);
  }, [widthInput, heightInput]);

  const handleCanvasTap = useCallback(
    (evt: { nativeEvent: { locationX: number; locationY: number } }) => {
      if (!sessionId) return;
      const { locationX, locationY } = evt.nativeEvent;
      const x = (locationX / CANVAS_SIZE) * roomWidth;
      const y = (locationY / canvasHeight) * roomHeight;
      const label = `P${positions.length + 1}`;
      tagPosition(x, y, label);
    },
    [sessionId, roomWidth, roomHeight, canvasHeight, positions.length, tagPosition],
  );

  const toPixelX = (x: number) => (x / roomWidth) * CANVAS_SIZE;
  const toPixelY = (y: number) => (y / roomHeight) * canvasHeight;

  if (showSetup) {
    return (
      <View style={styles.container}>
        <Text style={styles.title}>Room Setup</Text>
        <Text style={styles.subtitle}>Enter room dimensions in metres</Text>
        <View style={styles.inputRow}>
          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>Width (m)</Text>
            <TextInput
              style={styles.input}
              value={widthInput}
              onChangeText={setWidthInput}
              keyboardType="decimal-pad"
              placeholderTextColor="#4a5568"
            />
          </View>
          <View style={styles.inputGroup}>
            <Text style={styles.inputLabel}>Height (m)</Text>
            <TextInput
              style={styles.input}
              value={heightInput}
              onChangeText={setHeightInput}
              keyboardType="decimal-pad"
              placeholderTextColor="#4a5568"
            />
          </View>
        </View>
        <TouchableOpacity style={styles.tagButton} onPress={handleSetDimensions}>
          <Text style={styles.tagButtonText}>Start Mapping</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Signal Heatmap</Text>
        <View style={styles.counter}>
          <Text style={styles.counterText}>
            {positions.length} tag{positions.length !== 1 ? 's' : ''} | {roomWidth}x{roomHeight}m
          </Text>
        </View>
      </View>

      <View style={styles.canvasContainer}>
        <TouchableOpacity
          activeOpacity={1}
          onPress={handleCanvasTap}
          style={[styles.canvas, { width: CANVAS_SIZE, height: canvasHeight }]}
        >
          {mapData && mapData.heatmap.length > 0 && (
            <HeatmapOverlay
              heatmap={mapData.heatmap}
              gridBounds={mapData.grid_bounds}
              width={CANVAS_SIZE}
              height={canvasHeight}
            />
          )}
          <Svg
            width={CANVAS_SIZE}
            height={canvasHeight}
            style={StyleSheet.absoluteFill}
          >
            {/* Grid lines */}
            {Array.from({ length: Math.floor(roomWidth) + 1 }).map((_, i) => (
              <Line
                key={`vg${i}`}
                x1={toPixelX(i)}
                y1={0}
                x2={toPixelX(i)}
                y2={canvasHeight}
                stroke="#1e2d4a"
                strokeWidth={0.5}
              />
            ))}
            {Array.from({ length: Math.floor(roomHeight) + 1 }).map((_, i) => (
              <Line
                key={`hg${i}`}
                x1={0}
                y1={toPixelY(i)}
                x2={CANVAS_SIZE}
                y2={toPixelY(i)}
                stroke="#1e2d4a"
                strokeWidth={0.5}
              />
            ))}

            {/* Wall segments from GP model */}
            {mapData?.walls?.map((wall, i) => (
              <Line
                key={`wall${i}`}
                x1={toPixelX(wall.start[0])}
                y1={toPixelY(wall.start[1])}
                x2={toPixelX(wall.end[0])}
                y2={toPixelY(wall.end[1])}
                stroke="#ff4757"
                strokeWidth={2 + wall.confidence * 2}
                opacity={0.5 + wall.confidence * 0.5}
                strokeLinecap="round"
              />
            ))}

            {/* Position markers */}
            {positions.map((pos, i) => (
              <React.Fragment key={`pos${i}`}>
                <Circle
                  cx={toPixelX(pos.x)}
                  cy={toPixelY(pos.y)}
                  r={8}
                  fill="#00d4ff"
                  opacity={0.8}
                />
                <SvgText
                  x={toPixelX(pos.x)}
                  y={toPixelY(pos.y) - 12}
                  fill="#e8eaed"
                  fontSize={10}
                  textAnchor="middle"
                >
                  {pos.label}
                </SvgText>
              </React.Fragment>
            ))}
          </Svg>
        </TouchableOpacity>
      </View>

      <Text style={styles.hint}>
        {positions.length < 3
          ? `Tap ${3 - positions.length} more position${3 - positions.length !== 1 ? 's' : ''} to generate heatmap`
          : 'Tap to add more positions for better accuracy'}
      </Text>

      {currentSession && (
        <Text style={styles.sessionInfo}>Session: {currentSession.name}</Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0e17', padding: 16 },
  header: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  title: { fontSize: 22, fontWeight: '700', color: '#e8eaed' },
  subtitle: { fontSize: 14, color: '#8892a4', marginBottom: 24 },
  counter: { backgroundColor: '#131a2b', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 12 },
  counterText: { fontSize: 13, color: '#00d4ff', fontWeight: '600' },
  canvasContainer: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  canvas: {
    backgroundColor: '#131a2b',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#1e2a42',
    overflow: 'hidden',
    position: 'relative',
  },
  hint: { fontSize: 12, color: '#6b7280', textAlign: 'center', marginTop: 12 },
  sessionInfo: { fontSize: 12, color: '#6b7280', textAlign: 'center', marginTop: 8 },
  inputRow: { flexDirection: 'row', gap: 16, marginBottom: 24 },
  inputGroup: { flex: 1 },
  inputLabel: { fontSize: 13, color: '#8892a4', marginBottom: 6 },
  input: {
    backgroundColor: '#131a2b',
    borderWidth: 1,
    borderColor: '#1e2d4a',
    borderRadius: 8,
    padding: 12,
    color: '#e8eaed',
    fontSize: 18,
    fontWeight: '700',
    textAlign: 'center',
  },
  tagButton: { backgroundColor: '#00d4ff', paddingVertical: 16, borderRadius: 12, alignItems: 'center' },
  tagButtonText: { fontSize: 16, fontWeight: '700', color: '#0a0e17' },
});
