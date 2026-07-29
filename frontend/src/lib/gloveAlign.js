// Single source of truth for PER-FRAME glove flip-book alignment.
//
// The 6 glove photos (frame-000..005) were shot separately, so the hand isn't
// framed identically in each one — the closed-fist frame in particular reads a
// little larger than the open ones, which makes the crossfade "pulse" instead
// of morphing cleanly. Rather than re-shooting or re-cropping the assets, each
// frame gets a small corrective transform applied at render time.
//
// Both the live products page (ProductsV2) and the in-page aligner (/glove-tune)
// read this, so what you align in the tuner is exactly what ships.
//
//   scale   multiplier on the frame (1 = untouched, <1 shrinks, >1 grows)
//   x / y   nudge in PERCENT of the stage box (positive x = right, y = down)
//
// Tune visually at /glove-tune (onion-skins the other frames underneath so you
// can size-match by eye), then paste the printed block back in here.
const IDENTITY = { scale: 1, x: 0, y: 0 };

export const GLOVE_ALIGN = {
  // Tuned by Ronak 2026-07-28 via ?tune compare mode against frame 001.
  // Only the fist needed correcting; it was shot noticeably closer than the rest.
  "000": { scale: 0.790, x: 0.25, y: 4.50 },
  "001": { scale: 1, x: 0, y: 0 },
  "002": { scale: 1, x: 0, y: 0 },
  "003": { scale: 1, x: 0, y: 0 },
  "004": { scale: 1, x: 0, y: 0 },
  "005": { scale: 1, x: 0, y: 0 },
};

/** Frame ids in flip-book order — the one list both the page and tuner iterate. */
export const GLOVE_FRAME_IDS = ["000", "001", "002", "003", "004", "005"];

/**
 * Duration of ONE full flip-book cycle in milliseconds — closed -> open -> closed.
 * A sine drives the frame position, so this is the sine's period, not a per-frame
 * hold time.
 *
 * This used to be a bare `Math.sin(t * 0.012)` where `t` counted requestAnimationFrame
 * TICKS, not time. That made the animation frame-rate dependent: 523.6 ticks per cycle
 * is ~8.7s on a 60Hz display but only ~4.4s on a 120Hz ProMotion Mac or iPhone, so the
 * glove visibly raced on exactly the hardware most likely to be looking at it. Now it is
 * wall-clock driven and identical everywhere.
 *
 * Picking this number needs care, because "the old speed" was two different speeds.
 * At 60Hz the old code ran ~8.7s; at 120Hz (ProMotion Mac / iPhone) ~4.4s. Ronak
 * reviews on a 120Hz machine, so his felt baseline was ~4.4s and a 13000 default
 * read as "insanely slow" — 3x his reference, not a little slower than it.
 * 6000 is a modest slowdown from that real baseline.
 *
 * Tune live with `?tune` on /products (sliders over the real scene), or at
 * /glove-tune, then paste the value back here.
 */
export const GLOVE_CYCLE_MS = 4500;

/**
 * Live-tuning overrides, only ever written by the `?tune` panel on /products.
 * The rAF loop reads these each tick so a slider drag is felt immediately without
 * a rebuild. `active` stays false in normal page loads, and when it is false the
 * loop takes the shipped constants above, so this costs production nothing.
 */
function makeLiveTune() {
  return {
    active: false,
    cycleMs: GLOVE_CYCLE_MS,
    // Per-frame { scale, x, y } — same shape as GLOVE_ALIGN so the paste block is
    // a straight copy of this, and x/y stay in PERCENT of the stage box.
    align: Object.fromEntries(GLOVE_FRAME_IDS.map((id) => [id, { ...(GLOVE_ALIGN[id] || IDENTITY) }])),
    // Frame INDEX to freeze on, or null to keep cycling. Without this you cannot
    // actually size a specific frame: the crossfade is only showing frames `base`
    // and `base+1` at any instant, so dragging the fist's slider while the animation
    // sits on frame 3 changes nothing you can see.
    hold: null,
    // COMPARE mode: pin frame 000 opaque with frame 001 held translucent on top of
    // it, so the fist can be matched against its neighbour directly. This is the
    // actual working setup — 000 is the frame that needs correcting and 001 is what
    // it has to line up with, so freezing exactly that pair beats cycling.
    compare: false,
    compareAlpha: 0.45,
  };
}

export const liveTune = makeLiveTune();

/** Public URL for a frame id. */
export const gloveFrameSrc = (id) => `/hero/glove/frame-${id}.webp`;

/**
 * CSS transform for a frame id. Returns "none" for an untouched frame so we
 * don't hand the compositor a no-op matrix on every crossfade tick.
 */
export function gloveFrameTransform(id) {
  const a = GLOVE_ALIGN[id];
  if (!a) return "none";
  if (a.scale === 1 && a.x === 0 && a.y === 0) return "none";
  return `translate(${a.x}%, ${a.y}%) scale(${a.scale})`;
}
