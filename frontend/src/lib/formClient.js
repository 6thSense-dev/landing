/**
 * Shared lead-capture client for every marketing form on the site.
 *
 * One place owns the /api/leads contract so the hero waitlist, the Nerve
 * reserve/pre-order capture, the Skin contact form, and any future form all
 * send an identical, versioned payload.
 *
 * The backend LeadCreate schema (backend/app/schemas/lead.py) accepts:
 *   - kind:    "preorder" | "waitlist" | "contact"        (required intent)
 *   - product: "hand" | "nerve" | "skin" | null           (optional scope)
 *   - message: free text (required when kind === "contact")
 *   - website: honeypot — must stay empty; a filled value is silently dropped
 *   - name, email, organization
 * Callers pass a `kind` (and, where relevant, `product`/`message`) so the
 * backend can segment leads by intent. Unspecified fields are omitted so the
 * original bare { name, email, organization } waitlist payload still validates.
 */

const apiBase = import.meta.env.VITE_API_URL ?? "";

/** Human-readable copy for the HTTP status codes /api/leads can return. */
export function messageForStatus(status) {
  if (status === 429) return "Too many requests. Please wait a minute and try again.";
  if (status === 413) return "That submission is too large. Please shorten and try again.";
  if (status >= 500) return "Server error. Please try again shortly.";
  return "Please correct the errors and try again.";
}

/**
 * Submit a lead.
 *
 * @param {object} args
 * @param {string} args.kind          intent tag: "preorder" | "waitlist" | "contact"
 * @param {string} args.name
 * @param {string} args.email
 * @param {string} [args.organization]
 * @param {string} [args.product]     product scope: "hand" | "nerve" | "skin"
 * @param {string} [args.message]     free text (required by the backend for kind="contact")
 * @param {string} [args.website]     honeypot — leave empty; a value silently drops the lead
 * @returns {Promise<{ok:boolean, status:number, data:object, errors:object}>}
 */
export async function submitLead({
  kind,
  name,
  email,
  organization = "",
  product,
  message,
  website,
}) {
  const payload = {
    kind,
    name: (name ?? "").trim(),
    email: (email ?? "").trim().toLowerCase(),
    organization: (organization ?? "").trim(),
  };
  // Only forward the optional fields when a caller actually supplies them, so
  // the bare waitlist payload is unchanged and the backend's defaults apply.
  if (product) payload.product = product;
  if (message != null) payload.message = message.trim();
  // The honeypot is always sent (empty for real users) so bots that fill every
  // field are caught server-side.
  payload.website = (website ?? "").trim();

  const res = await fetch(`${apiBase}/api/leads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));

  return {
    ok: res.ok,
    status: res.status,
    data,
    errors: data?.errors ?? {},
  };
}
