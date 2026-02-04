export interface DecodeResult {
  bitmap: ImageBitmap;
}

interface DecodeTask {
  buffer: ArrayBuffer;
  resolve: (result: DecodeResult) => void;
  reject: (reason?: unknown) => void;
}

export class DecodeWorkerPool {
  private workers: Worker[] = [];
  private idle: Worker[] = [];
  private queue: DecodeTask[] = [];
  private closed = false;

  constructor(size = Math.max(1, Math.min(navigator.hardwareConcurrency || 4, 8))) {
    for (let i = 0; i < size; i += 1) {
      const worker = new Worker(new URL("./decode.worker.ts", import.meta.url), {
        type: "module",
      });
      worker.onmessage = (event) => this.handleMessage(worker, event);
      worker.onerror = (event) => this.handleError(worker, event);
      this.workers.push(worker);
      this.idle.push(worker);
    }
  }

  decode(buffer: ArrayBuffer): Promise<DecodeResult> {
    if (this.closed) {
      return Promise.reject(new Error("Decode pool is closed"));
    }
    return new Promise((resolve, reject) => {
      this.queue.push({ buffer, resolve, reject });
      this.pump();
    });
  }

  close(): void {
    this.closed = true;
    for (const worker of this.workers) {
      worker.terminate();
    }
    this.workers = [];
    this.idle = [];
    this.queue = [];
  }

  private pump(): void {
    if (this.closed) {
      return;
    }
    while (this.idle.length > 0 && this.queue.length > 0) {
      const worker = this.idle.pop();
      const task = this.queue.shift();
      if (!worker || !task) {
        return;
      }
      (worker as Worker & { __decodeTask?: DecodeTask }).__decodeTask = task;
      worker.postMessage(task.buffer, [task.buffer]);
    }
  }

  private handleMessage(worker: Worker, event: MessageEvent): void {
    const task = (worker as Worker & { __decodeTask?: DecodeTask }).__decodeTask;
    if (!task) {
      return;
    }
    (worker as Worker & { __decodeTask?: DecodeTask }).__decodeTask = undefined;
    this.idle.push(worker);

    if (event.data && typeof event.data === "object" && "error" in event.data) {
      task.reject(new Error(String((event.data as { error: string }).error)));
    } else {
      task.resolve({ bitmap: event.data as ImageBitmap });
    }

    this.pump();
  }

  private handleError(worker: Worker, event: ErrorEvent): void {
    const task = (worker as Worker & { __decodeTask?: DecodeTask }).__decodeTask;
    if (task) {
      task.reject(event.error ?? event.message);
    }
    (worker as Worker & { __decodeTask?: DecodeTask }).__decodeTask = undefined;
    this.idle.push(worker);
    this.pump();
  }
}

export async function decodeImageFallback(buffer: ArrayBuffer): Promise<DecodeResult> {
  const blob = new Blob([buffer], { type: "image/jpeg" });
  const bitmap = await createImageBitmap(blob);
  return { bitmap };
}
