import { LevelIndex, INDEX_FORMAT } from "../../client/src/network/LevelIndexParser";

function buildIndex(cols: number, rows: number, entries: Array<{ offset: bigint; length: number }>): ArrayBuffer {
  const bufferLength = INDEX_FORMAT.HEADER_SIZE + cols * rows * INDEX_FORMAT.ENTRY_SIZE;
  const buffer = new ArrayBuffer(bufferLength);
  const view = new DataView(buffer);
  INDEX_FORMAT.MAGIC.forEach((value, idx) => view.setUint8(idx, value));
  view.setUint32(8, INDEX_FORMAT.VERSION, true);
  view.setUint16(12, cols, true);
  view.setUint16(14, rows, true);
  let offset = INDEX_FORMAT.HEADER_SIZE;
  for (const entry of entries) {
    view.setBigUint64(offset, entry.offset, true);
    view.setUint32(offset + 8, entry.length, true);
    offset += INDEX_FORMAT.ENTRY_SIZE;
  }
  return buffer;
}

test("parses valid index", () => {
  const buffer = buildIndex(2, 1, [
    { offset: 0n, length: 10 },
    { offset: 10n, length: 0 },
  ]);
  const index = new LevelIndex(buffer);
  expect(index.cols).toBe(2);
  expect(index.rows).toBe(1);
  expect(index.tileRef(0, 0)).toEqual({ offset: 0n, length: 10 });
  expect(index.tileRef(1, 0)).toBeNull();
});

test("rejects bad magic", () => {
  const buffer = buildIndex(1, 1, [{ offset: 0n, length: 10 }]);
  const view = new DataView(buffer);
  view.setUint8(0, 0);
  expect(() => new LevelIndex(buffer)).toThrow(/magic/i);
});

test("rejects length mismatch", () => {
  const buffer = buildIndex(1, 1, [{ offset: 0n, length: 10 }]);
  const sliced = buffer.slice(0, buffer.byteLength - 1);
  expect(() => new LevelIndex(sliced)).toThrow(/length/i);
});
