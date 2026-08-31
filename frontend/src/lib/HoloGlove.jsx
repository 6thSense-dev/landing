import { useEffect, useRef } from "react";
import * as THREE from "three";
import { FBXLoader } from "three/examples/jsm/loaders/FBXLoader.js";
import { HOLO_HUES, createHoloMaterial, setHoloScale } from "./holoMaterial.js";

/**
 * HoloGlove — evaluation viewer for the new glove mesh, rendered as a
 * "hologram" (fresnel rim + object-space scanlines + a travelling scan sweep).
 *
 * WHY THIS EXISTS: it is a look-test only, mounted at /glove-holo, so we can
 * decide whether this mesh should replace the current Skin visual (today a
 * flip-book of /hero/glove/frame-00N.webp on /products, plus the STL Aero-hand
 * in Hand3D.jsx). Nothing on a shipped page imports it.
 *
 * The source is a Tripo-generated FBX (single mesh, ~40k verts, one 4096²
 * basecolor). It is loaded straight from /public/models/glove-holo as .fbx —
 * fine for a localhost look-test, NOT ship-shape: the raw pair is 5.2MB, and
 * FBXLoader adds ~21KB gzip on top of `three` (measured: this file builds to a
 * 59.3KB / 20.8KB-gzip chunk). Productionising means a GLB + Draco/meshopt and
 * a downscaled texture, like /public/dexterous-hand.glb.
 *
 * Palette follows DESIGN.md: warm orange #F0612A, "warm, not sci-fi cyan".
 * `hue="cyan"` exists only so the two can be compared side by side.
 *
 * MARKS. Dropping the basecolor also drops the two features that identify the
 * product — the anti-slip grip pad on the palm and the AprilTag on the back of
 * the wrist — so every look composites them back from a separate mask texture,
 * /models/glove-holo/glove-marks.png (see scripts/build-glove-marks.py):
 *   R = grip-pad mask, G = AprilTag luminance, B = AprilTag quad,
 *   A = glove-fabric mask (where a synthesised grip may land).
 * The tag drawn from G/B is a real, detector-verified tag36h11, replacing the
 * blobby non-grid glyph Tripo baked into the basecolor. Tripo only painted
 * grips on the palm, so the fingers get a procedural lattice (see GRIP_GLSL).
 * `marks=0` restores the mesh exactly as delivered.
 */

const MARKS_MAP = "/models/glove-holo/glove-marks.png";

// Procedural anti-slip grip, shared by every look so the palm and the fingers
// cannot drift apart.
//
// Tripo painted grips on the palm block only; the real glove carries them down
// every finger. Rather than hand-paint the finger UV islands (scattered all
// over the atlas, easy to land on a knuckle by mistake) the missing ones are
// generated in OBJECT space and projected along the palm normal, then gated by
// which way the surface faces and by the fabric mask in the marks map's alpha.
// Wherever Tripo DID paint, the baked pattern wins — see max() at the call site.
const GRIP_GLSL = /* glsl */ `
  uniform vec3 uPalmDir;      // object-space outward normal of the palm
  uniform vec3 uGripU;        // orthonormal basis spanning the palm plane
  uniform vec3 uGripV;
  uniform float uGripScale;   // lattice cells per object-space unit
  uniform float uGripExtend;  // 0 = baked grips only, 1 = full synthesised field

  // One "Y": three arms at 120 degrees from the cell centre, flipped on
  // alternate cells so the field interlocks the way the real print does.
  float gripCell(vec2 p) {
    vec2 cell = floor(p);
    vec2 f = fract(p) - 0.5;
    f.y *= mod(cell.x + cell.y, 2.0) < 0.5 ? 1.0 : -1.0;
    float d = 1e9;
    for (int i = 0; i < 3; i++) {
      float ang = 1.5707963 + float(i) * 2.0943951;
      vec2 dir = vec2(cos(ang), sin(ang));
      float t = clamp(dot(f, dir), 0.0, 0.34);
      d = min(d, length(f - dir * t));
    }
    return 1.0 - smoothstep(0.052, 0.086, d);
  }

  // posL/normalL are OBJECT space, so the field stays welded to the glove while
  // the turntable spins. fabric is the marks map's alpha.
  float synthGrip(vec3 posL, vec3 normalL, float fabric) {
    if (uGripExtend <= 0.0) return 0.0;
    // Only the palm-facing side gets grips — never the back of the hand.
    // 0.22 not 0.0: the real print wraps a little onto the sides of the
    // fingers but stops well before the knuckles, so grazing faces get only a
    // partial grip and back-facing ones get none.
    float facing = smoothstep(0.22, 0.68, dot(normalize(normalL), uPalmDir));
    vec2 p = vec2(dot(posL, uGripU), dot(posL, uGripV)) * uGripScale;
    return gripCell(p) * facing * fabric * uGripExtend;
  }
`;

// The glove's own additions to the shared hologram shader (holoMaterial.js):
// the anti-slip grip pad and the AprilTag, composited over the shell.
const MARKS_PARS = /* glsl */ `
  uniform sampler2D uMarkMap;
  uniform float uMarks;
  uniform vec3 uTagTint;
`;

const MARKS_BODY = /* glsl */ `
    vec4 mk = texture2D(uMarkMap, vHoloUv);

    // Anti-slip grip pad: the triradiate grips fire as hot line-work, so the
    // pad reads even through a translucent shell. Mostly the hot tint, pulled
    // back toward the core so it stays warm rather than blowing out to white.
    float grip = max(mk.r, synthGrip(vPosL, vNormalL, mk.a * (1.0 - mk.b))) * uMarks;
    col += mix(uCore, uRim, 0.55) * grip * 1.35;
    a = clamp(a + grip * 0.5, 0.0, 1.0);

    // AprilTag: a fiducial is only legible as black-vs-white, and additive
    // blending cannot paint black — so knock the shell down to almost nothing
    // across the whole quad, then light only the white cells back up.
    float tagIn = mk.b * uMarks;
    col = mix(col, col * 0.10, tagIn);
    a = mix(a, a * 0.18, tagIn);
    col += uTagTint * tagIn * mk.g * 1.5;
    a = clamp(a + tagIn * mk.g * 0.95, 0.0, 1.0);
`;

export default function HoloGlove({
  src = "/models/glove-holo/glove-holo.fbx",
  look = "holo", // holo | textured | solid
  hue = "orange",
  wire = false,
  spin = true,
  intensity = 1,
  scan = 1,
  glitch = 1,
  ring = true,
  rotX = 0,
  rotY = 0,
  rotZ = 0,
  trim = 0,
  marks = 1,
  gripExtend = 1,
  gripScale = 68,
  // "marks-only" skips the 3.5MB basecolor the FBX references. Only safe when
  // the caller will never select look="textured" — the /products preview only
  // ever shows the hologram, the /glove-holo bench needs all three.
  preload = "all",
  onReady,
  onError,
}) {
  const mountRef = useRef(null);
  // Everything the prop-driven effects need to touch after load, without
  // re-fetching the 1.5MB FBX on every slider nudge.
  const sceneRef = useRef({});
  const spinRef = useRef(spin);
  spinRef.current = spin;
  // Pose is read by the raf tick and by the loader callback, so it lives in a
  // ref rather than the [src]-only effect closure (which would freeze it at
  // whatever the first render passed).
  const poseRef = useRef({ rotX, rotY, rotZ, trim });
  poseRef.current = { rotX, rotY, rotZ, trim };

  // ---- build the scene once ------------------------------------------------
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let disposed = false;

    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
      // The mesh ships with a forearm attached; `trim` cuts it at the wrist.
      renderer.localClippingEnabled = true;
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
    renderer.domElement.style.cursor = "grab";

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, w / h, 0.01, 100);
    camera.position.set(0, 0, 4.2);

    // Lighting only matters for the textured / solid looks; the holo shader is
    // unlit by design.
    scene.add(new THREE.AmbientLight(0xffffff, 0.75));
    const key = new THREE.DirectionalLight(0xffffff, 1.9);
    key.position.set(2.2, 3, 2.6);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xf0612a, 2.4);
    rim.position.set(-3, 1.2, -2.4);
    scene.add(rim);

    const pivot = new THREE.Group();
    scene.add(pivot);

    // Slow turntable ring under the model (DESIGN.md decoration vocabulary).
    const ringMesh = new THREE.Mesh(
      new THREE.RingGeometry(0.92, 0.955, 96),
      new THREE.MeshBasicMaterial({
        color: HOLO_HUES[hue]?.core ?? HOLO_HUES.white.core,
        transparent: true,
        opacity: 0.22,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      })
    );
    ringMesh.rotation.x = -Math.PI / 2;
    ringMesh.position.y = -1.05;
    scene.add(ringMesh);

    // Drag to spin, with inertia; auto-spin resumes when idle. Start at rest
    // when spin is off so a screenshot lands on the exact yaw that was asked for.
    let velocity = spinRef.current ? 0.004 : 0;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let tiltX = 0;
    const onDown = (e) => {
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
      velocity = 0;
      renderer.domElement.style.cursor = "grabbing";
    };
    const onMove = (e) => {
      if (!dragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      pivot.rotation.y += dx * 0.01;
      tiltX = Math.max(-0.9, Math.min(0.9, tiltX + dy * 0.006));
      velocity = dx * 0.001;
    };
    const onUp = () => {
      if (!dragging) return;
      dragging = false;
      renderer.domElement.style.cursor = "grab";
      if (spinRef.current && Math.abs(velocity) < 0.001) velocity = 0.004;
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);

    // Grip pad + AprilTag masks. Data, not colour, so it stays in linear space;
    // max anisotropy because the grips are read at grazing angles on the palm.
    const markTex = new THREE.TextureLoader().load(MARKS_MAP, (t) => {
      sceneRef.current.markImage = t.image;
      calibratePalm();
    });
    markTex.anisotropy = renderer.capabilities.getMaxAnisotropy();
    markTex.colorSpace = THREE.NoColorSpace;

    // World-space horizontal cut: keep everything ABOVE trimPlane.constant.
    // Horizontal survives the turntable yaw, which is the rotation that matters.
    const trimPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 10);

    // The synthesised-grip uniforms are SHARED objects (not copies) across the
    // holo shader and the two patched lit materials, so the palm calibration
    // below only has to be written once.
    const gripUniforms = {
      uPalmDir: { value: new THREE.Vector3(0, 0, 1) },
      uGripU: { value: new THREE.Vector3(1, 0, 0) },
      uGripV: { value: new THREE.Vector3(0, 1, 0) },
      uGripScale: { value: gripScale },
      uGripExtend: { value: gripExtend },
    };

    // Shared by the matte + textured looks (the hologram has its own copy of
    // these), so one strength value moves all three together.
    const markUniforms = {
      uMarkMap: { value: markTex },
      uMarks: { value: marks },
      uGripCol: { value: new THREE.Color(0xd6cec0) },
    };

    // The canonical hologram (holoMaterial.js) plus the glove's own grip-pad
    // and AprilTag layers. The FBX is authored around unit size, so the default
    // glitch amplitude is already right.
    const holoMat = createHoloMaterial({
      hue,
      intensity,
      scan,
      glitch,
      clippingPlanes: [trimPlane],
      extraUniforms: {
        uMarkMap: { value: markTex },
        uMarks: { value: marks },
        uTagTint: { value: new THREE.Color(0xffffff) },
        ...gripUniforms,
      },
      extraPars: MARKS_PARS + GRIP_GLSL,
      extraBody: MARKS_BODY,
    });
    const holoUniforms = holoMat.uniforms;

    // MeshStandardMaterial/MeshPhongMaterial have no hook for a second mask
    // map, so patch their generated shaders. `textured` only deepens the grips
    // (the basecolor already paints them, just far too softly) while `matte`
    // has no basecolor at all and paints them outright.
    const withMarks = (mat, mode) => {
      mat.onBeforeCompile = (sh) => {
        sh.uniforms.uMarkMap = markUniforms.uMarkMap;
        sh.uniforms.uMarks = markUniforms.uMarks;
        sh.uniforms.uGripCol = markUniforms.uGripCol;
        Object.assign(sh.uniforms, gripUniforms);
        sh.vertexShader = sh.vertexShader
          .replace("#include <common>", "#include <common>\nvarying vec2 vMarkUv;\nvarying vec3 vPosL;\nvarying vec3 vNormalL;")
          .replace("#include <beginnormal_vertex>", "#include <beginnormal_vertex>\n\tvNormalL = objectNormal;")
          .replace("#include <begin_vertex>", "#include <begin_vertex>\n\tvMarkUv = uv;\n\tvPosL = transformed;");
        sh.fragmentShader = sh.fragmentShader
          .replace(
            "#include <common>",
            "#include <common>\nvarying vec2 vMarkUv;\nvarying vec3 vPosL;\nvarying vec3 vNormalL;\nuniform sampler2D uMarkMap;\nuniform float uMarks;\nuniform vec3 uGripCol;\n" + GRIP_GLSL
          )
          .replace(
            "#include <map_fragment>",
            `#include <map_fragment>
            vec4 mk = texture2D( uMarkMap, vMarkUv );
            float grip = max( mk.r, synthGrip( vPosL, vNormalL, mk.a * ( 1.0 - mk.b ) ) ) * uMarks;
            ${mode === "paint"
              ? "diffuseColor.rgb = mix( diffuseColor.rgb, uGripCol, grip );"
              : "diffuseColor.rgb *= mix( 1.0, 0.14, grip );"}
            float tagIn = mk.b * uMarks;
            diffuseColor.rgb = mix( diffuseColor.rgb, vec3( mk.g ), tagIn );`
          );
      };
      mat.needsUpdate = true;
      return mat;
    };

    const solidMat = withMarks(new THREE.MeshStandardMaterial({
      clippingPlanes: [trimPlane],
      color: 0x14120f,
      metalness: 0.2,
      roughness: 0.72,
      emissive: 0x1c0b03,
      emissiveIntensity: 0.5,
    }), "paint");

    const wireMat = new THREE.MeshBasicMaterial({
      clippingPlanes: [trimPlane],
      color: HOLO_HUES[hue]?.rim ?? HOLO_HUES.white.rim,
      wireframe: true,
      transparent: true,
      opacity: 0.07,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    Object.assign(sceneRef.current, {
      renderer, scene, camera, pivot, holoUniforms, holoMat, solidMat, wireMat, ringMesh, trimPlane,
      markUniforms, gripUniforms, markTex,
      originalMats: new Map(),
      wireMeshes: [],
      model: null,
      getTilt: () => tiltX,
    });

    // FBXLoader resolves the basecolor path baked into the file, so the only way
    // not to pay for it is to intercept the request. A 1x1 transparent GIF keeps
    // the material's map slot valid without the download.
    const manager = new THREE.LoadingManager();
    if (preload === "marks-only") {
      const STUB = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
      manager.setURLModifier((url) => (/\.(jpe?g|png)$/i.test(url) && url.includes(".fbm") ? STUB : url));
    }
    const loader = new FBXLoader(manager);
    loader.load(
      src,
      (obj) => {
        if (disposed) return;
        // Normalise: centre the geometry on the origin so the FBX's cm units and
        // Tripo's arbitrary framing stop mattering. Translating the GEOMETRY
        // (not the object) keeps the pivot at the visual centre, so the
        // turntable spins about the glove instead of orbiting it.
        const box = new THREE.Box3().setFromObject(obj);
        const c = box.getCenter(new THREE.Vector3());
        const s = box.getSize(new THREE.Vector3());
        const maxDim = Math.max(s.x, s.y, s.z) || 1;
        const k = 1 / maxDim; // unit cube first; the real fit happens below

        // Snapshot the meshes BEFORE mutating: traverse() walks children after
        // the callback runs, so parenting a wireframe clone inside the callback
        // makes it visit that clone, clone it again, and blow the stack.
        const meshes = [];
        obj.traverse((o) => { if (o.isMesh) meshes.push(o); });
        meshes.forEach((o) => {
          o.geometry.translate(-c.x, -c.y, -c.z);
          o.geometry.computeVertexNormals();
          const mats = Array.isArray(o.material) ? o.material : [o.material];
          mats.forEach((m) => {
            // FBX basecolor is authored in sRGB; without this it renders washed out.
            if (m?.map) m.map.colorSpace = THREE.SRGBColorSpace;
            if (m) {
              m.clippingPlanes = [trimPlane];
              withMarks(m, "deepen");
            }
          });
          sceneRef.current.originalMats.set(o, o.material);
          const wm = new THREE.Mesh(o.geometry, wireMat);
          wm.visible = false;
          o.add(wm);
          sceneRef.current.wireMeshes.push(wm);
        });
        obj.scale.setScalar(k);
        obj.position.set(0, 0, 0);

        pivot.add(obj);
        sceneRef.current.model = obj;
        sceneRef.current.unitScale = k;

        // Scanline pitch and sweep length are expressed in the model's LOCAL
        // space, so derive them from the local height — ~44 bands and one sweep
        // per model height, whatever the source units the file happened to use.
        setHoloScale(holoMat, s.y * k);

        fitModel();
        applyLook();
        calibratePalm();
        // Count from `meshes`, not a fresh traverse — the wireframe clones share
        // the same geometry and would double every number.
        onReady?.({
          verts: meshes.reduce((n, o) => n + o.geometry.attributes.position.count, 0),
          tris: meshes.reduce(
            (n, o) => n + (o.geometry.index ? o.geometry.index.count : o.geometry.attributes.position.count) / 3,
            0
          ),
          size: [s.x, s.y, s.z].map((v) => +v.toFixed(2)),
          palm: sceneRef.current.palmDir,
        });
      },
      undefined,
      (err) => { if (!disposed) onError?.(err); }
    );

    // Apply the pose, then re-frame. Pose lives on the MODEL (so re-framing can
    // account for it) while the turntable yaw and drag-tilt live on the PIVOT —
    // sharing a channel would make a slider fight the spin.
    // Bounds of just the part that survives the trim cut. Box3.setFromObject
    // can't see a clipping plane, so fitting off it would leave the trimmed
    // glove floating in the top of a frame sized for the whole forearm.
    const boundsAbove = (obj, cutY) => {
      const box = new THREE.Box3();
      const v = new THREE.Vector3();
      obj.updateWorldMatrix(true, true);
      obj.traverse((o) => {
        if (!o.isMesh) return;
        const pos = o.geometry.attributes.position;
        for (let i = 0; i < pos.count; i++) {
          v.fromBufferAttribute(pos, i).applyMatrix4(o.matrixWorld);
          if (v.y >= cutY) box.expandByPoint(v);
        }
      });
      return box.isEmpty() ? new THREE.Box3().setFromObject(obj) : box;
    };

    // Which way does the palm face? Rather than hard-code a direction for this
    // one mesh, read it back off the data: average the object-space normals of
    // every vertex that Tripo already painted a grip on. That is the palm by
    // definition, so the synthesised finger grips can only ever agree with the
    // baked ones. Needs BOTH the mesh and the mask, so it runs from whichever
    // finishes last.
    function calibratePalm() {
      const st = sceneRef.current;
      const img = st.markImage;
      if (!img || !st.model) return;

      const S = 512; // the grips average out at this size; we only need a direction
      const cv = document.createElement("canvas");
      cv.width = cv.height = S;
      const ctx = cv.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, S, S);
      const px = ctx.getImageData(0, 0, S, S).data;

      const acc = new THREE.Vector3();
      const n = new THREE.Vector3();
      let hits = 0;
      st.model.traverse((o) => {
        if (!o.isMesh || st.wireMeshes.includes(o)) return;
        const pos = o.geometry.attributes.uv;
        const nor = o.geometry.attributes.normal;
        if (!pos || !nor) return;
        for (let i = 0; i < pos.count; i++) {
          const u = pos.getX(i);
          // three flips textures vertically by default, so v = 0 is the LAST row.
          const v = 1 - pos.getY(i);
          const x = Math.min(S - 1, Math.max(0, (u * S) | 0));
          const y = Math.min(S - 1, Math.max(0, (v * S) | 0));
          // Downsampling averages grip-over-fabric, so a painted pad lands
          // around 60/255 rather than 255; 28 is comfortably above the noise.
          if (px[(y * S + x) * 4] > 28) {
            acc.add(n.fromBufferAttribute(nor, i));
            hits++;
          }
        }
      });
      if (hits < 200 || acc.lengthSq() < 1e-6) {
        console.warn("[HoloGlove] palm calibration found only", hits, "grip verts");
        return;
      }
      const palm = acc.normalize();
      // Any two axes spanning the palm plane will do; the lattice is isotropic.
      const up = Math.abs(palm.y) > 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0);
      const u = new THREE.Vector3().crossVectors(up, palm).normalize();
      const v = new THREE.Vector3().crossVectors(palm, u).normalize();
      gripUniforms.uPalmDir.value.copy(palm);
      gripUniforms.uGripU.value.copy(u);
      gripUniforms.uGripV.value.copy(v);
      st.palmDir = palm.toArray().map((k) => +k.toFixed(3));
    }
    sceneRef.current.calibratePalm = calibratePalm;

    function fitModel() {
      const st = sceneRef.current;
      const obj = st.model;
      if (!obj) return;
      const p = poseRef.current;
      obj.rotation.set(p.rotX, p.rotY, p.rotZ);
      obj.scale.setScalar(st.unitScale);
      obj.position.set(0, 0, 0);
      obj.updateWorldMatrix(true, true);

      // Where the wrist cut lands, as a fraction of the posed model's height.
      const full = new THREE.Box3().setFromObject(obj);
      const trim = Math.max(0, Math.min(0.95, p.trim || 0));
      const cutY = full.min.y + (full.max.y - full.min.y) * trim;
      const visible = trim > 0 ? boundsAbove(obj, cutY) : full;

      // Fit the WORST-CASE silhouette, not the current one: the turntable shows
      // every yaw, so fit the horizontal DIAGONAL. Fitting the front view alone
      // lets a finger overflow the stage a quarter-turn later.
      const ws = visible.getSize(new THREE.Vector3());
      const spinWidth = Math.hypot(ws.x, ws.z) || 1;
      const viewH = 2 * camera.position.z * Math.tan((camera.fov * Math.PI) / 360);
      const viewW = viewH * camera.aspect;
      const fitK = Math.min(viewW / spinWidth, viewH / (ws.y || 1)) * 0.78;
      const vc = visible.getCenter(new THREE.Vector3());

      // Scaling happens about the object's origin, so a point p in the current
      // configuration lands at p * fitK + position. Centre the VISIBLE part.
      obj.scale.setScalar(st.unitScale * fitK);
      obj.position.set(-vc.x * fitK, -vc.y * fitK, -vc.z * fitK);
      obj.updateWorldMatrix(true, true);

      // Same mapping applied to the cut height gives the world-space plane.
      st.trimPlane.constant = trim > 0 ? -((cutY - vc.y) * fitK) : 1e3;

      // Sit the turntable ring just under the visible glove, circumscribing its
      // footprint so it never clips a finger.
      const fh = ws.y * fitK;
      const r = Math.max(ws.x, ws.z) * fitK * 0.5 + 0.05;
      ringMesh.geometry.dispose();
      ringMesh.geometry = new THREE.RingGeometry(r, r * 1.03, 128);
      ringMesh.position.y = -fh / 2 - 0.06;
    }
    sceneRef.current.fitModel = fitModel;

    // Swap materials without touching the loaded geometry.
    function applyLook() {
      const st = sceneRef.current;
      if (!st.model) return;
      st.model.traverse((o) => {
        if (!o.isMesh || st.wireMeshes.includes(o)) return;
        o.material =
          st.look === "textured" ? st.originalMats.get(o)
          : st.look === "solid" ? st.solidMat
          : st.holoMat;
      });
      st.wireMeshes.forEach((m) => { m.visible = !!st.wire; });
    }
    sceneRef.current.applyLook = applyLook;
    sceneRef.current.look = look;
    sceneRef.current.wire = wire;

    const IDLE_SPIN = 0.004;
    let raf = 0;
    const clock = new THREE.Clock();
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const t = clock.getElapsedTime();
      holoUniforms.uTime.value = t;
      if (!dragging) {
        // Spin on: ease back to the idle turntable rate after a flick.
        // Spin off: let any residual flick coast to a stop, then hold still.
        velocity = spinRef.current
          ? velocity + (IDLE_SPIN - velocity) * 0.02
          : velocity * 0.94;
        pivot.rotation.y += velocity;
      }
      pivot.rotation.x = tiltX;
      ringMesh.rotation.z = t * 0.12;
      ringMesh.visible = !!sceneRef.current.ringOn;
      renderer.render(scene, camera);
    };
    sceneRef.current.ringOn = ring;
    tick();

    const onResize = () => {
      const [W, H] = size();
      renderer.setSize(W, H);
      camera.aspect = W / H;
      camera.updateProjectionMatrix();
      // The framing is aspect-dependent, so it has to be redone — otherwise a
      // mount that measured 0 on the first layout pass keeps a stale fit.
      fitModel();
    };
    const ro = new ResizeObserver(onResize);
    ro.observe(mount);

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      holoMat.dispose();
      solidMat.dispose();
      wireMat.dispose();
      markTex.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
    // Only the source path rebuilds the scene; every other prop is applied live below.
  }, [src]);

  // ---- live prop application ----------------------------------------------
  useEffect(() => {
    const st = sceneRef.current;
    if (!st.holoUniforms) return;
    const pair = HOLO_HUES[hue] || HOLO_HUES.white;
    st.holoUniforms.uCore.value.set(pair.core);
    st.holoUniforms.uRim.value.set(pair.rim);
    st.holoUniforms.uIntensity.value = intensity;
    st.holoUniforms.uScan.value = scan;
    st.holoUniforms.uGlitch.value = glitch;
    st.holoUniforms.uMarks.value = marks;
    if (st.markUniforms) st.markUniforms.uMarks.value = marks;
    if (st.gripUniforms) {
      st.gripUniforms.uGripExtend.value = gripExtend;
      st.gripUniforms.uGripScale.value = gripScale;
    }
    st.wireMat?.color.set(pair.rim);
    st.ringMesh?.material.color.set(pair.core);
    st.ringOn = ring;
    st.look = look;
    st.wire = wire;
    st.applyLook?.();
  }, [look, hue, wire, intensity, scan, glitch, ring, marks, gripExtend, gripScale]);

  // A pose change re-frames: standing the glove up changes its silhouette, so
  // the fit-to-stage scale computed at load is no longer the right one.
  useEffect(() => {
    sceneRef.current.fitModel?.();
  }, [rotX, rotY, rotZ, trim]);

  return (
    <div
      ref={mountRef}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", touchAction: "none" }}
      role="img"
      aria-label="6thSense Skin data glove, rotating render — drag to spin"
    />
  );
}
