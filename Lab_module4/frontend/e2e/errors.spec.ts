import { expect, test } from "@playwright/test";
import { PROD } from "./helpers";

test.skip(PROD, "uses mocked routes: local only");

// E6
test("network failure, rate limit countdown and quota fallback", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText(/Settings:/)).toBeVisible();

  await page.route("**/query?debug=true", (route) => route.abort());
  await page.getByLabel("Ask about the code").fill("How does authentication work?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Can't reach the service");

  await page.unroute("**/query?debug=true");
  await page.route("**/query?debug=true", (route) =>
    route.fulfill({
      status: 429,
      headers: { "Retry-After": "5", "Content-Type": "application/problem+json", "Access-Control-Expose-Headers": "Retry-After" },
      body: JSON.stringify({ type: "https://x/problems/rate-limited", title: "Too many requests.", status: 429 }),
    }),
  );
  await page.getByLabel("Ask about the code").fill("How does authentication work?");
  await page.getByRole("button", { name: "Ask" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("You can try again in");
  await page.getByLabel("Ask about the code").fill("again");
  await expect(page.getByRole("button", { name: "Ask" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Ask" })).toBeEnabled({ timeout: 8000 });

  await page.unroute("**/query?debug=true");
  await page.route("**/query?debug=true", (route) =>
    route.fulfill({
      status: 503,
      headers: { "Retry-After": "3600", "Content-Type": "application/problem+json" },
      body: JSON.stringify({ type: "https://x/problems/llm-quota-exhausted", title: "Quota", status: 503 }),
    }),
  );
  await page.getByLabel("Ask about the code").fill("How does authentication work?");
  await page.getByRole("button", { name: "Ask" }).click();
  await page.getByRole("button", { name: "Search instead" }).click();
  await expect(page.getByText(/chunks found. Search only/)).toBeVisible();
});
