export interface TileCoord {
  level: number;
  col: number;
  row: number;
}

export interface LevelInfo {
  level: number;
  downsample: number;
  cols: number;
  rows: number;
}

export interface SlideMetadata {
  dimensions: [number, number];
  tile_size: number;
  levels: LevelInfo[];
  target_mpp?: number;
  target_magnification?: number;
  background_color?: [number, number, number];
  tile_format?: string;
}

export interface SlideSummary {
  hash: string;
  name: string;
  dimensions: [number, number];
  levels: LevelInfo[];
  mpp: number | null;
  thumbnailUrl: string;
}

export interface Viewport {
  x: number;
  y: number;
  width: number;
  height: number;
  scale: number;
  velocityX: number;
  velocityY: number;
}

export function getLevel(metadata: SlideMetadata, level: number): LevelInfo | undefined {
  return metadata.levels.find((info) => info.level === level);
}

export function numLevels(metadata: SlideMetadata): number {
  return metadata.levels.length;
}
