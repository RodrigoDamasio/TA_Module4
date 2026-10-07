import { expect, test } from "@playwright/test";
import { askSuggested, PROD } from "./helpers";

// E2
test("a suggested question gets an answer with citations linked to sources", async ({ page }) => {
  await askSuggested(page, "What does the processOrder function do?");
  const cite = page.getByRole("button", { name: /^Source \d+: / }).first();
  await expect(cite).toBeVisible();
  const name = (await cite.getAttribute("aria-label")) ?? "";
  const n = name.match(/^Source (\d+)/)?.[1];
  await cite.click();
  const card = page.locator(`details[id$="-src-${n}"]`);
  await expect(card).toHaveClass(/flash/);
  await expect(card).toHaveAttribute("open", "");
  if (PROD) await expect(page.getByText("answer from cache (0 AI calls)")).toBeVisible();
});

// E3
test("the pipeline view shows candidates, matched terms and the prompt", async ({ page }) => {
  await askSuggested(page, "Where is the database connection configured?");
  await page.getByText("How this answer was made").click();
  await expect(page.getByRole("region", { name: "Vector search candidates" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Keyword search candidates" })).toContainText(/database|connection/);
  await expect(page.getByRole("region", { name: "User prompt" })).toContainText("# Question");
  await expect(page.getByText("Not run: this mode doesn't rerank.")).toBeVisible();
});

// E4
test("search only across two codebases labels each source", async ({ page }) => {
  await page.goto("/?cb=shopflow,ledger&mode=hybrid&k=10");
  await page.getByLabel("Search only (no AI call)").check();
  await page.getByLabel("Search the code").fill("authenticate API requests token");
  await page.getByRole("button", { name: "Search" }).click();
  await expect(page.getByText(/chunks found. Search only/)).toBeVisible();
  const sources = page.getByRole("region", { name: "Sources" });
  await expect(sources.getByText("shopflow", { exact: true }).first()).toBeVisible();
  await expect(sources.getByText("ledger", { exact: true }).first()).toBeVisible();
});
