import { futureDate, roleApi, json } from "./helpers";
import { expect, test, type Page } from "@playwright/test";

/**
 * Sprint 3 journey J2 (G09-G11, G13): SCRUM-11 venue requests, SCRUM-71 suitability
 * refusal, SCRUM-72 staff approval, the INT-02 affected-layout warning and
 * SCRUM-67 confirmed withdrawal.
 *
 * Real API and database, no mocks. Requires the API running with seeded demo data:
 *   python manage.py migrate && python manage.py seed_demo_data
 */

const PASSWORD = "connectsphere-demo";
const ORGANISER = "organiser@acme.example";
const COORDINATOR = "coordinator@connectsphere.example";
const OTHER_COORDINATOR = "coordinator2@connectsphere.example";
const LEAD = "lead@connectsphere.example";
const VENUE_STAFF = "venue@connectsphere.example";

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

test("J2: request, staff approval and confirmed venue withdrawal preserve the decision", async ({
  page, baseURL,
}) => {
  const eventName = `J2 Venue Request ${Date.now()}`;
  const venueName = `J2 Hall ${Date.now()}`;
  const staffApi = await roleApi(baseURL!, VENUE_STAFF);
  try {
    await json(await staffApi.post("/api/venues/", {
      name: venueName, capacity: 200, location: "J2 test wing",
      layouts: ["THEATRE", "BANQUET"], facilities: ["Hearing loop"],
      wheelchair_access: true, opens_at: "08:00", closes_at: "22:00",
      operating_days: [0, 1, 2, 3, 4, 5, 6],
    }), 201);
  } finally {
    await staffApi.api.dispose();
  }


  // An organiser submits a Theatre event for 60 people.
  await signIn(page, ORGANISER);
  await page.getByRole("link", { name: "New event request" }).click();
  await page.getByLabel("Event name").fill(eventName);
  await page.getByLabel("Purpose").fill("Sprint 3 venue planning journey");
  await page.getByLabel("Preferred start").fill(futureDate(35) + "T09:00");
  await page.getByLabel("Preferred end").fill(futureDate(35) + "T17:00");
  await page.getByLabel("Expected attendance").fill("60");
  await page.getByLabel("Required room layout").selectOption({ label: "Theatre" });
  await page.getByRole("button", { name: "Send to ConnectSphere" }).click();
  await expect(page).toHaveURL(/\/organiser$/);
  await signOut(page);

  // A Lead assigns Cora (SCRUM-89).
  await signIn(page, LEAD);
  await page.getByRole("link", { name: eventName }).click();
  const eventId = Number(page.url().split("/").pop());
  await page
    .getByLabel("Event Coordinator", { exact: true })
    .selectOption({ label: "Cora Coordinator (coordinator@connectsphere.example)" });
  await page.getByRole("button", { name: "Assign coordinator", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Coordinator assignment saved.");
  await signOut(page);

  // Cora approves the request (SCRUM-50), so venue planning can begin.
  await signIn(page, COORDINATOR);
  await page.goto(`/coordinator/events/${eventId}`);
  const planner = page.getByRole("region", { name: "Venue requests" });
  await expect(planner).toContainText("A venue can be requested once this event has been approved.");
  await page.getByRole("button", { name: "Approve request" }).click();
  await expect(planner.getByRole("button", { name: "Send request to Venue Staff" })).toBeVisible();
  await expect(planner).toContainText("No venue has been requested yet.");

  // SCRUM-71 AC4 - an unsuitable room is refused with its reasons, nothing saved.
  await planner.getByLabel("Venue", { exact: true }).selectOption({ label: "Skyline Room (capacity 60)" });
  await planner.getByRole("button", { name: "Send request to Venue Staff" }).click();
  const refusal = planner.getByRole("alert");
  await expect(refusal).toContainText("Skyline Room does not meet this event's requirements.");
  await expect(refusal).toContainText(/Theatre/);
  await expect(planner).toContainText("No venue has been requested yet.");

  // AC1-AC4 - a suitable room, timing and requirements; confirmation shown.
  await planner.getByLabel("Venue", { exact: true }).selectOption({ label: `${venueName} (capacity 200)` });
  await planner.getByLabel("Required facilities").fill("Hearing loop");
  await planner.getByLabel("Wheelchair access required").check();
  await planner.getByRole("button", { name: "Send request to Venue Staff" }).click();
  await expect(planner.getByRole("status")).toContainText(
    `Your request for ${venueName} has been sent to Venue Staff.`,
  );
  // AC5 - the request and its current status appear on the event.
  await expect(planner.getByRole("cell", { name: venueName, exact: true })).toBeVisible();
  await expect(planner.getByRole("cell", { name: /Pending/ })).toBeVisible();
  // The first request started planning.
  await page.reload();
  await expect(page.getByText("Planning", { exact: true })).toBeVisible();
  await signOut(page);

  // AC6 - another coordinator cannot request a venue for this event.
  await signIn(page, OTHER_COORDINATOR);
  const probe = await page.request.post(`/api/events/${eventId}/venue-bookings/`, {
    data: { venue: 1, starts_at: futureDate(35) + "T01:00:00Z", ends_at: futureDate(35) + "T09:00:00Z", attendance: 60 },
    headers: { "X-CSRFToken": await csrf(page) },
  });
  expect(probe.status()).toBe(403);
  await signOut(page);

  // AC4 - Venue Staff see the request in their inbox.
  await signIn(page, VENUE_STAFF);
  await page.getByRole("link", { name: "Booking requests" }).click();
  await expect(page).toHaveURL(/\/venues\/requests$/);
  const row = page.getByRole("row", { name: new RegExp(eventName) });
  await expect(row).toContainText(venueName);
  await expect(row).toContainText("Cora Coordinator");
  await expect(row).toContainText("Pending");
  await expect(row).toContainText("Wheelchair access required");

  // G10: the actual Venue Staff action, not a shell-created approval.
  await page.getByLabel("Show requests").selectOption({ label: "All requests" });
  await row.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(row).toContainText("Approved");

  // G13 (INT-02): removing Theatre from Harbour Hall warns about this approved
  // booking; confirming removes the layout and keeps the booking unchanged.
  await page.goto("/venues");
  await page.getByRole("button", { name: `Edit ${venueName}` }).click();
  const venueForm = page.getByRole("form", { name: "Venue details" });
  await venueForm.getByLabel("Theatre", { exact: true }).uncheck();
  await venueForm.getByRole("button", { name: "Save venue" }).click();
  const layoutWarning = venueForm.getByRole("alert", { name: "Layout removal warning" });
  await expect(layoutWarning).toContainText(`Removing Theatre from ${venueName} affects`);
  await expect(layoutWarning).toContainText(`${eventName} · Theatre`);
  await layoutWarning.getByRole("button", { name: "Remove anyway" }).click();
  await expect(page.getByRole("status")).toContainText(`Saved ${venueName}`);
  await page.goto("/venues/requests");
  await page.getByLabel("Show requests").selectOption({ label: "All requests" });
  await expect(page.getByRole("row", { name: new RegExp(eventName) })).toContainText("Approved");
  // Put Theatre back so later runs find Harbour Hall suitable; adding never warns.
  await page.goto("/venues");
  await page.getByRole("button", { name: `Edit ${venueName}` }).click();
  await venueForm.getByLabel("Theatre", { exact: true }).check();
  await venueForm.getByRole("button", { name: "Save venue" }).click();
  await expect(page.getByRole("status")).toContainText(`Saved ${venueName}`);
  await signOut(page);

  // G11: declining the warning leaves the approved arrangement unchanged.
  await signIn(page, COORDINATOR);
  await page.goto(`/coordinator/events/${eventId}`);
  const requests = page.getByRole("region", { name: "Venue requests" });
  const approved = requests.getByRole("row", { name: new RegExp(venueName) });
  await expect(approved).toContainText("Approved");
  page.once("dialog", async dialog => {
    expect(dialog.message()).toContain("release a confirmed venue arrangement");
    await dialog.dismiss();
  });
  await approved.getByRole("button", { name: `Withdraw ${venueName}` }).click();
  await page.reload();
  await expect(requests.getByRole("row", { name: new RegExp(venueName) })).toContainText("Approved");

  page.once("dialog", async dialog => { await dialog.accept(); });
  await requests.getByRole("button", { name: `Withdraw ${venueName}` }).click();
  await expect(requests.getByRole("status")).toContainText("Booking withdrawn");
  await page.reload();
  const withdrawn = requests.getByRole("row", { name: new RegExp(venueName) });
  await expect(withdrawn).toContainText("Withdrawn by Cora Coordinator");
  await expect(withdrawn).toContainText("by Vera Venue");
  await expect(withdrawn.getByRole("button", { name: /Withdraw/ })).toHaveCount(0);
});
