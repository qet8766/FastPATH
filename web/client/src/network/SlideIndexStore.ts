import type { SlideMetadata } from "../types";
import { LevelIndex } from "./LevelIndexParser";

export interface LevelIndexRecord {
  level: number;
  index: LevelIndex;
  packUrl: string;
  packSize: number;
}

export class SlideIndexStore {
  private baseUrl: string;
  private metadata: SlideMetadata;
  private indices = new Map<number, LevelIndex>();
  private packSizes = new Map<number, number>();

  constructor(baseUrl: string, metadata: SlideMetadata) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.metadata = metadata;

    if (metadata.pack_sizes) {
      for (const [level, size] of Object.entries(metadata.pack_sizes)) {
        this.packSizes.set(Number(level), size);
      }
    }
  }

  async load(): Promise<void> {
    const tasks = this.metadata.levels.map((level) => this.loadLevel(level.level));
    await Promise.all(tasks);
  }

  getIndex(level: number): LevelIndex | undefined {
    return this.indices.get(level);
  }

  getPackSize(level: number): number | undefined {
    return this.packSizes.get(level);
  }

  packUrl(level: number): string {
    return `${this.baseUrl}/tiles/level_${level}.pack`;
  }

  idxUrl(level: number): string {
    return `${this.baseUrl}/tiles/level_${level}.idx`;
  }

  private async loadLevel(level: number): Promise<void> {
    const index = await this.fetchIndex(this.idxUrl(level));
    this.indices.set(level, index);

    if (!this.packSizes.has(level)) {
      const packSize = await this.fetchPackSize(this.packUrl(level));
      this.packSizes.set(level, packSize);
    }
  }

  private async fetchIndex(url: string): Promise<LevelIndex> {
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Index fetch failed (${response.status})`);
    }
    const buffer = await response.arrayBuffer();
    return new LevelIndex(buffer);
  }

  private async fetchPackSize(url: string): Promise<number> {
    const head = await fetch(url, { method: "HEAD" });
    if (head.ok) {
      const length = head.headers.get("content-length");
      if (length) {
        const parsed = Number(length);
        if (Number.isFinite(parsed)) {
          return parsed;
        }
      }
    }

    const range = await fetch(url, { headers: { Range: "bytes=0-0" } });
    if (range.status === 206) {
      const contentRange = range.headers.get("content-range");
      const match = contentRange?.match(/\/(\d+)$/);
      if (match) {
        return Number(match[1]);
      }
    }

    if (range.ok) {
      const length = range.headers.get("content-length");
      if (length) {
        return Number(length);
      }
    }

    throw new Error("Unable to determine pack size");
  }
}
