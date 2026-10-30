import { expect, test } from "@playwright/test";
import { CLEAN, GOOD_TOKEN, launch, noHorizontalScroll, REJECTED_TOKEN, sentMessages, shot, SKIP } from "./helpers";

test.describe.configure({ mode: "serial" });

test("first run: complete onboarding with every integration, resuming midway", async ({ page }) => {
  await launch(page, CLEAN);
  await expect(page).toHaveURL(/\/setup\/welcome$/); // launch code is gone from the URL
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Find opportunities you");
  await shot(page, "01-welcome");

  // Step 1, part 1: validation errors are announced and linked.
  await page.getByRole("button", { name: "Get started" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("First, a little about you.");
  await page.getByRole("button", { name: /Next: interests/ }).click();
  const summary = page.getByRole("alert");
  await expect(summary).toContainText("Level of study: Choose your current level of study.");
  await expect(summary).toBeFocused();
  await expect(page.getByLabel("Country you study in")).toHaveAttribute("aria-invalid", "true");
  await shot(page, "02-profile-errors");

  await page.getByLabel("Bachelor's student").check();
  await page.getByLabel(/Year of study/).fill("2");
  await page.getByLabel("Country you study in").selectOption("DE");
  await shot(page, "03-profile-about");
  await page.getByRole("button", { name: /Next: interests/ }).click();

  // Part 2: chips plus a custom interest via the combobox.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("What are you into?");
  await page.getByRole("button", { name: "Machine learning" }).click();
  await page.getByRole("button", { name: "Robotics" }).click();
  await expect(page.getByRole("button", { name: "Robotics" })).toHaveAttribute("aria-pressed", "true");
  const combo = page.getByRole("combobox", { name: /Add an interest/ });
  await combo.fill("reinforcement learning");
  await combo.press("Enter");
  await expect(page.getByRole("button", { name: "Remove reinforcement learning" })).toBeVisible();
  await combo.fill("comp");
  await expect(page.getByRole("option", { name: "Computer vision" })).toBeVisible();
  await combo.press("ArrowDown");
  await combo.press("Enter");
  await expect(page.getByRole("button", { name: "Computer vision" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Draft saved")).toBeVisible();
  await shot(page, "04-profile-interests");

  // Interrupt: reload. Drafts come back from the server, not from browser storage.
  await page.reload();
  await expect(page).toHaveURL(/\/setup\/profile$/);
  await expect(page.getByLabel("Bachelor's student")).toBeChecked();
  await expect(page.getByLabel(/Year of study/)).toHaveValue("2");
  await page.getByRole("button", { name: /Next: interests/ }).click();
  await expect(page.getByRole("button", { name: "Remove reinforcement learning" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  await page.getByRole("button", { name: /Save and continue/ }).click();

  // Step 2: narrow the categories. Back/forward browser navigation works.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("What are you hunting for?");
  await page.goBack();
  await expect(page).toHaveURL(/\/setup\/profile$/);
  await page.goForward();
  await expect(page).toHaveURL(/\/setup\/opportunities$/);
  await page.getByRole("switch", { name: "Show me everything relevant" }).click();
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toContainText("Pick at least one");
  await page.getByLabel(/Summer schools/).check();
  await page.getByLabel(/Research programmes/).check();
  await page.getByRole("button", { name: "Europe (incl. UK, CH)" }).click();
  await shot(page, "05-opportunities");
  await page.getByRole("button", { name: "Continue" }).click();

  // Step 3: the preview runs the real scoring rules on labelled examples.
  await expect(page.getByRole("heading", { level: 1 })).toContainText("three opportunities");
  const examples = page.getByRole("article");
  await expect(examples).toHaveCount(3);
  await expect(examples.first()).toContainText("Example");
  await expect(page.getByText("a kind of opportunity you asked for").first()).toBeVisible();
  await shot(page, "06-matching");
  await page.getByRole("button", { name: /Looks right/ }).click();

  // Step 4: Telegram. Nothing is sent until the explicit test.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Want a nudge before deadlines?");
  await page.getByRole("switch", { name: "Send me Telegram alerts" }).click();
  const token = page.getByLabel("Bot token", { exact: true });
  await expect(token).toHaveAttribute("type", "password");
  await token.fill("not-a-token");
  await page.getByRole("button", { name: "Save & verify" }).click();
  await expect(page.getByText("It should look like 123456789:AA")).toBeVisible();
  await token.fill(REJECTED_TOKEN);
  await page.getByRole("button", { name: "Save & verify" }).click();
  await expect(page.getByText("Telegram rejected this token.")).toBeVisible();
  await token.fill(GOOD_TOKEN);
  await page.getByRole("button", { name: "Save & verify" }).click();
  await expect(page.getByText("Connected to @ohg_e2e_bot.")).toBeVisible();
  await expect(page.getByText("Bot token saved")).toBeVisible();
  await expect(page.getByLabel("Replace bot token")).toHaveValue(""); // cleared once stored
  expect(await page.content()).not.toContain(GOOD_TOKEN);
  expect(sentMessages("clean")).toHaveLength(0);
  await page.getByRole("button", { name: "Find my chat" }).click();
  await expect(page.getByText("Linked to Ada.")).toBeVisible();
  expect(sentMessages("clean")).toHaveLength(0);
  await page.getByRole("button", { name: "Send test message" }).click();
  await expect(page.getByText("Sent. Check Telegram.")).toBeVisible();
  expect(sentMessages("clean")).toHaveLength(1);
  await page.getByRole("button", { name: "1 day" }).click();
  await shot(page, "07-notifications");
  await page.getByRole("button", { name: /Save and continue/ }).click();

  // Step 5: AI. The test is impossible before the explicit acknowledgement.
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Let AI help");
  await expect(page.getByText("Gateway reachable")).toBeVisible();
  await expect(page.getByText("Model route available")).toBeVisible();
  await expect(page.getByRole("button", { name: "Run a test" })).toBeDisabled();
  await shot(page, "08-ai-before");
  await page.getByLabel(/I understand/).check();
  await page.getByRole("button", { name: "Acknowledge" }).click();
  await expect(page.getByText("Data policy acknowledged")).toBeVisible();
  await page.getByLabel("Unified key from FreeLLMAPI").fill("sk-fake-e2e-key-0001");
  await page.getByRole("button", { name: "Save key" }).click();
  await expect(page.getByText("API key stored")).toBeVisible();
  await page.getByRole("button", { name: "Run a test" }).click();
  await expect(page.getByText(/Working: answered via free-tier\/test-model/)).toBeVisible();
  await shot(page, "09-ai-ready");
  await page.getByRole("button", { name: "Continue", exact: true }).click();

  // Step 6: review and finish.
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Looks good?");
  await expect(page.getByText("Connected")).toBeVisible();
  await expect(page.getByText("Ready to use")).toBeVisible();
  await shot(page, "10-review");
  await page.getByRole("button", { name: /Start discovering opportunities/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("You're set up.");
  await expect(page.getByText(/No sources are enabled yet/)).toBeVisible();
  await shot(page, "11-success");
  await page.getByRole("button", { name: /Open dashboard/ }).click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByText("sources configured")).toBeVisible();
  await shot(page, "12-dashboard");

  // Restart persistence: a new session lands on the dashboard with everything intact.
  await launch(page, CLEAN);
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByText("Connected")).toBeVisible();
});

test("optional steps can be skipped and the result is honest", async ({ page }) => {
  await launch(page, SKIP);
  await page.getByRole("button", { name: "Get started" }).click();
  await page.getByLabel("Master's student").check();
  await page.getByLabel("Country you study in").selectOption("NL");
  await page.getByRole("button", { name: /Next: interests/ }).click();
  await page.getByRole("button", { name: /Save and continue/ }).click();
  await expect(page.getByRole("switch", { name: "Show me everything relevant" })).toHaveAttribute("aria-checked", "true");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /Looks right/ }).click();
  await page.getByRole("button", { name: "Continue without Telegram" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Let AI help");
  await page.getByRole("button", { name: /Continue without AI/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Looks good?");
  await expect(page.getByText("Everything relevant")).toBeVisible();
  await expect(page.getByText("You can connect it later")).toBeVisible();
  await page.getByRole("button", { name: /Start discovering opportunities/ }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("You're set up.");
  await expect(page.getByRole("navigation", { name: "Setup steps" }).getByRole("button", { name: /Notifications.*skipped/ })).toBeVisible();
  expect(sentMessages("skip")).toHaveLength(0);
});

test("@responsive welcome and profile fit a phone screen", async ({ page }) => {
  await launch(page, SKIP);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await noHorizontalScroll(page);
  await shot(page, `13-mobile-${test.info().project.name}`);
});
