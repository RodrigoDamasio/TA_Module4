import path from "node:path";
import { expect, test } from "@playwright/test";
import { PROD } from "./helpers";

// E1 (locally: a mini project; in production: the auction-checklist test project)
const folder = PROD
  ? path.resolve(__dirname, "../../../test_files/auction_checklist")
  : path.resolve(__dirname, "fixtures/mini-project");
const name = PROD ? "auction-checklist" : "mini-project";

test("upload a folder, browse its chunks, then delete it", async ({ page }) => {
  test.setTimeout(PROD ? 300_000 : 60_000);
  await page.goto("/codebases");
  await page.getByTestId("folder-input").setInputFiles(folder);
  await expect(page.getByText(/files accepted/)).toBeVisible();
  await expect(page.getByLabel("Codebase name")).toHaveValue(PROD ? "auction-checklist" : "mini-project");
  if (!PROD) await expect(page.getByText(/\(\+1 in dependency or build folders\)/)).toBeVisible();
  await page.getByRole("button", { name: "Index" }).click();
  await expect(page.getByText(new RegExp(`${name}: \\d+ files indexed`))).toBeVisible({ timeout: PROD ? 240_000 : 30_000 });

  await page.getByRole("link", { name: "See its files and chunks" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText(name);
  const file = PROD ? "auction/costs.py" : "app/billing.py";
  await page.getByRole("button", { name: file }).click();
  await expect(page.getByRole("heading", { name: new RegExp(`${file}: \\d+ chunk`) })).toBeVisible();
  await expect(page.getByRole("region", { name: new RegExp(`^Chunk 1 of ${file}`) })).toBeVisible();

  if (PROD) {
    // The one real Gemini call of the production run (FRONTEND_PLAN §11).
    await page.getByRole("link", { name: "Ask about this codebase" }).click();
    await page.getByLabel("Ask about the code").fill("Which costs are added to the bid when computing the maximum bid?");
    await page.getByRole("button", { name: "Ask" }).click();
    await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible({ timeout: 120_000 });
    await expect(page.getByRole("region", { name: "Sources" })).toContainText("auction/costs.py");
  }

  await page.goto("/codebases");
  const card = page.getByRole("listitem").filter({ hasText: name });
  await card.getByRole("button", { name: "Delete" }).click();
  await card.getByRole("button", { name: "Confirm delete" }).click();
  await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0);
});
