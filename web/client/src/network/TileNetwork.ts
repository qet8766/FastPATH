import type { TileCoord } from "../types";
import type { TileRef } from "./LevelIndexParser";
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
      throw new Error("Missing pack size for level");
    }
    validateTileRef(ref, packSize);
    return this.fetcher.fetchTile(this.store.packUrl(coord.level), ref, packSize);
  }
}
