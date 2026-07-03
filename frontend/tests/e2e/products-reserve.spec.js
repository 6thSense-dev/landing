import { test, expect } from "@playwright/test";

import {
  FORM_IDS,
  mockLeadsApi,
  fillAndSubmitLeadForm,
  statusLocator,
} from "./helpers.js";

/**
 * /products — Nerve reserve form (kind="preorder", product="nerve").
 *
 * Covers the happy path (fill → submit → success) and the error path (backend
 * returns 4xx → error status shown, form NOT cleared). Runs at all three
 * viewports via the config's projects.
 */
test.describe("/products reserve form (kind=preorder)", () => {
  const idPrefix = FORM_IDS.productsReserve;

  test("fills, submits, and shows success — posts kind=preorder product=nerve", async ({ page }) => {
    const api = await mockLeadsApi(page, { status: 200, body: { ok: true } });

    await page.goto("/products#reserve");
    await expect(page.locator(`#${idPrefix}-email`)).toBeVisible();

    await fillAndSubmitLeadForm(page, idPrefix, {
      name: "Grace Hopper",
      email: "Grace@Navy.MIL",
      organization: "US Navy",
    });

    // Success state.
    const status = statusLocator(page, idPrefix);
    await expect(status).toHaveText(/on the list/i);

    // Exactly one submission, with the correct intent + normalized email.
    expect(api.requests).toHaveLength(1);
    expect(api.requests[0]).toMatchObject({
      kind: "preorder",
      product: "nerve",
      name: "Grace Hopper",
      email: "grace@navy.mil",
      organization: "US Navy",
      website: "", // honeypot left empty by a real user
    });

    // On success the form clears.
    await expect(page.locator(`#${idPrefix}-email`)).toHaveValue("");
  });

  test("shows an error and preserves input when the backend rejects", async ({ page }) => {
    const api = await mockLeadsApi(page, {
      status: 422,
      body: { errors: { email: "That email looks invalid." } },
    });

    await page.goto("/products#reserve");
    await expect(page.locator(`#${idPrefix}-email`)).toBeVisible();

    await fillAndSubmitLeadForm(page, idPrefix, {
      name: "Katherine Johnson",
      email: "kat@nasa.gov",
      organization: "NASA",
    });

    const status = statusLocator(page, idPrefix);
    await expect(status).toHaveText(/correct the errors/i);
    // Field-level error surfaced from the backend payload.
    await expect(page.locator(`#${idPrefix}-email`)).toHaveAttribute("aria-invalid", "true");

    // The request went out once, and the form did NOT clear (so the user can fix).
    expect(api.requests).toHaveLength(1);
    await expect(page.locator(`#${idPrefix}-email`)).toHaveValue("kat@nasa.gov");
  });

  test("validates client-side before hitting the API", async ({ page }) => {
    const api = await mockLeadsApi(page);
    await page.goto("/products#reserve");

    // Submit empty → client blocks it; no network call.
    const form = page.locator(`form:has(#${idPrefix}-consent)`);
    await form.locator('button[type="submit"]').click();

    await expect(statusLocator(page, idPrefix)).toHaveText(/add your name and email/i);
    expect(api.requests).toHaveLength(0);
  });
});
