import { readFile } from "node:fs/promises";

import { expect, test } from "@playwright/test";

test.describe("/privacy/synapse", () => {
  test("renders the dedicated Synapse policy with matching prerender metadata", async ({ page }) => {
    await page.goto("/privacy/synapse");

    await expect(page.getByRole("heading", { level: 1, name: "Synapse Privacy Policy" })).toBeVisible();
    await expect(page.locator('link[rel="canonical"]')).toHaveAttribute(
      "href",
      "https://6thsense.dev/privacy/synapse",
    );

    const article = page.locator("article");
    await expect(article).toContainText("local network");
    await expect(article).toContainText("PostHog");
    await expect(article).toContainText("Camera controls work without an account");
    await expect(article).toContainText("Camera fleet reports");
    await expect(article).toContainText("Supabase");
    await expect(article).toContainText("Amazon Cognito");
    await expect(article).toContainText("commercial AI training and research");
    await expect(article).toContainText("share sheet");

    const prerendered = await readFile(
      new URL("../../dist/privacy/synapse/index.html", import.meta.url),
      "utf8",
    );
    expect(prerendered).toContain('<link rel="canonical" href="https://6thsense.dev/privacy/synapse"');
    expect(prerendered).toContain("Synapse Privacy Policy");
    expect(prerendered).toContain("PostHog");
  });
});
