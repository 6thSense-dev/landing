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
export const GLOVE_ALIGN = {
  "000": { scale: 1, x: 0, y: 0 },
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
 * 13000 is deliberately slower than the old 60Hz behaviour (Ronak asked for slower);
 * it is also ~3x slower than what a 120Hz display was actually getting.
 * Tune live at /glove-tune, then paste the value back here.
 */
export const GLOVE_CYCLE_MS = 13000;

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
