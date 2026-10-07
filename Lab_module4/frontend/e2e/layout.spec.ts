import { expect, test } from "@playwright/test";
import { askSuggested, expectAccessible, expectNoHorizontalScroll } from "./helpers";

// E7
test.describe("phone 375×667", () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test("no horizontal scroll on any page", async ({ page }) => {
    await askSuggested(page, "How does authentication work?");
    await page.getByText("How this answer was made").click();
    await expectNoHorizontalScroll(page);
    await page.goto("/codebases");
    await expect(page.getByRole("heading", { name: "Indexed codebases" })).toBeVisible();
    await expectNoHorizontalScroll(page);
    await page.goto("/codebases/shopflow");
    await page.getByRole("button", { name: "backend/app/db.py" }).click();
    await expect(page.getByRole("heading", { name: /chunk/ })).toBeVisible();
    await expectNoHorizontalScroll(page);
    await page.goto("/evaluation");
    await expect(page.getByText(/Full evaluation/)).toBeVisible();
    await expectNoHorizontalScroll(page);
    await page.getByRole("tab", { name: "Comparison grid" }).click();
    await expect(page.getByText(/of 72 rows/)).toBeVisible();
    await expectNoHorizontalScroll(page);
  });
});

// E8
test("no serious accessibility violations", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Try a question")).toBeVisible();
  await expectAccessible(page);
  await askSuggested(page, "What does the processOrder function do?");
  await page.getByText("How this answer was made").click();
  await expectAccessible(page);
  await page.goto("/codebases");
  await page.getByTestId("files-input").setInputFiles({ name: "a.py", mimeType: "text/x-python", buffer: Buffer.from("x = 1\n") });
  await expect(page.getByText(/1 files accepted/)).toBeVisible();
  await expectAccessible(page);
  await page.goto("/evaluation");
  await expect(page.getByText(/Full evaluation/)).toBeVisible();
  for (const tab of ["Report", "Comparison grid", "Run", "Server"]) {
    await page.getByRole("tab", { name: tab }).click();
    await page.waitForTimeout(300);
    await expectAccessible(page);
  }
});
