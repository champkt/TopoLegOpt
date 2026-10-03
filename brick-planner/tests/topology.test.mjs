import { test } from "node:test";
import assert from "node:assert/strict";
import { zipSync } from "fflate";
import { openArchive, readDensity, readHeader } from "../src/npz.js";
import {
  DEFAULT_SETTINGS,
  analyzeTopology,
  validateSettings,
} from "../src/topology-model.js";

function npy(
  values,
  shape,
  { dtype = "<f8", fortran = false, version = 1 } = {},
) {
  const prefix = version === 1 ? 10 : 12;
  const header = `{'descr': '${dtype}', 'fortran_order': ${fortran ? "True" : "False"}, 'shape': (${shape.join(", ")}${shape.length === 1 ? "," : ""}), }`;
  const padded =
    header.padEnd(
      Math.ceil((prefix + header.length + 1) / 64) * 64 - prefix - 1,
    ) + "\n";
  const itemSize = Number(dtype.slice(2));
  const bytes = new Uint8Array(prefix + padded.length + values.length * itemSize);
  bytes.set([147, 78, 85, 77, 80, 89, version, 0]);
  const view = new DataView(bytes.buffer);
  if (version === 1) view.setUint16(8, padded.length, true);
  else view.setUint32(8, padded.length, true);
  bytes.set(new TextEncoder().encode(padded), prefix);
  const kind = dtype[1];
  const method = kind === "f" ? `setFloat${itemSize * 8}`
    : kind === "b" ? "setUint8"
      : itemSize === 8 ? (kind === "i" ? "setBigInt64" : "setBigUint64")
        : `set${kind === "i" ? "Int" : "Uint"}${itemSize * 8}`;
  values.forEach((value, i) => view[method](
    prefix + padded.length + i * itemSize,
    itemSize === 8 && ["i", "u"].includes(kind) ? BigInt(value) : value,
    dtype[0] !== ">",
  ));
  return bytes;
}

test("NPZ reader supports NumPy format versions, endianness, and metadata", () => {
  for (const version of [1, 2, 3])
    for (const dtype of ["<f8", ">f8"]) {
      const archive = openArchive(
        zipSync({
          "density.npy": npy([0, 0.25, 0.5, 1], [1, 2, 2], { version, dtype }),
          "iterations.npy": npy([500], []),
        }),
      );
      assert.equal(archive.arrays.length, 1);
      const data = readDensity(archive, "density");
      assert.deepEqual([...data.values], [0, 0.25, 0.5, 1]);
      assert.equal(data.mean, 0.4375);
    }
});

test("Fortran storage is converted to X-Y-Z C order without transposing axes", () => {
  const archive = openArchive(
    zipSync({
      "density.npy": npy([0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7], [2, 2, 2], {
        fortran: true,
      }),
    }),
  );
  assert.deepEqual(
    [...readDensity(archive, "density").values],
    [0, 0.4, 0.2, 0.6, 0.1, 0.5, 0.3, 0.7],
  );
});

test("boolean arrays normalize every nonzero byte while integer masks remain strict", () => {
  const archive = openArchive(zipSync({
    "density.npy": npy([0, 1, 2, 255], [1, 2, 2], { dtype: "|b1" }),
  }));
  const density = readDensity(archive, "density");
  assert.deepEqual([...density.values], [0, 1, 1, 1]);
  assert.equal(density.mean, 0.75);
  const integerArchive = openArchive(zipSync({
    "density.npy": npy([0, 1, 2, 255], [1, 2, 2], { dtype: "|u1" }),
  }));
  assert.throws(() => readDensity(integerArchive, "density"), /finite and between/);
});

test("supported numeric masks preserve values across item sizes and byte orders", () => {
  for (const endian of ["<", ">"])
    for (const type of ["f4", "f8", "i1", "i2", "i4", "i8", "u1", "u2", "u4", "u8"]) {
      const archive = openArchive(zipSync({
        "density.npy": npy([0, 1, 1, 0], [1, 2, 2], { dtype: endian + type }),
      }));
      assert.deepEqual([...readDensity(archive, "density").values], [0, 1, 1, 0]);
    }
});

test("malformed arrays and non-density values are rejected", () => {
  assert.throws(() => openArchive(new Uint8Array([1, 2, 3])));
  assert.throws(() => readHeader(new Uint8Array(20)));
  for (const values of [[NaN], [Infinity], [-0.01], [1.01]]) {
    const archive = openArchive(
      zipSync({ "density.npy": npy(values, [1, 1, 1]) }),
    );
    assert.throws(() => readDensity(archive, "density"), /finite and between/);
  }
  const archive = openArchive(zipSync({ "density.npy": npy([1], [1, 2, 3]) }));
  assert.throws(() => readDensity(archive, "density"), /length/);
  assert.throws(
    () => openArchive(zipSync({ "density.npy": npy([1], [1]) })),
    /No supported 3D/,
  );
});

function density(values, shape) {
  return {
    values: Float64Array.from(values),
    shape,
    mean: values.reduce((a, b) => a + b, 0) / values.length,
    minimum: Math.min(...values),
    maximum: Math.max(...values),
  };
}

test("threshold counts full-resolution material and surface excludes internal faces", () => {
  const data = density([0, 0.5, 1], [1, 1, 3]);
  const result = analyzeTopology(data, DEFAULT_SETTINGS);
  assert.equal(result.solidVoxels, 2);
  assert.equal(result.totalVoxels, 3);
  assert.equal(result.faces, 10);
  assert.equal(result.positions.length, 180);
  assert.equal(
    analyzeTopology(data, { ...DEFAULT_SETTINGS, threshold: 1 }).faces,
    6,
  );
  assert.equal(
    analyzeTopology(density([0], [1, 1, 1]), DEFAULT_SETTINGS).faces,
    0,
  );
});

test("reflection doubles the selected axis and material, preserving isotropic voxels", () => {
  const data = density([1], [1, 1, 1]);
  for (const [i, mirror] of ["x", "y", "z"].entries()) {
    const result = analyzeTopology(data, { ...DEFAULT_SETTINGS, mirror });
    assert.equal(result.solidVoxels, 2);
    assert.equal(result.faces, 10);
    assert.deepEqual(
      result.dimensions,
      [0, 1, 2].map((axis) => (axis === i ? 2 : 1)),
    );
    const coordinates = [...result.positions].filter(
      (_, index) => index % 3 === i,
    );
    assert.equal(Math.min(...coordinates), -1);
    assert.equal(Math.max(...coordinates), 1);
  }
  const asymmetric = analyzeTopology(density([1, 0], [1, 1, 2]), {
    ...DEFAULT_SETTINGS,
    mirror: "z",
  });
  const z = [...asymmetric.positions].filter((_, index) => index % 3 === 2);
  assert.equal(Math.min(...z), -1);
  assert.equal(Math.max(...z), 1);
});

test("preview reduction never changes exact counts or target dimensions", () => {
  const data = density([1, 0, 1, 0, 1], [1, 1, 5]);
  const result = analyzeTopology(data, DEFAULT_SETTINGS, 6);
  assert.ok(result.previewStep > 1);
  assert.equal(result.solidVoxels, 3);
  assert.equal(result.totalVoxels, 5);
  assert.deepEqual(result.dimensions, [1, 1, 5]);
});

test("settings reject invalid axes and thresholds", () => {
  for (const value of [
    { ...DEFAULT_SETTINGS, threshold: NaN },
    { ...DEFAULT_SETTINGS, threshold: -1 },
    { ...DEFAULT_SETTINGS, mirror: "a" },
    { ...DEFAULT_SETTINGS, up: "none" },
  ]) {
    assert.throws(() => validateSettings(value));
  }
});
