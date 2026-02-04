import type { SlideMetadata, TileCoord, Viewport } from "../types";
import { getLevel, numLevels } from "../types";
import { levelForScale } from "./LevelSelector";
import { tilesInRect, visibleTiles } from "./ViewportCalculator";

export interface PrefetchConfig {
  tilesAhead: number;
  tilesAround: number;
  prefetchLevels: boolean;
  minVelocity: number;
}

export const DEFAULT_PREFETCH_CONFIG: PrefetchConfig = {
  tilesAhead: 2,
  tilesAround: 1,
  prefetchLevels: true,
  minVelocity: 50,
};

export class PrefetchCalculator {
  private config: PrefetchConfig;

  constructor(config: PrefetchConfig = DEFAULT_PREFETCH_CONFIG) {
    this.config = { ...DEFAULT_PREFETCH_CONFIG, ...config };
  }

  levelForScale(metadata: SlideMetadata, scale: number): number {
    return levelForScale(metadata, scale);
  }

  visibleTiles(metadata: SlideMetadata, viewport: Viewport): TileCoord[] {
    return visibleTiles(metadata, viewport);
  }

  prefetchTiles(
    metadata: SlideMetadata,
    viewport: Viewport,
    cached: (coord: TileCoord) => boolean
  ): TileCoord[] {
    const tiles: TileCoord[] = [];
    const seen = new Set<string>();
    const level = this.levelForScale(metadata, viewport.scale);

    const pushUnique = (coords: TileCoord[]) => {
      for (const coord of coords) {
        const key = `${coord.level}:${coord.col}:${coord.row}`;
        if (!seen.has(key) && !cached(coord)) {
          seen.add(key);
          tiles.push(coord);
        }
      }
    };

    const currentLevel = getLevel(metadata, level);
    if (!currentLevel) {
      return tiles;
    }

    const visible = this.visibleTiles(metadata, viewport);
    const [extX, extY, extW, extH] = this.extendedViewport(viewport, metadata.tile_size);
    const extended = tilesInRect(
      metadata.tile_size,
      currentLevel,
      extX,
      extY,
      extW,
      extH
    );

    pushUnique(visible);
    pushUnique(extended);

    if (this.config.prefetchLevels) {
      if (level + 1 < numLevels(metadata)) {
        const upLevel = getLevel(metadata, level + 1);
        if (upLevel) {
          const upTiles = tilesInRect(
            metadata.tile_size,
            upLevel,
            viewport.x,
            viewport.y,
            viewport.width,
            viewport.height
          );
          pushUnique(upTiles);
        }
      }

      if (level > 0) {
        const downLevel = getLevel(metadata, level - 1);
        if (downLevel) {
          const centerX = viewport.x + viewport.width / 2;
          const centerY = viewport.y + viewport.height / 2;
          const smallWidth = viewport.width / 4;
          const smallHeight = viewport.height / 4;
          const downTiles = tilesInRect(
            metadata.tile_size,
            downLevel,
            centerX - smallWidth / 2,
            centerY - smallHeight / 2,
            smallWidth,
            smallHeight
          );
          pushUnique(downTiles);
        }
      }
    }

    return tiles;
  }

  private extendedViewport(viewport: Viewport, tileSize: number): [number, number, number, number] {
    const baseExt = tileSize * this.config.tilesAround;

    let velExtX = 0;
    let velExtY = 0;

    if (
      Math.abs(viewport.velocityX) > this.config.minVelocity ||
      Math.abs(viewport.velocityY) > this.config.minVelocity
    ) {
      if (Math.abs(viewport.velocityX) > this.config.minVelocity) {
        velExtX = Math.sign(viewport.velocityX) * tileSize * this.config.tilesAhead;
      }
      if (Math.abs(viewport.velocityY) > this.config.minVelocity) {
        velExtY = Math.sign(viewport.velocityY) * tileSize * this.config.tilesAhead;
      }
    }

    const x = viewport.x - baseExt + Math.min(velExtX, 0);
    const y = viewport.y - baseExt + Math.min(velExtY, 0);
    const w = viewport.width + baseExt * 2 + Math.abs(velExtX);
    const h = viewport.height + baseExt * 2 + Math.abs(velExtY);

    return [x, y, w, h];
  }
}
