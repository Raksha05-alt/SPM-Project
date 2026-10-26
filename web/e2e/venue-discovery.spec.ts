import { expect, test, type APIRequestContext } from "@playwright/test";

test.use({ timezoneId: "Asia/Singapore" });

const PASSWORD = "connectsphere-demo";

async function csrf(api: APIRequestContext) {
  const state = await api.storageState();
  return state.cookies.find((cookie) => cookie.name === "csrftoken")!.value;
}

test("SCRUM-64/68: search, persist, recheck real date blocks, venue status and remove", async ({
  page,
  playwright,
}) => {
  const suffix = Date.now();
  const venueName = `Discovery room ${suffix}`;
  const eventName = `Discovery event ${suffix}`;
  const marker = `Discovery facility ${suffix}`;
  const staff = await playwright.request.newContext({ baseURL: "http://localhost:5173" });
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
    await page.getByLabel("Preferred start").fill("2027-03-01T09:00");
    await page.getByLabel("Preferred end").fill("2027-03-01T17:00");
    await page.getByLabel("Expected attendance").fill("60");
    await page.getByLabel("Required room layout").selectOption("THEATRE");
    await page.getByRole("button", { name: "Send to ConnectSphere" }).click();
    await expect(page.getByRole("link", { name: eventName })).toBeVisible();
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
    await expect(results).toContainText("Availability not verified");
    await results.getByRole("button", { name: `Shortlist ${venueName}` }).click();
    const saved = page.getByRole("region", { name: "Saved shortlist" });
    await expect(saved.getByRole("heading", { name: venueName })).toBeVisible();
    await page.reload();
    await expect(saved.getByRole("heading", { name: venueName })).toBeVisible();

    // A real staff block affects the same search and persisted shortlist, not a mock.
    const block = await staff.post(`/api/venues/${venueId}/blocks/`, {
      headers: { "X-CSRFToken": await csrf(staff) },
      data: {
        reason: "Air conditioning repair",
        starts_at: "2027-03-01T01:00:00Z",
        ends_at: "2027-03-01T09:00:00Z",
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
      data: { starts_at: "2027-03-02T01:00:00Z", ends_at: "2027-03-02T09:00:00Z" },
    })).status()).toBe(200);
    await page.reload();
    await expect(results.getByRole("heading", { name: venueName })).toBeVisible();
    await expect(saved).toContainText("No recorded block overlaps this period.");
    await expect(saved).toContainText("Availability not verified");
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
