import { expect, test, type Page } from "@playwright/test";

/**
 * Sprint 3 journey J3 (equipment) - the G14 slice: SCRUM-74, the assigned
 * coordinator records equipment and Technical Support see it. Availability
 * (SCRUM-12), reservation (SCRUM-16), holding events (SCRUM-76), amendment
 * (SCRUM-75) and release (SCRUM-77) extend this journey at gates G15-G18.
 *
 * Real API and database, no mocks. Requires the API running with seeded demo data:
 *   python manage.py migrate && python manage.py seed_demo_data
 */

const PASSWORD = "connectsphere-demo";
const ORGANISER = "organiser@acme.example";
const COORDINATOR = "coordinator@connectsphere.example";
const OTHER_COORDINATOR = "coordinator2@connectsphere.example";
const LEAD = "lead@connectsphere.example";
const TECH = "tech@connectsphere.example";
const NOTE = "HDMI and USB-C inputs; mount at the back of the hall";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

async function csrf(page: Page) {
  return (await page.context().cookies()).find((c) => c.name === "csrftoken")?.value ?? "";
}

test("J3: the assigned coordinator requests equipment and Technical Support see it", async ({
  page,
}) => {
  const eventName = `J3 Equipment ${Date.now()}`;

  // An organiser submits an event.
  await signIn(page, ORGANISER);
  await page.getByRole("link", { name: "New event request" }).click();
  await page.getByLabel("Event name").fill(eventName);
  await page.getByLabel("Purpose").fill("Sprint 3 equipment journey");
  await page.getByLabel("Preferred start").fill("2027-04-01T09:00");
  await page.getByLabel("Preferred end").fill("2027-04-01T17:00");
  await page.getByLabel("Expected attendance").fill("80");
  await page.getByRole("button", { name: "Send to ConnectSphere" }).click();
  await expect(page).toHaveURL(/\/organiser$/);
  await signOut(page);

  // A Lead assigns Cora.
  await signIn(page, LEAD);
  await page.getByRole("link", { name: eventName }).click();
  const eventId = Number(page.url().split("/").pop());
  await page
    .getByLabel("Event Coordinator", { exact: true })
    .selectOption({ label: "Cora Coordinator (coordinator@connectsphere.example)" });
  await page.getByRole("button", { name: "Assign coordinator", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Coordinator assignment saved.");
  await signOut(page);

  // Cora approves, so equipment can be requested.
  await signIn(page, COORDINATOR);
  await page.goto(`/coordinator/events/${eventId}`);
  const equipment = page.getByRole("region", { name: "Equipment requests" });
  await expect(equipment).toContainText(
    "Equipment can be requested once this event has been approved.",
  );
  await page.getByRole("button", { name: "Approve request" }).click();
  await expect(equipment).toContainText("No equipment has been requested yet.");

  // AC2 - a quantity of zero is blocked and the reason shown; nothing saved.
  await equipment.getByLabel("Equipment", { exact: true }).selectOption({ label: "Projector" });
  await equipment.getByLabel("Quantity").fill("0");
  await equipment.getByRole("button", { name: "Send request to Technical Support" }).click();
  await expect(equipment).toContainText("The quantity must be a whole number of 1 or more.");
  await expect(equipment).toContainText("No equipment has been requested yet.");

  // AC1/AC4 - type, quantity 3 and a technical note; confirmation shown.
  await equipment.getByLabel("Quantity").fill("3");
  await equipment.getByLabel(/Technical requirements/).fill(NOTE);
  await equipment.getByRole("button", { name: "Send request to Technical Support" }).click();
  await expect(equipment.getByRole("status")).toContainText(
    "Your request for 3 x Projector has been sent to Technical Support.",
  );
  const line = equipment.getByRole("row", { name: /Projector/ });
  await expect(line).toContainText("3");
  await expect(line).toContainText(NOTE);
  await expect(line).toContainText("by Cora Coordinator");
  // The first request started planning.
  await page.reload();
  await expect(page.getByText("Planning").first()).toBeVisible();
  await signOut(page);

  // AC5 - another coordinator cannot add equipment to this event.
  await signIn(page, OTHER_COORDINATOR);
  const probe = await page.request.post(`/api/events/${eventId}/equipment-requests/`, {
    data: { equipment_type: 1, quantity: 1 },
    headers: { "X-CSRFToken": await csrf(page) },
  });
  expect(probe.status()).toBe(403);
  await signOut(page);

  // AC3 - Technical Support see the item exactly as requested.
  await signIn(page, TECH);
  await page.goto("/equipment");
  const event = page.getByRole("region", { name: eventName });
  await expect(event).toContainText("Coordinator: Cora Coordinator");
  const requested = event.getByRole("row", { name: /Projector/ });
  await expect(requested).toContainText("3");
  await expect(requested).toContainText(NOTE);
  await expect(requested).toContainText("Requested");
});
