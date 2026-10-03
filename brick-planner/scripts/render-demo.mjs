import { build } from 'esbuild';
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { mkdir, mkdtemp, readFile, rm, writeFile, copyFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const run = promisify(execFile);
const app = fileURLToPath(new URL('..', import.meta.url));
const example = path.resolve(app, '../examples/cantilever');
const python = path.join(app, '.venv/bin/python');
const scratch = await mkdtemp(path.join(tmpdir(), 'topoleg-turntable-'));
let server, browser;
try {
  await run(python, [path.join(app, 'scripts/demo_mesh.py'), '--npz', path.join(example, 'topology.npz'), '--threshold', '.5', '--output', path.join(scratch, 'mesh.json')]);
  const mesh = JSON.parse(await readFile(path.join(scratch, 'mesh.json'), 'utf8'));
  const result = JSON.parse(await readFile(path.join(example, 'assembly.json'), 'utf8'));
  if (!result.success || !result.validation.valid || !result.sequence_validation.valid) throw new Error('Demo requires an independently validated plan.');
  if (result.options.threshold !== .5) throw new Error('The topology and assembly must use threshold 0.5.');
  if (result.demo_inputs.topology_sha256 !== mesh.provenance.source_sha256) throw new Error('The demo assembly was generated from a different topology file.');
  if (JSON.stringify(mesh.shape) !== JSON.stringify(result.source_shape)) throw new Error('Topology and assembly source dimensions differ.');
  await build({ absWorkingDir: app, entryPoints: ['scripts/demo_scene.js'], outfile: path.join(scratch, 'scene.js'), bundle: true, format: 'esm', target: 'es2022' });
  const script = await readFile(path.join(scratch, 'scene.js'));
  server = createServer((request, response) => {
    if (request.url === '/scene.js') { response.setHeader('Content-Type', 'text/javascript'); response.end(script); return; }
    if (request.url !== '/') { response.writeHead(404); response.end(); return; }
    response.setHeader('Content-Type', 'text/html');
    response.end('<!doctype html><html lang="en"><meta charset="utf-8"><title>TopoLegOpt turntable capture</title><style>body{margin:0;background:#f1f5f8}canvas{display:block;width:720px;height:504px}</style><canvas></canvas><script type="module" src="/scene.js"></script></html>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  browser = await chromium.launch({ headless: true, args: ['--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 720, height: 504 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => typeof window.prepareDemo === 'function');
  const settings = await page.evaluate(data => window.prepareDemo(data), { mesh, result });
  for (const kind of ['topology', 'assembly']) {
    const frames = path.join(scratch, kind);
    await mkdir(frames);
    for (let frame = 0; frame < settings.frames; frame++) {
      await page.evaluate(({ kind, angle }) => window.renderDemoFrame(kind, angle), { kind, angle: 2 * Math.PI * frame / settings.frames });
      await page.locator('canvas').screenshot({ path: path.join(frames, `frame-${String(frame).padStart(3, '0')}.png`) });
      if (frame % 30 === 0) console.log(`${kind}: ${frame}/${settings.frames} frames`);
    }
    // The loop supplies the closing 356° -> 360°/0° step without a repeated frame.
    const first = path.join(frames, 'frame-000.png');
    if (kind === 'assembly') await copyFile(first, path.join(example, 'assembly.png'));
    const encoded = await run(python, [path.join(app, 'scripts/demo_gif.py'), '--frames-dir', frames, '--output', path.join(example, `${kind}.gif`), '--duration-ms', '80']);
    console.log(encoded.stdout.trim());
  }
  if (errors.length) throw new Error(errors.join('\n'));
  await writeFile(path.join(example, 'render.json'), JSON.stringify({ ...settings, durationMsPerFrame: 80, cycleSeconds: settings.frames * .08, topology: mesh.provenance, caption: 'Density 0.5 isosurface and brick assembly, matching Y-axis camera orbit and physical framing.' }, null, 2) + '\n');
} finally {
  await browser?.close();
  if (server) await new Promise(resolve => server.close(resolve));
  await rm(scratch, { recursive: true, force: true });
}
