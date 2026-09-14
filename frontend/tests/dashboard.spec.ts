import { test, expect } from "@playwright/test";

test("feed, filters, pagination, and event detail work without browser errors", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What matters in AI." }),
  ).toBeVisible();
  await expect(
    page.getByText("Illustrative stories and analysis.", { exact: false }),
  ).toBeVisible();
  await expect(page.locator("article.event-card")).toHaveCount(12);
  await page.getByRole("link", { name: "Next", exact: true }).click();
  await expect(page).toHaveURL(/page=2/);
  await expect(page.locator("article.event-card")).toHaveCount(2);
  await page.getByRole("link", { name: "Previous", exact: true }).click();
  await page
    .getByRole("heading", {
      name: "A smaller language model, built for a longer train of thought",
    })
    .getByRole("link")
    .click();
  await expect(
    page.getByRole("heading", { name: "Why it matters" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Source coverage" }),
  ).toBeVisible();
  await expect(page.locator(".coverage-row")).toHaveCount(4);
  await page.getByRole("link", { name: "Back to overview" }).click();
  await page
    .getByRole("textbox", { name: "Search stories" })
    .fill("does-not-exist-123");
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Nothing in this view yet" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Browse all stories" }).click();
  await page.getByRole("textbox", { name: "Search stories" }).fill("agents");
  await page.getByRole("button", { name: "Apply", exact: true }).click();
  await expect(page.locator("article.event-card")).toHaveCount(2);
  expect(errors).toEqual([]);
});

test("topic changes persist, enforce limits, and change Following", async ({
  page,
}) => {
  await page.goto("/settings");
  await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(3);
  await expect(
    page.getByRole("checkbox", { name: "Computer vision" }),
  ).toBeDisabled();
  await page.getByRole("checkbox", { name: "Language models" }).uncheck();
  await page.getByRole("checkbox", { name: "AI agents" }).uncheck();
  await page.getByRole("checkbox", { name: /^Research/ }).uncheck();
  await page.getByRole("checkbox", { name: "Computer vision" }).check();
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Sample preferences saved",
  );
  await page.reload();
  await expect(page.getByRole("checkbox", { checked: true })).toHaveCount(1);
  await expect(
    page.getByRole("checkbox", { name: "Computer vision" }),
  ).toBeChecked();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Following" })
    .click();
  await expect(page.locator("article.event-card")).toHaveCount(2);
  await page.goto("/settings");
  await page.getByRole("checkbox", { name: "Computer vision" }).uncheck();
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Sample preferences saved",
  );
  await page.goto("/?following=true");
  await expect(
    page.getByRole("heading", { name: "Choose your first topics" }),
  ).toBeVisible();
});

test("missing analysis, unknown events, and responsive layout have honest states", async ({
  page,
}) => {
  await page.goto("/events/00000000-0000-4000-8000-000000000020");
  await expect(
    page.getByRole("heading", { name: "Analysis is not ready yet" }),
  ).toBeVisible();
  await expect(page.getByText("Not yet assessed", { exact: true })).toHaveCount(
    2,
  );
  await page.goto("/events/00000000-0000-4000-8000-999999999999");
  await expect(
    page.getByRole("heading", { name: "This event isn’t here." }),
  ).toBeVisible();
  for (const route of [
    "/",
    "/settings",
    "/events/00000000-0000-4000-8000-000000000010",
    "/login",
  ]) {
    await page.goto(route);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  }
});
