import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export const PART_COLORS = Object.freeze({
  "1x1": "#e9b949", "2x1": "#598ab0", "4x1": "#588f83",
  "6x1": "#916eaa", "2x2": "#c86b62", "2x3": "#82a166",
  "2x4": "#53869a", "2x6": "#c79357", "2x8": "#777dac",
});

// x/z are stud coordinates; y is a brick layer. These relative lengths are
// deliberately independent of the source NPZ's cubic voxel coordinates.
export function createAssemblyViewer(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0xf1f5f8);
  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute("aria-label", "Assembled brick model. Drag to rotate, scroll to zoom, arrow keys to pan.");
  container.append(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf1f5f8);
  const camera = new THREE.PerspectiveCamera(38, 1, 0.01, 10000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.listenToKeyEvents(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x536777, 2.5));
  const sun = new THREE.DirectionalLight(0xffffff, 3);
  sun.position.set(8, 15, 10);
  scene.add(sun);
  const group = new THREE.Group();
  scene.add(group);
  let span = 100, body = null, studs = null, studEnds = [], placements = [], highlight = null, neighbors = null;
  const render = () => renderer.render(scene, camera);
  // Browsers can restore a context after changing GPU processes. Redraw this
  // demand-rendered viewer as soon as Three.js has rebuilt its renderer state.
  renderer.domElement.addEventListener("webglcontextrestored", () => requestAnimationFrame(render));
  function resize() {
    if (!container.clientWidth || !container.clientHeight) return;
    renderer.setSize(container.clientWidth, container.clientHeight, false);
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    render();
  }
  function reset() {
    const distance = span / Math.min(camera.aspect, 1);
    camera.position.set(distance * 0.95, distance * 0.8, distance * 1.25);
    camera.near = Math.max(span / 10000, 0.001);
    camera.far = span * 100;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.minDistance = span * 0.08;
    controls.maxDistance = span * 20;
    controls.update();
    render();
  }
  function clear() {
    for (const child of [...group.children]) {
      group.remove(child);
      child.traverse((object) => {
        object.geometry?.dispose();
        object.material?.dispose();
        object.dispose?.();
      });
    }
    body = studs = highlight = neighbors = null;
  }
  function update(orderedPlacements) {
    clear();
    placements = orderedPlacements;
    studEnds = [0];
    if (!placements.length) { render(); return; }
    const material = () => new THREE.MeshStandardMaterial({ roughness: 0.43, metalness: 0.02 });
    body = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), material(), placements.length);
    const studCount = placements.reduce((total, p) => total + p.width * p.depth, 0);
    studs = new THREE.InstancedMesh(new THREE.CylinderGeometry(1.48, 1.48, 0.8, 12), material(), studCount);
    // Disable culling: the shown count changes while stepping through the plan.
    body.frustumCulled = studs.frustumCulled = false;
    const matrix = new THREE.Matrix4();
    const transform = new THREE.Object3D();
    const bounds = new THREE.Box3();
    let studIndex = 0;
    placements.forEach((p, index) => {
      const height = p.height || 1;
      const color = new THREE.Color(PART_COLORS[p.part_id] || "#658c9f");
      transform.position.set((p.x + p.width / 2) * 5, (p.y + height / 2) * 6, (p.z + p.depth / 2) * 5);
      transform.scale.set(p.width * 5 - 0.13, height * 6 - 0.13, p.depth * 5 - 0.13);
      transform.updateMatrix();
      body.setMatrixAt(index, transform.matrix);
      body.setColorAt(index, color);
      bounds.expandByPoint(new THREE.Vector3(p.x * 5, p.y * 6, p.z * 5));
      bounds.expandByPoint(new THREE.Vector3((p.x + p.width) * 5, (p.y + height) * 6 + 0.8, (p.z + p.depth) * 5));
      for (let x = 0; x < p.width; x++) for (let z = 0; z < p.depth; z++) {
        matrix.makeTranslation((p.x + x + 0.5) * 5, (p.y + height) * 6 + 0.34, (p.z + z + 0.5) * 5);
        studs.setMatrixAt(studIndex, matrix);
        studs.setColorAt(studIndex++, color);
      }
      studEnds.push(studIndex);
    });
    body.instanceMatrix.needsUpdate = studs.instanceMatrix.needsUpdate = true;
    body.instanceColor.needsUpdate = studs.instanceColor.needsUpdate = true;
    group.add(body, studs);
    highlight = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)), new THREE.LineBasicMaterial({ color: 0x142a36, depthTest: false, transparent: true, opacity: 0.9 }));
    highlight.renderOrder = 2;
    highlight.visible = false;
    group.add(highlight);
    neighbors = new THREE.Group();
    group.add(neighbors);
    group.position.copy(bounds.getCenter(new THREE.Vector3())).negate();
    const size = bounds.getSize(new THREE.Vector3());
    span = Math.max(size.x, size.y, size.z, 5);
    resize();
    reset();
  }
  function showStep(count, emphasize = false, attachmentIds = []) {
    if (!body) return;
    const visible = Math.max(0, Math.min(placements.length, Number(count)));
    body.count = visible;
    studs.count = studEnds[visible];
    highlight.visible = emphasize && visible > 0;
    for (const child of [...neighbors.children]) { neighbors.remove(child); child.geometry.dispose(); child.material.dispose(); }
    if (highlight.visible) {
      const p = placements[visible - 1];
      highlight.position.set((p.x + p.width / 2) * 5, (p.y + (p.height || 1) / 2) * 6, (p.z + p.depth / 2) * 5);
      highlight.scale.set(p.width * 5 + 0.1, (p.height || 1) * 6 + 0.1, p.depth * 5 + 0.1);
      const attachments = new Set(attachmentIds.map(String));
      for (const neighbor of placements.slice(0, visible - 1)) {
        if (!attachments.has(String(neighbor.id))) continue;
        const outline = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(neighbor.width * 5 + 0.1, (neighbor.height || 1) * 6 + 0.1, neighbor.depth * 5 + 0.1)), new THREE.LineBasicMaterial({ color: 0x168bbf, depthTest: false, transparent: true, opacity: 0.9 }));
        outline.position.set((neighbor.x + neighbor.width / 2) * 5, (neighbor.y + (neighbor.height || 1) / 2) * 6, (neighbor.z + neighbor.depth / 2) * 5);
        outline.renderOrder = 1;
        neighbors.add(outline);
      }
    }
    render();
  }
  controls.addEventListener("change", render);
  const observer = new ResizeObserver(resize);
  observer.observe(container);
  return { update, showStep, reset, resize, dispose() { observer.disconnect(); controls.dispose(); clear(); renderer.dispose(); renderer.domElement.remove(); } };
}
