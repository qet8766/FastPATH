export interface AtlasEntry {
  key: string;
  layer: number;
  lastUsed: number;
}

export interface AtlasAllocation {
  layer: number;
  evictedKey: string | null;
}

export class TileTextureAtlas {
  private maxLayers: number;
  private entries = new Map<string, AtlasEntry>();
  private freeLayers: number[] = [];
  private clock = 0;

  constructor(maxLayers = 512) {
    this.maxLayers = maxLayers;
    this.reset();
  }

  reset(): void {
    this.entries.clear();
    this.freeLayers = Array.from({ length: this.maxLayers }, (_, idx) => idx);
    this.clock = 0;
  }

  get size(): number {
    return this.entries.size;
  }

  get capacity(): number {
    return this.maxLayers;
  }

  touch(key: string): number | null {
    const entry = this.entries.get(key);
    if (!entry) {
      return null;
    }
    entry.lastUsed = this.nextTick();
    return entry.layer;
  }

  allocate(key: string): AtlasAllocation {
    const existing = this.entries.get(key);
    if (existing) {
      existing.lastUsed = this.nextTick();
      return { layer: existing.layer, evictedKey: null };
    }

    const layer = this.freeLayers.pop();
    if (layer !== undefined) {
      this.entries.set(key, {
        key,
        layer,
        lastUsed: this.nextTick(),
      });
      return { layer, evictedKey: null };
    }

    const lru = this.findLru();
    if (!lru) {
      throw new Error("Atlas is full but no entries found");
    }
    this.entries.delete(lru.key);
    this.entries.set(key, {
      key,
      layer: lru.layer,
      lastUsed: this.nextTick(),
    });
    return { layer: lru.layer, evictedKey: lru.key };
  }

  release(key: string): void {
    const entry = this.entries.get(key);
    if (!entry) {
      return;
    }
    this.entries.delete(key);
    this.freeLayers.push(entry.layer);
  }

  private findLru(): AtlasEntry | null {
    let best: AtlasEntry | null = null;
    for (const entry of this.entries.values()) {
      if (!best || entry.lastUsed < best.lastUsed) {
        best = entry;
      }
    }
    return best;
  }

  private nextTick(): number {
    this.clock += 1;
    return this.clock;
  }
}
