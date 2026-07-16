/**
 * Secondary-page content manifest — single source of truth.
 *
 * Consumed by BOTH:
 *   - scripts/seoPrerenderPlugin.js  → emits a crawlable static `dist/<path>/index.html`
 *     per entry at build time (own <title>/description/canonical + hidden content block).
 *   - src/pages/ProductPage.jsx      → renders the styled, client-side page.
 *
 * Keep hardware claims verifiable. Hard numbers are marked `[SPEC: …]` — replace
 * with real values before promoting these pages in the main nav.
 */

export const productPages = [
  {
    path: "/product",
    kicker: "The 6thSense stack",
    title: "Product — Tactile Capture Stack for Robot Learning | 6thSense",
    description:
      "The 6thSense capture stack: a tactile sensing glove, contact-sensing skin, and an egocentric rig that record synchronized, model-ready demonstration data for contact-rich robot manipulation.",
    h1: "One capture stack. Three parts.",
    intro:
      "6thSense captures touch-aware human demonstrations for dexterous robots. The glove, the skin, and the egocentric rig record together on one clock — so every episode ships as aligned, model-ready data instead of raw sensor folders.",
    sections: [
      {
        h2: "Built for contact-rich manipulation",
        body: "Most demonstration data misses the moment of contact — onset timing, pressure evolution, and the small grip adjustments that decide whether a task succeeds. The 6thSense stack is designed to capture exactly those signals, calibrated and time-aligned across every modality.",
      },
      {
        h2: "How the stack works",
        body: "Capture, sync, calibrate, package — one pipeline, four stages.",
        items: [
          "Capture — the wearable glove, tactile skin, and egocentric rig record in parallel.",
          "Sync — one clock aligns every modality to a shared timebase.",
          "Calibrate — drift, fit, and timing checks, per channel.",
          "Package — episodes delivered model-ready, with QC metrics and documented assumptions.",
        ],
      },
    ],
    cards: [
      {
        href: "/product/gloves",
        title: "Gloves",
        blurb:
          "Wearable tactile glove — high-rate contact and pressure streams with per-channel calibration and grasp-phase tracking.",
      },
      {
        href: "/product/skin",
        title: "Skin",
        blurb:
          "Contact-sensing tactile skin — pressure proxies placed where touch matters for the task, with stated calibration boundaries.",
      },
      {
        href: "/product/rig",
        title: "Rig",
        blurb:
          "Egocentric capture rig — first-person RGB, depth, and IMU aligned to the same timebase as touch.",
      },
    ],
    related: [{ href: "/", label: "Home" }],
  },

  {
    path: "/product/gloves",
    kicker: "Hardware",
    title: "Tactile Sensing Glove for Robot Manipulation Data | 6thSense",
    description:
      "The 6thSense tactile glove records high-rate contact and pressure-aligned streams with per-channel calibration and grasp-phase tracking — capturing the touch signals that drive dexterous manipulation.",
    h1: "The tactile glove.",
    intro:
      "A wearable glove that captures what the hand feels — contact onset, pressure evolution, and grip adjustments — at high rate and time-aligned to everything else in the episode.",
    sections: [
      {
        h2: "What it captures",
        items: [
          "High-rate contact and pressure-aligned streams across the fingers and palm.",
          "Per-channel calibration, so each signal has documented, trainable meaning.",
          "Grasp phases and contact timing for contact-rich manipulation — not just 2D boxes in frame.",
          "440 tactile channels in a 20×22 grid — fingertips, finger pads, and palm — 16-bit (~0.01 N), <1 ms response, ~200 Hz.",
          "6-axis IMU plus device-side microsecond-monotonic timestamps; wired USB-C or wireless BLE 5.x, left and right variants.",
        ],
      },
      {
        h2: "Why it matters",
        body: "Pressure proxies and contact timing are defined so policy teams know exactly what each dimension means — and where it should, and shouldn't, be treated as ground-truth force.",
      },
    ],
    related: [
      { href: "/product/skin", label: "Skin" },
      { href: "/product/rig", label: "Rig" },
      { href: "/product", label: "The stack" },
    ],
  },

  {
    path: "/product/skin",
    kicker: "Hardware",
    title: "Tactile Skin & Pressure Sensing for Robotics | 6thSense",
    description:
      "6thSense tactile skin adds contact and pressure sensing exactly where touch matters for the task, with per-channel calibration and clearly stated reliability boundaries.",
    h1: "The tactile skin.",
    intro:
      "A conformable sensing layer that brings contact and pressure signal to the surfaces that touch the world — placed where the task needs it.",
    sections: [
      {
        h2: "What it captures",
        items: [
          "Contact and pressure proxies with per-channel calibration.",
          "Placement tuned to the task — where touch actually matters.",
          "Built on the same tactile-sensing family as the glove — 16-bit pressure sensing, <1 ms response, ~200 Hz — with the channel layout molded to each surface rather than fixed to a grid.",
          "Signals time-aligned to the glove, video, depth, and IMU in the same episode.",
        ],
      },
      {
        h2: "Calibration boundaries, stated",
        body: "We document where each signal is reliable, how drift is handled, and what should never be treated as ground-truth force — so what you train on is honest.",
      },
    ],
    related: [
      { href: "/product/gloves", label: "Gloves" },
      { href: "/product/rig", label: "Rig" },
      { href: "/product", label: "The stack" },
    ],
  },

  {
    path: "/product/rig",
    kicker: "Hardware",
    title: "Egocentric Capture Rig for Robot Demonstration Data | 6thSense",
    description:
      "The 6thSense egocentric rig records first-person RGB, per-frame depth, and IMU dynamics on one clock with touch — capturing what the demonstrator sees and does, aligned frame by frame.",
    h1: "The egocentric rig.",
    intro:
      "First-person capture that records what the demonstrator sees and how they move — RGB, depth, and motion — on the same clock as touch.",
    sections: [
      {
        h2: "What it captures",
        items: [
          "First-person RGB aligned to the demonstrator's view, with stable exposure for long runs.",
          "Per-frame depth (RGB-D) for geometry, reach, and clutter around the hands.",
          "IMU dynamics — acceleration, angular rates, and movement cues for inertia, rhythm, and effort.",
          "Global-shutter stereo at 4000×1200, 60 fps MJPEG — 1/2.6″ sensor, 3.0 µm pixels, over USB 3.0.",
        ],
      },
      {
        h2: "One clock, every modality",
        body: "The rig shares a single timebase with the glove and skin, so first-person video, depth, motion, and touch line up frame by frame — the alignment that makes episodes trainable.",
      },
    ],
    related: [
      { href: "/product/gloves", label: "Gloves" },
      { href: "/product/skin", label: "Skin" },
      { href: "/product", label: "The stack" },
    ],
  },
];

/** Lookup helper used by the React route components. */
export function getProductPage(path) {
  return productPages.find((p) => p.path === path) || null;
}
