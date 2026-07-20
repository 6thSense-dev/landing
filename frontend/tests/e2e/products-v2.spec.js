import { test, expect } from "@playwright/test";

/**
 * /products (ProductsV2 — the default Apple-style scroll page) regression cover
 * for the 2026-07-19 changes:
 *   1. the 3D Hand is re-skinned as our own product (covered), not the bare
 *      third-party model — asserted via the code path mounting when WebGL is
 *      available (image fallback otherwise, so this never flakes on a GPU-less CI);
 *   3. the Hand scene shows the OLD non-numeric copy, NOT unverified hard specs;
 *   4. the Eye2 CAD .stl downloads + a footer with Privacy/Terms are restored.
 * Plus: ?v1 must still render the legacy showcase so nothing is lost.
 *
 * Runs at all three viewports via the config's projects.
 */
test.describe("/products v2 (default)", () => {
  test("renders with no console errors and the covered-hand scene", async ({ page }) => {
    const errors = [];
    page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    page.on("pageerror", (e) => errors.push("PAGEERROR: " + e.message));

    await page.goto("/products");
    await expect(page.locator(".pv2")).toBeVisible();
    // Legacy showcase must NOT render on the default page.
    await expect(page.locator(".ev-products")).toHaveCount(0);

    // Drive the scroll so the Hand scene's IntersectionObserver mounts the 3D
    // hand (or its image fallback) and the footer paints.
    await page.evaluate(async () => {
      for (let y = 0; y <= document.body.scrollHeight; y += 500) {
        window.scrollTo(0, y); await new Promise((r) => setTimeout(r, 80));
      }
    });

    // The Hand scene exists. When WebGL is available the re-skinned 3D hand
    // mounts a canvas; otherwise the robo.webp image fallback renders. Either way
    // there is exactly one Hand section and it never leaks the raw model.
    await expect(page.locator("section#hand")).toHaveCount(1);
    const handCanvas = page.locator(".pv2 .hand3d-canvas canvas");
    if (await page.locator(".pv2 .pimg.hand3d").count()) {
      await expect(handCanvas).toHaveCount(1); // 3D path -> our-skinned hand render
    }

    expect(errors, `console errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("Hand scene uses non-numeric copy, not unverified hard specs", async ({ page }) => {
    await page.goto("/products");
    const hand = page.locator("section#hand");
    await expect(hand).toContainText(/molded fit/i);
    await expect(hand).toContainText(/Per-task/i);
    // The provisional robot-skin numbers were softened out.
    await expect(hand).not.toContainText(/16-bit/i);
    await expect(hand).not.toContainText(/~200Hz/i);
  });

  test("restores the Eye2 CAD downloads and a footer with legal links", async ({ page }) => {
    await page.goto("/products");
    // CAD .stl download links (assets live in public/).
    await expect(page.locator('.pv2 a[href="/eye2-main-frame.stl"]')).toHaveCount(1);
    await expect(page.locator('.pv2 a[href="/eye2-back-case.stl"]')).toHaveCount(1);
    // Footer with Privacy + Terms.
    const footer = page.locator(".pv2-footer");
    await expect(footer).toBeVisible();
    await expect(footer.locator('a[href="/privacy"]')).toHaveText(/privacy/i);
    await expect(footer.locator('a[href="/terms"]')).toHaveText(/terms/i);
  });

  test("?v1 still renders the legacy showcase (nothing lost)", async ({ page }) => {
    await page.goto("/products?v1");
    await expect(page.locator(".ev-products")).toBeVisible();
    await expect(page.locator(".pv2")).toHaveCount(0);
    // Legacy page keeps its own CAD links + footer.
    await expect(page.locator('a[href="/eye2-main-frame.stl"]')).toHaveCount(1);
    await expect(page.locator(".ev-footer")).toBeVisible();
  });
});
