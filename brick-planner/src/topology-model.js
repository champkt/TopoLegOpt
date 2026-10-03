export const DEFAULT_SETTINGS = Object.freeze({
  threshold: 0.5,
  up: "y",
  mirror: "none",
});

export function validateSettings(settings) {
  if (
    !settings ||
    !Number.isFinite(settings.threshold) ||
    settings.threshold < 0 ||
    settings.threshold > 1 ||
    !["x", "y", "z"].includes(settings.up) ||
    !["none", "x", "y", "z"].includes(settings.mirror)
  ) {
    throw new Error("Invalid topology settings.");
  }
  return {
    threshold: settings.threshold,
    up: settings.up,
    mirror: settings.mirror,
  };
}

const FACES = [
  {
    delta: [-1, 0, 0],
    corners: [
      [0, 0, 1],
      [0, 1, 1],
      [0, 1, 0],
      [0, 0, 0],
    ],
  },
  {
    delta: [1, 0, 0],
    corners: [
      [1, 0, 0],
      [1, 1, 0],
      [1, 1, 1],
      [1, 0, 1],
    ],
  },
  {
    delta: [0, -1, 0],
    corners: [
      [0, 0, 0],
      [1, 0, 0],
      [1, 0, 1],
      [0, 0, 1],
    ],
  },
  {
    delta: [0, 1, 0],
    corners: [
      [0, 1, 1],
      [1, 1, 1],
      [1, 1, 0],
      [0, 1, 0],
    ],
  },
  {
    delta: [0, 0, -1],
    corners: [
      [0, 1, 0],
      [1, 1, 0],
      [1, 0, 0],
      [0, 0, 0],
    ],
  },
  {
    delta: [0, 0, 1],
    corners: [
      [0, 0, 1],
      [1, 0, 1],
      [1, 1, 1],
      [0, 1, 1],
    ],
  },
];

export function analyzeTopology(density, inputSettings, faceLimit = 150_000) {
  const settings = validateSettings(inputSettings);
  const { shape, values } = density;
  const mirrorAxis = ["x", "y", "z"].indexOf(settings.mirror);
  const dimensions = shape.map((n, i) => n * (i === mirrorAxis ? 2 : 1));
  let solid = 0;
  for (const value of values) if (value >= settings.threshold) solid++;
  const multiplier = mirrorAxis < 0 ? 1 : 2;
  let step = Math.max(1, Math.ceil(Math.max(...dimensions) / 256));
  let grid, mask, faces;
  // Preview uses conservative occupancy pooling when needed. Exact counts always
  // come from the original full-resolution field, never this display grid.
  for (;;) {
    grid = dimensions.map((n) => Math.ceil(n / step));
    mask = new Uint8Array(grid[0] * grid[1] * grid[2]);
    const put = (x, y, z) => {
      mask[
        (Math.floor(x / step) * grid[1] + Math.floor(y / step)) * grid[2] +
          Math.floor(z / step)
      ] = 1;
    };
    let index = 0;
    for (let x = 0; x < shape[0]; x++)
      for (let y = 0; y < shape[1]; y++)
        for (let z = 0; z < shape[2]; z++, index++) {
          if (values[index] < settings.threshold) continue;
          if (mirrorAxis < 0) put(x, y, z);
          else {
            const coordinate = [x, y, z];
            coordinate[mirrorAxis] += shape[mirrorAxis];
            put(...coordinate);
            coordinate[mirrorAxis] =
              2 * shape[mirrorAxis] - 1 - coordinate[mirrorAxis];
            put(...coordinate);
          }
        }
    faces = 0;
    const occupied = (x, y, z) =>
      x >= 0 &&
      x < grid[0] &&
      y >= 0 &&
      y < grid[1] &&
      z >= 0 &&
      z < grid[2] &&
      mask[(x * grid[1] + y) * grid[2] + z];
    for (let x = 0; x < grid[0]; x++)
      for (let y = 0; y < grid[1]; y++)
        for (let z = 0; z < grid[2]; z++) {
          if (!occupied(x, y, z)) continue;
          for (const {
            delta: [dx, dy, dz],
          } of FACES)
            if (!occupied(x + dx, y + dy, z + dz)) faces++;
        }
    if (faces <= faceLimit || step >= Math.max(...dimensions)) break;
    step *= 2;
  }
  const positions = new Float32Array(faces * 18);
  let cursor = 0;
  const occupied = (x, y, z) =>
    x >= 0 &&
    x < grid[0] &&
    y >= 0 &&
    y < grid[1] &&
    z >= 0 &&
    z < grid[2] &&
    mask[(x * grid[1] + y) * grid[2] + z];
  for (let x = 0; x < grid[0]; x++)
    for (let y = 0; y < grid[1]; y++)
      for (let z = 0; z < grid[2]; z++) {
        if (!occupied(x, y, z)) continue;
        for (const {
          delta: [dx, dy, dz],
          corners,
        } of FACES) {
          if (occupied(x + dx, y + dy, z + dz)) continue;
          for (const vertex of [0, 1, 2, 0, 2, 3])
            for (let axis = 0; axis < 3; axis++) {
              positions[cursor++] =
                Math.min(
                  dimensions[axis],
                  ([x, y, z][axis] + corners[vertex][axis]) * step,
                ) -
                dimensions[axis] / 2;
            }
        }
      }
  // Full-resolution central X slice as a fallback when WebGL is unavailable.
  const slice = new Uint8ClampedArray(shape[1] * shape[2]);
  const x = Math.floor(shape[0] / 2);
  for (let y = 0; y < shape[1]; y++)
    for (let z = 0; z < shape[2]; z++) {
      slice[y * shape[2] + z] = Math.round(
        values[(x * shape[1] + y) * shape[2] + z] * 255,
      );
    }
  return {
    positions,
    slice,
    dimensions,
    sourceShape: shape,
    settings,
    previewStep: step,
    faces,
    solidVoxels: solid * multiplier,
    totalVoxels: values.length * multiplier,
    fill: solid / values.length,
    mean: density.mean,
    minimum: density.minimum,
    maximum: density.maximum,
  };
}
