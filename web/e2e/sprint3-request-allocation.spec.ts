import { expect, test, type Page } from "@playwright/test";

/**
 * Sprint 3 journey J1 (request and allocation) - the G06 slice:
 * SCRUM-61 coordinator edits and SCRUM-92 offline clarification notes.
 *
 * Real API and database, no mocks. Requires the API running with seeded demo data:
 *   python manage.py migrate && python manage.py seed_demo_data
 */

const PASSWORD = "connectsphere-demo";
const ORGANISER = "organiser@acme.example";
const OTHER_ORGANISER = "organiser@globex.example";
const COORDINATOR = "coordinator@connectsphere.example";
const LEAD = "lead@connectsphere.example";

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

// Page content only: the header's notification list repeats some of this text.
function main(page: Page) {
  return page.getByRole("main");
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);
}

test("J1: coordinator-led clarification with offline notes, edits and resumed review", async ({
  page,
}) => {
  const eventName = `J1 Clarification ${Date.now()}`;

  // The organiser submits a complete request.
  await signIn(page, ORGANISER);
  await page.getByRole("link", { name: "New event request" }).click();
  await page.getByLabel("Event name").fill(eventName);
  await page.getByLabel("Purpose").fill("Sprint 3 clarification journey");
  await page.getByLabel("Preferred start").fill("2027-03-01T09:00");
  await page.getByLabel("Preferred end").fill("2027-03-01T17:00");
  await page.getByLabel("Expected attendance").fill("60");
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

  // The assigned coordinator asks for clarification (SCRUM-49).
  await signIn(page, COORDINATOR);
  await page.goto(`/coordinator/events/${eventId}`);
  await page.getByRole("button", { name: "Request clarification" }).click();
  await page
    .getByLabel("What do you need from the client?")
    .fill("How many wheelchair users are attending?");
  await page.getByLabel("Accessibility needs").check();
  await page.getByRole("button", { name: "Send to client" }).click();
  await expect(main(page).getByText("Awaiting Clarification").first()).toBeVisible();
  await signOut(page);

  // SCRUM-92 AC3 - the client cannot edit; AC1 - they record the phone call instead.
  await signIn(page, ORGANISER);
  await page.goto(`/organiser/requests/${eventId}`);
  await expect(
    main(page).getByText("How many wheelchair users are attending?").first(),
  ).toBeVisible();
  await expect(page.getByLabel("Expected attendance")).toBeDisabled();
  await expect(page.getByRole("button", { name: /Resubmit|Send to ConnectSphere/ })).toHaveCount(0);
  await page
    .getByLabel("Add a note from your conversation")
    .fill("Called Cora: six wheelchair users, and 80 guests in total.");
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(
    page.getByRole("list", { name: "Clarification notes" }).getByText(/six wheelchair users/),
  ).toBeVisible();
  await signOut(page);

  // An unrelated organisation cannot see or annotate the request.
  await signIn(page, OTHER_ORGANISER);
  const probe = await page.request.post(`/api/events/${eventId}/clarification-notes/`, {
    data: { body: "Not my request" },
    headers: { "X-CSRFToken": (await page.context().cookies()).find((c) => c.name === "csrftoken")?.value ?? "" },
  });
  expect(probe.status()).toBe(403);
  await signOut(page);

  // The coordinator sees the note, records the agreement, edits on the client's
  // behalf (SCRUM-61) and resumes review (SCRUM-92 AC4).
  await signIn(page, COORDINATOR);
  await page.goto(`/coordinator/events/${eventId}`);
  await expect(main(page).getByText(/six wheelchair users, and 80 guests/)).toBeVisible();
  await page
    .getByLabel("Add a note from your conversation")
    .fill("Agreed: 80 guests, ramp at entrance B.");
  await page.getByRole("button", { name: "Save note" }).click();
  await expect(main(page).getByText("Agreed: 80 guests, ramp at entrance B.")).toBeVisible();

  await page.getByRole("button", { name: "Edit details" }).click();
  await page.getByLabel("Expected attendance").fill("80");
  await page.getByLabel("Accessibility needs").fill("Six wheelchair users; ramp at entrance B.");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByRole("status")).toContainText("Changes saved.");
  await expect(main(page).getByText(/Last edited by Cora Coordinator/)).toBeVisible();

  await page.getByRole("button", { name: "Resume review" }).click();
  await expect(page.getByRole("status")).toContainText("Review resumed.");
  await signOut(page);

  // A fresh read by the client: back in review, the edit and both notes kept.
  await signIn(page, ORGANISER);
  await page.goto(`/organiser/requests/${eventId}`);
  await expect(page.getByLabel("Expected attendance")).toHaveValue("80");
  await expect(page.getByLabel("Expected attendance")).toBeDisabled();
  const notes = page.getByRole("list", { name: "Clarification notes" });
  await expect(notes).toContainText("six wheelchair users, and 80 guests");
  await expect(notes).toContainText("Agreed: 80 guests, ramp at entrance B.");
  await expect(main(page).getByText(/answered/)).toBeVisible();
});
