import { useEffect, useRef } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js";
import { HOLO_HUES, createHoloMaterial, setHoloScale, holoFitScale, holoSweptBounds } from "./holoMaterial.js";

/**
 * HoloGlove — evaluation viewer for the new glove mesh, rendered as a
 * "hologram" (fresnel rim + object-space scanlines + a travelling scan sweep).
 *
 * WHY THIS EXISTS: it is a look-test only, mounted at /glove-holo, so we can
 * decide whether this mesh should replace the current Skin visual (today a
 * flip-book of /hero/glove/frame-00N.webp on /products, plus the STL Aero-hand
 * in Hand3D.jsx). Nothing on a shipped page imports it.
 *
 * The source was a Tripo-generated FBX; what ships is a meshopt-compressed GLB
 * built from it (scripts/fbx-to-glb.mjs). The FBX arrived as a 154k-corner
 * triangle soup carrying only 40,442 real points, so indexing it is most of the
 * win: 1.5MB of FBX became 418KB of GLB, and swapping FBXLoader for the
 * GLTFLoader the site already uses took its own bite out of the bundle.
 *
 * Palette follows DESIGN.md: warm orange #F0612A, "warm, not sci-fi cyan".
 * `hue="cyan"` exists only so the two can be compared side by side.
 *
 * MARKS. Dropping the basecolor also drops the two features that identify the
 * product — the anti-slip grip pad on the palm and the AprilTag on the back of
 * the wrist — so every look composites them back from a separate mask texture,
 * /models/glove-holo/glove-marks.webp (see scripts/build-glove-marks.py):
 *   R = grip-pad mask, G = AprilTag luminance, B = AprilTag quad,
 *   A = glove-fabric mask (where a synthesised grip may land).
 * The tag drawn from G/B is a real, detector-verified tag36h11, replacing the
 * blobby non-grid glyph Tripo baked into the basecolor. Tripo only painted
 * grips on the palm, so the fingers get a procedural lattice (see GRIP_GLSL).
 * `marks=0` restores the mesh exactly as delivered.
 */

const MARKS_MAP = "/models/glove-holo/glove-marks.webp";
// Only the "textured" look wants this, so it is fetched on demand — the
// hologram never samples it and /products must not pay for it.
const BASECOLOR_MAP = "/models/glove-holo/glove-basecolor.webp";

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
  src = "/models/glove-holo/glove.glb",
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
  // Inward shrink along the vertex normal, as a fraction of the model's
  // height. Slims the fingers far more than the palm — see slimMesh().
  slim = 0,
  // Lengthen the fingers, as a fraction of model height added at the tips.
  // The mesh's fingers are stubby; 0 leaves them as delivered.
  stretch = 0,
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
  const poseRef = useRef({ rotX, rotY, rotZ, trim, slim, stretch });
  poseRef.current = { rotX, rotY, rotZ, trim, slim, stretch };

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
      slimMesh();
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

    const loader = new GLTFLoader();
    loader.setMeshoptDecoder(MeshoptDecoder);
    loader.load(
      src,
      (gltf) => {
        if (disposed) return;
        const obj = gltf.scene;
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
        // De-interleave and de-quantize before anything touches the buffers.
        // meshopt stores position as INTERLEAVED normalized Int16 and normal as
        // Int8, so `attribute.array` is a shared quantized buffer, not per-vertex
        // floats. Every CPU pass here (the weld, the shrink, the stretch, the
        // palm calibration) reads and writes `.array` directly, and on quantized
        // data that reads integers and writes floats back into an Int16Array —
        // which is exactly how the mesh came out as a ball of spikes. The
        // accessor API dequantizes correctly, so rebuild through it once.
        //
        // The compression is still doing its job: it is a TRANSFER format, and
        // 418KB over the wire is the point, not the in-memory layout.
        const toFloat = (attr, itemSize) => {
          const out = new Float32Array(attr.count * itemSize);
          for (let i = 0; i < attr.count; i++) {
            out[i * itemSize] = attr.getX(i);
            if (itemSize > 1) out[i * itemSize + 1] = attr.getY(i);
            if (itemSize > 2) out[i * itemSize + 2] = attr.getZ(i);
          }
          return new THREE.BufferAttribute(out, itemSize);
        };
        meshes.forEach((o) => {
          const g = o.geometry;
          for (const [name, n] of [["position", 3], ["normal", 3], ["uv", 2]]) {
            const a = g.attributes[name];
            if (a && (a.isInterleavedBufferAttribute || a.normalized || !(a.array instanceof Float32Array))) {
              g.setAttribute(name, toFloat(a, n));
            }
          }
          o.geometry.translate(-c.x, -c.y, -c.z);
          // NO computeVertexNormals here. The GLB carries the source's own
          // per-vertex smooth normals; recomputing on the old non-indexed FBX
          // produced FACE normals and faceted the whole glove, which is also
          // why nothing could be welded (154k corners for 40k real points).
          const m = Array.isArray(o.material) ? o.material[0] : o.material;
          if (m) {
            m.clippingPlanes = [trimPlane];
            withMarks(m, "deepen");
          }
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
        sceneRef.current.modelHeight = s.y;

        // Scanline pitch and sweep length are expressed in the model's LOCAL
        // space, so derive them from the local height — ~44 bands and one sweep
        // per model height, whatever the source units the file happened to use.
        setHoloScale(holoMat, s.y * k);

        fitModel();
        applyLook();
        calibratePalm();
        slimMesh();
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
          axis: sceneRef.current.fingerAxis,
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
    // Per-vertex sample of the marks map, cached because both consumers below
    // need it and decoding the PNG to a canvas is not free.
    //   .fabric  glove shell (A), 0 on cuff / strap / forearm
    //   .grip    Tripo's baked grip pad (R) — only the palm carries it
    //   .tag     the fiducial quad (B)
    function sampleMarks() {
      const st = sceneRef.current;
      const img = st.markImage;
      if (!img || !st.model || st.markSamples) return st.markSamples;

      const S = 512; // the grips average out at this size; we need masks, not detail
      const cv = document.createElement("canvas");
      cv.width = cv.height = S;
      const ctx = cv.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, S, S);
      const px = ctx.getImageData(0, 0, S, S).data;

      const out = new Map();
      st.model.traverse((o) => {
        if (!o.isMesh || st.wireMeshes.includes(o)) return;
        const uv = o.geometry.attributes.uv;
        if (!uv) return;
        const n = uv.count;
        const rec = { grip: new Float32Array(n), fabric: new Float32Array(n), tag: new Float32Array(n) };
        for (let i = 0; i < n; i++) {
          // three flips textures vertically by default, so v = 0 is the LAST row.
          // GLTFExporter writes UVs verbatim, so these are the same numbers the
          // FBX carried and the same convention still applies.
          const x = Math.min(S - 1, Math.max(0, (uv.getX(i) * S) | 0));
          const y = Math.min(S - 1, Math.max(0, ((1 - uv.getY(i)) * S) | 0));
          const p = (y * S + x) * 4;
          rec.grip[i] = px[p] / 255;
          rec.tag[i] = px[p + 2] / 255;
          rec.fabric[i] = px[p + 3] / 255;
        }
        out.set(o, rec);
      });
      st.markSamples = out;
      return out;
    }

    // Which way does the palm face? Read it off the data rather than hard-code a
    // direction for this one mesh: average the object-space normals of every
    // vertex Tripo already painted a grip on. That is the palm by definition, so
    // the synthesised finger grips can only ever agree with the baked ones.
    function calibratePalm() {
      const st = sceneRef.current;
      const samples = sampleMarks();
      if (!samples) return;

      const acc = new THREE.Vector3();
      const n = new THREE.Vector3();
      let hits = 0;
      for (const [o, rec] of samples) {
        const nor = o.geometry.attributes.normal;
        if (!nor) continue;
        for (let i = 0; i < rec.grip.length; i++) {
          // Downsampling averages grip-over-fabric, so a painted pad lands
          // around 60/255 rather than 255; 0.11 is comfortably above the noise.
          if (rec.grip[i] > 0.11) {
            acc.add(n.fromBufferAttribute(nor, i));
            hits++;
          }
        }
      }
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

    // Tripo modelled the glove noticeably chunkier than the real one, the
    // fingers worst of all. Push every shell vertex inward along its own normal
    // by a fixed distance: a thin part loses a much larger FRACTION of its
    // girth than a thick one, so one uniform offset slims the ~0.045-radius
    // fingers about twice as hard (in %) as the palm, with no need to segment
    // the fingers — which is just as well, since they are curled and separate
    // cleanly on no axis.
    //
    // Gated on the fabric mask so the cuff, the wrist strap, the fiducial's
    // backing plate and the bare forearm keep their thickness; those are thin
    // plates that would erode or invert.
    //
    // Always re-derived from a pristine copy of the positions, never from the
    // current ones, so dragging the slider cannot compound the shrink.
    // Weld table for the slimming pass: which vertices occupy the same POINT
    // IN SPACE, regardless of how many UV copies of it the atlas holds.
    //
    // Everything below depends on this. FBXLoader expands the file's indexed
    // mesh into a non-indexed triangle soup, so 40k distinct points arrive as
    // 154k independent corners, and BOTH inputs to the offset are per-corner
    // and discontinuous across those duplicates:
    //   - computeVertexNormals() on a soup yields FACE normals, so neighbouring
    //     triangles point slightly differently;
    //   - the mask weight is sampled through UVs, and on an atlas this
    //     fragmented a corner near an island edge bleeds onto whatever sits
    //     next to it, so one corner reads "glove" and its twin reads "cuff".
    // Either alone tears the surface into confetti when you move it. Averaging
    // both per welded point makes the field continuous and the shell slides
    // inward as one piece.
    function weldTable(o, base) {
      const st = sceneRef.current;
      let t = st.weldTables?.get(o);
      if (t) return t;
      // Quantise to 1e-4 of model height: far finer than the ~7e-3 vertex
      // spacing, far coarser than float32 noise.
      const q = 1e4 / (st.modelHeight || 1);
      const n = base.length / 3;
      const groupOf = new Int32Array(n);
      const index = new Map();
      let groups = 0;
      for (let i = 0; i < n; i++) {
        const k = `${Math.round(base[i * 3] * q)},${Math.round(base[i * 3 + 1] * q)},${Math.round(base[i * 3 + 2] * q)}`;
        let g = index.get(k);
        if (g === undefined) { g = groups++; index.set(k, g); }
        groupOf[i] = g;
      }
      t = { groupOf, groups };
      (st.weldTables ||= new Map()).set(o, t);
      return t;
    }

    // Group adjacency, built from the triangle soup via the weld table.
    function weldAdjacency(o, base) {
      const st = sceneRef.current;
      let a = st.adjacency?.get(o);
      if (a) return a;
      const { groupOf, groups } = weldTable(o, base);
      const sets = Array.from({ length: groups }, () => new Set());
      // Triangles come from the index buffer when there is one. The GLB is
      // indexed (the FBX was a soup), so walking positions three at a time —
      // which is what this did — would connect vertices that share nothing.
      const idx = o.geometry.index;
      const triCount = idx ? idx.count : groupOf.length;
      const at = idx ? (i) => groupOf[idx.getX(i)] : (i) => groupOf[i];
      for (let t = 0; t < triCount; t += 3) {
        const g0 = at(t), g1 = at(t + 1), g2 = at(t + 2);
        if (g0 !== g1) { sets[g0].add(g1); sets[g1].add(g0); }
        if (g1 !== g2) { sets[g1].add(g2); sets[g2].add(g1); }
        if (g2 !== g0) { sets[g2].add(g0); sets[g0].add(g2); }
      }
      // Flatten to typed arrays — 26k Sets are fine to build once, miserable to
      // walk 14 times per slider move.
      const start = new Int32Array(groups + 1);
      for (let g = 0; g < groups; g++) start[g + 1] = start[g] + sets[g].size;
      const nbr = new Int32Array(start[groups]);
      for (let g = 0, k = 0; g < groups; g++) for (const n of sets[g]) nbr[k++] = n;
      a = { start, nbr };
      (st.adjacency ||= new Map()).set(o, a);
      return a;
    }

    // Tripo modelled the glove far chunkier than the real one, the fingers worst
    // of all. Slimming is LAPLACIAN SHRINK: each welded point steps toward the
    // average of its neighbours, repeatedly. Displacement scales with curvature,
    // so the thin, highly-curved fingers pull in hard while the broad flat palm
    // barely moves — which is exactly the correction wanted, and it needs no
    // finger segmentation (just as well: they are curled and separate cleanly
    // on no axis).
    //
    // Three approaches were tried before this one; all of them tear, and the
    // reason is worth keeping:
    //
    //  1. Offset along the raw per-vertex normal. FBXLoader hands back a
    //     non-indexed soup, so computeVertexNormals() yields FACE normals and
    //     each triangle flies off on its own — the mesh becomes confetti.
    //  2. Offset along normals welded per position. Continuous, still torn: a
    //     fixed offset INVERTS any concave feature whose radius of curvature is
    //     smaller than the offset, and this glove is covered in knuckle creases
    //     finer than any useful amount, so their walls crossed and sheared the
    //     fingers into rings.
    //  3. Offset along a Laplacian-SMOOTHED normal field. Fixes the creases, but
    //     over a fingertip the field averages toward the finger's axis, so the
    //     cap translates down the tube instead of shrinking radially and the
    //     walls punch through it — flat, cut-off tips.
    //
    // Laplacian shrink cannot do any of that: every step is a convex
    // combination of existing points, so the surface can never cross itself.
    // Its one cost is that it smooths away fine GEOMETRIC detail along with the
    // bulk — which is why the strength is kept modest. The grip pad, the
    // AprilTag and the basecolor are all UV-mapped, so none of them are touched
    // by this at any strength.
    //
    // Weighted by the fabric mask so the cuff, wrist strap, fiducial backing
    // plate and bare forearm hold their shape. Always re-derived from a pristine
    // copy of the positions, so the slider cannot compound the shrink.
    const SHRINK_MAX_ITERS = 45;
    const STRETCH_MAX = 0.22;   // fraction of model height added at the tips
    const STRETCH_START = 0.55; // where along the shell the ramp begins
    const SHRINK_LAMBDA = 0.5;

    // Welded point positions + the averaged mask weight per point. Averaging the
    // weight matters: sampled per corner it is discontinuous across UV seams on
    // an atlas this fragmented, and a discontinuous weight drags neighbouring
    // triangles by different amounts.
    function shrinkInputs(o, base, rec) {
      const st = sceneRef.current;
      let inp = st.shrinkInputs?.get(o);
      if (inp) return inp;
      const { groupOf, groups } = weldTable(o, base);
      const gp = new Float32Array(groups * 3);
      const gw = new Float32Array(groups);
      const count = new Float32Array(groups);
      for (let i = 0; i < groupOf.length; i++) {
        const g = groupOf[i];
        gp[g*3] = base[i*3]; gp[g*3+1] = base[i*3+1]; gp[g*3+2] = base[i*3+2];
        gw[g] += rec.fabric[i] * (1 - rec.tag[i]);
        count[g]++;
      }
      for (let g = 0; g < groups; g++) gw[g] /= count[g] || 1;
      inp = { gp, gw, groupOf, groups };
      (st.shrinkInputs ||= new Map()).set(o, inp);
      return inp;
    }

    // Where the fingers point, and where they start — both read off the mesh
    // rather than assumed, so this survives the model being re-exported.
    //
    // The palm is wherever Tripo painted grips (that is what calibratePalm
    // already keys on). The fingertips are the shell points furthest from the
    // palm centroid — restricting to the FABRIC shell is what makes this work,
    // because the model also carries a forearm, and the far end of that is
    // otherwise the furthest thing from the palm.
    function fingerAxis(o, base, rec) {
      const st = sceneRef.current;
      let fa = st.fingerAxes?.get(o);
      if (fa) return fa;

      const n = base.length / 3;
      const c = new THREE.Vector3();
      let hits = 0;
      for (let i = 0; i < n; i++) {
        if (rec.grip[i] > 0.11) { c.x += base[i*3]; c.y += base[i*3+1]; c.z += base[i*3+2]; hits++; }
      }
      if (hits < 200) return null;
      c.multiplyScalar(1 / hits);

      // Furthest 4% of shell points from the palm centroid = the fingertips.
      const shell = [];
      for (let i = 0; i < n; i++) {
        if (rec.fabric[i] < 0.5) continue;
        const dx = base[i*3] - c.x, dy = base[i*3+1] - c.y, dz = base[i*3+2] - c.z;
        shell.push([dx*dx + dy*dy + dz*dz, i]);
      }
      if (shell.length < 500) return null;
      shell.sort((a, b) => b[0] - a[0]);
      const tipN = Math.max(50, Math.floor(shell.length * 0.04));
      const axis = new THREE.Vector3();
      for (let k = 0; k < tipN; k++) {
        const i = shell[k][1];
        axis.x += base[i*3] - c.x; axis.y += base[i*3+1] - c.y; axis.z += base[i*3+2] - c.z;
      }
      axis.normalize();

      // Project the shell onto that axis to find where to start the stretch.
      let tMin = Infinity, tMax = -Infinity;
      for (let i = 0; i < n; i++) {
        if (rec.fabric[i] < 0.5) continue;
        const t = (base[i*3] - c.x) * axis.x + (base[i*3+1] - c.y) * axis.y + (base[i*3+2] - c.z) * axis.z;
        if (t < tMin) tMin = t;
        if (t > tMax) tMax = t;
      }
      fa = { axis, c, tMin, tMax };
      (st.fingerAxes ||= new Map()).set(o, fa);
      st.fingerAxis = axis.toArray().map((v) => +v.toFixed(3));
      return fa;
    }

    function slimMesh() {
      const st = sceneRef.current;
      const samples = sampleMarks();
      if (!samples) return;
      const strength = Math.max(0, Math.min(1, poseRef.current.slim || 0));

      for (const [o, rec] of samples) {
        const pos = o.geometry.attributes.position;
        let base = st.basePositions?.get(o);
        if (!base) {
          base = new Float32Array(pos.array);
          (st.basePositions ||= new Map()).set(o, base);
        }
        const arr = pos.array;
        arr.set(base);
        if (strength > 0) {
          const { gp, gw, groupOf, groups } = shrinkInputs(o, base, rec);
          const { start, nbr } = weldAdjacency(o, base);
          let cur = Float32Array.from(gp);
          let next = new Float32Array(groups * 3);
          // Shrinkage grows with ITERATION COUNT; lambda past ~0.6 only makes
          // each step wobble, so strength drives the count.
          const iters = Math.round(strength * SHRINK_MAX_ITERS);
          for (let it = 0; it < iters; it++) {
            for (let g = 0; g < groups; g++) {
              const s0 = start[g], s1 = start[g + 1], n = s1 - s0;
              if (n === 0) { next[g*3] = cur[g*3]; next[g*3+1] = cur[g*3+1]; next[g*3+2] = cur[g*3+2]; continue; }
              let ax = 0, ay = 0, az = 0;
              for (let k = s0; k < s1; k++) { const m = nbr[k] * 3; ax += cur[m]; ay += cur[m+1]; az += cur[m+2]; }
              const w = SHRINK_LAMBDA * gw[g];
              next[g*3]   = cur[g*3]   + w * (ax / n - cur[g*3]);
              next[g*3+1] = cur[g*3+1] + w * (ay / n - cur[g*3+1]);
              next[g*3+2] = cur[g*3+2] + w * (az / n - cur[g*3+2]);
            }
            const t = cur; cur = next; next = t;
          }
          for (let i = 0; i < groupOf.length; i++) {
            const g = groupOf[i] * 3;
            arr[i*3] = cur[g]; arr[i*3+1] = cur[g+1]; arr[i*3+2] = cur[g+2];
          }
        }

        // Lengthen the fingers: slide points along the finger axis by an amount
        // that ramps from 0 at the knuckles to full at the tips. A smooth
        // scalar field, so like the shrink it cannot fold the surface — it is a
        // stretch, not an offset. Runs on whatever the shrink produced, but
        // reads its ramp from the PRISTINE positions so the two are independent.
        const stretchAmt = Math.max(0, Math.min(1, poseRef.current.stretch || 0)) *
          STRETCH_MAX * (st.modelHeight || 1);
        if (stretchAmt > 0) {
          const fa = fingerAxis(o, base, rec);
          if (fa) {
            const { axis, c, tMin, tMax } = fa;
            // Knuckles sit ~55% of the way up the shell; below that is palm.
            const t0 = tMin + (tMax - tMin) * STRETCH_START;
            const span = Math.max(1e-6, tMax - t0);
            for (let i = 0; i < arr.length / 3; i++) {
              const t = (base[i*3] - c.x) * axis.x + (base[i*3+1] - c.y) * axis.y + (base[i*3+2] - c.z) * axis.z;
              let u = (t - t0) / span;
              if (u <= 0) continue;
              u = u > 1 ? 1 : u;
              const ramp = u * u * (3 - 2 * u) * rec.fabric[i];
              arr[i*3]   += axis.x * stretchAmt * ramp;
              arr[i*3+1] += axis.y * stretchAmt * ramp;
              arr[i*3+2] += axis.z * stretchAmt * ramp;
            }
          }
        }
        pos.needsUpdate = true;
        o.geometry.computeVertexNormals(); // positions really moved
        o.geometry.computeBoundingBox();
        o.geometry.computeBoundingSphere();
      }
      fitModel();
    }

    sceneRef.current.calibratePalm = calibratePalm;
    sceneRef.current.slimMesh = slimMesh;

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
      const viewH = 2 * camera.position.z * Math.tan((camera.fov * Math.PI) / 360);
      const viewW = viewH * camera.aspect;
      // Exact swept bounds — the same measure every holographic scene uses, so
      // the shared size rule actually means the same thing for all of them. A
      // trimmed model falls back to the clipped AABB, which is what defines
      // "visible" in that case.
      const sw = trim > 0 ? Math.hypot(ws.x, ws.z) : holoSweptBounds(obj).spinWidth;
      const fitK = holoFitScale(sw || 1, ws.y, viewW, viewH);
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

    // The GLB is geometry only. "Original texture" is the one look that wants
    // the basecolor, so it is fetched the first time that look is selected and
    // cached after — /products only ever shows the hologram and never pays.
    function ensureBasecolor() {
      const st = sceneRef.current;
      if (st.basecolor) return st.basecolor;
      st.basecolor = new THREE.TextureLoader().load(BASECOLOR_MAP, () => {
        // The mesh may already be showing the untextured material by the time
        // this lands, so nudge it.
        st.applyLook?.();
      });
      st.basecolor.colorSpace = THREE.SRGBColorSpace;
      st.basecolor.anisotropy = renderer.capabilities.getMaxAnisotropy();
      return st.basecolor;
    }

    // Swap materials without touching the loaded geometry.
    function applyLook() {
      const st = sceneRef.current;
      if (!st.model) return;
      st.model.traverse((o) => {
        if (!o.isMesh || st.wireMeshes.includes(o)) return;
        if (st.look === "textured") {
          const m = st.originalMats.get(o);
          const mat = Array.isArray(m) ? m[0] : m;
          if (mat && !mat.map) { mat.map = ensureBasecolor(); mat.needsUpdate = true; }
          o.material = m;
        } else {
          o.material = st.look === "solid" ? st.solidMat : st.holoMat;
        }
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

  useEffect(() => {
    sceneRef.current.slimMesh?.();
  }, [slim, stretch]);

  return (
    <div
      ref={mountRef}
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", touchAction: "none" }}
      role="img"
      aria-label="6thSense Skin data glove, rotating render — drag to spin"
    />
  );
}
