import { TileFetcher } from "./TileFetcher";

export interface QueueTask {
  promise: Promise<ArrayBuffer>;
  abort: () => void;
}

interface PendingItem {
  url: string;
  offset: bigint;
  length: number;
  resolve: (value: ArrayBuffer) => void;
  reject: (reason?: unknown) => void;
  aborter?: () => void;
  cancelled: boolean;
}

export class TileFetchQueue {
  private fetcher: TileFetcher;
  private maxConcurrent: number;
  private inFlight = 0;
  private pending: PendingItem[] = [];
  private active = new Set<PendingItem>();

  constructor(maxConcurrent = 8) {
    this.fetcher = new TileFetcher();
    this.maxConcurrent = maxConcurrent;
  }

  enqueueRange(url: string, offset: bigint, length: number): QueueTask {
    let item: PendingItem | null = null;
    const promise = new Promise<ArrayBuffer>((resolve, reject) => {
      item = {
        url,
        offset,
        length,
        resolve,
        reject,
        cancelled: false,
      };
      this.pending.push(item);
      this.pump();
    });

    const abort = () => {
      if (!item) {
        return;
      }
      item.cancelled = true;
      if (item.aborter) {
        item.aborter();
      } else {
        const idx = this.pending.indexOf(item);
        if (idx >= 0) {
          this.pending.splice(idx, 1);
          item.reject(new Error("Request cancelled"));
        }
      }
    };

    return { promise, abort };
  }

  cancelAll(): void {
    for (const item of this.pending.splice(0)) {
      item.cancelled = true;
      item.reject(new Error("Request cancelled"));
    }
    for (const item of this.active) {
      item.cancelled = true;
      item.aborter?.();
    }
  }

  private pump(): void {
    while (this.inFlight < this.maxConcurrent && this.pending.length > 0) {
      const item = this.pending.shift();
      if (!item) {
        return;
      }
      if (item.cancelled) {
        item.reject(new Error("Request cancelled"));
        continue;
      }
      const task = this.fetcher.fetchRange(item.url, item.offset, item.length);
      item.aborter = task.abort;
      this.active.add(item);
      this.inFlight += 1;
      task.promise
        .then((buffer) => {
          item.resolve(buffer);
        })
        .catch((err) => {
          item.reject(err);
        })
        .finally(() => {
          this.active.delete(item);
          this.inFlight -= 1;
          this.pump();
        });
    }
  }
}
