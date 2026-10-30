import { expect, type Page } from "@playwright/test";
import { existsSync, readFileSync, writeFileSync } from "node:fs";

export const CLEAN = "http://127.0.0.1:8765";
export const CONFIGURED = "http://127.0.0.1:8766";
export const SKIP = "http://127.0.0.1:8767";

// Must match tests/gui_harness.py. Fake values: they only work against the fake Telegram API.
export const GOOD_TOKEN = "123456789:AAE2eTestTokenForPlaywrightOnly_xyz123";
export const REJECTED_TOKEN = "123456789:AAThisTokenIsRejectedByTheFakeBot_00";

/** Each launch code works once; the counter lives on disk so worker restarts never reuse one. */
export function freshCode(base: string): string {
  const name = base === CLEAN ? "clean" : base === CONFIGURED ? "configured" : "skip";
  const f = `test-results/state-${name}/codes.txt`; // the harness wipes this dir on start
  const n = existsSync(f) ? Number(readFileSync(f, "utf8")) : 0;
  writeFileSync(f, String(n + 1));
  return `e2e-${n}`;
}

export async function launch(page: Page, base: string) {
  await page.goto(`${base}/launch?code=${freshCode(base)}`);
}

export function sentMessages(name: "clean" | "configured" | "skip"): string[] {
  return readFileSync(`test-results/state-${name}/telegram_sent.jsonl`, "utf8").split("\n").filter(Boolean);
}

export async function shot(page: Page, name: string) {
  await page.waitForTimeout(450); // let the 260ms step entrance settle
  await page.screenshot({ path: `test-results/screens/${name}.png`, fullPage: true });
}

export async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}
