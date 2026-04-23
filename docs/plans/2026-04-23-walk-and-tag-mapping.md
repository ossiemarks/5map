# Walk-and-Tag Environment Mapping Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enable users to walk around a space, tap positions on a room grid in the mobile app, and see a live signal strength heatmap with detected walls build up as they tag.

**Architecture:** Dual-render approach — instant IDW interpolation on the phone for <100ms preview, server-side Sparse GP model (Lambda) for accurate heatmap + wall detection pushed via WebSocket. Each position tag snapshots current RSSI readings from all visible devices and bundles them with x/y coordinates.

**Tech Stack:** React Native (mobile), Python 3.12 Lambda (backend), DynamoDB streams, WebSocket API Gateway, sklearn GP model (existing `ml/models/env_mapper.py`).

---

### Task 1: Extend Position Type with RSSI Snapshot

**Files:**
- Modify: `app/src/types/index.ts:1-5`

**Step 1: Update the Position interface**

```typescript
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
```

**Step 2: Commit**

```bash
git add app/src/types/index.ts
git commit -m "feat(types): add RssiReading type and rssi_snapshot to Position"
```

---

### Task 2: Add Room Dimensions to Store

**Files:**
- Modify: `app/src/store/index.ts:4-9` (MapSlice interface)
- Modify: `app/src/store/index.ts:41-46` (map slice state)

**Step 1: Extend MapSlice interface**

Add to the `MapSlice` interface after `clearMap`:

```typescript
interface MapSlice {
  mapData: MapData | null;
  positions: Array<{ x: number; y: number; label: string }>;
  roomWidth: number;
  roomHeight: number;
  setMapData: (data: MapData) => void;
  addPosition: (pos: { x: number; y: number; label: string }) => void;
  setRoomDimensions: (width: number, height: number) => void;
  clearMap: () => void;
}
```

**Step 2: Add state and actions**

In the `create<AppState>` call, update the map slice:

```typescript
  // Map slice
  mapData: null,
  positions: [],
  roomWidth: 10,
  roomHeight: 8,
  setMapData: (data) => set({ mapData: data }),
  addPosition: (pos) => set((state) => ({ positions: [...state.positions, pos] })),
  setRoomDimensions: (width, height) => set({ roomWidth: width, roomHeight: height }),
  clearMap: () => set({ mapData: null, positions: [], roomWidth: 10, roomHeight: 8 }),
```

**Step 3: Commit**

```bash
git add app/src/store/index.ts
git commit -m "feat(store): add room dimensions to map slice"
```

---

### Task 3: Update API Client — tagPosition with RSSI Snapshot

**Files:**
- Modify: `app/src/services/api.ts:49-59`

**Step 1: Fetch devices and bundle with position**

Replace the existing `tagPosition` method:

```typescript
  tagPosition: async (sessionId: string, position: Position, token?: string) => {
    // Snapshot current RSSI readings
    const { data: devicesData } = await request<{ devices: Device[] }>(
      'GET',
      `/api/devices/${sessionId}`,
      undefined,
      token,
    );

    const rssiSnapshot = (devicesData?.devices || []).map((d) => ({
      mac: d.mac_address,
      rssi_dbm: d.rssi_dbm,
      channel: 0,
      bandwidth: '',
    }));

    return request<{ position_id: string }>('POST', '/api/positions', {
      session_id: sessionId,
      x: position.x,
      y: position.y,
      label: position.label,
      rssi_snapshot: rssiSnapshot,
    }, token);
  },
```

Add `Device` to the import at line 1:

```typescript
import type { Device, MapData, Position, PresenceEvent, Session } from '../types';
```

**Step 2: Commit**

```bash
git add app/src/services/api.ts
git commit -m "feat(api): snapshot RSSI readings when tagging position"
```

---

### Task 4: IDW Interpolation Utility

**Files:**
- Create: `app/src/utils/idw.ts`

**Step 1: Write the IDW function**

```typescript
interface TaggedPosition {
  x: number;
  y: number;
  rssiMean: number;
}

/**
 * Inverse Distance Weighting interpolation.
 * Generates a gridSize x gridSize heatmap from sparse position-tagged RSSI data.
 */
export function idwInterpolate(
  positions: TaggedPosition[],
  gridSize: number,
  bounds: { xMin: number; xMax: number; yMin: number; yMax: number },
  power: number = 2,
): number[][] {
  if (positions.length === 0) return [];

  const grid: number[][] = [];
  const xStep = (bounds.xMax - bounds.xMin) / (gridSize - 1);
  const yStep = (bounds.yMax - bounds.yMin) / (gridSize - 1);

  for (let row = 0; row < gridSize; row++) {
    const gridRow: number[] = [];
    const py = bounds.yMin + row * yStep;

    for (let col = 0; col < gridSize; col++) {
      const px = bounds.xMin + col * xStep;

      let numerator = 0;
      let denominator = 0;
      let exactMatch = false;

      for (const pos of positions) {
        const dx = px - pos.x;
        const dy = py - pos.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < 0.001) {
          gridRow.push(pos.rssiMean);
          exactMatch = true;
          break;
        }

        const weight = 1 / Math.pow(dist, power);
        numerator += weight * pos.rssiMean;
        denominator += weight;
      }

      if (!exactMatch) {
        gridRow.push(denominator > 0 ? numerator / denominator : -100);
      }
    }
    grid.push(gridRow);
  }

  return grid;
}
```

**Step 2: Commit**

```bash
git add app/src/utils/idw.ts
git commit -m "feat(utils): add IDW interpolation for instant heatmap preview"
```

---

### Task 5: Rewrite MapScreen with Tappable Grid + Room Dimensions

**Files:**
- Modify: `app/src/screens/MapScreen.tsx` (full rewrite)
- Modify: `app/src/hooks/useMap.ts`

**Step 1: Update useMap hook**

Replace `app/src/hooks/useMap.ts` entirely:

```typescript
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
    (allPositions: Array<Position & { rssi_snapshot?: Array<{ rssi_dbm: number }> }>) => {
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

      // Fire API call (includes RSSI snapshot)
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
```

**Step 2: Rewrite MapScreen with tappable grid and room dimension inputs**

Replace `app/src/screens/MapScreen.tsx` entirely:

```typescript
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
import Svg, { Circle, Line, Rect, Text as SvgText } from 'react-native-svg';
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
      // Convert pixel tap to room coordinates
      const x = (locationX / CANVAS_SIZE) * roomWidth;
      const y = (locationY / canvasHeight) * roomHeight;
      const label = `P${positions.length + 1}`;
      tagPosition(x, y, label);
    },
    [sessionId, roomWidth, roomHeight, canvasHeight, positions.length, tagPosition],
  );

  // Convert room coords to canvas pixels for markers
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
```

**Step 3: Commit**

```bash
git add app/src/screens/MapScreen.tsx app/src/hooks/useMap.ts
git commit -m "feat(map): tappable room grid with IDW preview and room dimensions"
```

---

### Task 6: Add Wall Rendering to HeatmapOverlay

**Files:**
- Modify: `app/src/components/HeatmapOverlay.tsx`

**Step 1: Update props interface**

The wall rendering is handled in MapScreen's SVG layer (Task 5), so HeatmapOverlay only needs the `width`/`height` prop fix. The current component expects `canvasSize` but we need `width` and `height` separately since rooms aren't square.

The component already accepts `width` and `height` props (line 17-18). The issue is `MapScreen` previously passed `canvasSize` — Task 5 already passes `width` and `height` correctly. No changes needed.

**Step 2: Commit** — skip, no changes.

---

### Task 7: Extend API — positions endpoint accepts rssi_snapshot

**Files:**
- Modify: `backend/handlers/api_handler.py:163-192`

**Step 1: Update create_position to store rssi_snapshot**

Replace the `create_position` function:

```python
def create_position(event: dict[str, Any]) -> dict[str, Any]:
    """POST /api/positions - Tag a position with RSSI snapshot."""
    body = _parse_body(event)

    session_id = body.get("session_id")
    x = body.get("x")
    y = body.get("y")
    label = body.get("label")
    rssi_snapshot = body.get("rssi_snapshot", [])

    if not session_id:
        return _response(400, {"error": "session_id is required"})
    if x is None or y is None:
        return _response(400, {"error": "x and y coordinates are required"})

    position_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    # Build RSSI values list for the env mapper
    rssi_values = [Decimal(str(r.get("rssi_dbm", -100))) for r in rssi_snapshot if r.get("rssi_dbm")]

    item = {
        "session_id": session_id,
        "timestamp": timestamp,
        "position_id": position_id,
        "x": Decimal(str(x)),
        "y": Decimal(str(y)),
        "label": label or "",
        "rssi_snapshot": json.dumps(rssi_snapshot),
        "rssi_values": json.dumps([float(v) for v in rssi_values]),
        "device_count": len(rssi_snapshot),
    }

    table = dynamodb.Table(MAPS_TABLE)
    try:
        table.put_item(Item=item)

        # Check if we have enough positions to generate a map
        result = table.query(KeyConditionExpression=Key("session_id").eq(session_id))
        positions = result.get("Items", [])
        position_count = len([p for p in positions if "x" in p and "rssi_values" in p])

        response_body = {"position_id": position_id, "position_count": position_count}

        if position_count >= 3:
            # Trigger map generation inline (fast enough for <50 points)
            _generate_and_store_map(session_id, positions)
            response_body["map_generated"] = True

        return _response(201, response_body)
    except Exception as e:
        return _response(500, {"error": f"Failed to create position: {str(e)}"})
```

**Step 2: Add the map generation function**

Add this function above `handler()` in `api_handler.py`:

```python
import logging

logger = logging.getLogger(__name__)


def _generate_and_store_map(session_id: str, positions: list[dict]) -> None:
    """Run EnvironmentMapper and store result + push via WebSocket."""
    try:
        from ml.models.env_mapper import EnvironmentMapper
    except ImportError:
        logger.warning("env_mapper not available, skipping map generation")
        return

    # Build position data for the mapper
    pos_data = []
    for p in positions:
        if "x" not in p or "rssi_values" not in p:
            continue
        try:
            rssi_vals = json.loads(p["rssi_values"]) if isinstance(p["rssi_values"], str) else p["rssi_values"]
            pos_data.append({
                "x": float(p["x"]),
                "y": float(p["y"]),
                "rssi_values": [float(v) for v in rssi_vals],
            })
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    if len(pos_data) < 3:
        return

    try:
        mapper = EnvironmentMapper(grid_size=30)
        mapper.fit(pos_data)
        result = mapper.predict_heatmap()
    except Exception as e:
        logger.error("EnvironmentMapper failed: %s", e)
        return

    # Store the map result
    table = dynamodb.Table(MAPS_TABLE)
    timestamp = datetime.now(timezone.utc).isoformat()
    map_item = {
        "session_id": session_id,
        "timestamp": f"map#{timestamp}",
        "type": "heatmap",
        "heatmap": json.dumps(result["heatmap"]),
        "walls": json.dumps(result["walls"]),
        "grid_bounds": json.dumps(result["grid_bounds"]),
        "confidence": Decimal(str(round(result["confidence"], 4))),
        "position_count": len(pos_data),
    }
    try:
        table.put_item(Item=map_item)
    except Exception as e:
        logger.error("Failed to store map: %s", e)
        return

    # Push map_update via WebSocket
    _push_ws_map_update(session_id, result, timestamp)


def _push_ws_map_update(session_id: str, result: dict, timestamp: str) -> None:
    """Push map update to all WebSocket connections subscribed to this session."""
    ws_endpoint = os.environ.get("WEBSOCKET_API_ENDPOINT", "")
    if not ws_endpoint:
        return

    connections_table = dynamodb.Table(
        os.environ.get("DYNAMODB_CONNECTIONS_TABLE", "connections")
    )

    try:
        resp = connections_table.scan(
            FilterExpression=Key("session_id").eq(session_id)
        )
    except Exception:
        return

    if not resp.get("Items"):
        return

    # Clean endpoint for ApiGatewayManagementApi
    endpoint = ws_endpoint.replace("wss://", "https://").rstrip("/")
    client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)

    payload = json.dumps({
        "type": "map_update",
        "session_id": session_id,
        "data": {
            "heatmap": result["heatmap"],
            "walls": result["walls"],
            "grid_bounds": result["grid_bounds"],
            "confidence": result["confidence"],
            "updated_at": timestamp,
        },
    })

    for conn in resp["Items"]:
        try:
            client.post_to_connection(
                ConnectionId=conn["connection_id"],
                Data=payload.encode("utf-8"),
            )
        except client.exceptions.GoneException:
            connections_table.delete_item(Key={"connection_id": conn["connection_id"]})
        except Exception:
            pass
```

**Step 3: Add env vars to api_handler Lambda**

In `api_handler.py` `handler()`, no routing changes needed — `POST /api/positions` already routes to `create_position`.

**Step 4: Commit**

```bash
git add backend/handlers/api_handler.py
git commit -m "feat(api): positions endpoint stores RSSI snapshot and triggers map generation"
```

---

### Task 8: Terraform — Add env vars and Lambda layer for sklearn

**Files:**
- Modify: `terraform/modules/lambda/main.tf:167-185`

**Step 1: Add WEBSOCKET_API_ENDPOINT and CONNECTIONS_TABLE to api_handler Lambda env vars**

Update the api_handler Lambda environment block:

```hcl
  environment {
    variables = {
      DYNAMODB_MAPS_TABLE        = var.dynamodb_maps_table
      DYNAMODB_DEVICE_TABLE      = var.dynamodb_device_table
      DYNAMODB_PRESENCE_TABLE    = var.dynamodb_presence_table
      DYNAMODB_SESSIONS_TABLE    = var.dynamodb_sessions_table
      DYNAMODB_CONNECTIONS_TABLE = var.dynamodb_connections_table
      WEBSOCKET_API_ENDPOINT     = var.websocket_api_endpoint
    }
  }
```

**Step 2: Increase api_handler memory and timeout for GP model**

```hcl
  timeout     = 60
  memory_size = 512
```

**Step 3: Commit**

```bash
git add terraform/modules/lambda/main.tf
git commit -m "feat(terraform): add WS endpoint + connections table env to api handler, bump memory for GP model"
```

---

### Task 9: Package ML Model for Lambda

**Files:**
- Create: `backend/build_api_layer.sh`

**Step 1: Create build script for Lambda deployment package**

The api_handler Lambda needs `ml/models/env_mapper.py` and its dependencies (numpy, scikit-learn) bundled. Create a build script:

```bash
#!/bin/bash
# Build Lambda deployment package with ML dependencies
set -e

BUILD_DIR="$(dirname "$0")/../terraform/.build"
mkdir -p "$BUILD_DIR"

PACKAGE_DIR=$(mktemp -d)
trap "rm -rf $PACKAGE_DIR" EXIT

# Install sklearn + numpy into package
pip install --target "$PACKAGE_DIR" numpy scikit-learn -q

# Copy handler and ML model
cp backend/handlers/api_handler.py "$PACKAGE_DIR/"
cp -r ml "$PACKAGE_DIR/"

# Create zip
cd "$PACKAGE_DIR"
zip -r "$BUILD_DIR/api_handler_ml.zip" . -q

echo "Built: $BUILD_DIR/api_handler_ml.zip"
```

**Step 2: Commit**

```bash
chmod +x backend/build_api_layer.sh
git add backend/build_api_layer.sh
git commit -m "feat(build): add Lambda packaging script for API handler with ML deps"
```

---

### Task 10: Integration Test — End-to-End Position Tagging

**Files:**
- Create: `tests/integration/test_mapping_flow.py`

**Step 1: Write integration test**

```python
"""Integration test for walk-and-tag mapping flow."""

import json
import pytest


def test_position_with_rssi_snapshot(api_client, session_id):
    """Tagging a position includes RSSI snapshot and returns position_id."""
    response = api_client.post("/api/positions", json={
        "session_id": session_id,
        "x": 2.5,
        "y": 3.0,
        "label": "P1",
        "rssi_snapshot": [
            {"mac": "aa:bb:cc:dd:ee:01", "rssi_dbm": -45, "channel": 6, "bandwidth": "2.4GHz"},
            {"mac": "aa:bb:cc:dd:ee:02", "rssi_dbm": -62, "channel": 36, "bandwidth": "5GHz"},
        ],
    })
    assert response.status_code == 201
    body = response.json()
    assert "position_id" in body


def test_map_generation_after_three_positions(api_client, session_id):
    """After 3 position tags, map_generated should be True."""
    positions = [
        {"x": 0, "y": 0, "rssi": [-45, -62, -71]},
        {"x": 5, "y": 0, "rssi": [-55, -48, -80]},
        {"x": 2.5, "y": 4, "rssi": [-60, -55, -65]},
    ]
    for i, p in enumerate(positions):
        response = api_client.post("/api/positions", json={
            "session_id": session_id,
            "x": p["x"],
            "y": p["y"],
            "label": f"P{i+1}",
            "rssi_snapshot": [
                {"mac": f"aa:bb:cc:dd:ee:0{j}", "rssi_dbm": r, "channel": 6, "bandwidth": "2.4GHz"}
                for j, r in enumerate(p["rssi"])
            ],
        })
        assert response.status_code == 201

    body = response.json()
    assert body.get("map_generated") is True
    assert body["position_count"] == 3


def test_map_retrieval_has_heatmap(api_client, session_id):
    """After map generation, GET /api/map returns heatmap data."""
    # Tag 3 positions first (same as above)
    for i, (x, y) in enumerate([(0, 0), (5, 0), (2.5, 4)]):
        api_client.post("/api/positions", json={
            "session_id": session_id,
            "x": x,
            "y": y,
            "label": f"P{i+1}",
            "rssi_snapshot": [
                {"mac": "aa:bb:cc:dd:ee:01", "rssi_dbm": -50 - i * 10, "channel": 6, "bandwidth": "2.4GHz"},
            ],
        })

    response = api_client.get(f"/api/map/{session_id}")
    assert response.status_code == 200
    body = response.json()
    items = body.get("items", [])
    map_items = [item for item in items if item.get("type") == "heatmap"]
    assert len(map_items) >= 1

    heatmap = json.loads(map_items[0]["heatmap"])
    assert len(heatmap) == 30  # grid_size
    assert len(heatmap[0]) == 30
```

**Step 2: Commit**

```bash
git add tests/integration/test_mapping_flow.py
git commit -m "test: integration tests for walk-and-tag mapping flow"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | RssiReading type + Position.rssi_snapshot | `app/src/types/index.ts` |
| 2 | Room dimensions in store | `app/src/store/index.ts` |
| 3 | API client snapshots RSSI on tag | `app/src/services/api.ts` |
| 4 | IDW interpolation utility | `app/src/utils/idw.ts` (new) |
| 5 | MapScreen rewrite — tappable grid + room setup | `app/src/screens/MapScreen.tsx`, `app/src/hooks/useMap.ts` |
| 6 | HeatmapOverlay wall rendering | No changes needed (handled in MapScreen SVG) |
| 7 | API positions endpoint + map generation + WS push | `backend/handlers/api_handler.py` |
| 8 | Terraform env vars + memory bump | `terraform/modules/lambda/main.tf` |
| 9 | Lambda build script for ML deps | `backend/build_api_layer.sh` (new) |
| 10 | Integration tests | `tests/integration/test_mapping_flow.py` (new) |
