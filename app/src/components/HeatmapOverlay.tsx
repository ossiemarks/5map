import React, { useMemo } from 'react';
import { View, StyleSheet } from 'react-native';
import Svg, { Rect } from 'react-native-svg';

interface GridBounds {
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
}

interface HeatmapOverlayProps {
  heatmap: number[][];
  gridBounds: GridBounds;
  width: number;
  height: number;
}

function signalToColor(dbm: number): string {
  if (dbm >= -50) return '#2ed573';
  if (dbm >= -70) return '#ffa502';
  return '#ff4757';
}

function signalToOpacity(dbm: number): number {
  const clamped = Math.max(-100, Math.min(-30, dbm));
  return (clamped + 100) / 70;
}

function bilinearInterpolate(
  grid: number[][],
  targetRows: number,
  targetCols: number
): number[][] {
  const srcRows = grid.length;
  const srcCols = grid[0]?.length ?? 0;

  if (srcRows === 0 || srcCols === 0) return [];

  const result: number[][] = [];

  for (let i = 0; i < targetRows; i++) {
    const row: number[] = [];
    const srcY = (i / (targetRows - 1)) * (srcRows - 1);
    const y0 = Math.floor(srcY);
    const y1 = Math.min(y0 + 1, srcRows - 1);
    const fy = srcY - y0;

    for (let j = 0; j < targetCols; j++) {
      const srcX = (j / (targetCols - 1)) * (srcCols - 1);
      const x0 = Math.floor(srcX);
      const x1 = Math.min(x0 + 1, srcCols - 1);
      const fx = srcX - x0;

      const topLeft = grid[y0][x0];
      const topRight = grid[y0][x1];
      const bottomLeft = grid[y1][x0];
      const bottomRight = grid[y1][x1];

      const top = topLeft + (topRight - topLeft) * fx;
      const bottom = bottomLeft + (bottomRight - bottomLeft) * fx;
      const value = top + (bottom - top) * fy;

      row.push(value);
    }
    result.push(row);
  }

  return result;
}

const HeatmapOverlay: React.FC<HeatmapOverlayProps> = ({
  heatmap,
  gridBounds,
  width,
  height,
}) => {
  const interpolatedGrid = useMemo(() => {
    if (heatmap.length === 0) return [];
    const targetRows = Math.min(heatmap.length * 2, 40);
    const targetCols = Math.min((heatmap[0]?.length ?? 0) * 2, 40);
    return bilinearInterpolate(heatmap, targetRows, targetCols);
  }, [heatmap]);

  const rects = useMemo(() => {
    if (interpolatedGrid.length === 0) return [];

    const rows = interpolatedGrid.length;
    const cols = interpolatedGrid[0]?.length ?? 0;
    const cellWidth = width / cols;
    const cellHeight = height / rows;

    const elements: React.ReactElement[] = [];

    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) {
        const dbm = interpolatedGrid[row][col];
        const color = signalToColor(dbm);
        const opacity = signalToOpacity(dbm);

        elements.push(
          <Rect
            key={`${row}-${col}`}
            x={col * cellWidth}
            y={row * cellHeight}
            width={cellWidth}
            height={cellHeight}
            fill={color}
            opacity={opacity}
          />
        );
      }
    }

    return elements;
  }, [interpolatedGrid, width, height]);

  if (heatmap.length === 0) return null;

  return (
    <View style={styles.container}>
      <Svg width={width} height={height}>
        {rects}
      </Svg>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    top: 0,
    left: 0,
  },
});

export default HeatmapOverlay;
