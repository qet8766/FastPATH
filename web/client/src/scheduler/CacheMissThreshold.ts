export function cacheMissRatio(totalVisible: number, cachedVisible: number): number {
  if (totalVisible <= 0) {
    return 0;
  }
  const misses = Math.max(totalVisible - cachedVisible, 0);
  return misses / totalVisible;
}

export function shouldRenderAll(
  totalVisible: number,
  cachedVisible: number,
  threshold = 0.3
): boolean {
  return cacheMissRatio(totalVisible, cachedVisible) > threshold;
}
