import * as THREE from "three";

/**
 * The one hologram shader. Every holographic surface on the site is this
 * material — the Skin glove (HoloGlove.jsx), the Eye2 enclosure
 * (HoloTurntable.jsx) and the dexterous hand (Hand3D.jsx `holo` mode) — so the
 * three scenes cannot drift into three slightly different holograms.
 *
 * The look: unlit, additively blended, double-sided. A fresnel rim carries the
 * silhouette, object-space scanlines curve over the form, one soft band sweeps
 * up on a slow loop, and an occasional horizontal tear reads as signal dropout.
 * Nothing here is lit, so a caller's scene lighting is irrelevant to it.
 *
 * Callers that need extra per-surface detail (the glove's grip pad and
 * AprilTag) inject GLSL through `extraPars` / `extraBody` rather than forking
 * the shader. `extraBody` runs with `col` and `a` in scope, just before they
 * are written out, and may modify both.
 */

// [body tint, hot rim/sweep tint]. DESIGN.md is "restrained — black + white +
// one warm orange… warm, not sci-fi cyan", so orange is the on-brand choice;
// white is what reads best against the /products aurora, and cyan exists only
// for comparison.
export const HOLO_HUES = {
  orange: { core: 0xf0612a, rim: 0xffd9c2 },
  cyan: { core: 0x35d6ff, rim: 0xdff6ff },
  white: { core: 0xbcc4cc, rim: 0xffffff },
};

// NOTE: clippingPlanes on a ShaderMaterial does NOTHING without BOTH the
// clipping chunks below AND `clipping: true` on the material — three only wires
// clipping into its own materials. Miss either and the planes are silently
// ignored (which is exactly how the glove's forearm trim failed at first).
const VERT = /* glsl */ `
  #include <clipping_planes_pars_vertex>
  uniform float uTime;
  uniform float uGlitch;
  varying vec3 vNormalW;
  varying vec3 vViewW;
  varying vec3 vPosL;
  varying vec3 vNormalL;
  varying vec3 vPosW;
  varying vec2 vHoloUv;

  void main() {
    vPosL = position;
    vNormalL = normal;
    vHoloUv = uv;
    vec3 pos = position;
    // Occasional horizontal tear, a few bands at a time — the classic hologram
    // signal-dropout. uGlitch = 0 disables it entirely.
    float band = floor((position.y + uTime * 0.3) * 18.0);
    float g = fract(sin(band * 91.7 + floor(uTime * 3.0) * 13.73) * 43758.5453);
    pos.x += step(0.988, g) * (g - 0.994) * 2.2 * uGlitch * uGlitchScale;

    vec4 wp = modelMatrix * vec4(pos, 1.0);
    vPosW = wp.xyz;
    vec4 mvPosition = viewMatrix * wp;   // the clipping chunk reads this by name
    vNormalW = normalize(mat3(modelMatrix) * normal);
    vViewW = normalize(cameraPosition - wp.xyz);
    gl_Position = projectionMatrix * mvPosition;
    #include <clipping_planes_vertex>
  }
`;

const FRAG = /* glsl */ `
  #include <clipping_planes_pars_fragment>
  uniform vec3 uCore;
  uniform vec3 uRim;
  uniform float uTime;
  uniform float uIntensity;
  uniform float uScan;
  uniform float uLineFreq;
  uniform float uSweepScale;
  varying vec3 vNormalW;
  varying vec3 vViewW;
  varying vec3 vPosL;
  varying vec3 vNormalL;
  varying vec3 vPosW;
  varying vec2 vHoloUv;
__EXTRA_PARS__
  void main() {
    #include <clipping_planes_fragment>
    // DoubleSide: flip the normal on back faces so the inner shell rims too —
    // that inner glow is what makes it read as volume rather than a decal.
  #ifdef HOLO_FLAT
    // Face normal from screen-space derivatives. Needed for CAD exports that
    // carry no NORMAL attribute (trimesh writes POSITION only), where the
    // interpolated normal would be 0 and the fresnel would saturate the whole
    // model to white — and it is the right look for a printed enclosure anyway,
    // since it keeps the facets hard instead of smoothing them over.
    vec3 N = normalize(cross(dFdx(vPosW), dFdy(vPosW)));
    N *= sign(dot(N, normalize(vViewW)));
  #else
    vec3 N = normalize(vNormalW) * (gl_FrontFacing ? 1.0 : -1.0);
  #endif
    float fres = pow(1.0 - clamp(dot(N, normalize(vViewW)), 0.0, 1.0), 2.1);

    // Scanlines ride the MESH (object space), not the screen, so they curve
    // over the form instead of sitting on the glass like a CRT filter.
    // uLineFreq/uSweepScale are set from the model's real height at load, so
    // the band count is the same whatever units the source file used.
    float lines = 0.55 + 0.45 * sin(vPosL.y * uLineFreq - uTime * 2.2);
    lines = mix(1.0, lines, uScan * 0.55);

    // One soft band sweeping up the model on a slow loop.
    float sweep = fract(vPosL.y * uSweepScale - uTime * 0.16);
    float band = smoothstep(0.0, 0.03, sweep) * (1.0 - smoothstep(0.03, 0.13, sweep));

    // Additive blending means every term stacks, so the interior has to stay
    // dim or the model turns into a white blob where surfaces overlap.
    vec3 col = uCore * (0.19 + 0.70 * fres) + uRim * (fres * fres * 0.55 + band * 0.30);
    col *= lines;
    float a = clamp(0.12 + 0.7 * fres + band * 0.25, 0.0, 1.0);
__EXTRA_BODY__
    gl_FragColor = vec4(col * uIntensity, a);
  }
`;

/**
 * @param {object}  [o]
 * @param {string}  [o.hue]            key into HOLO_HUES
 * @param {number}  [o.intensity]      overall gain
 * @param {number}  [o.scan]           0..1 scanline depth
 * @param {number}  [o.glitch]         0 disables the tear
 * @param {number}  [o.glitchScale]    tear amplitude in OBJECT units — a model
 *                                     authored in mm needs a bigger number than
 *                                     one authored around unit size
 * @param {boolean} [o.flat]           derive the normal per-face from screen-
 *                                     space derivatives instead of the mesh's
 *                                     NORMAL attribute
 * @param {number}  [o.bands]          scanlines across the model's height
 * @param {number}  [o.modelHeight]    that height, in object units
 * @param {THREE.Plane[]} [o.clippingPlanes]
 * @param {object}  [o.extraUniforms]
 * @param {string}  [o.extraPars]      GLSL pasted above main()
 * @param {string}  [o.extraBody]      GLSL pasted before gl_FragColor; `col`
 *                                     (vec3) and `a` (float) are in scope
 */
export function createHoloMaterial(o = {}) {
  const {
    hue = "white",
    intensity = 1,
    scan = 1,
    glitch = 0.6,
    glitchScale = 1,
    flat = false,
    bands = 44,
    modelHeight = 1,
    clippingPlanes = [],
    extraUniforms = {},
    extraPars = "",
    extraBody = "",
  } = o;
  const pair = HOLO_HUES[hue] || HOLO_HUES.white;

  const uniforms = {
    uTime: { value: 0 },
    uCore: { value: new THREE.Color(pair.core) },
    uRim: { value: new THREE.Color(pair.rim) },
    uIntensity: { value: intensity },
    uScan: { value: scan },
    uGlitch: { value: glitch },
    uGlitchScale: { value: glitchScale },
    uLineFreq: { value: (bands * Math.PI * 2) / (modelHeight || 1) },
    uSweepScale: { value: 1 / (modelHeight || 1) },
    ...extraUniforms,
  };

  const mat = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: "uniform float uGlitchScale;\n" + VERT,
    fragmentShader: FRAG.replace("__EXTRA_PARS__", extraPars).replace(
      "__EXTRA_BODY__",
      extraBody
    ),
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    clippingPlanes,
    clipping: true,
    // dFdx/dFdy in HOLO_FLAT need no extension flag: three is WebGL2-only from
    // r163, where derivatives are core.
    defines: flat ? { HOLO_FLAT: "" } : {},
  });
  return mat;
}

/** Retune the scanline pitch once the model's real height is known. */
export function setHoloScale(mat, modelHeight, bands = 44) {
  const h = modelHeight || 1;
  mat.uniforms.uLineFreq.value = (bands * Math.PI * 2) / h;
  mat.uniforms.uSweepScale.value = 1 / h;
}
