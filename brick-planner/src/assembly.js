import { createAssemblyViewer, PART_COLORS } from "./assembly-viewer.js";

const $ = (id) => document.getElementById(id);
const format = (n) => Number(n).toLocaleString("en-US");
const SETTINGS_KEY = "topoleg-assembly-settings-v1";
const JOB_KEY = "topoleg-assembly-job-v1";
let inventory = null, topology = null, jobId = null, pollTimer = null, playing = null;
let result = null, ordered = [], viewer = null, resultSignature = null, runningSignature = null;
let runInventory = null, resultInventory = null, sequenceByBrick = new Map(), starting = false;
let renderedResult = null;
let noticeKind = "none";

$("assembly-view").innerHTML = `
  <div class="workspace-heading">
    <div><p class="eyebrow">03 / FROM SHAPE TO BRICKS</p><h1>Assembly planner</h1>
    <p class="intro">Find a connected build using the bricks you have, then explore it piece by piece.</p></div>
    <button id="assembly-export" class="button secondary" disabled>Export assembly ↓</button>
  </div>
  <div id="assembly-notice" class="notice" role="status" hidden></div>
  <div class="assembly-layout">
    <div class="assembly-main">
      <div id="assembly-empty" class="assembly-empty">
        <span class="assembly-empty-icon" aria-hidden="true">▦</span><h2>Your assembled structure</h2>
        <p>A completed plan will appear here with individual bricks and a step-by-step assembly preview.</p>
        <span class="small-tag">RELATIVE BRICK PROPORTIONS · 5 : 5 : 6</span>
      </div>
      <section id="assembly-preview" class="preview-panel" aria-label="Assembly preview" hidden>
        <div class="preview-toolbar"><div><strong id="assembly-preview-title">Assembled structure</strong>
        <span id="assembly-preview-subtitle">Drag to rotate · scroll to zoom</span></div>
        <button id="assembly-reset" class="button secondary small">Reset view</button></div>
        <div id="assembly-canvas" class="assembly-canvas"></div>
        <div id="assembly-viewer-error" class="assembly-viewer-error" hidden>3D rendering is unavailable in this browser. The assembly measurements, piece list, and exported plan remain available.</div>
        <div class="assembly-legend" id="assembly-legend" aria-label="Brick color legend"></div>
        <div class="assembly-sequence">
          <div class="assembly-sequence-heading"><strong>Assembly sequence</strong><output id="assembly-step-label" for="assembly-step">Complete build</output></div>
          <input id="assembly-step" type="range" min="0" max="1" value="1" step="1" aria-label="Number of assembled pieces" />
          <div class="assembly-sequence-controls">
            <button id="assembly-back" class="button secondary small" aria-label="Previous assembly step">← Previous</button>
            <button id="assembly-play" class="button secondary small">Play steps</button>
            <button id="assembly-next" class="button secondary small" aria-label="Next assembly step">Next →</button>
            <button id="assembly-complete" class="text-button">Show complete</button>
          </div>
          <p id="assembly-step-info" class="field-help"></p>
          <p class="field-help">Step outlines: dark = new piece · blue = completed attachment pieces.</p>
        </div>
      </section>
      <section id="assembly-report" class="assembly-report" hidden>
        <div class="assembly-report-heading"><h2>Build report</h2><span id="assembly-result-badge" class="small-tag"></span></div>
        <div id="assembly-metrics" class="assembly-metrics"></div>
        <p id="assembly-dimensions" class="field-help"></p>
        <ul id="assembly-checks" class="assembly-checks"></ul>
        <div id="assembly-result-message" class="field-help"></div>
        <ul id="assembly-warnings" class="assembly-warnings" hidden></ul>
        <details class="assembly-details"><summary>Pieces used</summary><div id="assembly-parts"></div></details>
        <details class="assembly-details"><summary>Assumptions for this plan</summary><ul id="assembly-assumptions"></ul></details>
      </section>
    </div>
    <aside class="assembly-sidebar" aria-label="Assembly settings">
      <section class="topology-settings">
        <h2>Build preferences</h2>
        <form id="assembly-form"><fieldset id="assembly-fields">
          <label for="assembly-cap">Approximate piece cap</label>
          <input id="assembly-cap" type="number" min="1" max="1000000" step="1" placeholder="Use available inventory" inputmode="numeric" />
          <p class="field-help">Leave blank to use as much of your collection as a feasible build allows.</p>
          <label for="assembly-tolerance">Allowed cap overrun</label>
          <div class="assembly-tolerance-field"><input id="assembly-tolerance" type="number" min="0" max="20" step="1" value="5" required inputmode="numeric" /><span>%</span></div>
          <p id="assembly-budget-help" class="field-help">Default: up to 5% above your cap. Fewer pieces may give a better connected fit.</p>
          <label for="assembly-symmetry">Symmetry</label>
          <select id="assembly-symmetry"><option value="auto">Detect automatically</option><option value="none">No symmetry constraint</option><option value="x">Source X plane</option><option value="y">Source Y plane</option><option value="z">Source Z plane</option></select>
          <p class="field-help">Symmetric portions must lock together through bricks crossing the center plane.</p>
        </fieldset>
        <div class="assembly-run-controls"><button id="assembly-run" type="submit" class="button primary" disabled>Generate assembly</button><button id="assembly-cancel" type="button" class="button secondary" hidden>Cancel</button></div>
        </form>
        <p id="assembly-status" class="field-help" role="status">Load a topology and add structural bricks to begin.</p>
      </section>
      <section class="topology-inventory">
        <p class="eyebrow">CURRENT INPUTS</p><h2 id="assembly-inventory-name">Your collection</h2>
        <p id="assembly-inventory-summary">Waiting for inventory…</p>
        <h2 id="assembly-topology-name">No topology loaded</h2><p id="assembly-topology-summary">Choose an NPZ in the Topology tab.</p>
        <a href="#inventory">Edit inventory</a> <span aria-hidden="true"> · </span> <a href="#topology">Inspect topology</a>
      </section>
      <p class="topology-local-note">1×1 bricks are reserved for surface details. Connections require overlapping studs between layers. The preview colors identify sizes, independent of the colors you own.</p>
    </aside>
  </div>`;

function notice(text, error = false, kind = error ? "error" : "info") {
  noticeKind = text ? kind : "none";
  $("assembly-notice").textContent = text;
  $("assembly-notice").hidden = !text;
  $("assembly-notice").classList.toggle("error", error);
}
function preferences() {
  return {
    piece_cap: $("assembly-cap").value === "" ? null : Number($("assembly-cap").value),
    tolerance: Number($("assembly-tolerance").value) / 100,
    symmetry: $("assembly-symmetry").value,
  };
}
function signature() {
  return JSON.stringify({ parts: inventory?.inventory.parts, topologyId: topology?.serverId, settings: topology?.settings, key: topology?.key, preferences: preferences() });
}
function changed() {
  const cap = preferences().piece_cap;
  $("assembly-budget-help").textContent = cap
    ? `Up to ${format(Math.floor(cap * (1 + preferences().tolerance) + 1e-8))} pieces, within your inventory. A feasible fit can use fewer.`
    : "No cap: use available structural inventory. 1×1 pieces remain reserved for details.";
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(preferences())); } catch { /* Session controls still work. */ }
  if (result && resultSignature !== signature() && noticeKind !== "error") {
    notice("Inputs have changed. This preview belongs to the previous plan; generate an assembly to update it.", false, "stale");
  } else if (result && resultSignature === signature() && noticeKind === "stale") {
    notice("");
  }
  readiness();
}
function readiness() {
  $("assembly-run").disabled = starting || Boolean(jobId) || !topology?.serverId || !inventory?.totals.structuralPieces;
  if (jobId || starting) return;
  $("assembly-status").textContent = !topology?.serverId
    ? topology ? topology.syncing ? "Preparing topology for the local planner…" : "Topology is not synced to the planner. Open the Topology tab to retry." : "Load a topology in the Topology tab to begin."
    : !inventory?.totals.structuralPieces ? "Add structural bricks to your inventory to begin."
    : "Ready to search for a connected assembly.";
}
document.addEventListener("topoleg:inventory", ({ detail }) => {
  inventory = detail;
  $("assembly-inventory-name").textContent = detail.inventory.name;
  $("assembly-inventory-summary").textContent = `${format(detail.totals.structuralPieces)} structural bricks · ${format(detail.totals.detailPieces)} detail bricks`;
  changed();
});
document.addEventListener("topoleg:topology", ({ detail }) => {
  topology = detail;
  $("assembly-topology-name").textContent = detail?.name || "No topology loaded";
  $("assembly-topology-summary").textContent = detail?.settings
    ? `${detail.key || "density"} · threshold ${Number(detail.settings.threshold).toFixed(2)} · ${detail.settings.up.toUpperCase()} up${detail.settings.mirror !== "none" ? ` · mirror ${detail.settings.mirror.toUpperCase()}` : ""}`
    : "Choose an NPZ in the Topology tab.";
  changed();
});
document.addEventListener("topoleg:view", ({ detail }) => {
  if (detail !== "assembly") { stopPlaying(); return; }
  if (result) drawPreview();
  viewer?.resize();
});
for (const id of ["assembly-cap", "assembly-tolerance", "assembly-symmetry"]) $(id).addEventListener("input", changed);
try {
  const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
  if (saved && (saved.piece_cap === null || Number.isInteger(saved.piece_cap) && saved.piece_cap > 0 && saved.piece_cap <= 1000000)) $("assembly-cap").value = saved.piece_cap ?? "";
  if (saved && Number.isFinite(saved.tolerance) && saved.tolerance >= 0 && saved.tolerance <= 0.2) $("assembly-tolerance").value = Math.round(saved.tolerance * 100);
  if (["auto", "none", "x", "y", "z"].includes(saved?.symmetry)) $("assembly-symmetry").value = saved.symmetry;
} catch { /* Ignore invalid saved preferences. */ }

async function request(url, options = {}) {
  const response = await fetch(url, options);
  let data;
  try { data = await response.json(); } catch { throw new Error("The local planner did not respond. Restart the TopoLegOpt server and try again."); }
  if (!response.ok) {
    const error = new Error(typeof data.detail === "string" ? data.detail : data.error || `Planner request failed (${response.status}).`);
    error.status = response.status;
    throw error;
  }
  return data;
}
function setRunning(value) {
  $("assembly-fields").disabled = value;
  $("assembly-run").disabled = value;
  $("assembly-run").textContent = value ? "Searching…" : "Generate assembly";
  $("assembly-cancel").hidden = !value;
  $("assembly-cancel").disabled = false;
  $("assembly-view").setAttribute("aria-busy", String(value));
  if (!value) readiness();
}
$("assembly-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (starting || jobId || !topology?.serverId || !inventory?.totals.structuralPieces || !$("assembly-form").reportValidity()) return;
  stopPlaying();
  notice("");
  runningSignature = signature();
  runInventory = JSON.parse(JSON.stringify(inventory.inventory));
  starting = true;
  setRunning(true);
  $("assembly-cancel").disabled = true;
  $("assembly-status").textContent = "Starting scale and connection search…";
  try {
    const data = await request("/api/assembly", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ topology_id: topology.serverId, inventory: inventory.inventory, options: { ...preferences(), ...topology.settings, key: topology.key } }) });
    if (!data.job_id) throw new Error("The planner did not return a job ID.");
    jobId = data.job_id;
    try { localStorage.setItem(JOB_KEY, JSON.stringify({ id: jobId, signature: runningSignature, inventory: runInventory })); } catch { /* Job still runs without browser persistence. */ }
    starting = false;
    $("assembly-cancel").disabled = false;
    await poll(jobId);
  } catch (error) {
    starting = false;
    jobId = null;
    setRunning(false);
    notice(error.message, true);
  }
});
async function poll(id) {
  if (id !== jobId) return;
  try {
    const data = await request(`/api/jobs/${encodeURIComponent(id)}`);
    if (id !== jobId) return;
    if (data.status === "completed") {
      jobId = null;
      setRunning(false);
      try { showResult(data.result); } catch (error) { notice(error.message, true); }
      return;
    }
    if (["failed", "cancelled"].includes(data.status)) {
      try { localStorage.removeItem(JOB_KEY); } catch { /* Optional persistence. */ }
      jobId = null;
      setRunning(false);
      notice(data.status === "cancelled" ? "Search cancelled. Adjust preferences and try again." : data.error || "The search could not finish.", data.status === "failed");
      return;
    }
    $("assembly-status").textContent = typeof data.progress === "string" ? data.progress : data.message || (data.status === "queued" ? "Queued for the local planner…" : "Searching scales, brick placements, and stud connections…");
    pollTimer = setTimeout(() => void poll(id), 1000);
  } catch (error) {
    if (error.status === 404 || error.status === 410) {
      try { localStorage.removeItem(JOB_KEY); } catch { /* Optional persistence. */ }
      jobId = null;
      setRunning(false);
      notice("The previous search is no longer available on the local server. Generate a new assembly.");
      return;
    }
    // Preserve the ID: a temporary network interruption must not launch duplicate searches.
    $("assembly-status").textContent = `${error.message} Retrying this search…`;
    pollTimer = setTimeout(() => void poll(id), 3000);
  }
}
$("assembly-cancel").addEventListener("click", async () => {
  if (!jobId) return;
  const cancelledId = jobId;
  $("assembly-cancel").disabled = true;
  try {
    const status = await request(`/api/jobs/${encodeURIComponent(cancelledId)}`, { method: "DELETE" });
    // A poll may finish this job, and the user may begin another, while the
    // cancellation request is in flight. Never clear the newer job's state.
    if (jobId !== cancelledId) return;
    clearTimeout(pollTimer);
    if (status.status !== "cancelled") {
      $("assembly-cancel").disabled = false;
      await poll(cancelledId);
      return;
    }
    try { localStorage.removeItem(JOB_KEY); } catch { /* Optional persistence. */ }
    jobId = null;
    setRunning(false);
    notice("Search cancelled. Adjust preferences and try again.");
  } catch (error) {
    if (jobId !== cancelledId) return;
    $("assembly-cancel").disabled = false;
    notice(error.message, true);
  }
});

function item(tag, text, className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}
function metric(label, value) {
  const node = item("div", "");
  node.append(item("strong", value), item("span", label));
  return node;
}
function checkValue(validation, ...names) {
  for (const name of names) if (typeof validation[name] === "boolean") return validation[name];
  return null;
}
function showResult(value) {
  if (!value || !Array.isArray(value.placements)) throw new Error("The planner returned an invalid assembly result.");
  result = value;
  resultInventory = runInventory;
  resultSignature = runningSignature;
  const byId = new Map(result.placements.map((p) => [String(p.id), p]));
  const sequence = Array.isArray(result.sequence) ? result.sequence : [];
  sequenceByBrick = new Map();
  const sequenceIds = sequence.flatMap((step) => {
    const ids = typeof step === "object" ? step.brick_ids || [step.placement_id ?? step.brick_id ?? step.id] : [step];
    for (const id of ids) sequenceByBrick.set(String(id), step);
    return ids;
  });
  ordered = sequenceIds.map((id) => byId.get(String(id))).filter(Boolean);
  const hasCompleteSequence = ordered.length === result.placements.length && new Set(ordered).size === result.placements.length;
  if (!hasCompleteSequence) ordered = [...result.placements].sort((a, b) => a.y - b.y || a.x - b.x || a.z - b.z);
  const validation = result.validation || {};
  const checks = [
    ["Stud-connected structure", checkValue(validation, "connected")],
    ["No overlapping bricks", checkValue(validation, "no_overlaps", "non_overlapping")],
    ["Within available inventory", checkValue(validation, "inventory_valid", "inventory")],
    ["Within cap and tolerance", checkValue(validation, "budget_valid", "budget")],
    ["Requested symmetry", checkValue(validation, "symmetry_valid", "symmetry")],
    ["Bricks cross symmetry planes", checkValue(validation, "center_bridges_valid", "center_bridges")],
  ];
  const verified = Boolean(result.success) && validation.valid === true && checks.every(([, valid]) => valid === true);
  $("assembly-result-badge").textContent = verified ? "GEOMETRY CHECKS PASSED" : "NO VALIDATED PLAN";
  $("assembly-result-badge").classList.toggle("assembly-warning", !verified);
  const hasSymmetry = (result.symmetry?.build_axes || validation.symmetry_axes || []).length > 0;
  $("assembly-checks").replaceChildren(...checks.map(([label, valid]) => {
    const na = !hasSymmetry && (label === "Requested symmetry" || label === "Bricks cross symmetry planes");
    return item("li", `${na ? "—" : valid === true ? "✓" : valid === false ? "✕" : "?"} ${label}${na ? " · not requested" : valid === null ? " · not reported" : ""}`, valid === true ? "passed" : "failed");
  }));
  const metrics = result.metrics || {};
  const pieceCount = result.placements.length;
  const detailCount = result.placements.filter((p) => p.part_id === "1x1").length;
  const metricNodes = [metric("pieces used", format(pieceCount)), metric("structural / detail", `${format(pieceCount - detailCount)} / ${format(detailCount)}`)];
  const iou = metrics.iou ?? metrics.shape_iou;
  if (Number.isFinite(iou)) metricNodes.push(metric("shape overlap (IoU)", `${(iou * 100).toFixed(1)}%`));
  if (pieceCount) metricNodes.push(metric("brick layers", format(new Set(result.placements.map((p) => p.y)).size)));
  if (Number.isFinite(metrics.target_coverage)) metricNodes.push(metric("target volume covered", `${(metrics.target_coverage * 100).toFixed(1)}%`));
  if (Number.isFinite(metrics.material_precision)) metricNodes.push(metric("brick volume inside target", `${(metrics.material_precision * 100).toFixed(1)}%`));
  if (Number.isFinite(metrics.structural_utilization)) metricNodes.push(metric("structural inventory used", `${(metrics.structural_utilization * 100).toFixed(1)}%`));
  if (Number.isFinite(metrics.maximum_pieces)) metricNodes.push(metric("allowed piece maximum", format(metrics.maximum_pieces)));
  $("assembly-metrics").replaceChildren(...metricNodes);
  if (pieceCount) {
    const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
    for (const p of result.placements) {
      min[0] = Math.min(min[0], p.x); min[1] = Math.min(min[1], p.y); min[2] = Math.min(min[2], p.z);
      max[0] = Math.max(max[0], p.x + p.width); max[1] = Math.max(max[1], p.y + (p.height || 1)); max[2] = Math.max(max[2], p.z + p.depth);
    }
    $("assembly-dimensions").textContent = `Build bounds: ${max[0] - min[0]} × ${max[2] - min[2]} studs · ${max[1] - min[1]} layers. Relative size: ${(max[0] - min[0]) * 5} × ${(max[2] - min[2]) * 5} × ${(max[1] - min[1]) * 6} (width × depth × height).`;
  } else $("assembly-dimensions").textContent = "";
  $("assembly-report").hidden = false;
  $("assembly-export").disabled = false;
  $("assembly-result-message").textContent = result.message || (verified ? "The checks validate grid geometry and stud connections. Physical strength and stability are not simulated. Follow the sequence notes for temporary hand support." : "The search did not establish a plan that passes every required geometry check. Any candidate shown is experimental.");
  const warnings = [...new Set([...(result.warnings || []), ...(result.diagnostics || []), ...(validation.warnings || []), ...(validation.errors || [])])];
  $("assembly-warnings").replaceChildren(...warnings.map((text) => item("li", text)));
  $("assembly-warnings").hidden = warnings.length === 0;
  const counts = new Map();
  for (const p of result.placements) counts.set(p.part_id, (counts.get(p.part_id) || 0) + 1);
  const table = document.createElement("table");
  const heading = document.createElement("tr");
  for (const label of ["Brick size", "Used", "Available"]) heading.append(item("th", label));
  const tableHead = document.createElement("thead");
  tableHead.append(heading);
  table.append(tableHead);
  const tableBody = document.createElement("tbody");
  // The result can carry the inventory snapshot used by the solver.
  for (const [id, count] of counts) {
    const row = document.createElement("tr");
    const available = result.input?.inventory?.parts?.find((p) => p.id === id)?.quantity ?? result.inventory?.parts?.find((p) => p.id === id)?.quantity ?? resultInventory?.parts.find((p) => p.id === id)?.quantity;
    row.append(item("td", id.replace("x", " × ")), item("td", format(count)), item("td", available === undefined ? "—" : format(available)));
    tableBody.append(row);
  }
  table.append(tableBody);
  $("assembly-parts").replaceChildren(table);
  const assumptions = Array.isArray(result.assumptions) ? result.assumptions : [];
  $("assembly-assumptions").replaceChildren(...assumptions.map((text) => item("li", text)));
  $("assembly-empty").hidden = pieceCount > 0;
  $("assembly-preview").hidden = pieceCount === 0;
  $("assembly-preview-title").textContent = verified ? "Assembled structure" : "Experimental candidate · validation incomplete";
  $("assembly-step").max = pieceCount;
  $("assembly-step").value = pieceCount;
  $("assembly-legend").replaceChildren(...[...counts.keys()].map((id) => {
    const label = item("span", "");
    const dot = item("i", "");
    dot.style.backgroundColor = PART_COLORS[id] || "#658c9f";
    label.append(dot, document.createTextNode(id.replace("x", " × ")));
    return label;
  }));
  $("assembly-play").disabled = !hasCompleteSequence;
  if (!verified) notice(result.message || "No verified assembly was found for these inputs. Review the build report before changing your inventory or preferences.", true);
  else if (resultSignature !== signature()) notice("This plan uses the inputs from when the search started. Inputs have since changed.", false, "stale");
  else notice("Assembly ready. Explore the finished model or step through the build.");
  drawPreview();
  showStep(pieceCount, false);
}
function drawPreview() {
  if (!ordered.length || $("assembly-view").hidden) return;
  try {
    viewer ||= createAssemblyViewer($("assembly-canvas"));
    if (renderedResult !== result) {
      viewer.update(ordered);
      renderedResult = result;
    }
    const count = Number($("assembly-step").value);
    viewer.showStep(count, count < ordered.length, sequenceByBrick.get(String(ordered[count - 1]?.id))?.attached_to || []);
    $("assembly-viewer-error").hidden = true;
  } catch {
    viewer?.dispose();
    viewer = null;
    renderedResult = null;
    $("assembly-canvas").replaceChildren();
    $("assembly-viewer-error").hidden = false;
  }
}
function showStep(value, emphasize = true) {
  const count = Math.max(0, Math.min(ordered.length, Number(value)));
  $("assembly-step").value = count;
  $("assembly-step-label").value = count === ordered.length ? `Complete · ${format(count)} pieces` : `${format(count)} / ${format(ordered.length)} pieces`;
  $("assembly-back").disabled = count === 0;
  $("assembly-next").disabled = count === ordered.length;
  const p = ordered[count - 1];
  const sequenceStep = p && sequenceByBrick.get(String(p.id));
  $("assembly-step-info").textContent = p
    ? `Step ${format(count)}: ${p.part_id.replace("x", " × ")} brick · layer ${p.y + 1} · stud origin X ${p.x}, Z ${p.z} · footprint ${p.width} × ${p.depth}. ${sequenceStep?.instruction || "Coordinates start at zero; layers start at one."}${sequenceStep?.requires_support ? " Temporarily support the assembly while attaching this piece." : ""}`
    : "Start with an empty build surface.";
  viewer?.showStep(count, emphasize, sequenceStep?.attached_to || []);
}
function stopPlaying() { clearInterval(playing); playing = null; $("assembly-play").textContent = "Play steps"; }
$("assembly-step").addEventListener("input", () => { stopPlaying(); showStep($("assembly-step").value); });
$("assembly-back").addEventListener("click", () => { stopPlaying(); showStep(Number($("assembly-step").value) - 1); });
$("assembly-next").addEventListener("click", () => { stopPlaying(); showStep(Number($("assembly-step").value) + 1); });
$("assembly-complete").addEventListener("click", () => { stopPlaying(); showStep(ordered.length, false); });
$("assembly-reset").addEventListener("click", () => viewer?.reset());
$("assembly-play").addEventListener("click", () => {
  if (playing) { stopPlaying(); return; }
  if (Number($("assembly-step").value) >= ordered.length) showStep(0);
  $("assembly-play").textContent = "Pause";
  playing = setInterval(() => {
    showStep(Number($("assembly-step").value) + 1);
    if (Number($("assembly-step").value) >= ordered.length) stopPlaying();
  }, 700);
});
$("assembly-export").addEventListener("click", () => {
  if (!result) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "topoleg-assembly.json";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});
changed();
document.dispatchEvent(new Event("topoleg:request-inventory"));
document.dispatchEvent(new Event("topoleg:request-topology"));
try {
  const previousJob = JSON.parse(localStorage.getItem(JOB_KEY));
  if (previousJob && typeof previousJob.id === "string" && previousJob.id) {
    jobId = previousJob.id;
    runningSignature = previousJob.signature;
    runInventory = previousJob.inventory;
    setRunning(true);
    $("assembly-status").textContent = "Restoring the last assembly search…";
    void poll(jobId);
  }
} catch { /* Ignore invalid stored job context. */ }
