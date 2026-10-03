// Solver-facing data model. No DOM or browser dependencies.
export const SCHEMA_VERSION = 1;
export const MAX_QUANTITY = 1_000_000;
export const GEOMETRY = Object.freeze({
  stud_pitch: 5,
  layer_height: 6,
  units: "relative",
});
export const CATALOG = Object.freeze(
  [
    ["1x1", 1, 1],
    ["2x1", 2, 1],
    ["4x1", 4, 1],
    ["6x1", 6, 1],
    ["2x2", 2, 2],
    ["2x3", 2, 3],
    ["2x4", 2, 4],
    ["2x6", 2, 6],
    ["2x8", 2, 8],
  ].map(([id, width, length]) =>
    Object.freeze({
      id,
      studs: Object.freeze([width, length]),
      height_layers: 1,
      role: id === "1x1" ? "detail" : "structure",
    }),
  ),
);

export function validateQuantity(value) {
  if (!Number.isSafeInteger(value) || value < 0 || value > MAX_QUANTITY) {
    throw new Error(
      `Quantities must be whole numbers from 0 to ${MAX_QUANTITY.toLocaleString("en-US")}.`,
    );
  }
  return value;
}

export function emptyInventory() {
  return {
    schema_version: SCHEMA_VERSION,
    name: "My brick collection",
    geometry: { ...GEOMETRY },
    parts: CATALOG.map((part) => ({
      ...part,
      studs: [...part.studs],
      quantity: 0,
    })),
  };
}

// Strictly validate imports before replacing any state. Derived geometry and roles
// are fixed by the catalog, so a file cannot silently change solver assumptions.
export function validateInventory(value) {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Expected an inventory JSON object.");
  if (value.schema_version !== SCHEMA_VERSION)
    throw new Error(
      "Unsupported inventory version. Expected schema_version 1.",
    );
  if (
    typeof value.name !== "string" ||
    !value.name.trim() ||
    value.name.length > 80
  ) {
    throw new Error("The collection name must contain 1–80 characters.");
  }
  if (
    value.geometry?.stud_pitch !== 5 ||
    value.geometry?.layer_height !== 6 ||
    value.geometry?.units !== "relative"
  ) {
    throw new Error(
      "Brick geometry must use relative stud pitch 5 and layer height 6.",
    );
  }
  if (!Array.isArray(value.parts) || value.parts.length !== CATALOG.length) {
    throw new Error(
      "The inventory must contain all nine supported brick sizes exactly once.",
    );
  }
  const seen = new Set();
  for (const part of value.parts) {
    const catalog = CATALOG.find((entry) => entry.id === part?.id);
    if (!catalog || seen.has(part.id))
      throw new Error(
        "The inventory contains an unknown or duplicate brick size.",
      );
    seen.add(part.id);
    if (
      !Array.isArray(part.studs) ||
      part.studs.length !== 2 ||
      part.studs.some((n, i) => n !== catalog.studs[i]) ||
      part.height_layers !== 1 ||
      part.role !== catalog.role
    ) {
      throw new Error(
        `Invalid dimensions or role for ${part.id}. The 1×1 is reserved for details; all other sizes are structural.`,
      );
    }
    validateQuantity(part.quantity);
  }
  return {
    schema_version: SCHEMA_VERSION,
    name: value.name.trim(),
    geometry: { ...GEOMETRY },
    parts: CATALOG.map((part) => ({
      ...part,
      studs: [...part.studs],
      quantity: value.parts.find((entry) => entry.id === part.id).quantity,
    })),
  };
}

export function summarize(inventory) {
  return inventory.parts.reduce(
    (totals, part) => {
      totals.pieces += part.quantity;
      totals.types += Number(part.quantity > 0);
      totals.studCells += part.quantity * part.studs[0] * part.studs[1];
      if (part.role === "detail") totals.detailPieces += part.quantity;
      else {
        totals.structuralPieces += part.quantity;
        totals.structuralStudCells +=
          part.quantity * part.studs[0] * part.studs[1];
      }
      return totals;
    },
    {
      pieces: 0,
      types: 0,
      studCells: 0,
      structuralPieces: 0,
      structuralStudCells: 0,
      detailPieces: 0,
    },
  );
}
