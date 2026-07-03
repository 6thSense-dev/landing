import { useState } from "react";

import { submitLead, messageForStatus } from "./formClient.js";

/**
 * The one shared lead-capture form for the whole site.
 *
 * Every marketing intake — the homepage Nerve reserve, the /products reserve
 * and Skin contact, and the waitlist — renders THIS component. It owns the full
 * form lifecycle so the idle / submitting / success / error behaviour, the
 * honeypot, the consent checkbox + privacy note, client-side validation, and the
 * POST to /api/leads (via the shared formClient) live in exactly one place.
 *
 * Callers only describe intent; the three canonical kinds are:
 *   - reserve  → kind="preorder", product="nerve"   (email capture only)
 *   - waitlist → kind="waitlist"
 *   - contact  → kind="contact",  product="skin"     (message required)
 *
 * @param {object}  props
 * @param {string}  props.kind            "preorder" | "waitlist" | "contact"
 * @param {string}  [props.product]       "hand" | "nerve" | "skin"
 * @param {string}  props.idPrefix        unique per-instance id namespace (a page
 *                                         can render more than one form)
 * @param {string}  props.submitLabel     button text in the idle state
 * @param {string}  props.successMessage  copy shown on a successful submit
 * @param {boolean} [props.requireMessage] show + require the free-text message
 *                                         (defaults on for kind="contact", which
 *                                         the backend also enforces)
 * @param {boolean} [props.requireOrg]     require the organization field
 *                                         (backend requires a non-empty org)
 * @param {string}  [props.messageLabel]   label for the message field
 * @param {string}  [props.messagePlaceholder]
 * @param {string}  [props.variant]        "evora" (dark ev-* classes, default) |
 *                                         "finale" (hero-finale classes)
 * @param {string}  [props.consentNote]    the short privacy note beside consent
 */
export default function LeadForm({
  kind,
  product,
  idPrefix,
  submitLabel,
  successMessage,
  requireMessage,
  requireOrg = true,
  messageLabel = "What are you building?",
  messagePlaceholder = "The hand or gripper, the task, and where you need touch.",
  variant = "evora",
  consentNote = "We'll only use this to reply to you about this enquiry — no spam, no sharing. See our privacy note.",
}) {
  // kind="contact" always needs a message (backend enforces it); other kinds
  // opt in via the prop.
  const wantsMessage = requireMessage ?? kind === "contact";

  const empty = { name: "", email: "", organization: "", message: "", website: "" };
  const [form, setForm] = useState(empty);
  const [consent, setConsent] = useState(false);
  const [errors, setErrors] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState("");
  // Drives the idle / submitting / success / error visual states.
  const [tone, setTone] = useState("idle");

  const setField = (key) => (e) => {
    setForm((f) => ({ ...f, [key]: e.target.value }));
    if (errors[key]) setErrors((prev) => ({ ...prev, [key]: undefined }));
    if (tone === "error") setTone("idle");
  };

  const onConsentChange = (e) => {
    setConsent(e.target.checked);
    if (tone === "error") setTone("idle");
  };

  const fail = (msg) => {
    setStatus(msg);
    setTone("error");
  };

  const onSubmit = async (event) => {
    event.preventDefault();

    const trimmed = {
      name: form.name.trim(),
      email: form.email.trim().toLowerCase(),
      organization: form.organization.trim(),
    };
    if (!trimmed.name || !trimmed.email) {
      return fail("Please add your name and email.");
    }
    if (!trimmed.email.includes("@")) {
      return fail("Enter a valid email address.");
    }
    if (requireOrg && !trimmed.organization) {
      return fail("Please add your organization.");
    }
    const message = form.message.trim();
    if (wantsMessage && !message) {
      return fail("Tell us a little about what you're building.");
    }
    if (!consent) {
      return fail("Please agree to be contacted so we can reply.");
    }

    setSubmitting(true);
    setTone("submitting");
    try {
      const res = await submitLead({
        kind,
        ...(product ? { product } : {}),
        website: form.website,
        ...(wantsMessage ? { message } : {}),
        ...trimmed,
      });
      if (!res.ok) {
        setStatus(messageForStatus(res.status));
        setErrors(res.errors);
        setTone("error");
        return;
      }
      setStatus(successMessage);
      setTone("success");
      setForm(empty);
      setConsent(false);
      setErrors({});
    } catch {
      fail("Network error. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const c = CLASSES[variant] ?? CLASSES.evora;
  const consentId = `${idPrefix}-consent`;

  return (
    <form className={c.form} onSubmit={onSubmit} noValidate>
      <Field
        c={c}
        id={`${idPrefix}-name`}
        label="Name"
        type="text"
        autoComplete="name"
        value={form.name}
        onChange={setField("name")}
        error={errors.name}
      />
      <Field
        c={c}
        id={`${idPrefix}-email`}
        label="Work email"
        type="email"
        autoComplete="email"
        value={form.email}
        onChange={setField("email")}
        error={errors.email}
      />
      <Field
        c={c}
        id={`${idPrefix}-org`}
        label={requireOrg ? "Organization" : "Organization (optional)"}
        type="text"
        autoComplete="organization"
        value={form.organization}
        onChange={setField("organization")}
        error={errors.organization}
      />

      {wantsMessage && (
        <div className={c.field}>
          <label className={c.label} htmlFor={`${idPrefix}-message`}>{messageLabel}</label>
          <textarea
            id={`${idPrefix}-message`}
            className={c.textarea}
            rows={3}
            value={form.message}
            onChange={setField("message")}
            placeholder={messagePlaceholder}
            aria-invalid={errors.message ? "true" : undefined}
          />
          {errors.message && <p className={c.fielderror}>{errors.message}</p>}
        </div>
      )}

      {/* Honeypot: hidden from real users; bots that fill it are dropped
          server-side by the /api/leads route. */}
      <div className={c.honeypot} aria-hidden="true">
        <label htmlFor={`${idPrefix}-website`}>Website</label>
        <input
          id={`${idPrefix}-website`}
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={form.website}
          onChange={setField("website")}
        />
      </div>

      {/* Consent checkbox + short privacy note (required before submit). */}
      <div className={c.consent}>
        <input
          id={consentId}
          type="checkbox"
          className={c.consentBox}
          checked={consent}
          onChange={onConsentChange}
          aria-describedby={`${consentId}-note`}
        />
        <label htmlFor={consentId} id={`${consentId}-note`} className={c.consentNote}>
          {consentNote}
        </label>
      </div>

      <div className={c.row}>
        <button type="submit" className={c.submit} disabled={submitting}>
          {submitting ? "Sending…" : submitLabel}
        </button>
      </div>

      <p className={`${c.status} ${c.status}--${tone}`} role="status" aria-live="polite">
        {status || " "}
      </p>
    </form>
  );
}

/** One labelled text input row, shared across the fields. */
function Field({ c, id, label, type, autoComplete, value, onChange, error }) {
  return (
    <div className={c.field}>
      <label className={c.label} htmlFor={id}>{label}</label>
      <input
        id={id}
        type={type}
        autoComplete={autoComplete}
        value={value}
        onChange={onChange}
        aria-invalid={error ? "true" : undefined}
      />
      {error && <p className={c.fielderror}>{error}</p>}
    </div>
  );
}

/**
 * Per-variant class map so the one component can render into either the dark
 * "Evora" surfaces (homepage + /products) or the hero finale surface, without
 * duplicating any logic.
 */
const CLASSES = {
  evora: {
    form: "ev-form",
    field: "ev-field",
    label: "",
    fielderror: "ev-fielderror",
    textarea: "ev-textarea",
    honeypot: "ev-hp",
    consent: "ev-consent-row",
    consentBox: "ev-consent-box",
    consentNote: "ev-consent",
    row: "ev-form-row",
    submit: "ev-pill ev-solid",
    status: "ev-status",
  },
  // The finale surface reuses its existing selectors: inputs are styled via
  // `.hero-finale-form input`, so the field wrapper carries no class and the
  // label reuses `.hero-finale-label`.
  finale: {
    form: "hero-finale-form",
    field: "hero-finale-field",
    label: "hero-finale-label",
    fielderror: "hero-finale-fielderror",
    textarea: "hero-finale-textarea",
    honeypot: "ev-hp",
    consent: "hero-finale-consent-row",
    consentBox: "hero-finale-consent-box",
    consentNote: "hero-finale-consent",
    row: "hero-finale-row",
    submit: "hero-finale-submit",
    status: "hero-finale-status",
  },
};
