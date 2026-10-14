import { expect, test } from "@playwright/test";

/**
 * The sprint 1 goal as a single end-to-end journey.
 *
 * Requires the API running with seeded demo data:
 *   python manage.py seed_demo_data
 */

const ORGANISER = {
  email: "organiser@acme.example",
  password: "connectsphere-demo",
};
const COORDINATOR = {
  email: "coordinator@connectsphere.example",
  password: "connectsphere-demo",
};
const LEAD = {
  email: "lead@connectsphere.example",
  password: "connectsphere-demo",
};

async function signIn(page, who: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(who.email);
  await page.getByLabel("Password").fill(who.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login$/);
}

test("an organiser submits a request, a Lead assigns it and the coordinator sees it", async ({
  page,
}) => {
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
  await expect(page.getByRole("link", { name: eventName })).toBeVisible();
  // Week 7 change 5: nobody is assigned automatically; the request waits for a Lead.
  await page.getByRole("link", { name: eventName }).click();
  await expect(
    page.getByRole("region", { name: "Coordinator assignment" }),
  ).toContainText("Coordinator Lead will assign");

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, LEAD);
  await expect(page).toHaveURL(/\/lead$/);
  const choose = page.getByLabel(`Coordinator for ${eventName}`);
  const cora = await choose
    .locator("option", { hasText: "Cora Coordinator" })
    .getAttribute("value");
  await choose.selectOption(cora!);
  await page.getByRole("button", { name: `Assign ${eventName}` }).click();
  await expect(page.getByRole("link", { name: eventName })).toBeHidden();

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, ORGANISER);
  await page.getByRole("link", { name: eventName }).click();
  await expect(
    page.getByRole("region", { name: "Coordinator assignment" }),
  ).toContainText("coordinator@connectsphere.example");
  await expect(
    page.getByRole("link", { name: "coordinator@connectsphere.example" }),
  ).toHaveAttribute("href", "mailto:coordinator@connectsphere.example");

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, COORDINATOR);

  await expect(page).toHaveURL(/\/coordinator$/);
  await expect(page.getByRole("link", { name: eventName })).toBeVisible();
  await page.getByText(/Notifications \(/).click();
  await expect(
    page.getByRole("list", { name: "Notifications", exact: true }),
  ).toContainText(eventName);
});
