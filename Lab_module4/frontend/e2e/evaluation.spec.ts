import { expect, test } from "@playwright/test";
import { PROD } from "./helpers";

// E5
test("stored report and grid render; retrieval and full runs complete", async ({ page }) => {
  await page.goto("/evaluation");
  await expect(page.getByText(/Full evaluation · 20 questions/)).toBeVisible();
  await expect(page.getByText(/Citations valid: 20 \/ 20/)).toBeVisible();
  await page.getByRole("tab", { name: "Comparison grid" }).click();
  await expect(page.getByText(/of 72 rows/)).toBeVisible();
  await page.getByRole("tab", { name: "Run" }).click();
  await page.getByRole("button", { name: "Run retrieval evaluation" }).click();
  await expect(page.getByText(/Retrieval evaluation · 20 questions/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Replay full evaluation" }).click();
  await expect(page.getByText(/Full evaluation · 20 questions/)).toBeVisible({ timeout: 60_000 });
  if (PROD) await expect(page.getByText(/· 0 real AI calls,/)).toBeVisible();
  await page.getByRole("tab", { name: "Server" }).click();
  await expect(page.getByText("Real AI calls today")).toBeVisible();
});
