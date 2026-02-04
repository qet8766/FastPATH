import { PrefetchCalculator } from "../../client/src/scheduler/PrefetchCalculator";
import type { SlideMetadata, Viewport } from "../../client/src/types";

const metadata: SlideMetadata = {
  dimensions: [10000, 10000],
  tile_size: 512,
  levels: [
    { level: 0, downsample: 4, cols: 5, rows: 5 },
    { level: 1, downsample: 2, cols: 10, rows: 10 },
    { level: 2, downsample: 1, cols: 20, rows: 20 },
  ],
};

const viewport: Viewport = {
  x: 0,
  y: 0,
  width: 1024,
  height: 1024,
  scale: 1,
  velocityX: 100,
  velocityY: 0,
};

test("prefetch tiles respects cache", () => {
  const calc = new PrefetchCalculator({ prefetchLevels: false, tilesAhead: 2, tilesAround: 1, minVelocity: 50 });
  const tiles = calc.prefetchTiles(metadata, viewport, () => true);
  expect(tiles.length).toBe(0);
});

test("prefetch tiles returns visible tiles", () => {
  const calc = new PrefetchCalculator({ prefetchLevels: false, tilesAhead: 2, tilesAround: 1, minVelocity: 50 });
  const tiles = calc.prefetchTiles(metadata, viewport, () => false);
  expect(tiles.length).toBeGreaterThan(0);
});
