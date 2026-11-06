import { futureDate } from "./helpers";
import { expect, test, type APIRequestContext } from "@playwright/test";

test.use({ timezoneId: "Asia/Singapore" });

const PASSWORD = "connectsphere-demo";

async function csrf(api: APIRequestContext) {
  const state = await api.storageState();
  return state.cookies.find((cookie) => cookie.name === "csrftoken")!.value;
}

test("G12 SCRUM-64/68: search, persist, refresh real approval/withdrawal, blocks and venue status", async ({
  page,
  playwright,
  baseURL,
}) => {
  const suffix = Date.now();
  const venueName = `Discovery room ${suffix}`;
  const eventName = `Discovery event ${suffix}`;
  const marker = `Discovery facility ${suffix}`;
  const staff = await playwright.request.newContext({ baseURL });
  try {
    // Real API precondition: create a dedicated venue, without changing shared demo rooms.
    await staff.get("/api/auth/csrf/");
    expect(
      (
        await staff.post("/api/auth/login/", {
          headers: { "X-CSRFToken": await csrf(staff) },
          data: { email: "venue@connectsphere.example", password: PASSWORD },
        })
      ).status(),
    ).toBe(200);
    const created = await staff.post("/api/venues/", {
      headers: { "X-CSRFToken": await csrf(staff) },
      data: {
        name: venueName,
        location: "Test wing",
        capacity: 60,
        layouts: ["THEATRE"],
        facilities: ["Projector", marker],
        opens_at: "08:00",
        closes_at: "22:00",
        operating_days: [0, 1, 2, 3, 4],
      },
    });
    expect(created.status()).toBe(201);
    const venueId = (await created.json()).id;

    await page.goto("/login");
    await page.getByLabel("Email").fill("organiser@acme.example");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("link", { name: "New event request" }).click();
    await page.getByLabel("Event name").fill(eventName);
    await page.getByLabel("Purpose").fill("Venue discovery integration test");
    await page.getByLabel("Preferred start").fill(futureDate(35) + "T09:00");
    await page.getByLabel("Preferred end").fill(futureDate(35) + "T17:00");
    await page.getByLabel("Expected attendance").fill("60");
    await page.getByLabel("Required room layout").selectOption("THEATRE");
    await page.getByRole("button", { name: "Send to ConnectSphere" }).click();
    await expect(page.getByRole("link", { name: eventName })).toBeVisible();
    await page.getByRole("button", { name: "Sign out" }).click();

    // SCRUM-89: requests enter the Lead's queue before coordinator planning.
    await page.getByLabel("Email").fill("lead@connectsphere.example");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("link", { name: eventName }).click();
    await page.getByLabel("Event Coordinator", { exact: true }).selectOption({ label: "Cora Coordinator (coordinator@connectsphere.example)" });
    await page.getByRole("button", { name: "Assign coordinator", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Coordinator assignment saved.");
    await page.getByRole("button", { name: "Sign out" }).click();

    await page.getByLabel("Email").fill("coordinator@connectsphere.example");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await page.getByRole("link", { name: eventName }).click();
    await page.getByRole("link", { name: "Venue search and shortlist" }).click();
    await page.getByLabel("Required facilities").fill(`Projector, ${marker}`);
    await page.getByRole("button", { name: "Search venues" }).click();
    const results = page.getByRole("region", { name: "Search results" });
    await expect(results.getByRole("heading", { name: venueName })).toBeVisible();
    await expect(results).toContainText("Capacity 60");
    await expect(results).toContainText("Available for this period");
    await results.getByRole("button", { name: `Shortlist ${venueName}` }).click();
    const saved = page.getByRole("region", { name: "Saved shortlist" });
    await expect(saved.getByRole("heading", { name: venueName })).toBeVisible();
    await page.reload();
    await expect(saved.getByRole("heading", { name: venueName })).toBeVisible();

    // Actual G09/G10/G11 APIs, with no shell-created booking or mocked response.
    // J2 covers their form/inbox UI; this case keeps discovery open to verify refresh.
    const eventId = Number(page.url().split("/").at(-2));
    expect((await page.request.post(`/api/events/${eventId}/approve/`, {
      headers: { "X-CSRFToken": await csrf(page.request) }, data: {},
    })).status()).toBe(200);
    const requested = await page.request.post(`/api/events/${eventId}/venue-bookings/`, {
      headers: { "X-CSRFToken": await csrf(page.request) },
      data: { venue: venueId, starts_at: futureDate(35) + "T01:00:00Z", ends_at: futureDate(35) + "T09:00:00Z",
        attendance: 60, layout: "THEATRE", required_facilities: ["Projector", marker] },
    });
    expect(requested.status()).toBe(201);
    const bookingId = (await requested.json()).booking.id;
    expect((await staff.post(`/api/venue-bookings/${bookingId}/approve/`, {
      headers: { "X-CSRFToken": await csrf(staff) }, data: {},
    })).status()).toBe(200);
    await page.getByRole("button", { name: "Refresh availability" }).click();
    await expect(results.getByRole("heading", { name: venueName })).toHaveCount(0);
    await expect(saved.getByRole("heading", { name: venueName })).toBeVisible();
    await expect(saved).toContainText("No longer available for these criteria");
    await expect(saved).toContainText(`Conflicting event(s): ${eventId}`);
    expect((await page.request.post(`/api/events/${eventId}/venue-bookings/${bookingId}/withdraw/`, {
      headers: { "X-CSRFToken": await csrf(page.request) },
      data: { expected_status: "APPROVED", confirm_release: true },
    })).status()).toBe(200);
    await page.getByRole("button", { name: "Refresh availability" }).click();
    await expect(results.getByRole("heading", { name: venueName })).toBeVisible();
    await expect(saved).toContainText("Available for this period");
    await page.reload();
    await expect(saved.getByRole("heading", { name: venueName })).toBeVisible();
    await expect(saved).toContainText("No approved booking overlaps this period.");

    // A real staff block affects the same search and persisted shortlist, not a mock.
    const block = await staff.post(`/api/venues/${venueId}/blocks/`, {
      headers: { "X-CSRFToken": await csrf(staff) },
      data: {
        reason: "Air conditioning repair",
        starts_at: futureDate(35) + "T01:00:00Z",
        ends_at: futureDate(35) + "T09:00:00Z",
      },
    });
    expect(block.status()).toBe(201);
    const blockUrl = `/api/venues/${venueId}/blocks/${(await block.json()).id}/`;
    await page.reload();
    await expect(results.getByRole("heading", { name: venueName })).toHaveCount(0);
    await expect(saved.getByRole("heading", { name: venueName })).toBeVisible();
    await expect(saved).toContainText("No longer available for these criteria");
    await expect(saved).toContainText("Blocked: Air conditioning repair");

    expect((await staff.patch(blockUrl, {
      headers: { "X-CSRFToken": await csrf(staff) },
      data: { starts_at: futureDate(36) + "T01:00:00Z", ends_at: futureDate(36) + "T09:00:00Z" },
    })).status()).toBe(200);
    await page.reload();
    await expect(results.getByRole("heading", { name: venueName })).toBeVisible();
    await expect(saved).toContainText("No recorded block overlaps this period.");
    await expect(saved).toContainText("Available for this period");
    expect((await staff.delete(blockUrl, {
      headers: { "X-CSRFToken": await csrf(staff) },
    })).status()).toBe(204);
    await page.reload();
    await expect(saved).toContainText("No recorded block overlaps this period.");

    expect(
      (
        await staff.patch(`/api/venues/${venueId}/`, {
          headers: { "X-CSRFToken": await csrf(staff) },
          data: { in_service: false },
        })
      ).status(),
    ).toBe(200);
    await page.reload();
    await expect(saved).toContainText("No longer available for these criteria");
    await saved.getByRole("button", { name: `Remove ${venueName}` }).click();
    await expect(saved).toContainText("No venues shortlisted yet.");
    await page.reload();
    await expect(saved).toContainText("No venues shortlisted yet.");
  } finally {
    await staff.dispose();
  }
});

for (const [email, landing] of [
  ["organiser@acme.example", "/organiser"],
  ["attendee@example.com", "/events"],
]) {
  test(`SCRUM-64 AC6: ${email} cannot open venue discovery`, async ({ page }) => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page).toHaveURL(new RegExp(`${landing}$`));
    await page.goto("/coordinator/venues");
    await expect(page).toHaveURL(new RegExp(`${landing}$`));
    await expect(page.getByRole("heading", { name: "Venue search" })).toHaveCount(0);
    expect((await page.request.get("/api/venues/search/")).status()).toBe(403);
    expect((await page.request.get("/api/events/999999/venue-shortlist/")).status()).toBe(403);
  });
}
