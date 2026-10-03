import { openArchive, readDensity } from "./npz.js";
import { DEFAULT_SETTINGS, analyzeTopology } from "./topology-model.js";
let archive, density;
self.onmessage = ({ data }) => {
  try {
    let nextArchive = archive;
    if (data.type === "load") nextArchive = openArchive(data.buffer);
    const key =
      data.key ||
      nextArchive.arrays.find((array) => array.key === "density")?.key ||
      nextArchive.arrays.find((array) => array.key === "design")?.key ||
      nextArchive.arrays[0].key;
    const nextDensity =
      data.type === "load" || density?.key !== key
        ? readDensity(nextArchive, key)
        : density;
    const result = analyzeTopology(
      nextDensity,
      data.settings || DEFAULT_SETTINGS,
    );
    archive = nextArchive;
    density = nextDensity;
    self.postMessage(
      {
        id: data.id,
        result,
        key,
        arrays: archive.arrays.map(({ key, shape, dtype }) => ({
          key,
          shape,
          dtype,
        })),
      },
      [result.positions.buffer, result.slice.buffer],
    );
  } catch (error) {
    self.postMessage({
      id: data.id,
      error: error.message || "Could not process this topology.",
    });
  }
};
