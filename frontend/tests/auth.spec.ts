import { test, expect } from "@playwright/test";

test("live workspace fails closed without authentication configuration", async ({
  page,
}) => {
  for (const path of [
    "/",
    "/settings",
    "/events/00000000-0000-4000-8000-000000000010",
  ]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/login/);
    await expect(
      page.getByText("Sign-in is not available yet.", { exact: false }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Email me a sign-in link" }),
    ).toBeDisabled();
    await expect(page.locator("article.event-card")).toHaveCount(0);
    await expect(page.getByText("Demo workspace", { exact: true })).toHaveCount(
      0,
    );
  }
});
test("invalid auth callback stays on this site and reveals no event data", async ({
  page,
}) => {
  await page.goto("/auth/callback?code=invalid&next=https://evil.example");
  await expect(page).toHaveURL(/\/login\?error=invalid_link/);
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "That link could not be verified" }),
  ).toBeVisible();
});
