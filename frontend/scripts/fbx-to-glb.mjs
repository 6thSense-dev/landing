// Convert the Tripo glove FBX to a GLB, in the browser.
//
// There is no Blender, assimp or FBX2glTF on this machine, and three's own
// FBXLoader/GLTFExporter cannot run under Node (they reach for document and
// canvas). So the conversion is driven through the Vite dev server, which
// rewrites the bare 'three' imports for us, using Playwright as the shell.
//
// The win is indexing, not the container: the FBX is a non-indexed triangle
// soup, 154,059 corners describing 40,442 real points, so mergeVertices alone
// takes it to a quarter of the vertices. Keeping the FBX's OWN normals is what
// makes that possible — the viewer used to overwrite them with
// computeVertexNormals(), which on a soup yields per-face normals that share
// nothing and therefore weld nothing.
//
// Geometry only: the basecolor is written separately and much smaller by
// scripts/build-glove-marks.py, and only the bench's "textured" look wants it.
//
// Usage — dev server must be running on 5174:
//   node frontend/scripts/fbx-to-glb.mjs
//   npx @gltf-transform/cli meshopt public/models/glove-holo/glove.glb \
//                                   public/models/glove-holo/glove.glb

import { chromium } from 'playwright';
import { writeFileSync } from 'fs';
const b = await chromium.launch({ args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'] });
const p = await b.newPage();
p.on('console', m => console.log('  [page]', m.text().slice(0,200)));
p.on('pageerror', e => console.log('  [err]', e.message.slice(0,300)));
await p.goto('http://localhost:5174/', { waitUntil:'domcontentloaded', timeout:60000 });

const out = await p.evaluate(async () => {
  const V = '?v=53e53ca8';
  const THREE = await import('/node_modules/.vite/deps/three.js' + V);
  const { FBXLoader } = await import('/node_modules/three/examples/jsm/loaders/FBXLoader.js');
  const { GLTFExporter } = await import('/node_modules/three/examples/jsm/exporters/GLTFExporter.js');
  const { mergeVertices } = await import('/node_modules/three/examples/jsm/utils/BufferGeometryUtils.js');

  // Skip the 3.5MB basecolor: the GLB carries geometry only. Every look that
  // needs colour loads it separately, and the hologram never does.
  const STUB = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7';
  const mgr = new THREE.LoadingManager();
  mgr.setURLModifier(u => (/\.(jpe?g|png)$/i.test(u) && u.includes('.fbm') ? STUB : u));

  const fbx = await new Promise((res, rej) =>
    new FBXLoader(mgr).load('/models/glove-holo/glove-holo.fbx', res, undefined, rej));

  const stats = { before: 0, after: 0, tris: 0 };
  const root = new THREE.Group();
  fbx.traverse((o) => {
    if (!o.isMesh) return;
    let g = o.geometry;
    stats.before += g.attributes.position.count;
    // Keep the FBX's OWN normals — they are per-corner smooth normals, and the
    // viewer was throwing them away with computeVertexNormals() (which on a
    // non-indexed soup yields face normals). Keeping them is both truer to the
    // source and what lets mergeVertices actually merge.
    g = mergeVertices(g, 1e-5);
    stats.after += g.attributes.position.count;
    stats.tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0xffffff }));
    m.name = 'glove';
    root.add(m);
  });

  const glb = await new Promise((res, rej) =>
    new GLTFExporter().parse(root, res, rej, { binary: true, onlyVisible: false }));

  // ArrayBuffer -> base64 in chunks (btoa on a 2MB string blows the stack)
  const u8 = new Uint8Array(glb);
  let s = '';
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return { b64: btoa(s), ...stats, bytes: u8.length };
});

writeFileSync(new URL('../public/models/glove-holo/glove.glb', import.meta.url), Buffer.from(out.b64, 'base64'));
console.log(`verts ${out.before} -> ${out.after}  (${out.tris} tris)   glb ${(out.bytes/1048576).toFixed(2)}MB`);
await b.close();
