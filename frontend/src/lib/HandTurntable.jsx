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
// Default transform for the still (Skin-composite) robotic hand. Overridable
// per-instance via the scale/posX/posY/rotY props (the /skin-tune page drives
// these live so we can dial in the alignment with the glove photo).
// Dialled in via /skin-tune so the robotic hand lines up with the glove photo.
const STILL_DEFAULTS = { scale: 1.42, posX: 0.14, posY: -0.19, rotY: -0.06 };

export default function HandTurntable({
  src = "/dexterous-hand.glb",
  still = false,
  scale,
  posX,
  posY,
  rotY,
  hires = false,
  fit = false,
}) {
  const mountRef = useRef(null);
  const [failed, setFailed] = useState(false);
  // The loaded robotic model + its base (fit-to-view) scale, so the live-update
  // effect below can re-apply the transform without reloading the .glb.
  const modelRef = useRef(null);
  const baseScaleRef = useRef(1);
  const cfg = {
    scale: scale != null ? scale : still ? STILL_DEFAULTS.scale : 1,
    posX: posX != null ? posX : still ? STILL_DEFAULTS.posX : 0,
    posY: posY != null ? posY : still ? STILL_DEFAULTS.posY : 0,
    rotY: rotY != null ? rotY : 0,
  };
  const cfgRef = useRef(cfg);
  cfgRef.current = cfg;

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
    // hires (the /robo-shot capture page) supersamples so the thin robotic
    // fingers don't alias when the screenshot is scaled up.
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, hires ? 4 : 2));
    renderer.setSize(w, h);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, w / h, 0.01, 100);
    camera.position.set(0, 0.15, 3.1);

    // Warm, dark studio lighting to match the paper/orange palette.
    // Neutral base so the light-gray hand reads gray and the black glove stays
    // visible, with a warm orange rim to tie into the palette.
    scene.add(new THREE.AmbientLight(0x6c6c6c, 0.9));
    const key = new THREE.DirectionalLight(0xffffff, 2.1);
    key.position.set(2.5, 3, 2.5);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xf0612a, 3.2);
    rim.position.set(-3, 1.2, -2.5);
    scene.add(rim);
    const fill = new THREE.DirectionalLight(0xffd9c2, 0.75);
    fill.position.set(0.5, -2, 2.5);
    scene.add(fill);

    const pivot = new THREE.Group();
    scene.add(pivot);

    // Pointer drag to rotate (with inertia); auto-spin resumes when idle.
    // In `still` mode the hand is frozen — no auto-spin, no drag.
    let velocity = reduce || still ? 0 : 0.004;
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
      if (!reduce && !still && Math.abs(velocity) < 0.001) velocity = 0.004;
    };
    // Drag to rotate is always available (still mode just doesn't auto-spin) —
    // lets the /robo-shot capture page be posed by hand before screenshotting.
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
        // you only ever see one of them per side. In `still` mode there's no
        // split — the FULL bare robotic hand renders (the glove is layered over
        // it as a photo by the caller), so we skip the clipping planes + shell.
        if (!still) {
          skinPlane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0);
          handPlane = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0);
        }
        // Light-gray robotic hand.
        const mat = new THREE.MeshStandardMaterial({
          color: 0xbcbcbc,
          metalness: 0.28,
          roughness: 0.5,
          clippingPlanes: still ? [] : [handPlane],
          side: THREE.DoubleSide,
        });
        model.traverse((o) => {
          if (o.isMesh) o.material = mat;
        });

        // Center the geometry at the origin, normalise, stand it up. Centering
        // the geometry (not the object) keeps it aligned with the glove below.
        const box = new THREE.Box3().setFromObject(model);
        const size = box.getSize(new THREE.Vector3());
        const center = box.getCenter(new THREE.Vector3());
        model.traverse((o) => {
          if (o.isMesh) o.geometry.translate(-center.x, -center.y, -center.z);
        });
        const maxDim = Math.max(size.x, size.y, size.z) || 1;
        baseScaleRef.current = 1.35 / maxDim;
        // The CAD arrives palm-down along Z; tip it up so it reads as a hand.
        model.rotation.x = -Math.PI / 2;
        modelRef.current = model;
        const c = cfgRef.current;
        if (fit) {
          // Auto-fit: scale + center the hand's ACTUAL rotated bounds to fill the
          // frame with margin, so it never overflows or sits off-centre (used by
          // the /robo-shot capture page).
          model.rotation.y = c.rotY;
          model.scale.setScalar(baseScaleRef.current);
          model.position.set(0, 0, 0);
          model.updateWorldMatrix(true, true);
          const wb = new THREE.Box3().setFromObject(model);
          const ws = wb.getSize(new THREE.Vector3());
          const viewH = 2 * Math.abs(camera.position.z) * Math.tan((camera.fov * Math.PI) / 360);
          const viewW = viewH * camera.aspect;
          const s = Math.min(viewW / ws.x, viewH / ws.y) * 0.86;
          model.scale.multiplyScalar(s);
          model.updateWorldMatrix(true, true);
          const wc = new THREE.Box3().setFromObject(model).getCenter(new THREE.Vector3());
          model.position.set(-wc.x, -wc.y, -wc.z);
          camera.lookAt(0, 0, 0);
        } else {
          // Manual transform (scale/position/yaw from cfgRef).
          model.scale.setScalar(baseScaleRef.current * c.scale);
          model.position.set(c.posX, c.posY, 0);
          model.rotation.y = c.rotY;
        }
        pivot.add(model);

        // The tactile-skin GLOVE: a SEPARATE, voxel-remeshed shell of the hand
        // (public/skin-glove.glb), smoothed so it encompasses the hand's curves
        // like a glove instead of molding to every crease and tendon. Matte black
        // like the real glove. Clipped to the RIGHT half (two fingers + thumb);
        // the hand is clipped to the opposite half, so on the glove side you see
        // only the glove, not the hand under it.
        if (!still) {
          const skinMat = new THREE.MeshStandardMaterial({
            color: 0x242424,
            metalness: 0.12,
            roughness: 0.62,
            clippingPlanes: [skinPlane],
            side: THREE.FrontSide,
          });
          loader.load("/skin-glove.glb", (g2) => {
            const glove = g2.scene;
            // Single WATERTIGHT shell in the HAND's coordinate space (no separate
            // parts to self-intersect). Apply the hand's exact centering + scale so
            // it lines up, a hair bigger so it sits just outside as a layer.
            glove.traverse((o) => {
              if (o.isMesh) {
                o.geometry.computeVertexNormals();
                o.geometry.translate(-center.x, -center.y, -center.z);
                o.material = skinMat;
              }
            });
            glove.scale.setScalar((1.35 / maxDim) * 1.06);
            glove.rotation.x = -Math.PI / 2;
            pivot.add(glove);
          });
        }
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

  // Live-apply transform changes (scale/position/yaw) without reloading the
  // .glb — the raf tick re-renders every frame, so updates show immediately.
  useEffect(() => {
    const m = modelRef.current;
    if (!m || fit) return; // fit mode auto-frames once; don't override it
    m.scale.setScalar(baseScaleRef.current * cfg.scale);
    m.position.set(cfg.posX, cfg.posY, 0);
    m.rotation.y = cfg.rotY;
  }, [cfg.scale, cfg.posX, cfg.posY, cfg.rotY, fit]);

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
      // Inline size so the canvas fills its parent even where products-showcase.css
      // isn't loaded (e.g. /robo-shot) — otherwise it falls back to a short 420px.
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", touchAction: "none" }}
      aria-label="Rotating dexterous hand, concept render — drag to spin"
    />
  );
}
