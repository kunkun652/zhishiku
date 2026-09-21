// Downloads are handled by npm ci and its integrity-checked lockfile.
// This script copies only explicitly listed generated assets, never user data.
import { readFile, mkdir, copyFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve, join } from 'node:path';
import { createHash } from 'node:crypto';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packages = join(root, 'tools/frontend/node_modules');
const target = join(root, 'src/static/vendor');
const files = [
  ['three/build/three.module.min.js', 'three/three.module.min.js'],
  ['three/build/three.core.min.js', 'three/three.core.min.js'],
  ['three/examples/jsm/controls/OrbitControls.js', 'three/OrbitControls.js'],
  ['three/LICENSE', 'three/LICENSE'],
  ['d3/dist/d3.min.js', 'd3/d3.min.js'],
  ['d3/LICENSE', 'd3/LICENSE'],
  ['occt-import-js/LICENSE.md', 'occt/LICENSE.md'],
  ...['occt-import-js.js', 'occt-import-js.wasm', 'occt-import-js-worker.js',
    'license.occt-import-js.txt', 'license.occt.txt'].map(name =>
      [`occt-import-js/dist/${name}`, `occt/${name}`]),
];
const check = process.argv.includes('--check');
const hash = value => createHash('sha256').update(value).digest('hex');
// Validate all inputs before touching the generated destination files.
const sources = await Promise.all(files.map(async ([source, destination]) =>
  ({ source: join(packages, source), destination: join(target, destination),
    digest: hash(await readFile(join(packages, source))) })));
for (const file of sources) {
  if (!check) {
    await mkdir(dirname(file.destination), { recursive: true });
    await copyFile(file.source, file.destination);
  }
  if (hash(await readFile(file.destination)) !== file.digest) {
    throw new Error(`Asset differs from the locked package: ${file.destination}`);
  }
}
console.log(`${check ? 'Verified' : 'Prepared and verified'} ${files.length} local assets and licenses.`);
