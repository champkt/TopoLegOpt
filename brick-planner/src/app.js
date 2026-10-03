import {
  CATALOG,
  MAX_QUANTITY,
  emptyInventory,
  validateInventory,
  validateQuantity,
  summarize,
} from "./inventory.js";

const STORAGE_KEY = "topoleg.inventory.v1";
// Preserve this key across the TopoLegOpt rename: existing collections must survive.
const $ = (id) => document.getElementById(id);
const format = (value) => value.toLocaleString("en-US");
let inventory = emptyInventory();
let importCandidate = null;
let dialogAction = null;

function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
  $("notice").hidden = false;
}

try {
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) inventory = validateInventory(JSON.parse(saved));
} catch {
  $("save-status").textContent = "Could not load saved data";
  notice(
    "Saved inventory could not be loaded. Import a backup or enter quantities to start a new collection. Existing browser data is unchanged until you edit.",
    true,
  );
}

function persist() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(inventory));
    $("save-status").textContent = "Saved in this browser";
  } catch {
    $("save-status").textContent = "Not saved · export a backup";
    notice(
      "Browser storage is unavailable. Your changes are in memory for this session; export your inventory before closing the page.",
      true,
    );
  }
}

// Isometric dimension diagrams: 5 units per stud and 6 units per layer.
// These are catalog geometry, not pictures of specific commercial molds.
function brickDiagram(part) {
  const long = Math.max(...part.studs) * 5;
  const short = Math.min(...part.studs) * 5;
  const scale = Math.min(
    4.5,
    175 / ((long + short) * 0.866),
    92 / ((long + short) * 0.5 + 6.7),
  );
  const centerY = 56 + 3.35 * scale;
  const project = (x, y, z) => [
    105 + (x - y - (long - short) / 2) * 0.866 * scale,
    centerY + ((x + y - (long + short) / 2) * 0.5 - z) * scale,
  ];
  const p = (x, y, z) => project(x, y, z).join(",");
  const gold = part.role === "detail";
  const top = gold ? "#f4c35e" : "#7cabc1";
  const front = gold ? "#c78a28" : "#466e84";
  const side = gold ? "#dfa235" : "#5e8ca3";
  let studs = "";
  for (let x = 2.5; x < long; x += 5) {
    for (let y = 2.5; y < short; y += 5) {
      const [cx, cy] = project(x, y, 6);
      studs += `<ellipse cx="${cx}" cy="${cy}" rx="${1.6 * scale}" ry="${0.92 * scale}" fill="${front}"/><ellipse cx="${cx}" cy="${cy - 0.7 * scale}" rx="${1.6 * scale}" ry="${0.92 * scale}" fill="${top}" stroke="${side}" stroke-width=".7"/>`;
    }
  }
  return `<svg viewBox="0 0 210 112" aria-hidden="true" focusable="false"><polygon points="${p(0, short, 6)} ${p(long, short, 6)} ${p(long, short, 0)} ${p(0, short, 0)}" fill="${side}"/><polygon points="${p(long, 0, 6)} ${p(long, short, 6)} ${p(long, short, 0)} ${p(long, 0, 0)}" fill="${front}"/><polygon points="${p(0, 0, 6)} ${p(long, 0, 6)} ${p(long, short, 6)} ${p(0, short, 6)}" fill="${top}"/>${studs}</svg>`;
}

$("brick-grid").innerHTML = CATALOG.map((part) => {
  const label = part.id.replace("x", " × ");
  return `<article class="brick-card" id="card-${part.id}" aria-labelledby="title-${part.id}"><div class="card-title"><h3 id="title-${part.id}">${label}</h3><span class="role-label ${part.role === "detail" ? "detail" : ""}">${part.role === "detail" ? "Detail only" : "Structural"}</span></div><div class="brick-diagram">${brickDiagram(part)}</div><div class="card-bottom"><label class="quantity-label" for="quantity-${part.id}">Quantity</label><div class="stepper"><button type="button" data-id="${part.id}" data-delta="-1" aria-label="Remove one ${label} brick">−</button><input id="quantity-${part.id}" data-id="${part.id}" type="number" inputmode="numeric" min="0" max="${MAX_QUANTITY}" step="1" aria-label="${label} brick quantity" value="0"><button type="button" data-id="${part.id}" data-delta="1" aria-label="Add one ${label} brick">+</button></div></div></article>`;
}).join("");

function renderSummary() {
  const totals = summarize(inventory);
  $("total-pieces").textContent = format(totals.pieces);
  $("structural-count").textContent = format(totals.structuralPieces);
  $("detail-count").textContent = format(totals.detailPieces);
  $("type-count").textContent = `${totals.types} / 9`;
  $("volume-count").textContent = format(totals.structuralStudCells);
  $("structural-bar").style.width =
    `${totals.pieces ? (100 * totals.structuralPieces) / totals.pieces : 0}%`;
  $("detail-bar").style.width =
    `${totals.pieces ? (100 * totals.detailPieces) / totals.pieces : 0}%`;
  $("inventory-hint").textContent = !totals.pieces
    ? "Add your quantities to prepare an inventory for the planner."
    : !totals.structuralPieces
      ? "Only detail bricks so far. Add larger bricks to provide material for the main structure."
      : `${format(totals.structuralPieces)} structural bricks available. A feasible build size will depend on the topology and connections.`;
  for (const part of inventory.parts) {
    $(`card-${part.id}`).classList.toggle("in-stock", part.quantity > 0);
    document.querySelector(`[data-id="${part.id}"][data-delta="-1"]`).disabled =
      part.quantity === 0;
    document.querySelector(`[data-id="${part.id}"][data-delta="1"]`).disabled =
      part.quantity === MAX_QUANTITY;
  }
  $("clear-button").disabled = totals.pieces === 0;
  shareInventory();
}

function shareInventory() {
  document.dispatchEvent(
    new CustomEvent("topoleg:inventory", {
      detail: {
        inventory: validateInventory(inventory),
        totals: summarize(inventory),
      },
    }),
  );
}
document.addEventListener("topoleg:request-inventory", shareInventory);

function showView() {
  const view = ['#topology', '#assembly'].includes(location.hash) ? location.hash.slice(1) : 'inventory';
  $("inventory-view").hidden = view !== "inventory";
  $("topology-view").hidden = view !== "topology";
  $("assembly-view").hidden = view !== "assembly";
  for (const link of document.querySelectorAll("[data-view]")) {
    if (link.dataset.view === view) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  document.dispatchEvent(new CustomEvent("topoleg:view", { detail: view }));
}
window.addEventListener("hashchange", showView);
showView();

function render() {
  $("collection-name").value = inventory.name;
  for (const part of inventory.parts) {
    const input = $(`quantity-${part.id}`);
    input.value = part.quantity;
    input.removeAttribute("aria-invalid");
    input.setCustomValidity("");
  }
  $("export-button").disabled = false;
  renderSummary();
}

function setQuantity(id, quantity) {
  const part = inventory.parts.find((entry) => entry.id === id);
  if (!part) throw new Error("Unknown brick size.");
  part.quantity = validateQuantity(quantity);
  persist();
  renderSummary();
}

function hasInvalidQuantity() {
  return Boolean(document.querySelector('.stepper input[aria-invalid="true"]'));
}

$("brick-grid").addEventListener("input", (event) => {
  const input = event.target;
  if (!input.matches("input[data-id]")) return;
  try {
    if (!/^\d+$/.test(input.value))
      throw new Error("Enter a non-negative whole number.");
    const quantity = validateQuantity(Number(input.value));
    input.removeAttribute("aria-invalid");
    input.setCustomValidity("");
    setQuantity(input.dataset.id, quantity);
  } catch {
    input.setAttribute("aria-invalid", "true");
    input.setCustomValidity(
      `Enter a whole number from 0 to ${format(MAX_QUANTITY)}.`,
    );
    $("save-status").textContent = "Quantity not saved · check input";
  }
  $("export-button").disabled = hasInvalidQuantity();
});

$("brick-grid").addEventListener("focusout", (event) => {
  const input = event.target;
  if (!input.matches("input[data-id]")) return;
  if (input.hasAttribute("aria-invalid")) {
    input.value = inventory.parts.find(
      (part) => part.id === input.dataset.id,
    ).quantity;
    input.removeAttribute("aria-invalid");
    input.setCustomValidity("");
    notice(
      `Invalid quantity was not saved. Restored the previous count for ${input.dataset.id.replace("x", " × ")}. Enter a whole number from 0 to ${format(MAX_QUANTITY)}.`,
      true,
    );
    persist();
  } else input.value = Number(input.value);
  $("export-button").disabled = hasInvalidQuantity();
});

$("brick-grid").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-delta]");
  if (!button) return;
  const part = inventory.parts.find((entry) => entry.id === button.dataset.id);
  setQuantity(part.id, part.quantity + Number(button.dataset.delta));
  $(`quantity-${part.id}`).value = part.quantity;
});

$("collection-name").addEventListener("input", (event) => {
  if (event.target.value.trim()) {
    inventory.name = event.target.value.trim();
    persist();
  }
});
$("collection-name").addEventListener("blur", () => {
  $("collection-name").value = inventory.name;
});

$("export-button").addEventListener("click", () => {
  if (hasInvalidQuantity()) return;
  const blob = new Blob(
    [JSON.stringify(validateInventory(inventory), null, 2) + "\n"],
    { type: "application/json" },
  );
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${
    inventory.name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "") || "brick"
  }-inventory.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  notice(
    "Inventory exported. Keep the JSON file as a backup or use it as input for the future planner.",
  );
});

function confirmAction(action, title, description, buttonText) {
  dialogAction = action;
  $("dialog-title").textContent = title;
  $("dialog-description").textContent = description;
  $("dialog-confirm").textContent = buttonText;
  $("confirm-dialog").returnValue = "cancel";
  $("confirm-dialog").showModal();
}

$("import-button").addEventListener("click", () => $("import-file").click());
$("import-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file) return;
  try {
    if (file.size > 100_000)
      throw new Error("Choose an inventory JSON file smaller than 100 KB.");
    importCandidate = validateInventory(JSON.parse(await file.text()));
    const total = summarize(importCandidate).pieces;
    confirmAction(
      "import",
      "Import this inventory?",
      `“${importCandidate.name}” contains ${format(total)} bricks. Importing replaces this browser’s current collection and quantities. Export first if you want to keep a backup.`,
      "Import inventory",
    );
  } catch (error) {
    importCandidate = null;
    notice(
      `Import failed: ${error instanceof SyntaxError ? "This file is not valid JSON." : error.message} Your inventory has not changed.`,
      true,
    );
  }
});

$("clear-button").addEventListener("click", () =>
  confirmAction(
    "clear",
    "Clear all quantities?",
    "All nine brick quantities will be set to zero. Export your inventory first if you want to keep a backup.",
    "Clear quantities",
  ),
);
$("confirm-dialog").addEventListener("close", () => {
  if ($("confirm-dialog").returnValue === "confirm") {
    if (dialogAction === "import" && importCandidate)
      inventory = importCandidate;
    else if (dialogAction === "clear")
      inventory.parts.forEach((part) => {
        part.quantity = 0;
      });
    notice(
      dialogAction === "clear"
        ? "All quantities cleared."
        : "Inventory imported. Your collection is ready to edit.",
    );
    persist();
    render();
  }
  dialogAction = null;
  importCandidate = null;
});

render();

// Optional browser-agent integration. Normal browsers require no polyfill.
if (document.modelContext?.registerTool) {
  const lifecycle = new AbortController();
  try {
    const registration = document.modelContext.registerTool(
      {
        name: "read_brick_inventory",
        title: "Read brick inventory",
        description:
          "Read the current brick quantities, geometry, detail-only rule, and totals. Does not modify the inventory.",
        inputSchema: {
          type: "object",
          properties: {},
          additionalProperties: false,
        },
        annotations: { readOnlyHint: true, untrustedContentHint: true },
        execute(input) {
          if (
            !input ||
            typeof input !== "object" ||
            Array.isArray(input) ||
            Object.keys(input).length
          )
            throw new Error("Expected an empty object.");
          return {
            inventory: validateInventory(inventory),
            totals: summarize(inventory),
          };
        },
      },
      { signal: lifecycle.signal },
    );
    Promise.resolve(registration).catch(() => {
      /* Optional integration cannot block inventory editing. */
    });
  } catch {
    /* Optional integration cannot block inventory editing. */
  }
  window.addEventListener(
    "pagehide",
    (event) => {
      if (!event.persisted) lifecycle.abort();
    },
    { once: true },
  );
}
