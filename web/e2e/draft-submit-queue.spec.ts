import { futureDate } from "./helpers";
import { expect, test, type Page } from "@playwright/test";

/**
 * The sprint 1 goal as a single end-to-end journey.
 *
 * Requires the API running with seeded demo data:
 *   python manage.py seed_demo_data
 */

const ORGANISER = { email: "organiser@acme.example", password: "connectsphere-demo" };
const COORDINATOR = { email: "coordinator@connectsphere.example", password: "connectsphere-demo" };

async function signIn(page: Page, who: { email: string; password: string }) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(who.email);
  await page.getByLabel("Password").fill(who.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(who.email.startsWith("lead") ? /\/lead$/ : who.email.startsWith("coordinator") ? /\/coordinator$/ : /\/organiser$/);
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
  await page.getByLabel("Preferred start").fill(futureDate(35) + "T09:00");
  await page.getByLabel("Preferred end").fill(futureDate(35) + "T17:00");
  await page.getByLabel("Expected attendance").fill("60");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("status")).toContainText("Draft saved.");
  await page.reload();
  await expect(page.getByLabel("Preferred start")).toHaveValue(futureDate(35) + "T09:00");
  await expect(page.getByLabel("Preferred end")).toHaveValue(futureDate(35) + "T17:00");
  await expect(page.getByLabel("Purpose")).toHaveValue("End to end test");
  await page.getByLabel("Description").fill("Preserve times while editing another field");
  await page.getByRole("button", { name: "Save draft" }).click();
  await expect(page.getByRole("status")).toContainText("Draft saved.");
  await page.reload();
  await expect(page.getByLabel("Preferred start")).toHaveValue(futureDate(35) + "T09:00");
  await expect(page.getByLabel("Preferred end")).toHaveValue(futureDate(35) + "T17:00");
  await expect(page.getByLabel("Description")).toHaveValue("Preserve times while editing another field");
  await page.getByRole("button", { name: "Send to ConnectSphere" }).click();

  await expect(page).toHaveURL(/\/organiser$/);
  await expect(page.getByRole("link", { name: eventName })).toBeVisible();
  await page.getByRole("link", { name: eventName }).click();
  await expect(page.getByRole("region", { name: "Coordinator assignment" })).toContainText("waiting for a Coordinator Lead");
  await page.getByRole("button", { name: "Sign out" }).click();

  // SCRUM-89 AC2: any Lead can see the same unassigned request.
  await signIn(page, { email: "lead2@connectsphere.example", password: "connectsphere-demo" });
  await expect(page.getByRole("link", { name: eventName })).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, { email: "lead@connectsphere.example", password: "connectsphere-demo" });
  await page.getByRole("link", { name: eventName }).click();
  await expect(page).toHaveURL(/\/lead\/events\/\d+$/);
  const eventId = Number(page.url().split("/").pop());
  await page.getByLabel("Event Coordinator", { exact: true }).selectOption({ label: "Cora Coordinator (coordinator@connectsphere.example)" });
  await page.getByRole("button", { name: "Assign coordinator", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Coordinator assignment saved.");
  await page.reload();
  await expect(page.getByRole("region", { name: "Assignment history" })).toContainText("Unassigned → Cora Coordinator");
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, ORGANISER);

  // Contact and recipient-only notices follow the persisted Lead allocation.
  await page.locator("summary", { hasText: "Notifications" }).click();
  await expect(page.getByRole("list", { name: "Notifications" })).toContainText(eventName);
  await page.locator("summary", { hasText: "Notifications" }).click();
  await page.getByRole("link", { name: eventName }).click();
  await expect(page.getByRole("region", { name: "Coordinator assignment" })).toContainText("coordinator@connectsphere.example");
  await expect(page.getByRole("link", { name: "coordinator@connectsphere.example" })).toHaveAttribute("href", "mailto:coordinator@connectsphere.example");

  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, COORDINATOR);

  await expect(page).toHaveURL(/\/coordinator$/);
  await expect(page.getByRole("cell", { name: eventName })).toBeVisible();
  await page.locator("summary", { hasText: "Notifications" }).click();
  await expect(page.getByRole("list", { name: "Notifications" })).toContainText(eventName);
  await page.locator("summary", { hasText: "Notifications" }).click();
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, { email: "lead@connectsphere.example", password: "connectsphere-demo" });
  await page.goto(`/lead/events/${eventId}`);
  await page.getByLabel("Event Coordinator", { exact: true }).selectOption({ label: "Casey Coordinator (coordinator2@connectsphere.example)" });
  await page.getByRole("button", { name: "Reassign coordinator", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Coordinator assignment saved.");
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, COORDINATOR);
  await page.goto(`/coordinator/events/${eventId}`);
  await expect(page.getByRole("alert")).toContainText("We could not load this event.");
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, { email: "coordinator2@connectsphere.example", password: "connectsphere-demo" });
  await expect(page.getByRole("link", { name: eventName })).toBeVisible();
  await page.getByRole("link", { name: eventName }).click();
  await expect(page.getByRole("heading", { name: eventName })).toBeVisible();
  // E2E-03 / SCRUM-52: the newly assigned coordinator rejects with a reason.
  await page.getByRole("button", { name: "Reject request", exact: true }).click();
  const rejection = page.getByRole("region", { name: "Reject request", exact: true });
  await rejection.getByRole("button", { name: "Confirm rejection" }).click();
  await expect(rejection.getByRole("alert")).toContainText("Enter a reason");
  await rejection.getByLabel("Why can ConnectSphere not support this request?").fill("This event is outside the supported scope.");
  await rejection.getByRole("button", { name: "Confirm rejection" }).click();
  await expect(page.getByRole("region", { name: "Rejection decision" })).toContainText("This event is outside the supported scope.");
  await page.getByRole("button", { name: "Sign out" }).click();
  await signIn(page, ORGANISER);
  await page.goto("/organiser/requests/" + eventId);
  await expect(page.getByRole("region", { name: "Rejection decision" })).toContainText("This event is outside the supported scope.");
  await expect(page.getByRole("button", { name: "Send to ConnectSphere" })).toHaveCount(0);
});
