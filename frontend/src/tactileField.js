// frontend/src/tactileField.js
// Canvas2D "constellation" background: sparse colored nodes drift slowly,
// nearby nodes link with faint edges, nodes near the pointer grow.

const NODE_COUNT = 288;
const LINK_DISTANCE = 210;     // CSS px — nodes closer than this get an edge
const HOVER_RADIUS = 180;      // CSS px — nodes inside this scale up on hover
const HOVER_SCALE = 2.1;       // max scale multiplier under the pointer
const DRIFT_SPEED = 0.22;      // CSS px per frame (60 fps ≈ 13 px/s)
const MIN_LAYOUT_PX = 64;      // defer seeding until canvas has real dimensions
const EDGE_ALPHA = 0.22;       // peak edge opacity; fades with distance
const TWINKLE_ALPHA = 0.35;    // ±alpha swing from the twinkle wave
const TWINKLE_SIZE = 0.22;     // ±size swing (fraction of base)
const BOB_AMPLITUDE = 2.5;     // CSS px — sub-pixel water ripple

const EDGE_COLOR = "197, 224, 99";   // #c5e063 lime, as r,g,b for rgba()
const NODE_PALETTE = [
  "#c5e063", // brand lime
  "#7a8f3a", // deep olive
  "#d08a87", // muted pink
  "#a78463", // soft tan
  "#e8d9a6"  // cream
];

export function initTactileField(canvas) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;

  const nodes = [];

  const state = {
    w: 0, h: 0,                // CSS pixels
    pointerX: -9999,
    pointerY: -9999,
    pressure: 0,               // 0..1, wrapper decays on pointer leave
    reduced: 0,
    lastT: 0,
    disposed: false
  };

  const seed = () => {
    nodes.length = 0;
    for (let i = 0; i < NODE_COUNT; i++) {
      const angle = Math.random() * Math.PI * 2;
      nodes.push({
        x: Math.random() * state.w,
        y: Math.random() * state.h,
        vx: Math.cos(angle) * DRIFT_SPEED,
        vy: Math.sin(angle) * DRIFT_SPEED,
        color: NODE_PALETTE[Math.floor(Math.random() * NODE_PALETTE.length)],
        baseSize: 5.5 + Math.random() * 3.5,  // 5.5–9 CSS px dot — readable mesh at rest
        // Per-node shimmer params — each particle has its own phase/frequency
        // so the field twinkles asynchronously instead of pulsing in unison.
        twPhase: Math.random() * Math.PI * 2,
        twFreq:  0.5 + Math.random() * 1.2,   // twinkle rad/s
        bobPhaseX: Math.random() * Math.PI * 2,
        bobPhaseY: Math.random() * Math.PI * 2,
        bobFreqX:  0.25 + Math.random() * 0.45,
        bobFreqY:  0.25 + Math.random() * 0.45
      });
    }
  };

  return {
    setPointer(x, y, pressure) {
      state.pointerX = x;
      state.pointerY = y;
      state.pressure = pressure;
    },
    setReduced(r) {
      state.reduced = r ? 1 : 0;
    },
    setSize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const cssW = canvas.clientWidth;
      const cssH = canvas.clientHeight;

      // Canvas often mounts at 0×0 (or 1×1) before layout. Seeding there
      // clusters every node in a pin-point that slowly drifts apart — the
      // "tiny green mesh spawn" artifact. Wait for a real viewport, then
      // re-seed once when we graduate from the placeholder size.
      if (cssW < MIN_LAYOUT_PX || cssH < MIN_LAYOUT_PX) return;

      const prevW = state.w;
      const prevH = state.h;
      const hadPlaceholderLayout =
        prevW > 0 && prevH > 0 && (prevW < MIN_LAYOUT_PX || prevH < MIN_LAYOUT_PX);

      canvas.width = Math.round(cssW * dpr);
      canvas.height = Math.round(cssH * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      state.w = cssW;
      state.h = cssH;

      if (nodes.length === 0 || hadPlaceholderLayout) {
        seed();
        return;
      }

      // Keep the field distributed when the viewport resizes materially.
      if (prevW > 0 && prevH > 0) {
        const scaleX = cssW / prevW;
        const scaleY = cssH / prevH;
        if (Math.abs(scaleX - 1) > 0.12 || Math.abs(scaleY - 1) > 0.12) {
          for (const n of nodes) {
            n.x *= scaleX;
            n.y *= scaleY;
          }
        }
      }
    },
    render(timeSec) {
      if (state.disposed) return;
      const { w, h } = state;
      if (w === 0 || h === 0) return;

      // Step drift motion. Reduced-motion users get a calmer drift.
      const motionScale = state.reduced ? 0.25 : 1.0;
      for (const n of nodes) {
        n.x += n.vx * motionScale;
        n.y += n.vy * motionScale;
        if (n.x < -10) n.x = w + 10;
        else if (n.x > w + 10) n.x = -10;
        if (n.y < -10) n.y = h + 10;
        else if (n.y > h + 10) n.y = -10;
      }

      // Per-node rendered positions (drift + bob). Cached so edges & nodes stay
      // in sync without two sin() calls per pair.
      const rxs = new Float32Array(nodes.length);
      const rys = new Float32Array(nodes.length);
      const twinkles = new Float32Array(nodes.length);
      const bobAmp = BOB_AMPLITUDE * motionScale;
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        rxs[i] = n.x + Math.sin(timeSec * n.bobFreqX + n.bobPhaseX) * bobAmp;
        rys[i] = n.y + Math.sin(timeSec * n.bobFreqY + n.bobPhaseY) * bobAmp;
        // Twinkle wave in 0..1. Reduced motion mutes the swing.
        twinkles[i] = (Math.sin(timeSec * n.twFreq + n.twPhase) * 0.5 + 0.5)
                    * motionScale;
      }

      ctx.clearRect(0, 0, w, h);

      // Edges first so nodes overdraw them.
      ctx.lineWidth = 1;
      const linkD2 = LINK_DISTANCE * LINK_DISTANCE;
      for (let i = 0; i < nodes.length; i++) {
        const ax = rxs[i], ay = rys[i];
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = ax - rxs[j], dy = ay - rys[j];
          const d2 = dx * dx + dy * dy;
          if (d2 > linkD2) continue;
          const d = Math.sqrt(d2);
          const alpha = (1 - d / LINK_DISTANCE) * EDGE_ALPHA;
          ctx.strokeStyle = `rgba(${EDGE_COLOR}, ${alpha.toFixed(3)})`;
          ctx.beginPath();
          ctx.moveTo(ax, ay);
          ctx.lineTo(rxs[j], rys[j]);
          ctx.stroke();
        }
      }

      // Nodes as small filled circles with twinkle + hover brightening.
      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i];
        const rx = rxs[i], ry = rys[i];
        const dx = rx - state.pointerX, dy = ry - state.pointerY;
        const d = Math.sqrt(dx * dx + dy * dy);
        const hover =
          d < HOVER_RADIUS ? (1 - d / HOVER_RADIUS) * state.pressure : 0;
        const tw = twinkles[i];
        const radius =
          (n.baseSize * (1 + hover * (HOVER_SCALE - 1) + TWINKLE_SIZE * (tw - 0.5) * 2)) / 2;
        ctx.globalAlpha = 0.55 + TWINKLE_ALPHA * tw + 0.3 * hover;
        ctx.fillStyle = n.color;
        ctx.beginPath();
        ctx.arc(rx, ry, radius, 0, Math.PI * 2);
        ctx.fill();
      }

      state.lastT = timeSec;
    },
    dispose() {
      state.disposed = true;
    }
  };
}
