import { expect } from "@playwright/test";

/**
 * Shared helpers for the marketing-form E2E specs.
 *
 * The single <LeadForm> component (src/lib/LeadForm.jsx) backs every form on the
 * site. Its inputs are addressed by stable, per-instance ids derived from an
 * `idPrefix`:  `${idPrefix}-name`, `${idPrefix}-email`, `${idPrefix}-org`,
 * `${idPrefix}-message`, `${idPrefix}-consent`, `${idPrefix}-website` (honeypot).
 * All POST to `${VITE_API_URL}/api/leads` via src/lib/formClient.js.
 */

// Known idPrefixes in the app, so specs read intent instead of magic strings.
export const FORM_IDS = {
  productsReserve: "rsv", // /products  ReserveForm  kind=preorder product=nerve
  productsContact: "ct", // /products  ContactForm  kind=contact  product=skin
  homeReserve: "home-rsv", // homepage EvoraHome ReserveForm kind=preorder
  heroWaitlist: "hero", // HeroFinale waitlist form kind=waitlist
};

/**
 * Intercept the lead-capture endpoint and record every request body.
 *
 * Returns `{ requests, respondWith }`:
 *   - `requests` is a live array of the parsed JSON payloads the client POSTed.
 *   - `respondWith(status, body)` swaps the mocked response for the next calls
 *     (e.g. to simulate a 422 validation error or a 429).
 *
 * The route matches any origin so it works whether VITE_API_URL is same-origin
 * or an absolute backend URL.
 */
export async function mockLeadsApi(page, { status = 200, body = { ok: true } } = {}) {
  const state = { status, body };
  const requests = [];

  await page.route("**/api/leads", async (route) => {
    const req = route.request();
    let payload = {};
    try {
      payload = JSON.parse(req.postData() ?? "{}");
    } catch {
      payload = { __unparsable: req.postData() };
    }
    requests.push(payload);
    await route.fulfill({
      status: state.status,
      contentType: "application/json",
      body: JSON.stringify(state.body),
    });
  });

  return {
    requests,
    respondWith(nextStatus, nextBody) {
      state.status = nextStatus;
      state.body = nextBody ?? {};
    },
  };
}

/**
 * Fill and submit a LeadForm instance addressed by `idPrefix`.
 *
 * Only fills the message field when the form actually renders one (contact
 * forms). Ticks the required consent checkbox. Does NOT touch the honeypot.
 */
export async function fillAndSubmitLeadForm(
  page,
  idPrefix,
  {
    name = "Ada Lovelace",
    email = "Ada@Example.COM",
    organization = "Analytical Engines",
    message = "We are putting tactile skin on a five-finger hand.",
  } = {},
) {
  await page.locator(`#${idPrefix}-name`).fill(name);
  await page.locator(`#${idPrefix}-email`).fill(email);
  await page.locator(`#${idPrefix}-org`).fill(organization);

  const messageField = page.locator(`#${idPrefix}-message`);
  if (await messageField.count()) {
    await messageField.fill(message);
  }

  await page.locator(`#${idPrefix}-consent`).check();

  // The submit button lives inside the same <form>. Scope to the consent's
  // form so a page with multiple forms submits the right one.
  const form = page.locator(`form:has(#${idPrefix}-consent)`);
  await form.locator('button[type="submit"]').click();
}

/**
 * The status <p role="status"> that LeadForm renders. Its tone class encodes
 * idle / submitting / success / error.
 */
export function statusLocator(page, idPrefix) {
  return page.locator(`form:has(#${idPrefix}-consent) [role="status"]`);
}

/**
 * Attach a console-error and pageerror collector. Returns the array; assert it's
 * empty after the page has settled. Filters out benign noise the app can't
 * control (favicon 404s, third-party analytics) so the check stays meaningful.
 */
export function collectConsoleErrors(page) {
  const errors = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (/favicon/i.test(text)) return;
    if (/Failed to load resource/i.test(text) && /404/.test(text)) return;
    errors.push(text);
  });
  page.on("pageerror", (err) => {
    errors.push(String(err?.message ?? err));
  });
  return errors;
}

/**
 * Assert nothing on the page overflows the viewport horizontally — the classic
 * responsive-layout smell. Allows a 2px fudge for sub-pixel rounding.
 */
export async function expectNoHorizontalOverflow(page) {
  const overflow = await page.evaluate(() => {
    const doc = document.documentElement;
    return {
      scrollWidth: doc.scrollWidth,
      clientWidth: doc.clientWidth,
    };
  });
  expect(
    overflow.scrollWidth,
    `document overflows horizontally (scrollWidth ${overflow.scrollWidth} > clientWidth ${overflow.clientWidth})`,
  ).toBeLessThanOrEqual(overflow.clientWidth + 2);
}
