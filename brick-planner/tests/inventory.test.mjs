import { test } from "node:test";
import assert from "node:assert/strict";
import {
  emptyInventory,
  validateInventory,
  validateQuantity,
  summarize,
  MAX_QUANTITY,
} from "../src/inventory.js";

test("inventory round trip preserves all nine part quantities and geometry", () => {
  const inventory = emptyInventory();
  inventory.parts.forEach((part, i) => {
    part.quantity = i * 17;
  });
  const parsed = validateInventory(JSON.parse(JSON.stringify(inventory)));
  assert.deepEqual(parsed, inventory);
  assert.equal(parsed.parts.length, 9);
  assert.deepEqual(parsed.geometry, {
    stud_pitch: 5,
    layer_height: 6,
    units: "relative",
  });
});

test("structural material excludes detail bricks and accounts for footprint", () => {
  const inventory = emptyInventory();
  inventory.parts.find((part) => part.id === "1x1").quantity = 50;
  inventory.parts.find((part) => part.id === "2x4").quantity = 10;
  inventory.parts.find((part) => part.id === "2x8").quantity = 3;
  assert.deepEqual(summarize(inventory), {
    pieces: 63,
    types: 3,
    studCells: 178,
    structuralPieces: 13,
    structuralStudCells: 128,
    detailPieces: 50,
  });
});

test("quantities reject negative, fractional, overflowing, and nonnumeric inputs", () => {
  for (const value of [-1, 1.5, NaN, Infinity, "3", null, MAX_QUANTITY + 1]) {
    assert.throws(() => validateQuantity(value));
  }
  assert.equal(validateQuantity(0), 0);
  assert.equal(validateQuantity(MAX_QUANTITY), MAX_QUANTITY);
});

test("imports cannot change dimensions, detail-only policy, catalog, or format", () => {
  for (const mutate of [
    (data) => {
      data.schema_version = 2;
    },
    (data) => {
      data.geometry.layer_height = 5;
    },
    (data) => {
      data.parts[0].role = "structure";
    },
    (data) => {
      data.parts[1].studs = [1, 2];
    },
    (data) => {
      data.parts[2].height_layers = 2;
    },
    (data) => {
      data.parts[0].quantity = -1;
    },
    (data) => {
      data.parts[1] = data.parts[0];
    },
    (data) => {
      data.parts.pop();
    },
    (data) => {
      data.parts[1].id = "3x3";
    },
    (data) => {
      data.name = "";
    },
  ]) {
    const data = emptyInventory();
    mutate(data);
    assert.throws(() => validateInventory(data));
  }
});

test("import normalizes order, trims name, and does not retain input references", () => {
  const data = emptyInventory();
  data.name = "  My bricks  ";
  data.parts.reverse();
  const normalized = validateInventory(data);
  assert.equal(normalized.name, "My bricks");
  assert.equal(normalized.parts[0].id, "1x1");
  normalized.parts[0].studs[0] = 10;
  assert.equal(data.parts.at(-1).studs[0], 1);
  assert.equal(emptyInventory().parts[0].studs[0], 1);
});
