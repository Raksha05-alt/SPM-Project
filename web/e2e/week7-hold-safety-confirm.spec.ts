import { expect, test, type Page } from "@playwright/test";

/**
 * The Week 7 workflow end to end, against the real API and database:
 * Lead assignment (change 5), a venue booked as a tentative hold (change 4) with
 * setup and turnaround (change 1), the Operational Safety Check (change 6), then
 * confirmation. Requires the API running with seeded demo data.
 */

const PASSWORD = "connectsphere-demo";
const who = (email: string) => ({ email, password: PASSWORD });
const ORGANISER = who("organiser@acme.example");
const LEAD = who("lead@connectsphere.example");
const COORDINATOR = who("coordinator@connectsphere.example");
const VENUE = who("venue@connectsphere.example");
const SAFETY = who("safety@connectsphere.example");

async function signIn(page: Page, user: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Wait for the role's landing page before navigating anywhere else.
  await expect(page).not.toHaveURL(/\/login$/);
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

async function openAsCoordinator(page: Page, eventName: string) {
  await signIn(page, COORDINATOR);
  await page.getByRole("link", { name: eventName }).click();
  await expect(page.getByRole("heading", { name: eventName })).toBeVisible();
}

test("a request is assigned, held, safety-checked and confirmed", async ({
  page,
}) => {
  const eventName = `Week 7 Summit ${Date.now()}`;
  const day = 10 + (Date.now() % 18); // a different day each run keeps the venue free

  // Organiser submits.
  await signIn(page, ORGANISER);
  await page.getByRole("link", { name: "New event request" }).click();
  await page.getByLabel("Event name").fill(eventName);
  await page.getByLabel("Purpose").fill("Week 7 end-to-end journey");
  await page.getByLabel("Preferred start").fill(`2027-04-${day}T10:00`);
  await page.getByLabel("Preferred end").fill(`2027-04-${day}T12:00`);
  await page.getByLabel("Expected attendance").fill("60");
  await page.getByRole("button", { name: "Send to ConnectSphere" }).click();
  await expect(page).toHaveURL(/\/organiser$/);
  await signOut(page);

  // Change 5 - the Lead assigns Cora.
  await signIn(page, LEAD);
  const choose = page.getByLabel(`Coordinator for ${eventName}`);
  const cora = await choose
    .locator("option", { hasText: "Cora Coordinator" })
    .getAttribute("value");
  await choose.selectOption(cora!);
  await page.getByRole("button", { name: `Assign ${eventName}` }).click();
  await expect(page.getByRole("link", { name: eventName })).toBeHidden();
  await signOut(page);

  // The coordinator approves and requests Harbour Hall.
  await openAsCoordinator(page, eventName);
  await page.getByRole("button", { name: "Approve request" }).click();
  await page.getByRole("button", { name: "Search venues" }).click();
  await page
    .getByRole("button", { name: "Request Harbour Hall" })
    .first()
    .click();
  await page.getByLabel("Session").fill("Main programme");
  await page.getByRole("button", { name: "Send booking request" }).click();
  const bookings = page.getByRole("region", { name: "Venue bookings" });
  await expect(bookings).toContainText("Harbour Hall (Main programme)");
  // Change 1 - Harbour Hall needs 30 minutes before and 45 after.
  await expect(bookings).toContainText("setup 30 min, turnaround 45 min");
  await signOut(page);

  // Change 4 - Venue Staff approve it as a tentative hold.
  await signIn(page, VENUE);
  await page.goto("/venues/bookings");
  const request = page.getByRole("listitem").filter({ hasText: eventName });
  await request
    .getByLabel(/Hold tentatively until/)
    .fill(`2027-04-0${(day % 9) + 1}T12:00`);
  await request
    .getByRole("button", { name: "Approve as tentative hold" })
    .click();
  await expect(request.getByRole("status")).toContainText("Tentatively held");
  await signOut(page);

  // The coordinator confirms the hold and sends the event for its safety check.
  await openAsCoordinator(page, eventName);
  await page
    .getByRole("button", { name: "Confirm hold on Harbour Hall" })
    .click();
  await expect(bookings).toContainText("Approved");
  const readiness = page.getByRole("region", { name: "Readiness" });
  await readiness
    .getByLabel(/Note for the Safety Officer/)
    .fill("Standard briefing set-up");
  await readiness.getByRole("button", { name: "Request safety check" }).click();
  await expect(readiness).toContainText("Awaiting Safety Officer");
  // Not yet: the Safety Officer has not approved.
  await page.getByRole("button", { name: "Confirm event" }).click();
  await expect(page.getByRole("alert").first()).toContainText(
    "awaiting the Safety Officer",
  );
  await signOut(page);

  // Change 6 - the Safety Officer reviews and approves.
  await signIn(page, SAFETY);
  await expect(page).toHaveURL(/\/safety$/);
  await page.getByRole("link", { name: eventName }).click();
  await expect(
    page.getByText(/Four fire exits; assembly point at the front plaza/),
  ).toBeVisible();
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText(/Approved by Sam Safety/)).toBeVisible();
  await signOut(page);

  // The coordinator confirms the event.
  await openAsCoordinator(page, eventName);
  await expect(page.getByRole("region", { name: "Readiness" })).toContainText(
    "You can confirm the event",
  );
  await page.getByRole("button", { name: "Confirm event" }).click();
  await expect(
    page.getByText("Confirmed", { exact: true }).first(),
  ).toBeVisible();
});
