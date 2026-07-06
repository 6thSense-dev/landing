// Single source of truth for the Skin composite alignment. Both the live page
// and the in-page aligner (/products?align) read this. Everything is a flat 2D
// image (robotic hand + glove photo) — no WebGL/camera — so what you align on
// the page is exactly what ships, at every screen size.
//
//   size      overall composite scale (both hands together)
//   rob*      robotic hand image: scale, X/Y position (%), rotation (deg)
//   robCrop   seam, % — robotic shown LEFT of this
//   robBottom % cropped off the robotic's bottom
//   glo*      glove photo: scale, X/Y position (%), rotation (deg)
//   gloCrop   clip, % — glove shown RIGHT of this
//   gloBottom % cropped off the glove's bottom
//   flip      mirror the glove horizontally
export const SKIN_ALIGN = {
  size: 1.4,
  robScale: 0.78,
  robX: 10,
  robY: 0,
  robRot: -2,
  robCrop: 46,
  robBottom: 0,
  gloScale: 1.06,
  gloX: -28,
  gloY: 12,
  gloRot: 3,
  gloCrop: 46,
  gloBottom: 13,
  flip: false,
};
