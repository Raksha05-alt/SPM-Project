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
  await page.getByRole("button", { name: "Save venue" }).click();
  await expect(page.getByRole("status")).toContainText(`Saved ${name}`);
  const row = page.getByRole("row", { name: new RegExp(name) });
  await expect(row).toContainText("Level 5");

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

test("SCRUM-9: venue staff open a venue's full details, and gaps are named", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(VENUE_STAFF.email);
  await page.getByLabel("Password").fill(VENUE_STAFF.password);
  await page.getByRole("button", { name: "Sign in" }).click();

  // AC1 / AC2 / AC4
  await page.getByRole("link", { name: "Harbour Hall" }).click();
  await expect(page.getByRole("heading", { name: "Harbour Hall" })).toBeVisible();
  await expect(page.getByText("Level 2, Marina Wing")).toBeVisible();
  await expect(page.getByText("Theatre, Banquet")).toBeVisible();
  await expect(page.getByText("In service", { exact: true })).toBeVisible();

  // AC3
  await page.getByRole("link", { name: "Back to venues" }).click();
  await page.getByRole("link", { name: "Studio Annex" }).click();
  await expect(page.getByRole("note")).toContainText("Not provided yet: Facilities");
  await expect(page.getByText("Not provided", { exact: true }).first()).toBeVisible();
});

test("SCRUM-9 AC5: an attendee cannot open the venue catalogue", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("attendee@example.com");
  await page.getByLabel("Password").fill(VENUE_STAFF.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/events$/);

  await page.goto("/venues");
  await expect(page).toHaveURL(/\/events$/);
  await expect(page.getByRole("heading", { name: "Venues" })).toHaveCount(0);

  const response = await page.request.get("/api/venues/");
  expect(response.status()).toBe(403);
});
