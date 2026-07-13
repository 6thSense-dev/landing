import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

/**
 * Live turntable of the 6thSense glove for the Hand (01) and Nerve (02)
 * sections of /products. Unlike the Skin turntable — the robotic dexterous hand
 * (HandTurntable.jsx / dexterous-hand.glb) — the Hand and Nerve are worn on
 * human fingers, so this is a black textile GLOVE on a human hand, generated
 * from the MANO human-hand template (see scripts/build-glove-cad.py).
 *
 * The .glb scene has named meshes so we can style each part:
 *   "glove"   soft matte-black fabric
 *   "module"  the 3D-printed 6thSense wrist module (darker plastic)
 *   "sensors" (nerve only) the 15 per-joint tactile bumps — emissive orange,
 *             gently pulsing to sell the "one glove, two states" upgrade.
 *
 * Honest imagery (DESIGN.md): this is a CAD render of the real product's form
 * (public/hand.jpg), not an AI-generated product photo. Auto-rotates; drag to
 * spin. Falls back to a caption panel where WebGL is unavailable.
 *
 * @param {string}  [props.src]      path to the .glb.
 * @param {boolean} [props.sensors]  light + pulse the per-joint sensors (Nerve).
 * @param {string}  [props.caption]  fallback caption when WebGL is unavailable.
 */
export default function GloveTurntable({
  src = "/glove-hand.glb",
  sensors = false,
  caption = "6thSense glove — CAD render",
}) {
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
    camera.position.set(0, 0.1, 3.1);

    // Warm, dark studio lighting to match the paper/orange palette — same rig
    // as the Skin turntable so all three products read as one set.
    scene.add(new THREE.AmbientLight(0x6c6c6c, 0.85));
    const key = new THREE.DirectionalLight(0xffffff, 2.0);
    key.position.set(2.5, 3, 2.5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xf0612a, 3.0);
    rim.position.set(-3, 1.2, -2.5);
    scene.add(rim);
    const fill = new THREE.DirectionalLight(0xffd9c2, 0.7);
    fill.position.set(0.5, -2, 2.5);
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

    // Materials keyed by mesh name from the .glb.
    const gloveMat = new THREE.MeshStandardMaterial({
      color: 0x1b1b1b,
      metalness: 0.05,
      roughness: 0.9,
      side: THREE.DoubleSide,
    });
    const moduleMat = new THREE.MeshStandardMaterial({
      color: 0x0d0d0d,
      metalness: 0.18,
      roughness: 0.55,
    });
    // Per-joint sensors: light grey (per feedback), with a faint breathing
    // pulse so the Nerve still reads as "live" without the old orange glow.
    const sensorMat = new THREE.MeshStandardMaterial({
      color: 0xcfcfcf,
      metalness: 0.1,
      roughness: 0.45,
      emissive: new THREE.Color(0xffffff),
      emissiveIntensity: 0,
    });
    // The 6thSense logo decal on the module top — unlit so the light mark reads
    // crisply on the dark module regardless of the scene lighting.
    const logoTex = new THREE.TextureLoader().load("/glove-logo.png");
    logoTex.colorSpace = THREE.SRGBColorSpace;
    logoTex.anisotropy = 4;
    const logoMat = new THREE.MeshBasicMaterial({
      map: logoTex,
      transparent: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -2,
    });

    let raf = 0;
    const loader = new GLTFLoader();
    loader.load(
      src,
      (gltf) => {
        const model = gltf.scene;
        model.traverse((o) => {
          if (!o.isMesh) return;
          // The module/sensor/logo meshes ship without normals — compute smooth
          // ones so the puck and bumps shade nicely (the glove already has them).
          if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
          const n = (o.name || "").toLowerCase();
          if (n.includes("logo")) o.material = logoMat;
          else if (n.includes("sensor")) o.material = sensorMat;
          else if (n.includes("module")) o.material = moduleMat;
          else o.material = gloveMat;
        });

        // Center the geometry at the origin and normalise size. Centering the
        // geometry (not the object) keeps every part aligned within the pivot.
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        model.traverse((o) => {
          if (o.isMesh) o.geometry.translate(-center.x, -center.y, -center.z);
        });
        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        model.scale.setScalar(1.5 / maxDim);
        // The mesh is authored fingers-up (+Y); a slight forward tilt gives a
        // display-piece 3/4 read rather than a flat mugshot.
        model.rotation.x = -0.12;
        pivot.add(model);
      },
      undefined,
      () => setFailed(true),
    );

    const tick = () => {
      raf = requestAnimationFrame(tick);
      if (!dragging) pivot.rotation.y += velocity;
      if (sensors) {
        // Faint grey breathing pulse on the per-joint sensors (keeps them light
        // grey; no orange glow).
        const t = performance.now() * 0.0016;
        sensorMat.emissiveIntensity = 0.06 + 0.12 * (0.5 + 0.5 * Math.sin(t));
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
      logoTex.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) {
        mount.removeChild(renderer.domElement);
      }
    };
  }, [src, sensors]);

  if (failed) {
    return (
      <div className="ev-skin-ph" role="img" aria-label={caption}>
        <div className="ev-skin-mark">◍</div>
        <div className="ev-skin-cap">{caption}</div>
      </div>
    );
  }
  return (
    <div
      ref={mountRef}
      className="ev-hand3d"
      aria-label="Rotating 6thSense glove, CAD render — drag to spin"
    />
  );
}
