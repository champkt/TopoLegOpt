import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

export function createViewer(container) {
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0xf1f5f8);
  renderer.domElement.tabIndex = 0;
  renderer.domElement.setAttribute(
    "aria-label",
    "3D topology. Drag to rotate, scroll to zoom, or use arrow keys to pan.",
  );
  container.append(renderer.domElement);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(40, 1, 0.1, 10000);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.listenToKeyEvents(renderer.domElement);
  const group = new THREE.Group();
  scene.add(group, new THREE.HemisphereLight(0xffffff, 0x486477, 2.7));
  const light = new THREE.DirectionalLight(0xffffff, 3.2);
  light.position.set(2, 4, 3);
  scene.add(light);
  const material = new THREE.MeshStandardMaterial({
    color: 0x4989a9,
    roughness: 0.65,
    metalness: 0.03,
  });
  let span = 100,
    previousLayout = "";
  const render = () => renderer.render(scene, camera);
  function resize() {
    if (!container.clientWidth || !container.clientHeight) return;
    renderer.setSize(container.clientWidth, container.clientHeight, false);
    camera.aspect = container.clientWidth / container.clientHeight;
    camera.updateProjectionMatrix();
    render();
  }
  function reset() {
    const distance = span / Math.min(1, camera.aspect);
    camera.position.set(distance * 0.9, distance * 0.62, distance);
    camera.near = Math.max(span / 10000, 0.001);
    camera.far = span * 100;
    camera.updateProjectionMatrix();
    controls.target.set(0, 0, 0);
    controls.maxDistance = span * 20;
    controls.minDistance = span * 0.05;
    controls.update();
    render();
  }
  function update(result) {
    for (const object of [...group.children]) {
      group.remove(object);
      object.traverse((child) => {
        child.geometry?.dispose();
        if (child.material && child.material !== material) {
          child.material.map?.dispose();
          child.material.dispose();
        }
      });
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
      "position",
      new THREE.BufferAttribute(result.positions, 3),
    );
    geometry.computeVertexNormals();
    group.add(new THREE.Mesh(geometry, material));
    const half = new THREE.Vector3(...result.dimensions).multiplyScalar(0.5);
    group.add(
      new THREE.Box3Helper(
        new THREE.Box3(half.clone().negate(), half),
        0xb6c7d2,
      ),
    );
    span = Math.max(...result.dimensions);
    const axes = new THREE.AxesHelper(span * 0.23);
    axes.position.copy(half).negate();
    group.add(axes);
    const axisVectors = [
      new THREE.Vector3(1, 0, 0),
      new THREE.Vector3(0, 1, 0),
      new THREE.Vector3(0, 0, 1),
    ];
    for (let i = 0; i < 3; i++) {
      const canvas = document.createElement("canvas");
      canvas.width = 64;
      canvas.height = 64;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = ["#a33131", "#287842", "#285eaf"][i];
      ctx.font = "bold 44px sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("XYZ"[i], 32, 32);
      const sprite = new THREE.Sprite(
        new THREE.SpriteMaterial({
          map: new THREE.CanvasTexture(canvas),
          depthTest: false,
        }),
      );
      sprite.position
        .copy(axes.position)
        .addScaledVector(axisVectors[i], span * 0.28);
      sprite.scale.setScalar(span * 0.055);
      group.add(sprite);
    }
    group.quaternion.setFromUnitVectors(
      axisVectors["xyz".indexOf(result.settings.up)],
      new THREE.Vector3(0, 1, 0),
    );
    const layout = `${result.dimensions.join(",")}:${result.settings.up}`;
    resize();
    if (layout !== previousLayout) reset();
    previousLayout = layout;
    render();
  }
  controls.addEventListener("change", render);
  new ResizeObserver(resize).observe(container);
  return { update, reset, resize };
}
