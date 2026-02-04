export interface FetchTask {
  promise: Promise<ArrayBuffer>;
  abort: () => void;
}

export class TileFetcher {
  fetchRange(url: string, offset: bigint, length: number): FetchTask {
    const controller = new AbortController();
    const end = offset + BigInt(Math.max(length - 1, 0));
    const headers = {
      Range: `bytes=${offset}-${end}`,
    };

    const promise = fetch(url, { headers, signal: controller.signal }).then((response) => {
      if (!response.ok && response.status !== 206) {
        throw new Error(`Tile fetch failed (${response.status})`);
      }
      return response.arrayBuffer();
    });

    return {
      promise,
      abort: () => controller.abort(),
    };
  }
}
