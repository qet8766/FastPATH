export class TileCache<T> {
  private maxEntries: number;
  private map = new Map<string, T>();

  constructor(maxEntries = 500) {
    this.maxEntries = maxEntries;
  }

  get(key: string): T | undefined {
    const value = this.map.get(key);
    if (value !== undefined) {
      this.map.delete(key);
      this.map.set(key, value);
    }
    return value;
  }

  set(key: string, value: T): void {
    if (this.map.has(key)) {
      this.map.delete(key);
    }
    this.map.set(key, value);
    if (this.map.size > this.maxEntries) {
      const oldest = this.map.keys().next().value as string | undefined;
      if (oldest) {
        this.map.delete(oldest);
      }
    }
  }

  clear(): void {
    this.map.clear();
  }
}
