import { useEffect, useRef } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

/**
 * Hand3D — Phase 3a of the /products v2 Hand scene.
 *
 * Renders a STATIC, assembled 3D render of the dexterous hand by parsing the
 * MuJoCo MJCF (`/hand/right_hand.xml`) <body> tree into nested THREE.Groups and
 * parenting each link's STL mesh under its body. No physics, no animation yet
 * (3b = gesture animation, 3c = skin warp — see tasks/products-v2-roadmap.md).
 *
 * Feature-flagged: only mounted when the page is on `?v2&hand3d`. The default
 * Hand scene keeps the existing robo.webp image.
 *
 * Attribution: the hand model is the "Tetheria Aero Hand" (right, open) from the
 * Google DeepMind MuJoCo Menagerie (https://github.com/google-deepmind/mujoco_menagerie),
 * licensed under Apache-2.0. The MJCF + STL assets live in /public/hand.
 * A copy of the Apache-2.0 license terms applies to those redistributed assets.
 */

// MuJoCo stores rotations as quaternion (w, x, y, z). three.js wants (x, y, z, w).
function readVec(el, attr, fallback) {
  const raw = el.getAttribute(attr);
  if (!raw) return fallback;
  const v = raw.trim().split(/\s+/).map(Number);
  return v.some(Number.isNaN) ? fallback : v;
}

function applyTransform(obj, el) {
  const [px, py, pz] = readVec(el, "pos", [0, 0, 0]);
  obj.position.set(px, py, pz);
  const [qw, qx, qy, qz] = readVec(el, "quat", [1, 0, 0, 0]); // MuJoCo wxyz
  obj.quaternion.set(qx, qy, qz, qw); // -> three.js xyzw
}

export default function Hand3D() {
  const mountRef = useRef(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let disposed = false;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, 1, 0.001, 100);
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setClearColor(0x000000, 0); // transparent so the aurora shows through
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    mount.appendChild(renderer.domElement);

    // Neutral lighting: a soft key + fill + ambient so the metal reads as depth,
    // not gloss (matches the "depth via light not gloss" design principle).
    scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 1.1);
    key.position.set(0.4, 0.8, 1.0);
    scene.add(key);
    const fill = new THREE.DirectionalLight(0xbcd0ff, 0.5);
    fill.position.set(-0.8, 0.2, -0.4);
    scene.add(fill);

    const material = new THREE.MeshStandardMaterial({
      color: 0x9aa2ad, metalness: 0.35, roughness: 0.55,
    });

    // rootGroup holds the raw MuJoCo tree; pivot orients it for presentation.
    const pivot = new THREE.Group();
    const rootGroup = new THREE.Group();
    // MuJoCo Z-up, fingers point +Z -> orient so the fingers point up (+Y) and the
    // palm faces the viewer for a recognizable 3/4 portrait of the hand.
    rootGroup.rotation.x = -Math.PI / 2;
    rootGroup.rotation.z = Math.PI / 2;
    pivot.add(rootGroup);
    scene.add(pivot);

    const loader = new STLLoader();
    const meshFiles = {};
    let pending = 0;
    let started = false;

    const sizeToMount = () => {
      const w = mount.clientWidth || 480;
      const h = mount.clientHeight || 480;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };

    const frameCamera = () => {
      const box = new THREE.Box3().setFromObject(pivot);
      if (box.isEmpty()) return;
      const size = new THREE.Vector3();
      const center = new THREE.Vector3();
      box.getSize(size);
      box.getCenter(center);
      const maxDim = Math.max(size.x, size.y, size.z);
      const fov = (camera.fov * Math.PI) / 180;
      const dist = (maxDim / 2 / Math.tan(fov / 2)) * 1.55;
      // 3/4 view from front-right, slightly above.
      const dir = new THREE.Vector3(0.45, 0.28, 1).normalize();
      camera.position.copy(center).add(dir.multiplyScalar(dist));
      camera.lookAt(center);
      camera.near = dist / 100;
      camera.far = dist * 100;
      camera.updateProjectionMatrix();
    };

    const render = () => {
      if (disposed) return;
      renderer.render(scene, camera);
    };

    fetch("/hand/right_hand.xml")
      .then((r) => r.text())
      .then((xml) => {
        if (disposed) return;
        const doc = new DOMParser().parseFromString(xml, "application/xml");
        doc.querySelectorAll("asset > mesh").forEach((m) => {
          meshFiles[m.getAttribute("name")] = m.getAttribute("file");
        });

        const walk = (bodyEl, parentGroup) => {
          const g = new THREE.Group();
          applyTransform(g, bodyEl);
          parentGroup.add(g);

          for (const child of bodyEl.children) {
            if (child.tagName === "geom") {
              const meshName = child.getAttribute("mesh");
              // Only visual link meshes: skip collision/tendon helper geoms.
              // Tendon-viz meshes carry a `group` attr; skip those.
              if (!meshName || child.getAttribute("group")) continue;
              const file = meshFiles[meshName];
              if (!file) continue;
              pending++;
              const geomEl = child;
              loader.load(
                `/hand/${file}`,
                (bufGeo) => {
                  pending--;
                  if (disposed) { bufGeo.dispose(); return; }
                  bufGeo.computeVertexNormals();
                  const mesh = new THREE.Mesh(bufGeo, material);
                  applyTransform(mesh, geomEl);
                  g.add(mesh);
                  if (pending === 0) { frameCamera(); }
                  render();
                },
                undefined,
                () => { pending--; if (pending === 0) { frameCamera(); render(); } }
              );
            } else if (child.tagName === "body") {
              walk(child, g);
            }
          }
        };

        const world = doc.querySelector("worldbody");
        if (world) {
          for (const child of world.children) {
            if (child.tagName === "body") walk(child, rootGroup);
          }
        }
        started = true;
        sizeToMount();
        frameCamera();
        render();
      })
      .catch((err) => {
        // Non-fatal: leave the (transparent) canvas empty rather than crash the page.
        console.warn("[Hand3D] failed to load MJCF:", err);
      });

    sizeToMount();
    render();

    const ro = new ResizeObserver(() => {
      sizeToMount();
      if (started) frameCamera();
      render();
    });
    ro.observe(mount);

    return () => {
      disposed = true;
      ro.disconnect();
      material.dispose();
      scene.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
      renderer.dispose();
      if (renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    };
  }, []);

  return <div ref={mountRef} className="hand3d-canvas" aria-label="3D dexterous hand render" role="img" />;
}
