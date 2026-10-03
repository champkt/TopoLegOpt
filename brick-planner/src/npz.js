import { unzipSync } from "fflate";

export const MAX_FILE_BYTES = 128 * 1024 * 1024;
const MAX_UNPACKED_BYTES = 512 * 1024 * 1024;
const MAX_VOXELS = 32_000_000;

export function readHeader(bytes) {
  if (
    bytes.length < 10 ||
    ![147, 78, 85, 77, 80, 89].every((n, i) => bytes[i] === n)
  ) {
    throw new Error("An array is not a valid NumPy NPY file.");
  }
  const major = bytes[6];
  if (![1, 2, 3].includes(major) || bytes[7] !== 0)
    throw new Error("Unsupported NPY format version.");
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const prefix = major === 1 ? 10 : 12;
  if (bytes.length < prefix) throw new Error("Truncated NPY header.");
  const size = major === 1 ? view.getUint16(8, true) : view.getUint32(8, true);
  if (size > 65536 || prefix + size > bytes.length)
    throw new Error("Invalid or oversized NPY header.");
  const header = new TextDecoder(major === 3 ? "utf-8" : "latin1").decode(
    bytes.subarray(prefix, prefix + size),
  );
  const dtype = /['"]descr['"]\s*:\s*['"]([^'"]+)['"]/.exec(header)?.[1];
  const order = /['"]fortran_order['"]\s*:\s*(True|False)/.exec(header)?.[1];
  const shapeText = /['"]shape['"]\s*:\s*\(([^)]*)\)/.exec(header)?.[1];
  if (
    !dtype ||
    !order ||
    shapeText === undefined ||
    !/^[\d\s,]*$/.test(shapeText)
  ) {
    throw new Error(
      "Unsupported NPY header. Only plain numeric arrays are supported.",
    );
  }
  const shape = shapeText
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map(Number);
  if (shape.some((n) => !Number.isSafeInteger(n) || n < 0))
    throw new Error("Invalid array dimensions.");
  return { dtype, fortran: order === "True", shape, offset: prefix + size };
}

export function openArchive(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.length > MAX_FILE_BYTES)
    throw new Error("Choose an NPZ file smaller than 128 MiB.");
  let count = 0,
    unpacked = 0;
  const names = new Set();
  let files;
  try {
    files = unzipSync(bytes, {
      filter(file) {
        if (++count > 64)
          throw new Error("The archive contains more than 64 entries.");
        if (names.has(file.name))
          throw new Error("Duplicate array names are not supported.");
        names.add(file.name);
        unpacked += file.originalSize;
        if (!Number.isSafeInteger(unpacked) || unpacked > MAX_UNPACKED_BYTES) {
          throw new Error("Unpacked arrays exceed the 512 MiB browser limit.");
        }
        return file.name.endsWith(".npy");
      },
    });
  } catch (error) {
    throw new Error(`Cannot read this NPZ archive: ${error.message}`);
  }
  const arrays = [];
  for (const [filename, data] of Object.entries(files)) {
    // Ignore scalar/string/object metadata. No pickle or Python code is executed.
    let header;
    try {
      header = readHeader(data);
    } catch {
      continue;
    }
    if (header.shape.length !== 3) continue;
    if (!/^[<>|=]?(?:f[48]|[iu][1248]|b1)$/.test(header.dtype)) continue;
    arrays.push({ key: filename.slice(0, -4), ...header });
  }
  if (!arrays.length)
    throw new Error(
      "No supported 3D numeric array found. Expected a density array shaped (X, Y, Z).",
    );
  return { files, arrays };
}

export function readDensity(archive, key) {
  const header = archive.arrays.find((array) => array.key === key);
  if (!header) throw new Error("Choose a supported 3D array.");
  const { shape, offset, fortran, dtype } = header;
  const count = shape.reduce((a, b) => a * b, 1);
  if (!Number.isSafeInteger(count) || count < 1 || count > MAX_VOXELS) {
    throw new Error("The selected array must contain 1–32,000,000 voxels.");
  }
  const [, endian, kind, sizeText] = /^([<>|=]?)([fiub])(\d+)$/.exec(dtype);
  const size = Number(sizeText),
    little = endian !== ">";
  const bytes = archive.files[`${key}.npy`];
  if (offset + count * size !== bytes.length)
    throw new Error("Array length does not match its declared dimensions.");
  const view = new DataView(
    bytes.buffer,
    bytes.byteOffset + offset,
    count * size,
  );
  const method =
    kind === "f"
      ? `getFloat${size * 8}`
      : kind === "b"
        ? "getUint8"
        : size === 8
          ? kind === "i"
            ? "getBigInt64"
            : "getBigUint64"
          : `get${kind === "i" ? "Int" : "Uint"}${size * 8}`;
  // Keep float64 precision, especially for threshold comparisons on f8 inputs.
  const values = new Float64Array(count);
  let minimum = Infinity,
    maximum = -Infinity,
    sum = 0;
  const [nx, ny, nz] = shape;
  for (let index = 0; index < count; index++) {
    const rawValue = Number(view[method](index * size, little));
    // NumPy booleans use zero/nonzero semantics. A valid bool view may contain
    // a noncanonical true byte (for example 255), which np.savez preserves.
    const value = kind === "b" ? Number(rawValue !== 0) : rawValue;
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      throw new Error(
        "Density values must be finite and between 0 and 1. This array cannot be used as a density field.",
      );
    }
    let target = index;
    if (fortran) {
      const x = index % nx,
        y = Math.floor(index / nx) % ny,
        z = Math.floor(index / (nx * ny));
      target = (x * ny + y) * nz + z;
    }
    values[target] = value;
    minimum = Math.min(minimum, value);
    maximum = Math.max(maximum, value);
    sum += value;
  }
  return {
    values,
    shape: [...shape],
    minimum,
    maximum,
    mean: sum / count,
    key,
    dtype,
  };
}
