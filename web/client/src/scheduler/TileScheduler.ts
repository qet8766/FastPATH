import type { LevelInfo, SlideMetadata, TileCoord, Viewport } from "../types";
import { getLevel } from "../types";
import { PrefetchCalculator } from "./PrefetchCalculator";
import { visibleTiles } from "./ViewportCalculator";
import { TileTextureAtlas } from "../renderer/TileTextureAtlas";
import type { TileInstance } from "../renderer/WebGPURenderer";
import { WebGPURenderer } from "../renderer/WebGPURenderer";
import { TileCache } from "../cache/TileCache";
import { TileNetwork } from "../network/TileNetwork";
import { TileFetchQueue } from "../network/TileFetchQueue";
import { DecodeWorkerPool, decodeImageFallback } from "../workers/DecodePool";

export interface TileSchedulerOptions {
  prefetchBudget?: number;
  maxInFlight?: number;
  decodedCacheSize?: number;
  decodeWorkers?: number;
}

interface PendingRequest {
  coord: TileCoord;
  key: string;
  generation: number;
}

export class TileScheduler {
  private metadata: SlideMetadata | null = null;
  private generation = 0;
  private prefetch: PrefetchCalculator;
  private prefetchBudget: number;
  private maxInFlight: number;
  private decodedCache: TileCache<ImageBitmap>;
  private renderer: WebGPURenderer | null = null;
  private atlas: TileTextureAtlas | null = null;
  private network: TileNetwork | null = null;
  private fetchQueue: TileFetchQueue | null = null;
  private decodePool: DecodeWorkerPool | null = null;
  private viewport: Viewport | null = null;
  private pending: PendingRequest[] = [];
  private pendingKeys = new Set<string>();
  private inFlight = new Map<string, number>();
  private abortHandles = new Map<string, () => void>();
  private renderPending = false;
  private needsInitialRender = true;
  private previousLevel: number | null = null;
  private fallbackActive = false;
  private currentInstances: TileInstance[] = [];
  private fallbackInstances: TileInstance[] = [];

  constructor(options: TileSchedulerOptions = {}) {
    this.prefetch = new PrefetchCalculator();
    this.prefetchBudget = options.prefetchBudget ?? 32;
    this.maxInFlight = options.maxInFlight ?? 48;
    this.decodedCache = new TileCache<ImageBitmap>(options.decodedCacheSize ?? 256);

    if (typeof Worker !== "undefined") {
      try {
        this.decodePool = new DecodeWorkerPool(options.decodeWorkers);
      } catch (error) {
        this.decodePool = null;
      }
    }
  }

  attachRenderer(renderer: WebGPURenderer, atlas: TileTextureAtlas): void {
    this.renderer = renderer;
    this.atlas = atlas;
    if (this.metadata) {
      renderer.configureAtlas(this.metadata.tile_size, atlas.capacity);
    }
  }

  attachNetwork(network: TileNetwork, fetchQueue?: TileFetchQueue): void {
    this.network = network;
    this.fetchQueue = fetchQueue ?? null;
  }

  open(metadata: SlideMetadata): void {
    this.metadata = metadata;
    this.generation += 1;
    this.needsInitialRender = true;
    this.previousLevel = null;
    this.fallbackActive = false;
    this.currentInstances = [];
    this.fallbackInstances = [];
    this.pending = [];
    this.pendingKeys.clear();
    this.inFlight.clear();
    this.abortHandles.clear();
    this.fetchQueue?.cancelAll();
    this.decodedCache.clear();
    this.atlas?.reset();

    if (this.renderer && this.atlas) {
      this.renderer.configureAtlas(metadata.tile_size, this.atlas.capacity);
    }
  }

  async bootstrapLevel(level: number): Promise<void> {
    if (!this.metadata || !this.network || !this.renderer || !this.atlas) {
      return;
    }
    const levelInfo = getLevel(this.metadata, level);
    if (!levelInfo) {
      return;
    }
    const gen = this.generation;
    const coords: TileCoord[] = [];
    for (let row = 0; row < levelInfo.rows; row++) {
      for (let col = 0; col < levelInfo.cols; col++) {
        coords.push({ level, col, row });
      }
    }

    const results = await Promise.all(
      coords.map(async (coord) => {
        try {
          const buffer = await this.network!.fetchTile(coord);
          if (!buffer || gen !== this.generation) return null;
          const decoded = this.decodePool
            ? await this.decodePool.decode(buffer)
            : await decodeImageFallback(buffer);
          if (gen !== this.generation) {
            decoded.bitmap.close();
            return null;
          }
          return { coord, bitmap: decoded.bitmap };
        } catch {
          return null;
        }
      })
    );

    if (gen !== this.generation || !this.renderer || !this.atlas) {
      for (const r of results) {
        if (r) r.bitmap.close();
      }
      return;
    }

    const instances: TileInstance[] = [];
    for (const r of results) {
      if (!r) continue;
      const key = tileKey(r.coord);
      const allocation = this.atlas.allocate(key);
      await this.renderer.uploadTile(allocation.layer, r.bitmap);
      this.decodedCache.set(key, r.bitmap);
      const instance = this.buildInstance(r.coord, allocation.layer);
      if (instance) {
        instances.push(instance);
      }
    }

    if (gen === this.generation) {
      this.fallbackInstances = instances;
      this.fallbackActive = instances.length > 0;
      this.scheduleRender();
    }
  }

  close(): void {
    this.metadata = null;
    this.generation += 1;
    this.viewport = null;
    this.pending = [];
    this.pendingKeys.clear();
    this.inFlight.clear();
    this.abortHandles.clear();
    this.fetchQueue?.cancelAll();
    this.decodedCache.clear();
    this.atlas?.reset();
    if (this.renderer) {
      this.renderer.setTiles([]);
      this.renderer.render();
    }
  }

  updateViewport(viewport: Viewport): void {
    this.viewport = viewport;
    this.scheduleRender();
  }

  /**
   * Cancel pending and in-flight requests for tiles not in the wanted set.
   * This prevents stale requests from consuming bandwidth when viewport changes.
   */
  private cancelStaleRequests(wantedKeys: Set<string>): void {
    // Cancel in-flight requests not in current viewport
    for (const [key, abort] of this.abortHandles) {
      if (!wantedKeys.has(key)) {
        abort();
        this.abortHandles.delete(key);
        this.inFlight.delete(key);
      }
    }

    // Filter pending queue to only include wanted tiles
    this.pending = this.pending.filter((item) => {
      if (!wantedKeys.has(item.key)) {
        this.pendingKeys.delete(item.key);
        return false;
      }
      return true;
    });
  }

  prefetchTiles(viewport: Viewport, cached: (coord: TileCoord) => boolean): TileCoord[] {
    if (!this.metadata) {
      return [];
    }
    const tiles = this.prefetch.prefetchTiles(this.metadata, viewport, cached);
    return tiles.slice(0, this.prefetchBudget);
  }

  private scheduleRender(): void {
    if (this.renderPending) {
      return;
    }
    this.renderPending = true;
    const raf =
      typeof requestAnimationFrame === "function"
        ? requestAnimationFrame
        : (callback: FrameRequestCallback) => globalThis.setTimeout(callback, 0);
    raf(() => {
      this.renderPending = false;
      this.render();
    });
  }

  private render(): void {
    if (!this.metadata || !this.renderer || !this.atlas || !this.viewport) {
      return;
    }

    const level = this.prefetch.levelForScale(this.metadata, this.viewport.scale);
    if (this.previousLevel !== null && this.previousLevel !== level) {
      this.fallbackInstances = this.currentInstances;
      this.fallbackActive = this.fallbackInstances.length > 0;
    }
    this.previousLevel = level;

    const visible = visibleTiles(this.metadata, this.viewport);

    // Compute keys once and reuse - avoid repeated tileKey() calls
    const visibleKeys: string[] = [];
    for (const coord of visible) {
      visibleKeys.push(tileKey(coord));
    }

    // Build set of tiles we want (visible + prefetch) and cancel stale requests
    const cachedCheck = (coord: TileCoord) => {
      return (this.atlas?.touch(tileKey(coord)) ?? null) !== null;
    };
    const prefetch = this.prefetchTiles(this.viewport, cachedCheck);

    const wantedKeys = new Set<string>(visibleKeys);
    for (const coord of prefetch) {
      wantedKeys.add(tileKey(coord));
    }
    this.cancelStaleRequests(wantedKeys);

    // Resolve visible tiles using pre-computed keys
    const { cached, missing } = this.resolveVisibleTilesWithKeys(visible, visibleKeys);

    if (this.needsInitialRender && visible.length > 0) {
      this.needsInitialRender = false;
    }

    if (this.fallbackActive && visible.length > 0) {
      if (cached.length >= visible.length) {
        this.fallbackActive = false;
        this.fallbackInstances = [];
      }
    }

    // Always draw fallback tiles underneath new-level tiles so the
    // background never shows through during zoom transitions.
    const renderInstances =
      this.fallbackInstances.length > 0
        ? [...this.fallbackInstances, ...cached]
        : cached;

    this.currentInstances = cached;

    this.renderer.setViewport({
      x: this.viewport.x,
      y: this.viewport.y,
      width: this.viewport.width,
      height: this.viewport.height,
    });
    this.renderer.setTiles(renderInstances);
    this.renderer.render();

    // Pass prefetch tiles directly - avoid recomputing
    this.requestTiles(missing, prefetch);
  }

  private resolveVisibleTilesWithKeys(
    visible: TileCoord[],
    keys: string[]
  ): {
    cached: TileInstance[];
    missing: TileCoord[];
  } {
    const cached: TileInstance[] = [];
    const missing: TileCoord[] = [];

    for (let i = 0; i < visible.length; i++) {
      const coord = visible[i];
      const key = keys[i];
      const layer = this.atlas?.touch(key);
      if (layer !== null && layer !== undefined) {
        const instance = this.buildInstance(coord, layer);
        if (instance) {
          cached.push(instance);
        }
      } else {
        missing.push(coord);
      }
    }

    return { cached, missing };
  }

  private requestTiles(visibleMissing: TileCoord[], prefetch: TileCoord[]): void {
    if (!this.network) {
      return;
    }

    // Enqueue visible missing tiles first (priority)
    for (const coord of visibleMissing) {
      this.enqueueTile(coord);
    }

    // Then enqueue prefetch tiles up to budget
    const prefetchLimit = this.prefetchBudget;
    for (let i = 0; i < prefetch.length && i < prefetchLimit; i++) {
      this.enqueueTile(prefetch[i]);
    }

    this.pump();
  }

  private enqueueTile(coord: TileCoord): void {
    const key = tileKey(coord);
    if (this.pendingKeys.has(key) || this.inFlight.has(key)) {
      return;
    }

    if (this.atlas?.touch(key) !== null) {
      return;
    }

    const cachedBitmap = this.decodedCache.get(key);
    if (cachedBitmap && this.atlas && this.renderer) {
      const allocation = this.atlas.allocate(key);
      this.uploadBitmap(key, cachedBitmap, allocation.layer, this.generation);
      return;
    }

    this.pending.push({ coord, key, generation: this.generation });
    this.pendingKeys.add(key);
  }

  private pump(): void {
    if (!this.network) {
      return;
    }

    while (this.inFlight.size < this.maxInFlight && this.pending.length > 0) {
      const item = this.pending.shift();
      if (!item) {
        return;
      }
      const { coord, key, generation } = item;
      this.pendingKeys.delete(key);
      if (generation !== this.generation) {
        continue;
      }
      this.inFlight.set(key, generation);
      this.fetchAndUpload(coord, key, generation)
        .catch(() => {
          // Ignore; errors already logged in fetch
        })
        .finally(() => {
          this.inFlight.delete(key);
          this.pump();
        });
    }
  }

  private async fetchAndUpload(coord: TileCoord, key: string, generation: number): Promise<void> {
    if (!this.network || !this.metadata) {
      return;
    }

    if (generation !== this.generation) {
      return;
    }

    let buffer: ArrayBuffer | null = null;
    try {
      const abortable = this.network.fetchTileAbortable(coord);
      if (!abortable) {
        return;
      }
      // Store abort handle so we can cancel if tile goes out of viewport
      this.abortHandles.set(key, abortable.abort);
      try {
        buffer = await abortable.promise;
      } finally {
        // Clean up abort handle after fetch completes (success or failure)
        this.abortHandles.delete(key);
      }
    } catch (error) {
      // Request was cancelled or failed
      return;
    }

    if (!buffer) {
      return;
    }

    if (generation !== this.generation) {
      return;
    }

    const decoded = this.decodePool
      ? await this.decodePool.decode(buffer)
      : await decodeImageFallback(buffer);

    if (generation !== this.generation) {
      decoded.bitmap.close();
      return;
    }

    if (!this.renderer || !this.atlas) {
      decoded.bitmap.close();
      return;
    }

    const allocation = this.atlas.allocate(key);
    await this.uploadBitmap(key, decoded.bitmap, allocation.layer, generation);
  }

  private async uploadBitmap(
    key: string,
    bitmap: ImageBitmap,
    layer: number,
    generation: number
  ): Promise<void> {
    if (!this.renderer || generation !== this.generation) {
      return;
    }
    try {
      await this.renderer.uploadTile(layer, bitmap);
      this.decodedCache.set(key, bitmap);
      this.scheduleRender();
    } catch (error) {
      // Ignore upload failures
    }
  }

  private buildInstance(coord: TileCoord, layer: number): TileInstance | null {
    if (!this.metadata) {
      return null;
    }
    const levelInfo = getLevel(this.metadata, coord.level);
    if (!levelInfo) {
      return null;
    }
    const position = tilePosition(this.metadata, levelInfo, coord.col, coord.row);
    if (position.width <= 0 || position.height <= 0) {
      return null;
    }
    return {
      x: position.x,
      y: position.y,
      width: position.width,
      height: position.height,
      layer,
    };
  }
}

function tileKey(coord: TileCoord): string {
  return `${coord.level}:${coord.col}:${coord.row}`;
}

function tilePosition(
  metadata: SlideMetadata,
  levelInfo: LevelInfo,
  col: number,
  row: number
): { x: number; y: number; width: number; height: number } {
  const tileSize = metadata.tile_size * levelInfo.downsample;
  const x = col * tileSize;
  const y = row * tileSize;
  const width = Math.max(0, Math.min(tileSize, metadata.dimensions[0] - x));
  const height = Math.max(0, Math.min(tileSize, metadata.dimensions[1] - y));
  return { x, y, width, height };
}
