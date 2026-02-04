import { tilesInRect } from "../../client/src/scheduler/ViewportCalculator";

const levelInfo = { level: 2, downsample: 1, cols: 4, rows: 3 };

test("tiles in rect within bounds", () => {
  const tiles = tilesInRect(512, levelInfo, 0, 0, 1024, 1024);
  expect(tiles.length).toBeGreaterThan(0);
  expect(tiles.every((tile) => tile.level === 2)).toBe(true);
});

test("tiles in rect outside bounds returns empty", () => {
  const tiles = tilesInRect(512, levelInfo, 99999, 99999, 512, 512);
  expect(tiles.length).toBe(0);
});
