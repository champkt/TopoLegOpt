import { MAX_FILE_BYTES } from "./npz.js";
import { DEFAULT_SETTINGS, validateSettings } from "./topology-model.js";
import { createViewer } from "./topology-viewer.js";
import { readSavedTopology, saveTopology } from "./topology-storage.js";

const $ = (id) => document.getElementById(id);
const format = (value) => value.toLocaleString("en-US");
let client = null,
  record = null,
  latest = null,
  viewer = null,
  viewerFailed = false;
let inventoryTotals = null,
  busy = false,
  userChoseFile = false;
let serverSync = false;
function shareTopology() {
  document.dispatchEvent(new CustomEvent('topoleg:topology', {detail: record ? {
    serverId: record.serverId || null, name: record.name, key: record.key,
    settings: { ...record.settings }, syncing: serverSync,
  } : null}));
}
document.addEventListener('topoleg:request-topology', shareTopology);
async function syncToServer(file) {
  serverSync = true;
  $('topology-server-status').textContent = 'Connecting topology to the local solver…';
  shareTopology();
  try {
    const response = await fetch('/api/topology', {
      method: 'POST', headers: {'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(file.name)}, body: file,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || 'Local solver is unavailable.');
    }
    const uploaded = await response.json();
    if (record?.file !== file) return;
    record.serverId = uploaded.id;
    $('topology-server-status').textContent = 'Ready for the local assembly solver';
  } catch (error) {
    if (record?.file !== file) return;
    $('topology-server-status').textContent = `Preview available; solver connection failed. ${error.message} Reload to retry.`;
  } finally {
    if (record?.file === file) { serverSync = false; shareTopology(); }
  }
}

function message(text, error = false) {
  $("topology-notice").textContent = text;
  $("topology-notice").classList.toggle("error", error);
  $("topology-notice").hidden = !text;
}
function setBusy(value) {
  busy = value;
  $("choose-topology").disabled = value;
  $("topology-drop").setAttribute("aria-disabled", String(value));
  $("topology-settings-fields").disabled = value || !record;
  $("topology-view").setAttribute("aria-busy", String(value));
}
function makeWorker() {
  const worker = new Worker(
    new URL("./topology-worker.bundle.js", import.meta.url),
    { type: "module" },
  );
  let nextId = 0;
  const pending = new Map();
  worker.onmessage = ({ data }) => {
    const task = pending.get(data.id);
    if (!task) return;
    clearTimeout(task.timeout);
    pending.delete(data.id);
    if (data.error) task.reject(new Error(data.error));
    else task.resolve(data);
  };
  const fail = () => {
    for (const task of pending.values()) {
      clearTimeout(task.timeout);
      task.reject(
        new Error(
          "Topology processing stopped. Try a smaller file or reload the topology.",
        ),
      );
    }
    pending.clear();
  };
  worker.onerror = fail;
  return {
    call(data, transfer = []) {
      return new Promise((resolve, reject) => {
        const id = ++nextId;
        const timeout = setTimeout(() => {
          worker.terminate();
          fail();
        }, 60000);
        pending.set(id, { resolve, reject, timeout });
        worker.postMessage({ ...data, id }, transfer);
      });
    },
    close() {
      worker.terminate();
      fail();
    },
  };
}
function updateReadiness() {
  $("topology-readiness").textContent = !latest
    ? "Load a topology to prepare for fitting."
    : !latest.result.solidVoxels
      ? "No solid voxels at this threshold. Lower the threshold or choose another array."
      : !inventoryTotals?.structuralPieces
        ? "Topology loaded. Add structural bricks to your inventory before fitting."
        : "Topology and structural inventory are ready for the fitting stage.";
}
document.addEventListener("topoleg:inventory", ({ detail }) => {
  inventoryTotals = detail.totals;
  $("topology-collection").textContent = detail.inventory.name;
  $("topology-brick-count").textContent =
    `${format(detail.totals.structuralPieces)} structural bricks · ${format(detail.totals.detailPieces)} detail bricks`;
  updateReadiness();
});
document.dispatchEvent(new Event("topoleg:request-inventory"));

function drawFallback(result) {
  $("topology-canvas").hidden = true;
  $("topology-fallback").hidden = false;
  $("reset-view").hidden = true;
  $("preview-help").textContent = "Source density slice";
  const canvas = $("slice-canvas");
  canvas.width = result.sourceShape[2];
  canvas.height = result.sourceShape[1];
  const ctx = canvas.getContext("2d");
  const image = ctx.createImageData(canvas.width, canvas.height);
  for (let y = 0; y < canvas.height; y++)
    for (let z = 0; z < canvas.width; z++) {
      const density = result.slice[y * canvas.width + z] / 255;
      const index = ((canvas.height - 1 - y) * canvas.width + z) * 4;
      image.data.set(
        [241 - 175 * density, 245 - 114 * density, 248 - 84 * density, 255],
        index,
      );
    }
  ctx.putImageData(image, 0, 0);
}
function drawPreview() {
  if (!latest || $("topology-view").hidden) return;
  if (!viewer && !viewerFailed) {
    try {
      viewer = createViewer($("topology-canvas"));
    } catch {
      viewerFailed = true;
    }
  }
  if (viewerFailed) drawFallback(latest.result);
  else {
    try {
      viewer.update(latest.result);
    } catch {
      viewerFailed = true;
      drawFallback(latest.result);
    }
  }
}
document.addEventListener("topoleg:view", ({ detail }) => {
  if (detail === "topology") drawPreview();
});
$("reset-view").addEventListener("click", () => viewer?.reset());

function syncSettings() {
  $("density-array").value = record.key;
  $("density-threshold").value = record.settings.threshold;
  $("threshold-value").value = record.settings.threshold.toFixed(2);
  $("up-axis").value = record.settings.up;
  $("mirror-axis").value = record.settings.mirror;
}
function applyResult(response) {
  latest = response;
  const { result, arrays } = response;
  $("density-array").replaceChildren(
    ...arrays.map((array) => {
      const option = document.createElement("option");
      option.value = array.key;
      option.textContent = `${array.key} · ${array.shape.join(" × ")}`;
      return option;
    }),
  );
  syncSettings();
  $("topology-drop").hidden = true;
  $("topology-preview").hidden = false;
  $("topology-statistics").hidden = false;
  $("topology-filename").textContent = record.name;
  $("source-grid").textContent = result.sourceShape.join(" × ");
  $("target-grid").textContent = result.dimensions.join(" × ");
  $("solid-voxels").textContent = format(result.solidVoxels);
  $("solid-fraction").textContent = `${(100 * result.fill).toFixed(2)}%`;
  $("mean-density").textContent = result.mean.toFixed(4);
  $("preview-resolution").textContent =
    result.previewStep === 1
      ? "Full-resolution voxel surface"
      : `Preview simplified in ${result.previewStep}³-voxel blocks · counts remain full resolution`;
  if (!result.solidVoxels)
    message(
      "This threshold leaves no solid voxels. Lower the threshold to see the shape.",
    );
  else if (response.key === "design")
    message(
      "Previewing design variables. Use the density array when available to see the filtered physical shape.",
    );
  else message("");
  drawPreview();
  updateReadiness();
  shareTopology();
}
async function persist() {
  $("topology-save-status").textContent = "Saving topology…";
  try {
    await saveTopology(record);
    $("topology-save-status").textContent = "Saved in this browser";
  } catch {
    $("topology-save-status").textContent =
      "Session only · browser storage unavailable";
  }
}
async function loadFile(file, savedSettings = null) {
  if (busy) return;
  if (!file || !/\.npz$/i.test(file.name)) {
    message("Choose a .npz topology file.", true);
    return;
  }
  if (file.size > MAX_FILE_BYTES) {
    message("Choose an NPZ file smaller than 128 MiB.", true);
    return;
  }
  setBusy(true);
  message(`Reading ${file.name}…`);
  let candidate;
  try {
    candidate = makeWorker();
    const buffer = await file.arrayBuffer();
    const settings = savedSettings
      ? validateSettings(savedSettings.settings)
      : { ...DEFAULT_SETTINGS };
    const response = await candidate.call(
      { type: "load", buffer, settings, key: savedSettings?.key },
      [buffer],
    );
    client?.close();
    client = candidate;
    record = { file, name: file.name, settings, key: response.key };
    applyResult(response);
    await persist();
    void syncToServer(file);
  } catch (error) {
    candidate?.close();
    message(
      `${error.message}${record ? " Your previous topology is unchanged." : ""}`,
      true,
    );
  } finally {
    setBusy(false);
  }
}

$("choose-topology").addEventListener("click", () =>
  $("topology-file").click(),
);
$("topology-file").addEventListener("change", (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (file) {
    userChoseFile = true;
    void loadFile(file);
  }
});
const drop = $("topology-drop");
drop.addEventListener("click", () => {
  if (!busy) $("topology-file").click();
});
drop.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    if (!busy) $("topology-file").click();
  }
});
for (const eventName of ["dragenter", "dragover"])
  drop.addEventListener(eventName, (event) => {
    event.preventDefault();
    drop.classList.add("drag-over");
  });
drop.addEventListener("dragleave", () => drop.classList.remove("drag-over"));
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  drop.classList.remove("drag-over");
  if (busy) return;
  if (event.dataTransfer.files.length !== 1) {
    message("Drop one NPZ file at a time.", true);
    return;
  }
  userChoseFile = true;
  void loadFile(event.dataTransfer.files[0]);
});
$("density-threshold").addEventListener("input", (event) => {
  $("threshold-value").value = Number(event.target.value).toFixed(2);
});
async function changeSettings() {
  if (!record || busy) return;
  const settings = {
    threshold: Number($("density-threshold").value),
    up: $("up-axis").value,
    mirror: $("mirror-axis").value,
  };
  const key = $("density-array").value;
  setBusy(true);
  message("Updating target shape…");
  try {
    const response = await client.call({ type: "update", settings, key });
    record = { ...record, settings, key };
    applyResult(response);
    await persist();
  } catch (error) {
    syncSettings();
    message(`${error.message} Previous settings restored.`, true);
  } finally {
    setBusy(false);
  }
}
for (const id of [
  "density-array",
  "density-threshold",
  "up-axis",
  "mirror-axis",
])
  $(id).addEventListener("change", changeSettings);

try {
  const saved = await readSavedTopology();
  if (saved && !userChoseFile && !busy) await loadFile(saved.file, saved);
} catch {
  message(
    "Topology storage is unavailable. You can still load and inspect a file for this session.",
  );
}
