import { validateTileRef } from "../../client/src/network/TileNetwork";

const ref = (offset: bigint, length: number) => ({ offset, length });

test("validateTileRef allows in-bounds tiles", () => {
  expect(() => validateTileRef(ref(0n, 10), 10)).not.toThrow();
  expect(() => validateTileRef(ref(5n, 5), 20)).not.toThrow();
});

test("validateTileRef rejects out-of-bounds tiles", () => {
  expect(() => validateTileRef(ref(10n, 5), 12)).toThrow(/exceeds/);
});
