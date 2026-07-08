/**
 * Shared lead-capture client for the site's Contact Us form.
 *
 * One place owns the /api/leads contract. The backend LeadCreate schema
 * (backend/app/schemas/lead.py) accepts:
 *   - name, email, organization   (all required)
 *   - message                     (required free text)
 *   - website: honeypot — must stay empty; a filled value is silently dropped
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
 * Submit a contact enquiry.
 *
 * @param {object} args
 * @param {string} args.name
 * @param {string} args.email
 * @param {string} [args.organization]
 * @param {string} args.message      free text (required by the backend)
 * @param {string} [args.website]    honeypot — leave empty; a value silently drops the lead
 * @returns {Promise<{ok:boolean, status:number, data:object, errors:object}>}
 */
export async function submitLead({
  name,
  email,
  organization = "",
  message,
  website,
}) {
  const payload = {
    name: (name ?? "").trim(),
    email: (email ?? "").trim().toLowerCase(),
    organization: (organization ?? "").trim(),
    message: (message ?? "").trim(),
    // The honeypot is always sent (empty for real users) so bots that fill
    // every field are caught server-side.
    website: (website ?? "").trim(),
  };

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
