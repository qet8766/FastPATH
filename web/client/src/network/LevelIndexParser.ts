export interface TileRef {
  offset: bigint;
  length: number;
}

const MAGIC = new Uint8Array([70, 80, 76, 73, 68, 88, 49, 0]);
const VERSION = 1;
const HEADER_SIZE = 16;
const ENTRY_SIZE = 12;

export class LevelIndex {
  readonly cols: number;
  readonly rows: number;
  private entries: DataView;

  constructor(buffer: ArrayBuffer) {
    if (buffer.byteLength < HEADER_SIZE) {
      throw new Error("Index buffer too small");
    }

    const view = new DataView(buffer);
    for (let i = 0; i < MAGIC.length; i += 1) {
      if (view.getUint8(i) !== MAGIC[i]) {
        throw new Error("Invalid index magic");
      }
    }

    const version = view.getUint32(8, true);
    if (version !== VERSION) {
      throw new Error(`Unsupported index version: ${version}`);
    }

    this.cols = view.getUint16(12, true);
    this.rows = view.getUint16(14, true);

    const expectedLength = HEADER_SIZE + this.cols * this.rows * ENTRY_SIZE;
    if (buffer.byteLength !== expectedLength) {
      throw new Error("Index length mismatch");
    }

    this.entries = new DataView(buffer, HEADER_SIZE);
  }

  tileRef(col: number, row: number): TileRef | null {
    if (col < 0 || row < 0 || col >= this.cols || row >= this.rows) {
      return null;
    }
    const idx = row * this.cols + col;
    const base = idx * ENTRY_SIZE;
    const offset = this.entries.getBigUint64(base, true);
    const length = this.entries.getUint32(base + 8, true);
    if (length === 0) {
      return null;
    }
    return { offset, length };
  }
}

export const INDEX_FORMAT = {
  MAGIC,
  VERSION,
  HEADER_SIZE,
  ENTRY_SIZE,
};
