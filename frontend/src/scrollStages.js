export const scrollStages = [
  {
    id: "glove",
    frameDir: "/hero/glove",
    frameCount: 6,
    // Asset indices whose PIXELS are actually painted on the homepage. This is
    // ScrollStage's BEAT_TO_ASSET — frame 0 (the fist) is never drawn there.
    //
    // frameCount stays 6 because every per-frame array in ScrollStage
    // (PER_FRAME_TIP_V / _TIP_Y / _ZOOM) is indexed by ASSET index, so the
    // loaded array has to keep slot 0 even when nothing occupies it. The
    // preloader leaves unpainted slots null rather than compacting them.
    //
    // Frame 0 is the single largest frame on disk (~512KB full tier / ~88KB
    // w1100). It used to be fetched purely so tipYForFrame() could read its
    // naturalWidth/naturalHeight — two numbers that are identical for every
    // frame in a tier. tipYForFrame() now reads them off the frame it is
    // already given, so the fist's pixels are dead weight on this page.
    // /products still paints frame 0, so the file stays on disk.
    paintedIndices: [1, 2, 3, 4, 5]
  }
];
