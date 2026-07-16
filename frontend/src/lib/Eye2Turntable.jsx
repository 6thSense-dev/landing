import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";

/**
 * Live turntable of the Eye2 egocentric capture camera, tessellated from the
 * REAL printed-enclosure CAD (public/eye2.glb — assembled from the two STL
 * parts by scripts/build-eye2-cad.py, then meshopt-compressed).
 *
 * Same warm-dark studio lighting rig as HandTurntable / GloveTurntable so all
 * the products read as one set (DESIGN.md). The enclosure is a single dark
 * matte-plastic material; a bright key + front fill make the body read, and the
 * orange rim catches its edges. Static at rest; drag to spin (a flick glides to
 * a stop). Falls back to a caption panel where WebGL is unavailable.
 *
 * Honest imagery (DESIGN.md): this is the product's actual CAD, not an AI shot.
 *
 * @param {string} [props.src]      path to the .glb (meshopt-compressed).
 * @param {string} [props.caption]  fallback caption when WebGL is unavailable.
 */
export default function Eye2Turntable({
  src = "/eye2.glb",
  caption = "Eye2 enclosure — CAD render",
}) {
  const mountRef = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

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
    camera.position.set(0, 0, 2.85);

    // Warm, dark studio lighting — same rig as the glove/hand turntables so the
    // whole product set reads consistently (DESIGN.md palette). Brighter ambient
    // + a front fill from the camera so the enclosure body reads (not just the
    // rim), matching how the Skin/Hand rows sit lit and centered.
    scene.add(new THREE.AmbientLight(0x9a958c, 1.15));
    const key = new THREE.DirectionalLight(0xffffff, 2.6);
    key.position.set(2.5, 3, 2.5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xf0612a, 3.2);
    rim.position.set(-3, 1.2, -2.5);
    scene.add(rim);
    // Front fill from the viewer's side so the lens face isn't in shadow.
    const frontFill = new THREE.DirectionalLight(0xfff1e6, 1.25);
    frontFill.position.set(0, 0.6, 4);
    scene.add(frontFill);
    const underFill = new THREE.DirectionalLight(0xffd9c2, 0.6);
    underFill.position.set(0.5, -2, 2.5);
    scene.add(underFill);

    const pivot = new THREE.Group();
    scene.add(pivot);

    // Drag-to-spin only: static at rest, no continuous auto-rotation. A drag
    // imparts inertia (velocity) that decays to zero via friction in the tick
    // loop, so the enclosure glides to a stop rather than spinning forever.
    let velocity = 0;
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
    };
    renderer.domElement.style.cursor = "grab";
    renderer.domElement.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);

    // One dark matte-plastic material for the whole printed enclosure. Slight
    // metalness so the orange rim reads on the edges; DoubleSide because the
    // raw CAD isn't watertight (open lens/port cutouts).
    const shellMat = new THREE.MeshStandardMaterial({
      color: 0x36342f,
      metalness: 0.25,
      roughness: 0.55,
      side: THREE.DoubleSide,
    });

    let raf = 0;
    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    loader.load(
      src,
      (gltf) => {
        const model = gltf.scene;
        model.traverse((o) => {
          if (!o.isMesh) return;
          if (!o.geometry.attributes.normal) o.geometry.computeVertexNormals();
          o.material = shellMat;
        });

        // Center the geometry at the origin and normalise size (center the
        // GEOMETRY, not the object, so both enclosure parts stay aligned).
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        model.traverse((o) => {
          if (o.isMesh) o.geometry.translate(-center.x, -center.y, -center.z);
        });
        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        model.scale.setScalar(1.85 / maxDim);
        // The CAD's +Y is already up; a small yaw + forward tilt gives a 3/4
        // read (embossed "Eye2" face + lens toward the viewer) instead of a
        // flat side-on mugshot.
        model.rotation.y = -0.5;
        model.rotation.x = -0.05;
        pivot.add(model);
      },
      undefined,
      () => setFailed(true),
    );

    const tick = () => {
      raf = requestAnimationFrame(tick);
      if (!dragging) {
        pivot.rotation.y += velocity;
        velocity *= 0.94; // friction: flick inertia decays to a stop
        if (Math.abs(velocity) < 0.00002) velocity = 0;
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
      <div className="ev-skin-ph" role="img" aria-label={caption}>
        <div className="ev-skin-mark">◉</div>
        <div className="ev-skin-cap">{caption}</div>
      </div>
    );
  }
  return (
    <div
      ref={mountRef}
      className="ev-hand3d"
      aria-label="Rotating Eye2 camera enclosure, CAD render — drag to spin"
    />
  );
}
