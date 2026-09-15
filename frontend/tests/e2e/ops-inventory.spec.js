import { test, expect } from "@playwright/test";

test("coverage is explicit, partial stays unknown, failed refresh clears old counts", async ({ page }) => {
  let checks = 0;
  const writes = [];
  await page.route("**/api/**", async route => {
    const req = route.request();
    if (req.method() !== "GET") writes.push(req.url());
    const path = new URL(req.url()).pathname;
    let data = {};
    let status = 200;
    if (path === "/api/auth/me") data = { id: 1, role: "ops", email: "fixture@example.test" };
    else if (path === "/api/ops/state") data = { episodes: [], wearers: [], tasks: [] };
    else if (path === "/api/ops/inventory-sources") data = { sources: [{ id: 'operations', label: 'Operations raw', bucket: 'synthetic-fixture', prefix: '', expected_owner: null }] };
    else if (path === "/api/ops/inventory-coverage") {
      checks++;
      if (checks > 1) status = 503;
      else data = {
        source_id: 'operations', bucket: "synthetic-fixture", scope_prefix: "", observed_at: "2026-09-13T00:00:00Z",
        listing_complete: false, stop_reason: "object_limit", objects_observed: 10000,
        recognized_recording_prefixes: 3, recordings_missing_metadata: 2,
        unrecognized_objects: 9990, collision_recording_names: 1,
        examples: { unrecognized_keys: ["<img src=x onerror=alert(1)>"] }, limitations: [],
      };
    } else status = 404;
    await route.fulfill({ status, json: data });
  });
  await page.goto("/portal/ops");
  await page.getByText("Which recordings does this board cover?", { exact: true }).click();
  expect(checks).toBe(0);
  await page.getByRole("button", { name: "Check inventory coverage" }).click();
  const report = page.getByRole("region", { name: "Inventory coverage result" });
  await expect(report).toContainText("Partial inventory");
  await expect(report).toContainText("Metadata.json not yet observed");
  await report.getByText("Example entries outside the board’s recognized layout", { exact: true }).click();
  await expect(report.locator("li code")).toHaveText("<img src=x onerror=alert(1)>");
  await expect(report.locator("img")).toHaveCount(0);
  await page.getByRole("button", { name: "Check inventory coverage" }).click();
  await expect(page.getByRole("alert")).toContainText("Coverage is unknown");
  await expect(report).toHaveCount(0);
  expect(checks).toBe(2);
  expect(writes).toEqual([]);
});
