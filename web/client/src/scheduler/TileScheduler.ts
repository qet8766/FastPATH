import type { LevelInfo, SlideMetadata, TileCoord, Viewport } from "../types";
import { getLevel } from "../types";
import { PrefetchCalculator } from "./PrefetchCalculator";
import { visibleTiles } from "./ViewportCalculator";
import { cacheMissRatio } from "./CacheMissThreshold";
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
  cacheMissThreshold?: number;
  decodedCacheSize?: number;
  decodeWorkers?: number;
}

interface PendingRequest {
  coord: TileCoord;
  generation: number;
}

export class TileScheduler {
  private metadata: SlideMetadata | null = null;
  private generation = 0;
  private prefetch: PrefetchCalculator;
  private prefetchBudget: number;
  private maxInFlight: number;
  private cacheMissThreshold: number;
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
  private renderPending = false;
  private needsInitialRender = true;
  private previousLevel: number | null = null;
  private fallbackActive = false;
  private currentInstances: TileInstance[] = [];
  private fallbackInstances: TileInstance[] = [];

  constructor(options: TileSchedulerOptions = {}) {
    this.prefetch = new PrefetchCalculator();
    this.prefetchBudget = options.prefetchBudget ?? 32;
    this.maxInFlight = options.maxInFlight ?? 24;
    this.cacheMissThreshold = options.cacheMissThreshold ?? 0.3;
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
    this.fetchQueue?.cancelAll();
    this.decodedCache.clear();
    this.atlas?.reset();

    if (this.renderer && this.atlas) {
      this.renderer.configureAtlas(metadata.tile_size, this.atlas.capacity);
    }
  }

  close(): void {
    this.metadata = null;
    this.generation += 1;
    this.viewport = null;
    this.pending = [];
    this.pendingKeys.clear();
    this.inFlight.clear();
    this.fetchQueue?.cancelAll();
    this.decodedCache.clear();
    this.atlas?.reset();
    if (this.renderer) {
      this.renderer.setTiles([]);
      this.renderer.render();
    }
  }

  getGeneration(): number {
    return this.generation;
  }

  updateViewport(viewport: Viewport): void {
    this.viewport = viewport;
    this.scheduleRender();
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
    const { cached, missing } = this.resolveVisibleTiles(visible);

    if (this.needsInitialRender && visible.length > 0) {
      this.needsInitialRender = false;
    }

    if (this.fallbackActive && visible.length > 0) {
      const ratio = cacheMissRatio(visible.length, cached.length);
      if (ratio <= this.cacheMissThreshold) {
        this.fallbackActive = false;
        this.fallbackInstances = [];
      }
    }

    const renderInstances = this.fallbackActive
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

    this.requestTiles(missing, this.viewport);
  }

  private resolveVisibleTiles(visible: TileCoord[]): {
    cached: TileInstance[];
    missing: TileCoord[];
  } {
    const cached: TileInstance[] = [];
    const missing: TileCoord[] = [];

    for (const coord of visible) {
      const key = tileKey(coord);
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

  private requestTiles(visibleMissing: TileCoord[], viewport: Viewport): void {
    if (!this.metadata || !this.network) {
      return;
    }

    const cachedCheck = (coord: TileCoord) => {
      const key = tileKey(coord);
      return (this.atlas?.touch(key) ?? null) !== null;
    };

    const prefetch = this.prefetchTiles(viewport, cachedCheck);
    const queue = visibleMissing.concat(prefetch).slice(0, this.prefetchBudget + visibleMissing.length);

    for (const coord of queue) {
      this.enqueueTile(coord);
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
      if (allocation.evictedKey) {
        // Evicted tiles are dropped from the atlas; cache keeps decoded bitmap.
      }
      return;
    }

    this.pending.push({ coord, generation: this.generation });
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
      const key = tileKey(item.coord);
      this.pendingKeys.delete(key);
      if (item.generation !== this.generation) {
        continue;
      }
      this.inFlight.set(key, item.generation);
      this.fetchAndUpload(item.coord, item.generation)
        .catch(() => {
          // Ignore; errors already logged in fetch
        })
        .finally(() => {
          this.inFlight.delete(key);
          this.pump();
        });
    }
  }

  private async fetchAndUpload(coord: TileCoord, generation: number): Promise<void> {
    if (!this.network || !this.metadata) {
      return;
    }

    const key = tileKey(coord);
    if (generation !== this.generation) {
      return;
    }

    let buffer: ArrayBuffer | null = null;
    try {
      buffer = await this.network.fetchTile(coord);
    } catch (error) {
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
