import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

/**
 * Live turntable of a dexterous robot hand, tessellated from the real
 * open-hardware CAD (see /public/dexterous-hand.glb). Dark matte material lit
 * with a warm-orange key + rim to match the site. Auto-rotates; drag to spin.
 *
 * NDA: the mesh is renamed "dexterous-hand" and never labelled as the partner
 * hand. The tactile-skin story is a concept — the model is the bare hand.
 *
 * @param {string} [props.src]  path to the .glb (meshopt-compressed).
 */
export default function HandTurntable({ src = "/dexterous-hand.glb" }) {
  const mountRef = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const reduce =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      renderer.localClippingEnabled = true;
    } catch {
      setFailed(true);
      return;
    }

    const getSize = () => [mount.clientWidth || 480, mount.clientHeight || 420];
    let [w, h] = getSize();
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setSize(w, h);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, w / h, 0.01, 100);
    camera.position.set(0, 0.15, 3.1);

    // Warm, dark studio lighting to match the paper/orange palette.
    scene.add(new THREE.AmbientLight(0x3a2418, 0.7));
    const key = new THREE.DirectionalLight(0xfff1e6, 2.4);
    key.position.set(2.5, 3, 2.5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xf0612a, 5.5);
    rim.position.set(-3, 1.2, -2.5);
    scene.add(rim);
    const fill = new THREE.DirectionalLight(0xf0612a, 1.4);
    fill.position.set(0.5, -2.5, 2.5);
    scene.add(fill);

    const pivot = new THREE.Group();
    scene.add(pivot);

    // Pointer drag to rotate (with inertia); auto-spin resumes when idle.
    let velocity = reduce ? 0 : 0.004;
    let dragging = false;
    let lastX = 0;
    const onDown = (e) => {
      dragging = true;
      lastX = e.clientX;
      velocity = 0;
    };
    const onMove = (e) => {
      if (!dragging) return;
      const dx = e.clientX - lastX;
      lastX = e.clientX;
      pivot.rotation.y += dx * 0.01;
      velocity = dx * 0.001;
    };
    const onUp = () => {
      dragging = false;
      if (!reduce && Math.abs(velocity) < 0.001) velocity = 0.004;
    };
    renderer.domElement.style.cursor = "grab";
    renderer.domElement.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);

    let raf = 0;
    let skinPlane = null;
    let handPlane = null;
    const UP = new THREE.Vector3(0, 1, 0);
    const tmpN = new THREE.Vector3();
    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    loader.load(
      src,
      (gltf) => {
        const model = gltf.scene;
        // Vertical split that co-rotates with the hand (updated in the tick):
        // the bare hand renders on one half, the tactile skin on the other so
        // you only ever see one of them per side.
        skinPlane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
        handPlane = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0);
        const mat = new THREE.MeshStandardMaterial({
          color: 0x171310,
          metalness: 0.38,
          roughness: 0.52,
          clippingPlanes: [handPlane],
          side: THREE.DoubleSide,
        });
        model.traverse((o) => {
          if (o.isMesh) o.material = mat;
        });

        // Center, normalise scale, stand it up.
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        model.position.sub(center);
        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        model.scale.setScalar(1.35 / maxDim);
        // The CAD arrives palm-down along Z; tip it up so it reads as a hand.
        model.rotation.x = -Math.PI / 2;
        pivot.add(model);

        // The tactile skin: a distinct, thicker sheath (a bigger offset clone) in
        // a soft matte silicone material, clipped to the RIGHT half so it wraps
        // the two right fingers + thumb. It's opaque and stands off the surface,
        // so it reads as an applied skin (not a recolour); the hand is clipped to
        // the opposite half, so on the skin side you see only the skin.
        const skinMat = new THREE.MeshStandardMaterial({
          color: 0xcf6a34,
          metalness: 0.0,
          roughness: 0.95,
          emissive: 0xf0612a,
          emissiveIntensity: 0.32,
          clippingPlanes: [skinPlane],
          side: THREE.DoubleSide,
        });
        const skin = model.clone(true);
        skin.traverse((o) => {
          if (o.isMesh) o.material = skinMat;
        });
        skin.scale.multiplyScalar(1.14);
        pivot.add(skin);
      },
      undefined,
      () => setFailed(true),
    );

    const tick = () => {
      raf = requestAnimationFrame(tick);
      if (!dragging) pivot.rotation.y += velocity;
      // Co-rotate the vertical split with the hand so the same fingers stay
      // skinned. Hand on one side, skin on the other.
      if (skinPlane) {
        tmpN.set(1, 0, 0).applyAxisAngle(UP, pivot.rotation.y);
        handPlane.normal.copy(tmpN).negate();
        skinPlane.normal.copy(tmpN);
      }
      renderer.render(scene, camera);
    };
    tick();

    const onResize = () => {
      const [W, H] = getSize();
      renderer.setSize(W, H);
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [src]);

  if (failed) {
    return (
      <div className="ev-skin-ph" role="img" aria-label="Dexterous hand — concept render">
        <div className="ev-skin-mark">◑</div>
        <div className="ev-skin-cap">
          Concept render
          <br />
          skin conforming to a dexterous hand
        </div>
      </div>
    );
  }
  return (
    <div
      ref={mountRef}
      className="ev-hand3d"
      aria-label="Rotating dexterous hand, concept render — drag to spin"
    />
  );
}
