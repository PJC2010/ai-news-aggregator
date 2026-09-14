import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  testMatch: "**/*.spec.ts",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    trace: "retain-on-failure",
    launchOptions: process.env.CHROMIUM_EXECUTABLE_PATH
      ? {
          executablePath: process.env.CHROMIUM_EXECUTABLE_PATH,
          args: ["--no-sandbox", "--disable-dev-shm-usage"],
        }
      : {},
  },
  webServer: [
    {
      command:
        "cd ../backend && ../.venv/bin/python tests/serve_dashboard_fixture.py",
      url: "http://127.0.0.1:3200/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run start -- --port 3100",
      url: "http://127.0.0.1:3100",
      reuseExistingServer: false,
      env: {
        DASHBOARD_DEMO_MODE: "true",
        SUPABASE_URL: "",
        SUPABASE_PUBLISHABLE_KEY: "",
      },
    },
    {
      command: "npm run start -- --port 3101",
      url: "http://127.0.0.1:3101/login",
      reuseExistingServer: false,
      env: {
        DASHBOARD_DEMO_MODE: "false",
        SUPABASE_URL: "",
        SUPABASE_PUBLISHABLE_KEY: "",
      },
    },
    {
      command: "npm run start -- --port 3102",
      url: "http://127.0.0.1:3102/login",
      reuseExistingServer: false,
      env: {
        DASHBOARD_DEMO_MODE: "false",
        SUPABASE_URL: "http://127.0.0.1:3200",
        SUPABASE_PUBLISHABLE_KEY: "test-publishable",
        BACKEND_URL: "http://127.0.0.1:3200",
      },
    },
  ],
  projects: [
    {
      name: "desktop",
      testMatch: "dashboard.spec.ts",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1000 },
        baseURL: "http://127.0.0.1:3100",
      },
    },
    {
      name: "mobile",
      testMatch: "dashboard.spec.ts",
      use: {
        ...devices["iPhone 13"],
        defaultBrowserType: "chromium",
        baseURL: "http://127.0.0.1:3100",
      },
    },
    {
      name: "auth-boundary",
      testMatch: "auth.spec.ts",
      use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:3101" },
    },
    {
      name: "live-integration",
      testMatch: "live.spec.ts",
      use: { ...devices["Desktop Chrome"], baseURL: "http://127.0.0.1:3102" },
    },
  ],
});
