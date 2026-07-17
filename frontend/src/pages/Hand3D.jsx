import { useEffect, useRef } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

/**
 * Hand3D — Phase 3a of the /products v2 Hand scene.
 *
 * Renders an ANIMATED, assembled 3D render of the dexterous hand by parsing the
 * MuJoCo MJCF (`/hand/right_hand.xml`) <body> tree into nested THREE.Groups and
 * parenting each link's STL mesh under its body.
 *
 * Phase 3b (this file): a looping "power-on" gesture. Every MJCF <joint> is a
 * hinge at pos 0 0 0, so we rotate that body's Group about the joint's local
 * axis. We record each joint group by name during the tree walk, then drive the
 * angles from a RAF clock with smootherstep easing:
 *   thumb curls first -> all fingers curl to a fist -> fingers open one-by-one
 *   (staggered) -> hold open -> pause -> loop. Plus a slow calm idle yaw.
 * dip is coupled to pip and thumb_ip to thumb_mcp (natural tendon coupling).
 * 0 rad = fully open; positive angle = flexion/curl (MJCF range 0..1.5708).
 * (3c = skin warp — see tasks/products-v2-roadmap.md.)
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

export default function Hand3D({ onReady }) {
  const mountRef = useRef(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;
    let disposed = false;
    // Fire onReady exactly once, when the model has loaded + first rendered, so
    // the parent can drop the robo.webp placeholder. Guarded against re-fires.
    let notifiedReady = false;
    const signalReady = () => {
      if (notifiedReady || disposed) return;
      notifiedReady = true;
      if (onReady) onReady();
    };

    const scene = new THREE.Scene();
    // Telephoto (narrow FOV): compresses perspective so the fist folding toward
    // the camera doesn't read as a "zoom"/size change. Distance auto-compensates
    // in frameCamera() to keep the hand the same on-screen size.
    const camera = new THREE.PerspectiveCamera(14, 1, 0.001, 100);
    // Defensive: if WebGL context creation fails at runtime, bail without
    // crashing the page (the parent already gates on WebGL support, but a lost/
    // blocked context can still throw). The transparent div just stays empty.
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch (err) {
      console.warn("[Hand3D] WebGL unavailable, skipping 3D hand:", err);
      return;
    }
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

    // ---- Skin dissolve/warp overlay (Phase 3c) ------------------------------
    // A second shell mesh over every link (shares the same STL geometry) draped
    // in the 6thSense tactile "skin". A custom shader dissolves it in from the
    // wrist upward via value-noise threshold, with a soft light-red rim glow at the
    // growing boundary and a slight normal-warp while forming. Driven by uReveal
    // on its OWN slow timer, offset from the gesture clock, so the skin appearing
    // and the hand's gesture are asynchronous. uReveal=0 => fully discarded, so
    // the default metal hand is untouched when the skin is absent.
    const GLSL_NOISE = `
      float hash(vec3 p){ p=fract(p*0.3183099+0.1); p*=17.0; return fract(p.x*p.y*p.z*(p.x+p.y+p.z)); }
      float vnoise(vec3 x){
        vec3 i=floor(x), f=fract(x); f=f*f*(3.0-2.0*f);
        return mix(mix(mix(hash(i+vec3(0,0,0)),hash(i+vec3(1,0,0)),f.x),
                       mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
                   mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),
                       mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);
      }`;
    const skinMaterial = new THREE.ShaderMaterial({
      transparent: true,
      depthWrite: false,
      side: THREE.FrontSide,
      uniforms: {
        uReveal: { value: 0.0 },
        uTime: { value: 0.0 },
        uYMin: { value: -0.1 },
        uYMax: { value: 0.1 },
        uColor: { value: new THREE.Color(0x14090a) }, // near-black glove body, faint red tint
        // Rim/glow color is now sampled per-fragment from a warm-biased aurora
        // palette (see warmPalette() in the fragment shader) instead of one flat
        // color, so the dissolving edge shimmers red/orange/amber with a band of
        // purple and occasional cool hits. uSat/uPurple are live-tunable knobs.
        uSat: { value: 0.82 },     // overall saturation of the glow (subtle when lower)
        uPurple: { value: 1.0 },   // 0..1.5 weight on the violet accent (warm still dominates)
        uCamPos: { value: new THREE.Vector3() },
      },
      vertexShader: `
        ${GLSL_NOISE}
        uniform float uReveal; uniform float uWarpTime;
        varying vec3 vWorld; varying vec3 vNormalW;
        void main(){
          vec3 n = normalize(normal);
          // constant tiny outset (avoid z-fight w/ the metal shell) + warp while forming
          float warp = (1.0 - uReveal) * 0.004 * (vnoise(position * 34.0) - 0.5);
          vec3 p = position + n * (0.0007 + warp);
          vec4 wp = modelMatrix * vec4(p, 1.0);
          vWorld = wp.xyz;
          vNormalW = normalize(mat3(modelMatrix) * n);
          gl_Position = projectionMatrix * viewMatrix * wp;
        }`,
      fragmentShader: `
        ${GLSL_NOISE}
        uniform float uReveal; uniform float uTime;
        uniform float uYMin; uniform float uYMax;
        uniform vec3 uColor; uniform vec3 uCamPos;
        uniform float uSat; uniform float uPurple;
        varying vec3 vWorld; varying vec3 vNormalW;

        vec3 hsv2rgb(vec3 c){
          vec4 K = vec4(1.0, 2.0/3.0, 1.0/3.0, 3.0);
          vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
          return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
        }
        void main(){
          float g = clamp((vWorld.y - uYMin) / max(uYMax - uYMin, 1e-4), 0.0, 1.0);
          float n = vnoise(vWorld * 55.0 + vec3(0.0, 0.0, uTime * 0.15));
          float coord = g * 0.62 + n * 0.38;      // sweep from wrist up, broken by noise
          float edge = 0.07;
          float a = smoothstep(uReveal + edge, uReveal - edge, coord);
          if (a < 0.01) discard;
          float rim = smoothstep(edge, 0.0, abs(coord - uReveal)); // hot line at boundary

          // ---- warm sunset-aurora glow, built in layers. Warm DOMINATES (red ->
          // orange -> amber -> gold); rose/magenta is a warm secondary; violet is
          // a rare garnish; teal a whisper. Each layer is driven by its own noise
          // field so the accents appear in sparse patches, not everywhere. -------
          // Base (~dominant): warm sweep red -> orange -> amber -> gold.
          float w1 = vnoise(vWorld * 5.0 + vec3(uTime * 0.06, 0.0, uTime * 0.04));
          vec3 warm = hsv2rgb(vec3(mix(0.005, 0.11, w1), mix(0.95, 0.80, w1), 1.0));
          // w2 ramps the accent coolward: warm -> rose (mid) -> violet (high), so
          // purple actually shows in patches (~25% of the edge) while warm stays
          // the base. (The old top-slice threshold never fired -> no purple.)
          float w2 = vnoise(vWorld * 3.2 + vec3(37.0, uTime * 0.05, -uTime * 0.035));
          float roseAmt = smoothstep(0.42, 0.70, w2);
          vec3 rose = hsv2rgb(vec3(0.93, 0.78, 0.98));            // magenta-pink
          float purpleAmt = smoothstep(0.62, 0.88, w2) * clamp(uPurple, 0.0, 1.5);
          vec3 purple = hsv2rgb(vec3(0.77, 0.72, 0.96));          // clear violet
          // Teal whisper: rarest, from a 3rd field's top slice.
          float w3 = vnoise(vWorld * 7.0 + vec3(-19.0, uTime * 0.09, 11.0));
          float coolAmt = smoothstep(0.82, 0.97, w3);
          vec3 cool = hsv2rgb(vec3(0.52, 0.50, 0.96));
          vec3 edgeCol = warm;
          edgeCol = mix(edgeCol, rose, roseAmt * 0.60);
          edgeCol = mix(edgeCol, purple, purpleAmt * 0.72);
          edgeCol = mix(edgeCol, cool, coolAmt * 0.40);
          // Overall saturation trim (uSat: lower = more muted).
          float luma = dot(edgeCol, vec3(0.299, 0.587, 0.114));
          edgeCol = clamp(mix(vec3(luma), edgeCol, clamp(uSat / 0.82, 0.0, 1.4)), 0.0, 1.0);

          vec3 col = mix(uColor, edgeCol, rim);
          float fres = pow(1.0 - max(dot(normalize(vNormalW), normalize(uCamPos - vWorld)), 0.0), 2.0);
          col += edgeCol * fres * 0.45 * a;        // colored fresnel keeps the black silhouette readable
          gl_FragColor = vec4(col, a * (0.5 + rim * 0.5));
        }`,
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
    // jointName -> { group, axis (unit Vector3, body-local), base (rest quaternion) }
    const jointGroups = {};
    // bodyName -> THREE.Group (used to auto-orient the hand from its geometry)
    const namedGroups = {};
    let oriented = false;
    let pending = 0;
    let started = false;
    let rafId = 0;
    let startMs = 0;

    const sizeToMount = () => {
      const w = mount.clientWidth || 480;
      const h = mount.clientHeight || 480;
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
    };

    // Auto-orient the hand from its own geometry (robust to the MJCF's frames):
    // rotate so the fingers point up (+Y) and the palm faces the viewer (+Z).
    // Runs ONCE, at pivot yaw 0, so the world frame == the pivot frame and the
    // correction can be premultiplied onto rootGroup safely.
    const orientHand = () => {
      if (oriented) return;
      const palm = namedGroups["palm"];
      const tipNames = [
        "right_index_distal_link", "right_middle_distal_link",
        "right_ring_distal_link", "right_pinky_distal_link",
      ];
      const tips = tipNames.map((n) => namedGroups[n]).filter(Boolean);
      if (!palm || tips.length < 2) return;
      pivot.rotation.y = 0;
      rootGroup.updateWorldMatrix(true, true);
      const V = () => new THREE.Vector3();
      const wrist = palm.getWorldPosition(V());
      const mid = V();
      tips.forEach((t) => mid.add(t.getWorldPosition(V())));
      mid.multiplyScalar(1 / tips.length);
      const fingerDir = mid.clone().sub(wrist).normalize();      // wrist -> fingertips
      const idx = namedGroups["right_index_distal_link"].getWorldPosition(V());
      const pnk = namedGroups["right_pinky_distal_link"].getWorldPosition(V());
      const spread = idx.clone().sub(pnk).normalize();           // across the knuckles
      // Build an orthonormal source basis (y = up along fingers, z = out of palm).
      const yS = fingerDir.clone();
      const zS = new THREE.Vector3().crossVectors(spread, yS).normalize(); // palm normal
      const xS = new THREE.Vector3().crossVectors(yS, zS).normalize();
      zS.crossVectors(xS, yS).normalize();
      const mSrc = new THREE.Matrix4().makeBasis(xS, yS, zS);
      // Inverse of the source basis maps (fingerDir->+Y, palmNormal->+Z).
      const qCorr = new THREE.Quaternion().setFromRotationMatrix(mSrc).invert();
      rootGroup.quaternion.premultiply(qCorr);
      rootGroup.updateWorldMatrix(true, true);
      oriented = true;
    };

    const frameCamera = () => {
      const box = new THREE.Box3().setFromObject(rootGroup);
      if (box.isEmpty()) return;
      const size = new THREE.Vector3();
      const center = new THREE.Vector3();
      box.getSize(size);
      box.getCenter(center);
      // Recenter the hand at the pivot origin (idempotent) so the idle yaw
      // spins it in place instead of orbiting it out of frame.
      rootGroup.position.sub(center);
      // After recenter the world-Y range is symmetric about 0; feed it to the
      // skin shader so the dissolve sweeps wrist -> fingertips.
      skinMaterial.uniforms.uYMin.value = -size.y / 2;
      skinMaterial.uniforms.uYMax.value = size.y / 2;
      // Portrait hand: frame on height so it reads big in the scene column, but
      // clamp on width so a wide 3/4 can't overflow. Product-is-hero => tight-ish.
      const fitDim = Math.max(size.y, size.x * 1.1, size.z);
      const fov = (camera.fov * Math.PI) / 180;
      const dist = (fitDim / 2 / Math.tan(fov / 2)) * 2.05; // pushed back a bit -> flatter perspective, less forward "zoom" at fist
      // Gentle 3/4: mostly front-on (palm to viewer), a little from the right and
      // slightly above. Camera sits on +Z so the palm normal (+Z) faces it.
      const dir = new THREE.Vector3(0.32, 0.16, 1).normalize();
      camera.position.copy(dir.multiplyScalar(dist));
      camera.lookAt(0, 0, 0);
      camera.near = dist / 100;
      camera.far = dist * 100;
      camera.updateProjectionMatrix();
    };

    const render = () => {
      if (disposed) return;
      renderer.render(scene, camera);
    };

    // ---- Gesture animation (Phase 3b) ---------------------------------------
    const tmpQ = new THREE.Quaternion();
    const setJoint = (name, angle) => {
      const j = jointGroups[name];
      if (!j) return;
      tmpQ.setFromAxisAngle(j.axis, angle);
      j.group.quaternion.copy(j.base).multiply(tmpQ); // rest * jointRotation
    };
    // Perlin-style smootherstep (C2 continuous) for calm ease-in/out.
    const smoother = (a, b, x) => {
      let u = (x - a) / (b - a);
      u = u < 0 ? 0 : u > 1 ? 1 : u;
      return u * u * u * (u * (u * 6 - 15) + 10);
    };
    const FINGERS = ["index", "middle", "ring", "pinky"];
    // Slightly looser fist so the fingers don't punch toward the camera (palm
    // faces the viewer, so a tight curl reads as a forward "zoom").
    const MCP = 1.28, PIP = 1.34, TH = 1.1; // curl targets (rad), within 0..1.5708
    const CYCLE = 10.0; // seconds per full power-on loop (slower, calmer motion)
    // Skin reveal runs on its OWN clock (coprime-ish period + phase offset) so
    // the tactile skin dissolving in is async from the hand's gesture.
    const SKIN_CYCLE = 10.0;  // s per skin appear->hold->dissolve-out->pause loop
    const SKIN_OFFSET = 3.1;  // s phase shift off the gesture clock

    const animate = (nowMs) => {
      if (disposed) return;
      rafId = requestAnimationFrame(animate);
      if (!started) return;
      const t = ((nowMs - startMs) / 1000) % CYCLE;

      // Thumb leads: curls 0.56->1.68s, opens last 5.28->6.40s (times stretched
      // ~1.6x from the original so the motion itself is slower, not just paused).
      const thumb = smoother(0.56, 1.68, t) * (1 - smoother(5.28, 6.4, t));
      setJoint("right_thumb_cmc_abd", thumb * 0.9);   // opposition (axis 0 1 0)
      setJoint("right_thumb_cmc_flex", thumb * 0.5);
      setJoint("right_thumb_mcp", thumb * TH);
      setJoint("right_thumb_ip", thumb * TH);          // ip coupled to mcp

      // Fingers curl together after the thumb, then open one-by-one (staggered).
      const close = smoother(1.68, 2.96, t);
      for (let i = 0; i < FINGERS.length; i++) {
        const openStart = 4.32 + i * 0.29;
        const curl = close * (1 - smoother(openStart, openStart + 0.96, t));
        const f = FINGERS[i];
        setJoint(`right_${f}_mcp_flex`, curl * MCP);
        setJoint(`right_${f}_pip`, curl * PIP);
        setJoint(`right_${f}_dip`, curl * PIP);        // dip coupled to pip
      }

      // Slow calm idle yaw (in-place, since the hand is recentered).
      pivot.rotation.y = Math.sin(((nowMs - startMs) / 1000) * 0.25) * 0.22;

      // Skin dissolve on its own async clock: dissolve IN, hold, dissolve OUT,
      // then a long pause with no skin (reveal reverses the same threshold).
      const st = ((nowMs - startMs) / 1000 + SKIN_OFFSET) % SKIN_CYCLE;
      // Sweep-on (2.2s), hold, dissolve-off (2.2s), then a short pause.
      const reveal = smoother(0.0, 2.2, st) * (1.0 - smoother(6.2, 8.4, st));
      skinMaterial.uniforms.uReveal.value = reveal;
      skinMaterial.uniforms.uTime.value = (nowMs - startMs) / 1000;
      skinMaterial.uniforms.uCamPos.value.copy(camera.position);

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
          const bodyName = bodyEl.getAttribute("name");
          if (bodyName) namedGroups[bodyName] = g;

          for (const child of bodyEl.children) {
            if (child.tagName === "joint") {
              // Record the hinge so the animation loop can rotate this body.
              const jn = child.getAttribute("name");
              if (jn) {
                const ax = readVec(child, "axis", [1, 0, 0]);
                jointGroups[jn] = {
                  group: g,
                  axis: new THREE.Vector3(ax[0], ax[1], ax[2]).normalize(),
                  base: g.quaternion.clone(),
                };
              }
            } else if (child.tagName === "geom") {
              const meshName = child.getAttribute("mesh");
              // Only visual link meshes: skip collision/tendon helper geoms.
              // Tendon-viz meshes carry a `group` attr; skip those.
              if (!meshName || child.getAttribute("group")) continue;
              // Skip the industrial mounting bracket — it's the robot-arm adapter,
              // not the hand. Hiding it makes the hand the hero (design principle:
              // "product is the hero"). The real hand frame is mesh right_frame_link.
              if (meshName === "tetheria_mount") continue;
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
                  // Skin shell: same geometry + transform, drawn after the metal.
                  const skin = new THREE.Mesh(bufGeo, skinMaterial);
                  applyTransform(skin, geomEl);
                  skin.renderOrder = 1;
                  g.add(skin);
                  if (pending === 0) { orientHand(); frameCamera(); signalReady(); }
                  render();
                },
                undefined,
                () => { pending--; if (pending === 0) { orientHand(); frameCamera(); render(); signalReady(); } }
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
        if (pending === 0) signalReady(); // no meshes queued -> don't strand the placeholder
        startMs = performance.now();
        rafId = requestAnimationFrame(animate);
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
      if (rafId) cancelAnimationFrame(rafId);
      ro.disconnect();
      material.dispose();
      skinMaterial.dispose();
      scene.traverse((o) => { if (o.geometry) o.geometry.dispose(); });
      renderer.dispose();
      if (renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    };
  }, []);

  return <div ref={mountRef} className="hand3d-canvas" aria-label="3D dexterous hand render" role="img" />;
}
