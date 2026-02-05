import { TileFetcher } from "./TileFetcher";
import { TileFetchQueue } from "./TileFetchQueue";
import type { TileRef } from "./LevelIndexParser";

export interface AbortableFetch {
  promise: Promise<ArrayBuffer>;
  abort: () => void;
}

export class LevelPackFetcher {
  private fetcher: TileFetcher;
  private queue?: TileFetchQueue;
  private fullPackCache = new Map<string, ArrayBuffer>();
  private thresholdBytes: number;

  constructor(thresholdBytes = 2_000_000, queue?: TileFetchQueue) {
    this.fetcher = new TileFetcher();
    this.thresholdBytes = thresholdBytes;
    this.queue = queue;
  }

  async fetchTile(packUrl: string, ref: TileRef, packSize?: number): Promise<ArrayBuffer> {
    return this.fetchTileAbortable(packUrl, ref, packSize).promise;
  }

  fetchTileAbortable(packUrl: string, ref: TileRef, packSize?: number): AbortableFetch {
    // For small packs, fetch the entire pack and slice (not abortable once started)
    if (packSize && packSize <= this.thresholdBytes) {
      const cached = this.fullPackCache.get(packUrl);
      if (cached) {
        const offset = Number(ref.offset);
        if (!Number.isSafeInteger(offset)) {
          return {
            promise: Promise.reject(new Error("Tile offset exceeds safe integer range")),
            abort: () => {},
          };
        }
        return {
          promise: Promise.resolve(cached.slice(offset, offset + ref.length)),
          abort: () => {},
        };
      }
      // Full pack fetch - not individually abortable, but rare for large slides
      const promise = this.fetchFullPack(packUrl).then((buffer) => {
        const offset = Number(ref.offset);
        if (!Number.isSafeInteger(offset)) {
          throw new Error("Tile offset exceeds safe integer range");
        }
        return buffer.slice(offset, offset + ref.length);
      });
      return { promise, abort: () => {} };
    }

    // Range request through queue (abortable)
    if (this.queue) {
      return this.queue.enqueueRange(packUrl, ref.offset, ref.length);
    }

    // Direct range fetch (abortable)
    return this.fetcher.fetchRange(packUrl, ref.offset, ref.length);
  }

  async fetchFullPack(packUrl: string): Promise<ArrayBuffer> {
    const response = await fetch(packUrl);
    if (!response.ok) {
      throw new Error(`Pack fetch failed (${response.status})`);
    }
    const buffer = await response.arrayBuffer();
    this.fullPackCache.set(packUrl, buffer);
    return buffer;
  }
}
