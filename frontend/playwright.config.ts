import { defineConfig, devices } from "@playwright/test";

// Both servers are the real GUI backed by fakes (tests/gui_harness.py): no network, no Keychain,
// no real Telegram. Each run starts from an empty OHG_HOME.
const harness = (port: number, scenario: string, name = scenario) => ({
  command: `uv run --project .. python ../tests/gui_harness.py --port ${port} --scenario ${scenario} --state-dir test-results/state-${name}`,
  url: `http://127.0.0.1:${port}/static/brand/favicon.svg`,
  reuseExistingServer: false,
  timeout: 60_000,
  stdout: "pipe" as const,
});

export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: { trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 860 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@responsive/ },
  ],
  webServer: [harness(8765, "clean"), harness(8766, "configured"), harness(8767, "clean", "skip")],
});
