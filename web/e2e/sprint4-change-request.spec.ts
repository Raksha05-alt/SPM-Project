import { futureDate } from "./helpers";
import { expect, test, type Page } from "@playwright/test";

/**
 * Sprint 4 journey S4-J3 (approved change) - the INTAKE and ASSESS slices: SCRUM-20, an
 * organiser requests a change to a submitted event and the assigned
 * coordinator sees it Pending; SCRUM-59/78, the coordinator sees it flagged
 * significant, reviews its impact and approves it with a reason, and the
 * organiser sees the decision. Staff review, fresh Safety and reconfirmation
 * (SCRUM-80) extend this journey.
 *
 * Real API and database, no mocks. Requires the API running with seeded demo data:
 *   python manage.py migrate && python manage.py seed_demo_data
 */

const PASSWORD = "connectsphere-demo";
const ORGANISER = "organiser@acme.example";
const OTHER_ORGANISER = "organiser@globex.example";
const COORDINATOR = "coordinator@connectsphere.example";
const LEAD = "lead@connectsphere.example";
const WHAT = "Please increase the expected attendance to 150.";
const WHY = "Two partner organisations have joined the conference.";

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

test("S4-J3 (INTAKE + ASSESS): an organiser requests a change and the coordinator decides it", async ({
  page,
}) => {
  const eventName = `S4-J3 Change ${Date.now()}`;

  // An organiser submits an event.
  await signIn(page, ORGANISER);
  await page.getByRole("link", { name: "New event request" }).click();
  await page.getByLabel("Event name").fill(eventName);
  await page.getByLabel("Purpose").fill("Sprint 4 change request journey");
  await page.getByLabel("Preferred start").fill(futureDate(49) + "T09:00");
  await page.getByLabel("Preferred end").fill(futureDate(49) + "T17:00");
  await page.getByLabel("Expected attendance").fill("120");
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

  // The organiser opens the submitted request: it cannot be edited directly.
  await signIn(page, ORGANISER);
  await page.goto(`/organiser/requests/${eventId}`);
  const changes = page.getByRole("region", { name: "Change requests" });
  await expect(changes).toContainText("No changes have been requested.");

  // AC3 - without a description the request is not sent.
  await changes.getByLabel("Why is the change needed?").fill(WHY);
  await changes.getByRole("button", { name: "Send change request" }).click();
  await expect(changes).toContainText("Enter a description of the change.");
  await expect(changes).toContainText("No changes have been requested.");

  // AC1/AC2 - what and why, with a typed new attendance; the receipt says Pending.
  await changes.getByLabel("What do you want changed?").fill(WHAT);
  await changes.getByLabel("Proposed attendance").fill("150");
  await changes.getByRole("button", { name: "Send change request" }).click();
  await expect(changes.getByRole("status")).toContainText(
    "Your change request has been sent and is Pending review.",
  );
  // AC5 - the request appears against the event with its status.
  const mine = changes.getByRole("listitem").filter({ hasText: WHAT });
  await expect(mine).toContainText("Pending");
  await expect(mine).toContainText("Expected attendance: 120 → 150");
  // The event itself is unchanged until the change is approved and applied.
  await page.reload();
  await expect(page.getByLabel("Expected attendance", { exact: true })).toHaveValue("120");
  await signOut(page);

  // Another organisation cannot request a change to this event.
  await signIn(page, OTHER_ORGANISER);
  const probe = await page.request.post(`/api/events/${eventId}/change-requests/`, {
    data: { description: "Tampering", reason: "Not ours" },
    headers: { "X-CSRFToken": await csrf(page) },
  });
  expect(probe.status()).toBe(403);
  await signOut(page);

  // AC2 - the assigned coordinator sees the Pending request on the event.
  await signIn(page, COORDINATOR);
  await page.goto(`/coordinator/events/${eventId}`);
  const review = page.getByRole("region", { name: "Change requests" });
  const received = review.getByRole("listitem").filter({ hasText: WHAT });
  await expect(received).toContainText("Pending");
  await expect(received).toContainText(`Why: ${WHY}`);
  await expect(received).toContainText("Requested by");
  await expect(review.getByRole("form", { name: "Request a change" })).toHaveCount(0);

  // ASSESS (SCRUM-59/78): the attendance change is flagged significant; the
  // impact is assessed read-only - this submitted event has no arrangements yet.
  await expect(received.getByText("Significant")).toBeVisible();
  await received.getByRole("button", { name: "Review impact" }).click();
  const assessment = received.getByRole("region", { name: /Review of change request/ });
  await expect(assessment).toContainText("This change does not affect any existing arrangements.");

  // SCRUM-78 AC5 - a decision needs a reason; then it is recorded.
  await assessment.getByRole("button", { name: "Approve change" }).click();
  await expect(assessment).toContainText("Enter the reason for your decision.");
  await assessment.getByLabel("Reason for your decision").fill("The venue can take 150 guests.");
  await assessment.getByRole("button", { name: "Approve change" }).click();
  await expect(received).toContainText("Approved by Cora Coordinator");
  await expect(received).toContainText("The venue can take 150 guests.");
  await expect(received.getByRole("button", { name: "Review impact" })).toHaveCount(0);
  await signOut(page);

  // SCRUM-20 AC5 - the organiser sees the decision; the event itself is unchanged.
  await signIn(page, ORGANISER);
  await page.goto(`/organiser/requests/${eventId}`);
  const decided = page
    .getByRole("region", { name: "Change requests" })
    .getByRole("listitem")
    .filter({ hasText: WHAT });
  await expect(decided).toContainText("Approved");
  await expect(decided).toContainText("Approved by Cora Coordinator");
  await expect(page.getByLabel("Expected attendance", { exact: true })).toHaveValue("120");
});
