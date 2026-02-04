import type { LevelInfo, SlideMetadata, TileCoord, Viewport } from "../types";
import { getLevel } from "../types";
import { levelForScale } from "./LevelSelector";

export function tilesInRect(
  tileSize: number,
  levelInfo: LevelInfo,
  x: number,
  y: number,
  width: number,
  height: number
): TileCoord[] {
  const levelTileSize = tileSize * levelInfo.downsample;

  const colStart = Math.max(Math.floor(x / levelTileSize), 0);
  const colEnd = Math.min(Math.ceil((x + width) / levelTileSize), levelInfo.cols);
  const rowStart = Math.max(Math.floor(y / levelTileSize), 0);
  const rowEnd = Math.min(Math.ceil((y + height) / levelTileSize), levelInfo.rows);

  if (colEnd <= colStart || rowEnd <= rowStart) {
    return [];
  }

  const tiles: TileCoord[] = [];
  for (let row = rowStart; row < rowEnd; row += 1) {
    for (let col = colStart; col < colEnd; col += 1) {
      tiles.push({ level: levelInfo.level, col, row });
    }
  }

  return tiles;
}

export function visibleTiles(metadata: SlideMetadata, viewport: Viewport): TileCoord[] {
  const level = levelForScale(metadata, viewport.scale);
  const levelInfo = getLevel(metadata, level);
  if (!levelInfo) {
    return [];
  }
  return tilesInRect(
    metadata.tile_size,
    levelInfo,
    viewport.x,
    viewport.y,
    viewport.width,
    viewport.height
  );
}
