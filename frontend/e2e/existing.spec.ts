import { expect, test } from "@playwright/test";
import { CONFIGURED, launch, noHorizontalScroll, sentMessages, shot } from "./helpers";

test.describe.configure({ mode: "serial" });

test("existing install opens the dashboard and edits return there", async ({ page }) => {
  await launch(page, CONFIGURED);
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Your setup.");
  await expect(page.getByText("Connected")).toBeVisible(); // token and chat already in the (fake) Keychain
  await expect(page.getByText(/Bachelor's student in Germany · 6 interests/)).toBeVisible();

  // Preferences are editable after onboarding; Save returns to the dashboard.
  await page.getByRole("button", { name: "Edit Opportunities" }).click();
  await expect(page).toHaveURL(/\/setup\/opportunities$/);
  await expect(page.getByRole("button", { name: /Dashboard/ })).toBeVisible();
  await page.getByRole("switch", { name: "Show me everything relevant" }).click();
  await page.getByLabel(/Hackathons/).check();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page).toHaveURL(/\/home$/);
  await expect(page.getByText("1 kind")).toBeVisible();

  // The profile editor keeps the existing values.
  await page.getByRole("button", { name: "Edit Profile" }).click();
  await expect(page.getByLabel("Bachelor's student")).toBeChecked();
  await expect(page.getByLabel("Country you study in")).toHaveValue("DE");
  expect(sentMessages("configured")).toHaveLength(0);
});

test("@responsive dashboard fits a phone screen", async ({ page }) => {
  await launch(page, CONFIGURED);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await noHorizontalScroll(page);
  await shot(page, `14-dashboard-${test.info().project.name}`);
});

test("launch links are single-use and the API needs the session and CSRF token", async ({ page, browser, request }) => {
  const code = "e2e-199";
  await page.goto(`${CONFIGURED}/launch?code=${code}`);
  await expect(page).toHaveURL(/\/home$/);

  const other = await browser.newPage();
  await other.goto(`${CONFIGURED}/launch?code=${code}`);
  await expect(other.getByRole("heading", { level: 1 })).toHaveText("This setup link has expired");
  await other.close();

  expect((await request.get(`${CONFIGURED}/api/state`)).status()).toBe(401);
  // Same session cookie, but no CSRF token and no Origin: refused.
  const noCsrf = await page.request.post(`${CONFIGURED}/api/finish`, { data: {} });
  expect(noCsrf.status()).toBe(403);
  const headers = (await page.request.get(`${CONFIGURED}/`)).headers();
  expect(headers["content-security-policy"]).toContain("default-src 'none'");
  expect(headers["x-frame-options"]).toBe("DENY");
});

test("dark mode renders and every control has an accessible name", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await launch(page, CONFIGURED);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shot(page, "15-dashboard-dark");
  for (const step of ["profile", "opportunities", "matching", "notifications", "ai"]) {
    await page.goto(`${CONFIGURED}/setup/${step}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    if (step === "matching") await expect(page.getByRole("article")).toHaveCount(3);
    if (step === "ai") await expect(page.getByText("Gateway reachable")).toBeVisible();
    const unnamed = await page.evaluate(() =>
      [...document.querySelectorAll("button, input, select, [role=switch], [role=combobox]")]
        .filter((el) => !(el as HTMLElement).hidden && (el as HTMLInputElement).type !== "hidden")
        .filter((el) => {
          const e = el as HTMLElement;
          const id = e.id && document.querySelector(`label[for="${e.id}"]`);
          const wrapped = e.closest("label");
          const labelledby = e.getAttribute("aria-labelledby");
          return !(e.getAttribute("aria-label") || labelledby || id || wrapped || e.textContent?.trim());
        })
        .map((e) => e.outerHTML.slice(0, 80)),
    );
    expect(unnamed, `unnamed controls on ${step}`).toEqual([]);
    if (step === "matching" || step === "ai") await shot(page, `16-${step}-dark`);
  }
});
