import { levelForScale } from "../../client/src/scheduler/LevelSelector";
import type { SlideMetadata } from "../../client/src/types";

const metadata: SlideMetadata = {
  dimensions: [10000, 10000],
  tile_size: 512,
  levels: [
    { level: 0, downsample: 4, cols: 5, rows: 5 },
    { level: 1, downsample: 2, cols: 10, rows: 10 },
    { level: 2, downsample: 1, cols: 20, rows: 20 },
  ],
};

test("selects level for scale", () => {
  expect(levelForScale(metadata, 1.0)).toBe(2);
  expect(levelForScale(metadata, 0.5)).toBe(1);
  expect(levelForScale(metadata, 0.25)).toBe(0);
  expect(levelForScale(metadata, 0.6)).toBe(2);
  expect(levelForScale(metadata, 0.3)).toBe(1);
});
