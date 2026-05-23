import { useState } from "react";

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
  { src: "/logos/YC_logo.png", alt: "Y Combinator" },
  { src: "/logos/University Logo_2Color_DarkGreystone_WhiteFill_RGB.png", alt: "The University of Chicago", needsLightBg: true },
  { src: "/logos/Gtech.png", alt: "Georgia Tech", needsLightBg: true }
];

export function HeroFinale() {
  const [form, setForm] = useState({ name: "", email: "", organization: "" });
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState("");
  const [tone, setTone] = useState("idle");

  const apiBase = import.meta.env.VITE_API_URL ?? "";

  const setField = (key) => (e) => {
    setForm((f) => ({ ...f, [key]: e.target.value }));
    if (errors[key]) setErrors((prev) => ({ ...prev, [key]: undefined }));
    if (tone === "error") setTone("idle");
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    const trimmed = {
      name: form.name.trim(),
      email: form.email.trim().toLowerCase(),
      organization: form.organization.trim(),
    };
    if (!trimmed.name || !trimmed.email || !trimmed.organization) {
      setStatus("Please fill in all fields.");
      setTone("error");
      return;
    }
    if (!trimmed.email.includes("@")) {
      setStatus("Enter a valid email address.");
      setTone("error");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch(`${apiBase}/api/leads`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(trimmed),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status === 429)
          setStatus("Too many requests. Please wait a minute and try again.");
        else if (res.status === 413)
          setStatus("That submission is too large. Please shorten and try again.");
        else if (res.status >= 500)
          setStatus("Server error. Please try again shortly.");
        else
          setStatus("Please correct the errors and try again.");
        setErrors(data.errors ?? {});
        setTone("error");
        return;
      }
      setStatus("Received. The 6thSense team will follow up with a dataset scoping call.");
      setTone("success");
      setForm({ name: "", email: "", organization: "" });
      setErrors({});
    } catch {
      setStatus("Network error. Please try again.");
      setTone("error");
    } finally {
      setSubmitting(false);
    }
  };

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

      <form className="hero-finale-form" onSubmit={onSubmit} noValidate>
        <h2 className="hero-finale-title">Give your robot a sixth sense.</h2>
        <p className="hero-finale-subtitle">
          We build the tactile dataset that closes the gap.
        </p>

        <label className="hero-finale-label" htmlFor="hero-name">Name</label>
        <input
          id="hero-name"
          type="text"
          autoComplete="name"
          value={form.name}
          onChange={setField("name")}
          aria-invalid={errors.name ? "true" : undefined}
          required
        />
        {errors.name && <p className="hero-finale-fielderror">{errors.name}</p>}

        <label className="hero-finale-label" htmlFor="hero-email">Work email</label>
        <p className="hero-finale-hint" id="hero-email-hint">
          Used only for technical follow-up and project scoping.
        </p>
        <input
          id="hero-email"
          type="email"
          autoComplete="email"
          value={form.email}
          aria-describedby="hero-email-hint"
          aria-invalid={errors.email ? "true" : undefined}
          onChange={setField("email")}
          required
        />
        {errors.email && <p className="hero-finale-fielderror">{errors.email}</p>}

        <label className="hero-finale-label" htmlFor="hero-org">Organization</label>
        <input
          id="hero-org"
          type="text"
          autoComplete="organization"
          value={form.organization}
          onChange={setField("organization")}
          aria-invalid={errors.organization ? "true" : undefined}
          required
        />
        {errors.organization && (
          <p className="hero-finale-fielderror">{errors.organization}</p>
        )}

        <button
          type="submit"
          className="hero-finale-submit"
          disabled={submitting}
        >
          {submitting ? "Sending…" : "Discuss your data need"}
        </button>

        <p
          className={`hero-finale-status hero-finale-status--${tone}`}
          role="status"
          aria-live="polite"
        >
          {status || " "}
        </p>
      </form>

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
