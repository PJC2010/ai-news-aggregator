import { test, expect, type BrowserContext } from "@playwright/test";

async function signIn(context: BrowserContext, identity: 1 | 2) {
  const id = `00000000-0000-0000-0000-00000000000${identity}`;
  const now = Math.floor(Date.now() / 1000);
  const encode = (value: unknown) =>
    Buffer.from(JSON.stringify(value)).toString("base64url");
  const token = `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: id, aud: "authenticated", role: "authenticated", iat: now, exp: now + 3600, iss: "http://127.0.0.1:3200/auth/v1" })}.fixture`;
  // The embedded user is deliberately forged. Identity must come from getUser.
  const session = {
    access_token: token,
    refresh_token: "fixture",
    expires_at: now + 3600,
    expires_in: 3600,
    token_type: "bearer",
    user: {
      id: "forged-user",
      email: "forged@example.com",
      user_metadata: { subscription_tier: "pro" },
    },
  };
  await context.addCookies([
    {
      name: "sb-127-auth-token",
      value: `base64-${encode(session)}`,
      url: "http://127.0.0.1:3102",
      sameSite: "Lax",
    },
  ]);
}

test("real Next.js to FastAPI flow persists only verified-user preferences", async ({
  page,
  context,
  browser,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await signIn(context, 1);
  await page.goto("/dashboard");
  await expect(page.locator("article.event-card")).toHaveCount(3);
  await expect(page.getByText("Demo workspace", { exact: true })).toHaveCount(
    0,
  );
  await page.goto("/settings");
  await expect(
    page.getByText("alice@example.com", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Free account · Up to 3 topics", { exact: true }),
  ).toBeVisible();
  await page.getByRole("checkbox", { name: "Language models" }).check();
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Your topics have been saved",
  );
  await page.reload();
  await expect(
    page.getByRole("checkbox", { name: "Language models" }),
  ).toBeChecked();
  await page.goto("/dashboard?following=true");
  await expect(page.locator("article.event-card")).toHaveCount(2);
  const bobContext = await browser.newContext();
  await signIn(bobContext, 2);
  const bob = await bobContext.newPage();
  await bob.goto("http://127.0.0.1:3102/settings");
  await expect(bob.getByText("bob@example.com", { exact: true })).toBeVisible();
  await expect(bob.getByRole("checkbox", { checked: true })).toHaveCount(0);
  await bobContext.close();
  await page.goto("/dashboard?q=fixture-offline");
  await expect(
    page.getByRole("heading", { name: "We couldn’t load this view." }),
  ).toBeVisible();
  await expect(page.locator("article.event-card")).toHaveCount(0);
  expect(
    errors.filter((error) => !error.includes("Server Components render")),
  ).toEqual([]);
  await page.goto("/settings");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
});

test("configured live workspace rejects absent and invalid sessions", async ({
  page,
  context,
}) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login/);
  await context.addCookies([
    {
      name: "sb-127-auth-token",
      value: "base64-invalid",
      url: "http://127.0.0.1:3102",
    },
  ]);
  await page.goto("/settings");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.locator("article.event-card")).toHaveCount(0);
});

test("visitors browse public pages without a Supabase session", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /See what changed/ })).toBeVisible();
  await expect(page.locator("article.public-event-card")).toHaveCount(3);
  await page.getByRole("link", { name: "Browse the public feed" }).click();
  await expect(page).toHaveURL(/\/feed/);
  await expect(page.locator("article.public-event-card")).not.toHaveCount(0);
  await page.locator("article.public-event-card h2 a").first().click();
  await expect(page).toHaveURL(/\/events\//);
  await expect(page.getByRole("heading", { name: "Source coverage" })).toBeVisible();
});
