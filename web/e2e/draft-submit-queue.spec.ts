import { expect, test } from "@playwright/test";

/**
 * The sprint 1 goal as a single end-to-end journey.
 *
 * Requires the API running with seeded demo data:
 *   python manage.py seed_demo_data
 */

const ORGANISER = { email: "organiser@acme.example", password: "connectsphere-demo" };
const COORDINATOR = { email: "coordinator@connectsphere.example", password: "connectsphere-demo" };

async function signIn(page, who: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(who.email);
  await page.getByLabel("Password").fill(who.password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("an organiser drafts and submits a request, and the coordinator sees it", async ({ page }) => {
  const eventName = `Playwright Conference ${Date.now()}`;

  await signIn(page, ORGANISER);
  await expect(page).toHaveURL(/\/organiser$/);

  await page.getByRole("link", { name: "New event request" }).click();
  await page.getByLabel("Event name").fill(eventName);
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("status")).toContainText("Draft saved.");

  // US-02.2 AC2 - submitting an incomplete request names what is missing.
  await page.getByRole("button", { name: "Send to ConnectSphere" }).click();
  await expect(page.getByRole("alert")).toContainText("Purpose");

  await page.getByLabel("Purpose").fill("End to end test");
  await page.getByLabel("Preferred start").fill("2027-03-01T09:00");
  await page.getByLabel("Preferred end").fill("2027-03-01T17:00");
  await page.getByLabel("Expected attendance").fill("60");
  await page.getByRole("button", { name: "Send to ConnectSphere" }).click();

  await expect(page).toHaveURL(/\/organiser$/);
  await expect(page.getByText(eventName)).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, COORDINATOR);

  await expect(page).toHaveURL(/\/coordinator$/);
  await expect(page.getByRole("cell", { name: eventName })).toBeVisible();
});
