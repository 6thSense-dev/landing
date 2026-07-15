/**
 * Homepage narrative content — edit here; UI maps over these structures.
 */
export const heroCopy = {
  wordmark: "6THSENSE",
  tagline: "Robots have five senses. We are building the sixth.",
  deck: "Tactile capture hardware for the next generation of dexterous robots — gloves that feel, and custom skin molded to robot hands."
};

/** Problem framing — keep claims verifiable when replacing placeholders. */
export const tractionItems = [
  {
    label: "Signal gap",
    title: "Contact onset and grip evolution are under-captured",
    detail: "Most capture setups miss touch timing, pressure trends, and the subtle grip adjustments that decide contact-rich tasks.",
    icon: "ActivitySquare"
  },
  {
    label: "Tooling",
    title: "Off-the-shelf stacks produce unusable raw dumps",
    detail: "Standalone sensors and DIY recording scripts fall down on calibration, synchronization, and the reliability real capture demands.",
    icon: "Wrench"
  },
  {
    label: "Operations",
    title: "Teams want to capture, not to build a rig",
    detail: "Robot-learning teams want to record their own demonstrations on day one, not spend months sourcing sensors, wiring rigs, and debugging sync.",
    icon: "Boxes"
  },
  {
    label: "Learning",
    title: "Manipulation progress is data-constrained",
    detail: "For contact-rich tasks, the next performance gains come from better multimodal demonstrations, not model scale alone.",
    icon: "BrainCircuit"
  }
];

export const platformStages = [
  {
    id: "capture",
    step: "01",
    label: "Capture",
    caption: "Wearable + egocentric rigs",
    glyph: "rig"
  },
  {
    id: "sync",
    step: "02",
    label: "Sync",
    caption: "One clock, every modality",
    glyph: "sync"
  },
  {
    id: "calibrate",
    step: "03",
    label: "Calibrate",
    caption: "Drift, fit, and timing checks",
    glyph: "calibrate"
  },
  {
    id: "package",
    step: "04",
    label: "Package",
    caption: "Episodes shipped model-ready",
    glyph: "package"
  }
];

export const platformSummary =
  "Hardware, sync, calibration, packaging — one stack, four stages. You capture your own demonstrations and get aligned episodes, not raw folders.";

/** Offering — data catalog tiles (tune specs to shipped hardware + programs). */
export const dataCatalogTiles = [
  {
    id: "tactile",
    title: "Tactile & pressure proxies",
    spec: "High-rate contact and pressure-aligned streams with per-channel calibration — where touch matters for the task.",
    sync: "Egocentric video, hand pose, IMU, episodes",
    glyph: "wave"
  },
  {
    id: "ego",
    title: "Egocentric video",
    spec: "First-person RGB aligned to what the demonstrator sees — stable exposure for long household runs.",
    sync: "Tactile, depth, wrist & scene views, labels",
    glyph: "eye"
  },
  {
    id: "depth",
    title: "Depth (RGB-D)",
    spec: "Per-frame depth aligned to ego timebase for geometry, reach, and clutter around the hands.",
    sync: "RGB, hand pose, scene layout",
    glyph: "layers"
  },
  {
    id: "hand",
    title: "Hand pose",
    spec: "Articulated hand state and grasp phases for contact-rich manipulation — not just 2D boxes in frame.",
    sync: "Tactile, ego video, object interaction",
    glyph: "hand"
  },
  {
    id: "imu",
    title: "Motion & IMU dynamics",
    spec: "Linear acceleration, angular rates, and movement cues that characterize inertia, rhythm, and effort during the task.",
    sync: "Egocentric video, tactile timing, pose",
    glyph: "imu"
  },
  {
    id: "wrist",
    title: "Wrist & scene cameras",
    spec: "Secondary viewpoints for occlusion recovery, tool use, and context beyond the ego cone (roadmap / program-dependent).",
    sync: "Ego path, depth, annotations",
    glyph: "cam"
  },
  {
    id: "labels",
    title: "Labels & dense commentary",
    spec: "Task and subtask boundaries, contact phases, QC flags — plus optional timestamped, frame-aligned text narration paired to video for richer training supervision.",
    sync: "All synchronized streams · episode contract",
    glyph: "tag"
  },
  {
    id: "outcomes",
    title: "Success / failure outcomes",
    spec: "Binary or graded success, failure modes, and segment-level tags for imitation and evaluation.",
    sync: "Full multimodal episode windows",
    glyph: "check"
  }
];

/**
 * Representative domestic scenes — illustrative of the task families we scope with customers,
 * not an exhaustive or exclusive list.
 */
export const catalogSceneExamples = [
  "Washing & rinsing dishes",
  "Loading / unloading dishwasher",
  "Folding & putting away laundry",
  "Vacuuming & floor cleaning",
  "Coffee & beverage prep"
];

export const catalogMeta = {
  kicker: "What the hardware captures",
  title: "Eight aligned modalities, one episode"
};

export const credibilityPrinciples = [
  {
    num: "01",
    title: "Calibration boundaries, stated",
    body: "We document where each signal is reliable, how drift is handled, and what should never be treated as ground-truth force."
  },
  {
    num: "02",
    title: "Semantics you can train on",
    body: "Pressure proxies, contact timing, and failure flags are defined so policy teams know exactly what each dimension means."
  },
  {
    num: "03",
    title: "Model-ready packaging",
    body: "Episodes land in the formats your trainers expect, with QC metrics and assumptions — not a dump of raw sensor folders."
  }
];
