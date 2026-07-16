import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

/**
 * Live turntable of the Eye2 egocentric capture camera, tessellated from the
 * REAL printed-enclosure CAD (public/eye2.glb — assembled from every STL part
 * by scripts/build-eye2-cad.py, then meshopt-compressed).
 *
 * The .glb ships THREE named meshes so each reads as its own material:
 *   "housing"  the printed enclosure body + rear cover — dark matte plastic
 *   "logo"     the embossed "Eye2" wordmark on the front face — cream inlay
 *   "dots"     the six-dot 6thSense motif below it — glowing brand-orange
 *
 * Look: a real studio environment map (RoomEnvironment via PMREM) gives the
 * dark shell soft, believable reflections; ACES filmic tone mapping keeps the
 * highlights from blowing out. A key + warm fill + orange rim shape the body on
 * top of the env. The rest angle is a 3/4-front hero so the branded face —
 * wordmark + dots — reads, not a flat side-on CAD mugshot. Static at rest; drag
 * to spin (a flick glides to a stop). Falls back to a caption where WebGL is
 * unavailable.
 *
 * Honest imagery (DESIGN.md): this is the product's actual CAD — an enclosure,
 * so there are no fabricated lenses; the hero read is the real branded face.
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
    // ACES filmic tone mapping: keeps the studio reflections and the orange rim
    // from clipping to flat white, so the dark shell holds gradient + detail.
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.98;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(32, w / h, 0.01, 100);
    camera.position.set(0, 0.05, 2.9);

    // Studio environment map for real PBR reflections on the dark shell. We
    // render three's RoomEnvironment through a PMREM so glossy surfaces pick up
    // soft, believable highlights (a matte enclosure with NO env just reads as
    // dead flat plastic). Used for reflections only — the page keeps its own
    // dark background (alpha canvas), so we don't set scene.background.
    const pmrem = new THREE.PMREMGenerator(renderer);
    const envRT = pmrem.fromScene(new RoomEnvironment(), 0.5);
    scene.environment = envRT.texture;

    // Directional rig on TOP of the env map — same warm-dark studio character as
    // the glove/hand turntables so the products read as one set (DESIGN.md).
    scene.add(new THREE.AmbientLight(0x8a8578, 0.35));
    const key = new THREE.DirectionalLight(0xffffff, 2.2);
    key.position.set(2.4, 3.2, 2.6);
    scene.add(key);
    // Warm front fill from the viewer's side so the branded face isn't in shade.
    const frontFill = new THREE.DirectionalLight(0xfff1e6, 0.9);
    frontFill.position.set(-0.4, 0.5, 4);
    scene.add(frontFill);
    // Orange rim from behind to catch the top/side edges (brand accent).
    const rim = new THREE.DirectionalLight(0xf0612a, 2.4);
    rim.position.set(-3, 1.6, -2.4);
    scene.add(rim);
    // Warm-white counter-rim from behind-right so the dark silhouette separates
    // from the dark page (a product shot always lifts the subject off the bg).
    const edge = new THREE.DirectionalLight(0xffe9d6, 1.5);
    edge.position.set(3.2, 1.0, -2.6);
    scene.add(edge);

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

    // --- Materials, keyed by mesh name from the .glb ------------------------
    // Housing: dark warm charcoal plastic. Real roughness + the env map give it
    // a soft anodized sheen instead of dead-flat CAD grey. FrontSide (both shells
    // are watertight) so the interior walls don't bleed through the outer faces.
    const housingMat = new THREE.MeshStandardMaterial({
      color: 0x1c1a17,
      metalness: 0.32,
      roughness: 0.6,
      envMapIntensity: 0.45,
      side: THREE.FrontSide,
    });
    // Wordmark: bright cream inlay (the paper tone from the palette) so "Eye2"
    // pops off the dark shell; a touch of self-illumination keeps it legible
    // from any angle without looking like a sticker.
    const logoMat = new THREE.MeshStandardMaterial({
      color: 0xf4ecdd,
      metalness: 0.0,
      roughness: 0.35,
      emissive: new THREE.Color(0xf4ecdd),
      emissiveIntensity: 0.55,
      envMapIntensity: 1.0,
    });
    // Six-dot 6thSense motif: brand orange, gently glowing so it reads as the
    // product's "live" accent (echoes the tactile-dot language across the set).
    const dotsMat = new THREE.MeshStandardMaterial({
      color: 0xf0612a,
      metalness: 0.2,
      roughness: 0.38,
      emissive: new THREE.Color(0xf0612a),
      emissiveIntensity: 0.55,
      envMapIntensity: 1.0,
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
          const n = (o.name || "").toLowerCase();
          if (n.includes("logo")) o.material = logoMat;
          else if (n.includes("dot")) o.material = dotsMat;
          else o.material = housingMat;
        });

        // Center the GEOMETRY (not the object) at the origin and normalise size,
        // so all three named meshes stay aligned inside the spinning pivot.
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        model.traverse((o) => {
          if (o.isMesh) o.geometry.translate(-center.x, -center.y, -center.z);
        });
        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        model.scale.setScalar(1.58 / maxDim);
        // trimesh's GLB export maps the CAD's Z-up to glTF's Y-up, so the branded
        // face (CAD +Z) points +Y here. We tilt that face toward the viewer (a
        // small +X pitch) and yaw it into a 3/4 so the wordmark + rounded front
        // edge read as a device, not a flat CAD mugshot.
        model.rotation.y = 0.58;
        model.rotation.x = 0.44;
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
      envRT.dispose();
      pmrem.dispose();
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
