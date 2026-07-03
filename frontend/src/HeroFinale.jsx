import LeadForm from "./lib/LeadForm.jsx";

/**
 * Finale scene: 5 brown dots rise from fingertip positions to form the 6-dot
 * logo stair on the LEFT side of the viewport. The olive 6th dot materializes
 * as the browns settle. On the RIGHT, a dataset-conversation form fades in.
 *
 * Phase timing (driven by CSS vars from ScrollStage):
 *   0.55–0.85  assemble: hand canvas descends, dots fade in (30%) then
 *              move (70%) to their logo stair positions on the left.
 *   0.80–0.95  shift: waitlist form fades in on the right.
 *
 * Brown dot start positions track the glove's paint rect (--glove-x/y/w/h)
 * exposed by ScrollStage: start = glove-origin + tip * glove-size, so the dots
 * stay on the fingertips regardless of viewport size or glove zoom.
 */
// Fingertip coords are normalized (u, v) in the source PNG (2752×1536),
// measured once by alpha-scanning the open-hand frame (frame-005).
// End positions: compact stair tucked in the top-left corner so the new
// beats (stat / pipeline / video) own the rest of the viewport. 3% horizontal
// step, 5% vertical step. Ordered bottom-left → top-right (olive last).
const dots = [
  { tipU: 0.6235, tipV: 0.1810, endLeft: 4,  endTop: 18, color: "brown" }, // pinky
  { tipU: 0.5683, tipV: 0.0879, endLeft: 7,  endTop: 18, color: "brown" }, // ring
  { tipU: 0.5058, tipV: 0.0417, endLeft: 7,  endTop: 13, color: "brown" }, // middle
  { tipU: 0.4415, tipV: 0.0703, endLeft: 10, endTop: 13, color: "brown" }, // index
  { tipU: 0.3656, tipV: 0.3151, endLeft: 10, endTop: 8,  color: "brown" }, // thumb
  { startLeft: 13, startTop: 8, endLeft: 13, endTop: 8, color: "olive" }
];

// Three partner logos, rendered as a footer row directly under the form
// title. Sourced from /public/logos/. Same files previously used by the
// (now-removed) standalone BackedBySection beat.
const BACKERS = [
  { src: "/logos/YC_LOGO_Keyed.png", alt: "Y Combinator", needsLightBg: true },
  { src: "/logos/nvidia-inception.png", alt: "NVIDIA Inception Program", needsLightBg: true },
  { src: "/logos/University Logo_2Color_DarkGreystone_WhiteFill_RGB.png", alt: "The University of Chicago", needsLightBg: true },
  { src: "/logos/Gtech.png", alt: "Georgia Tech", needsLightBg: true }
];

export function HeroFinale() {
  const SHOW_ASSEMBLE_DOTS = false;

  return (
    <div className="hero-finale">
      {SHOW_ASSEMBLE_DOTS && dots.map((d, i) => {
        const style = d.color === "brown"
          ? {
              "--tip-u": d.tipU,
              "--tip-v": d.tipV,
              "--end-left": `${d.endLeft}%`,
              "--end-top": `${d.endTop}%`
            }
          : {
              "--start-left": `${d.startLeft}%`,
              "--start-top": `${d.startTop}%`,
              "--end-left": `${d.endLeft}%`,
              "--end-top": `${d.endTop}%`
            };
        return (
          <span
            key={i}
            className={`finale-dot finale-dot--${d.color}`}
            aria-hidden="true"
            style={style}
          />
        );
      })}

      <div className="hero-finale-formwrap">
        <h2 className="hero-finale-title">Give your robot a sixth sense.</h2>
        <p className="hero-finale-subtitle">
          We build the tactile dataset that closes the gap.
        </p>
        {/* The one shared LeadForm, tagged kind="waitlist" (finale variant). */}
        <LeadForm
          kind="waitlist"
          idPrefix="hero"
          variant="finale"
          submitLabel="Discuss your data need"
          successMessage="Received. The 6thSense team will follow up with a dataset scoping call."
        />
      </div>

      <div className="hero-finale-backed">
        <p className="hero-finale-backed-label">Backed by</p>
        <ul className="hero-finale-backed-row">
          {BACKERS.map((b) => (
            <li
              key={b.src}
              className={
                "hero-finale-backed-item" +
                (b.needsLightBg ? " hero-finale-backed-item--lit" : "")
              }
            >
              <img
                className="hero-finale-backed-logo"
                src={b.src}
                alt={b.alt}
                loading="lazy"
              />
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
