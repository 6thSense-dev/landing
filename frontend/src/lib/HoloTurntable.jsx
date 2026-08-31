import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { createHoloMaterial, setHoloScale, holoFitScale, holoSweptBounds, HOLO_FIT_TARGET } from "./holoMaterial.js";

/**
 * A .glb rendered as a slowly-turning hologram, using the shared material in
 * holoMaterial.js. Used for the Eye2 enclosure on /products.
 *
 * Deliberately dumb next to HoloGlove.jsx: no marks map, no palm calibration,
 * no forearm trim — just load, frame, spin. Anything model-specific belongs in
 * the caller, not here.
 *
 * The mesh is centred and fitted to the WORST-CASE (diagonal) silhouette, so a
 * long object cannot overflow its box a quarter-turn later.
 */
export default function HoloTurntable({
  src,
  hue = "white",
  intensity = 1,
  scan = 1,
  glitch = 0.6,
  wire = false,
  spin = true,
  flat = false,       // per-face normals (CAD without a NORMAL attribute)
  fill = 1,           // per-scene nudge on the shared target; containment
                      // still caps it, so this can never cause an overflow
  tiltX = 0,          // static pitch, radians
  rotY = 0,           // starting yaw
  rotZ = 0,           // roll. A wide, flat model in a portrait cell is capped
                      // by width containment long before it reaches the shared
                      // size target; rolling its long axis onto the cell
                      // diagonal is what lets it match the other scenes.
  label,
  onReady,
  onError,
}) {
  const mountRef = useRef(null);
  const spinRef = useRef(spin);
  spinRef.current = spin;

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || !src) return;
    let disposed = false;

    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch (err) {
      onError?.(err);
      return;
    }
    const size = () => [mount.clientWidth || 640, mount.clientHeight || 560];
    let [w, h] = size();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h);
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, w / h, 0.01, 100);
    camera.position.set(0, 0, 4.2);

    // Pivot is the turntable axis only — the static pitch goes on the model so
    // the fit measures the posed silhouette.
    const pivot = new THREE.Group();
    scene.add(pivot);

    // Amplitude is in OBJECT units and the Eye2 CAD is in millimetres (~96mm
    // across), so the unit-scale default would be invisible. Set once the real
    // bounds are known, below.
    const mat = createHoloMaterial({ hue, intensity, scan, glitch, flat });
    const wireMat = new THREE.MeshBasicMaterial({
      wireframe: true,
      transparent: true,
      opacity: 0.07,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    let model = null;   // the posed holder; refit scales THIS
    let swept = null;   // exact swept bounds at scale 1, pose applied

    // Fit the WORST-CASE (diagonal) silhouette: the turntable shows every yaw,
    // so fitting the current one lets a long object overflow a quarter-turn
    // later. Re-run on resize — it depends on camera.aspect, and the very first
    // layout pass can measure the mount at zero.
    //
    // Centring uses a WRAPPER with an offset child, never geometry.translate():
    // a meshopt/quantized .glb keeps its positions in a scaled node space, so a
    // world-space translate displaces the model instead of centring it. Posing
    // the wrapper also means the rotation pivots on the part rather than on the
    // file's origin — which for this CAD sits well outside the body, and swung
    // it far enough out to inflate its measured size by ~25%.
    const refit = () => {
      if (!model || !swept) return;
      const viewH = 2 * camera.position.z * Math.tan((camera.fov * Math.PI) / 360);
      const viewW = viewH * camera.aspect;
      // Shared across all three holographic scenes so they read as one size.
      // `fill` scales the TARGET, not the result: applied afterwards it would
      // sail straight past the containment clamp and let the model overflow.
      const k = holoFitScale(swept.spinWidth, swept.height, viewW, viewH, HOLO_FIT_TARGET * fill);
      model.scale.setScalar(k);
      // Swept bounds are radial about Y, so X/Z are centred by construction;
      // only the vertical midpoint needs taking out.
      model.position.set(0, -((swept.yMin + swept.yMax) / 2) * k, 0);
    };

    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    loader.load(
      src,
      (gltf) => {
        if (disposed) return;
        const obj = gltf.scene;

        // Snapshot before mutating: traverse() walks children added during the
        // callback, so parenting the wireframe clone inside it recurses.
        const meshes = [];
        obj.traverse((o) => { if (o.isMesh) meshes.push(o); });

        // Height in GEOMETRY space, which is what `position` is in the shader.
        // Not the same as the world height when the file is quantized, and the
        // scanline pitch and glitch amplitude are both read off `position`.
        let localH = 0;
        meshes.forEach((o) => {
          // trimesh's GLB export writes POSITION only, so without this the
          // shader would read a zero normal. `flat` ignores it, but a smooth
          // model passed to this component still needs it.
          if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
          o.geometry.computeBoundingBox();
          const bb = o.geometry.boundingBox;
          localH = Math.max(localH, bb.max.y - bb.min.y);
          o.material = mat;
          const wm = new THREE.Mesh(o.geometry, wireMat);
          wm.visible = wire;
          o.add(wm);
        });
        setHoloScale(mat, localH);
        mat.uniforms.uGlitchScale.value = localH;

        obj.updateWorldMatrix(true, true);
        const raw = new THREE.Box3().setFromObject(obj);
        const c = raw.getCenter(new THREE.Vector3());
        obj.position.set(-c.x, -c.y, -c.z);

        const holder = new THREE.Group();
        holder.add(obj);
        holder.rotation.set(tiltX, rotY, rotZ);
        pivot.add(holder);
        model = holder;

        swept = holoSweptBounds(holder);
        refit();
        onReady?.({
          size: raw.getSize(new THREE.Vector3()).toArray().map((v) => +v.toFixed(1)),
          swept: [+swept.spinWidth.toFixed(1), +swept.height.toFixed(1)],
        });
      },
      undefined,
      (err) => { if (!disposed) onError?.(err); }
    );

    let raf = 0;
    const clock = new THREE.Clock();
    const tick = () => {
      raf = requestAnimationFrame(tick);
      mat.uniforms.uTime.value = clock.getElapsedTime();
      if (spinRef.current) pivot.rotation.y += 0.004;
      renderer.render(scene, camera);
    };
    tick();

    const onResize = () => {
      const [W, H] = size();
      renderer.setSize(W, H);
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
      refit();
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      // Dispose each geometry ONCE: the wireframe clones share their parent's,
      // so a plain traverse would dispose the same buffers twice.
      if (model) {
        const seen = new Set();
        model.traverse((o) => {
          if (o.isMesh && !seen.has(o.geometry)) { seen.add(o.geometry); o.geometry.dispose(); }
        });
      }
      mat.dispose();
      wireMat.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
  }, [src]);

  return (
    <div
      ref={mountRef}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : "true"}
    />
  );
}
