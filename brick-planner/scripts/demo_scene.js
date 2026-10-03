// Scientific turntable rendering: data geometry and one shared camera for both views.
import * as THREE from 'three';
import { PART_COLORS } from '../src/assembly-viewer.js';

const canvas = document.querySelector('canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(1);
renderer.setSize(720, 504, false);
renderer.setClearColor(0xf1f5f8);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0xf1f5f8);
scene.add(new THREE.HemisphereLight(0xffffff, 0x536777, 2.5));
const sun = new THREE.DirectionalLight(0xffffff, 3);
sun.position.set(-8, 15, 10);
scene.add(sun);
const camera = new THREE.OrthographicCamera();
const topology = new THREE.Group();
const assembly = new THREE.Group();
scene.add(topology, assembly);

window.prepareDemo = ({ mesh, result }) => {
  if (result.options.up !== 'y' || result.options.mirror !== 'none') {
    throw new Error('This demo renderer expects Y up and a complete, unmirrored topology.');
  }
  const sourceScale = result.metrics.source_voxel_size_in_relative_units;
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.Float32BufferAttribute(mesh.positions.map(v => v * sourceScale), 3));
  geometry.setIndex(mesh.faces);
  geometry.computeVertexNormals();
  topology.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: 0x326e93, roughness: 0.48, metalness: 0.02, side: THREE.DoubleSide })));

  // Match the application's rectangular brick bodies, spacing, stud dimensions,
  // and part colors. Studs illustrate engagement; fit metrics use brick bodies.
  const material = () => new THREE.MeshStandardMaterial({ roughness: 0.43, metalness: 0.02 });
  const placements = result.placements;
  const bodies = new THREE.InstancedMesh(new THREE.BoxGeometry(1, 1, 1), material(), placements.length);
  const studCount = placements.reduce((n, p) => n + p.width * p.depth, 0);
  const studs = new THREE.InstancedMesh(new THREE.CylinderGeometry(1.48, 1.48, 0.8, 12), material(), studCount);
  const transform = new THREE.Object3D();
  const matrix = new THREE.Matrix4();
  let stud = 0;
  placements.forEach((p, index) => {
    const color = new THREE.Color(PART_COLORS[p.part_id]);
    transform.position.set((p.x + p.width / 2) * 5, (p.y + .5) * 6, (p.z + p.depth / 2) * 5);
    transform.scale.set(p.width * 5 - .13, 6 - .13, p.depth * 5 - .13);
    transform.updateMatrix();
    bodies.setMatrixAt(index, transform.matrix);
    bodies.setColorAt(index, color);
    for (let x = 0; x < p.width; x++) for (let z = 0; z < p.depth; z++) {
      matrix.makeTranslation((p.x + x + .5) * 5, (p.y + 1) * 6 + .34, (p.z + z + .5) * 5);
      studs.setMatrixAt(stud, matrix);
      studs.setColorAt(stud++, color);
    }
  });
  bodies.instanceMatrix.needsUpdate = studs.instanceMatrix.needsUpdate = true;
  bodies.instanceColor.needsUpdate = studs.instanceColor.needsUpdate = true;
  assembly.add(bodies, studs);
  const pitches = [5, 6, 5];
  assembly.position.set(...result.dimensions.map((n, i) => -n * pitches[i] / 2));
  const extents = result.dimensions.map((n, i) => Math.max(n * pitches[i], mesh.shape[i] * sourceScale));
  const radius = Math.hypot(extents[0], extents[2]) / 2;
  const elevation = Math.atan2(3, Math.hypot(7, 2.5));
  const halfHeight = 1.12 * Math.max(radius / (720 / 504), radius * Math.sin(elevation) + (extents[1] / 2 + .8) * Math.cos(elevation));
  camera.left = -halfHeight * 720 / 504;
  camera.right = -camera.left;
  camera.top = halfHeight;
  camera.bottom = -halfHeight;
  camera.near = .01;
  camera.far = Math.max(...extents) * 20;
  camera.updateProjectionMatrix();
  const distance = Math.max(...extents) * 3;
  const initialAngle = Math.atan2(-7, 2.5);
  window.renderDemoFrame = (kind, angle) => {
    topology.visible = kind === 'topology';
    assembly.visible = kind === 'assembly';
    const theta = initialAngle + angle;
    camera.position.set(distance * Math.cos(elevation) * Math.sin(theta), distance * Math.sin(elevation), distance * Math.cos(elevation) * Math.cos(theta));
    camera.up.set(0, 1, 0);
    camera.lookAt(0, 0, 0);
    renderer.render(scene, camera);
  };
  return { width: 720, height: 504, frames: 90, degreesPerFrame: 4, verticalAxis: 'y', projection: 'orthographic', sourceScale, elevationDegrees: THREE.MathUtils.radToDeg(elevation) };
};
