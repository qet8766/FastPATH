import type { SlideMetadata } from "../types";

export function levelForScale(metadata: SlideMetadata, scale: number): number {
  if (!metadata.levels.length) {
    return 0;
  }
  const safeScale = scale <= 0 ? 1 : scale;
  const targetDownsample = 1 / safeScale;
  let candidate: { level: number; downsample: number } | null = null;

  for (const level of metadata.levels) {
    if (level.downsample <= targetDownsample) {
      if (!candidate || level.downsample > candidate.downsample) {
        candidate = level;
      }
    }
  }

  if (candidate) {
    return candidate.level;
  }

  const best = metadata.levels.reduce((min, level) =>
    level.downsample < min.downsample ? level : min
  );
  return best.level;
}
