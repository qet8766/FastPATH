import { TileFetcher } from "./TileFetcher";
import { TileFetchQueue } from "./TileFetchQueue";
import type { TileRef } from "./LevelIndexParser";

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
    if (packSize && packSize <= this.thresholdBytes) {
      const cached = this.fullPackCache.get(packUrl);
      const buffer = cached ?? (await this.fetchFullPack(packUrl));
      const offset = Number(ref.offset);
      if (!Number.isSafeInteger(offset)) {
        throw new Error("Tile offset exceeds safe integer range");
      }
      return buffer.slice(offset, offset + ref.length);
    }

    if (this.queue) {
      return this.queue.enqueueRange(packUrl, ref.offset, ref.length).promise;
    }

    return this.fetcher.fetchRange(packUrl, ref.offset, ref.length).promise;
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
