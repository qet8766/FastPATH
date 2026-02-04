import type { SlideMetadata, TileCoord } from "../types";
import { getLevel } from "../types";

export function resolveFallbackLevel(
  currentLevel: number,
  previousLevel: number | null,
  metadata: SlideMetadata
): number | null {
  if (previousLevel === null) {
    return null;
  }
  const info = getLevel(metadata, previousLevel);
  if (!info) {
    return null;
  }
  return previousLevel === currentLevel ? null : previousLevel;
}

export function fallbackTileFor(
  coord: TileCoord,
  fallbackLevel: number,
  metadata: SlideMetadata
): TileCoord | null {
  const target = getLevel(metadata, coord.level);
  const fallback = getLevel(metadata, fallbackLevel);
  if (!target || !fallback) {
    return null;
  }

  const targetTileSize = metadata.tile_size * target.downsample;
  const fallbackTileSize = metadata.tile_size * fallback.downsample;

  const x = coord.col * targetTileSize;
  const y = coord.row * targetTileSize;

  const fallbackCol = Math.floor(x / fallbackTileSize);
  const fallbackRow = Math.floor(y / fallbackTileSize);

  if (fallbackCol < 0 || fallbackRow < 0) {
    return null;
  }

  if (fallbackCol >= fallback.cols || fallbackRow >= fallback.rows) {
    return null;
  }

  return { level: fallback.level, col: fallbackCol, row: fallbackRow };
}
