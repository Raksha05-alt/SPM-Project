import { expect, test } from "@playwright/test";
import { actors, cancelEvent, dispose, futureDate, json, notifications, signIn } from "./helpers";

// Real wall clock and the production process_venue_holds worker; no database
// date rewriting, browser clock overrides, route mocks or skipped expiration.
test("E2E-10 SCRUM-88 expiry releases the room and refuses late confirmation", async ({ page, baseURL }) => {
  test.setTimeout(60_000);
  const all = await actors(baseURL!);
  const day = futureDate(95);
  const event = await json(await all.organiser.post("/api/events/", {
    name: "Expiring hold " + crypto.randomUUID(), purpose: "Hold expiry journey",
    preferred_start: day + "T02:00:00Z", preferred_end: day + "T04:00:00Z", expected_attendance: 20,
  }), 201);
  try {
    await json(await all.organiser.post(`/api/events/${event.id}/submit/`));
    const who = await json(await all.coordinator.api.get("/api/auth/me/"));
    await json(await all.lead.post(`/api/events/${event.id}/assign-coordinator/`, {
      coordinator_id: who.id, expected_revision: 0,
    }));
    await json(await all.coordinator.post(`/api/events/${event.id}/approve/`));
    const venue = await json(await all.staff.post("/api/venues/", {
      name: event.name, location: "Expiry wing", capacity: 25, layouts: ["THEATRE"], facilities: [],
      opens_at: "08:00", closes_at: "22:00", operating_days: [0,1,2,3,4,5,6],
    }), 201);
    const bookingInput = { venue: venue.id, starts_at: event.preferred_start, ends_at: event.preferred_end, attendance: 20, layout: "THEATRE" };
    const { booking } = await json(await all.coordinator.post(`/api/events/${event.id}/venue-bookings/`, bookingInput), 201);
    await json(await all.staff.post(`/api/venue-bookings/${booking.id}/approve/`, {
      hold_until: new Date(Date.now() + 15_000).toISOString(),
    }));
    await signIn(page, "coordinator@connectsphere.example");
    await page.goto(`/coordinator/events/${event.id}`);
    const row = page.getByRole("region", { name: "Venue requests" }).getByRole("row").filter({ hasText: event.name });
    await expect(row).toContainText("Held");
    await expect(row.getByRole("button", { name: "Confirm hold" })).toBeVisible();
    await expect.poll(async () => {
      const rows = await json(await all.coordinator.api.get(`/api/events/${event.id}/venue-bookings/`));
      return rows.find((b: { id: number }) => b.id === booking.id).status;
    }, { timeout: 25_000, intervals: [1000] }).toBe("EXPIRED");
    await page.reload();
    await expect(row).toContainText("Expired");
    await expect(row.getByRole("button", { name: "Confirm hold" })).toHaveCount(0);
    const late = await all.coordinator.post(`/api/venue-bookings/${booking.id}/confirm-hold/`);
    expect(late.status()).toBe(409);
    const notices = await notifications(all.coordinator, event.id);
    expect(notices.filter((n: { kind: string }) => n.kind === "VENUE_HOLD_EXPIRED")).toHaveLength(1);
    const replacement = await json(await all.coordinator.post(`/api/events/${event.id}/venue-bookings/`, bookingInput), 201);
    expect(replacement.booking.id).not.toBe(booking.id);
    expect(replacement.booking.status).toBe("PENDING");
  } finally {
    await cancelEvent(all, event.id);
    await dispose(all);
  }
});
