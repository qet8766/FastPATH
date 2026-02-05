import type { TileCoord } from "../types";
import type { TileRef } from "./LevelIndexParser";
import type { AbortableFetch } from "./LevelPackFetcher";
import { LevelPackFetcher } from "./LevelPackFetcher";
import { SlideIndexStore } from "./SlideIndexStore";

export function validateTileRef(ref: TileRef, packSize: number): void {
  const end = ref.offset + BigInt(ref.length);
  if (end > BigInt(packSize)) {
    throw new Error("Tile reference exceeds pack size");
  }
}

export class TileNetwork {
  private store: SlideIndexStore;
  private fetcher: LevelPackFetcher;

  constructor(store: SlideIndexStore, fetcher = new LevelPackFetcher()) {
    this.store = store;
    this.fetcher = fetcher;
  }

  async load(): Promise<void> {
    await this.store.load();
  }

  async fetchTile(coord: TileCoord): Promise<ArrayBuffer | null> {
    const result = this.fetchTileAbortable(coord);
    if (!result) {
      return null;
    }
    return result.promise;
  }

  /**
   * Fetch a tile with the ability to abort the request.
   * Returns null if the tile doesn't exist in the index.
   */
  fetchTileAbortable(coord: TileCoord): AbortableFetch | null {
    const index = this.store.getIndex(coord.level);
    if (!index) {
      return null;
    }
    const ref = index.tileRef(coord.col, coord.row);
    if (!ref) {
      return null;
    }
    const packSize = this.store.getPackSize(coord.level);
    if (packSize === undefined) {
      return {
        promise: Promise.reject(new Error("Missing pack size for level")),
        abort: () => {},
      };
    }
    validateTileRef(ref, packSize);
    return this.fetcher.fetchTileAbortable(this.store.packUrl(coord.level), ref, packSize);
  }
}
