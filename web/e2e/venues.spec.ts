import { expect, test } from "@playwright/test";

/**
 * SCRUM-65 - Venue Staff maintain the venue catalogue.
 *
 * Requires the API running with seeded demo data:
 *   python manage.py seed_demo_data
 */

const VENUE_STAFF = { email: "venue@connectsphere.example", password: "connectsphere-demo" };

test("venue staff add a venue, are stopped by a zero capacity, then update it", async ({
  page,
}) => {
  const name = `Playwright Studio ${Date.now()}`;

  await page.goto("/login");
  await page.getByLabel("Email").fill(VENUE_STAFF.email);
  await page.getByLabel("Password").fill(VENUE_STAFF.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/venues$/);

  // AC1
  await page.getByRole("button", { name: "Add venue" }).click();
  await page.getByLabel("Name").fill(name);
  await page.getByLabel("Location").fill("Level 5");
  await page.getByLabel("Maximum capacity").fill("40");
  await page.getByLabel("Setup time (minutes)").fill("20");
  await page.getByLabel("Turnaround time (minutes)").fill("10");
  await page.getByLabel("Emergency access").fill("One exit beside the lift.");
  await page.getByLabel("Known restrictions").fill("No catering.");
  await page.getByRole("button", { name: "Save venue" }).click();
  await expect(page.getByRole("status")).toContainText(`Saved ${name}`);
  const row = page.getByRole("row", { name: new RegExp(name) });
  await expect(row).toContainText("20 / 10 min");

  // AC3
  await page.getByRole("button", { name: `Edit ${name}` }).click();
  await page.getByLabel("Maximum capacity").fill("0");
  await page.getByRole("button", { name: "Save venue" }).click();
  await expect(page.getByText("Capacity must be at least one person.")).toBeVisible();

  // AC2
  await page.getByLabel("Maximum capacity").fill("45");
  await page.getByRole("button", { name: "Save venue" }).click();
  await expect(page.getByRole("status")).toContainText("by Vera Venue");
  await expect(row).toContainText("45");
});
