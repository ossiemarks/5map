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
