export function cacheMissRatio(totalVisible: number, cachedVisible: number): number {
  if (totalVisible <= 0) {
    return 0;
  }
  const misses = Math.max(totalVisible - cachedVisible, 0);
  return misses / totalVisible;
}
