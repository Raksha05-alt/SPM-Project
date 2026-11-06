import { expect, test } from "@playwright/test";
import { actors, cancelEvent, confirmedEvent, dispose, EMAILS, json, localInput, notifications, signIn } from "./helpers";

// E2E-09 / SCRUM-86,58,90: block a confirmed booking, request a linked replacement and re-confirm.
test("E2E-09 disrupted venue is replaced and requires fresh Safety approval", async ({ browser, baseURL }) => {
  test.setTimeout(90_000);
  const all = await actors(baseURL!);
  const state = await confirmedEvent(all, "Disruption replacement", 100);
  const contexts = await Promise.all([0, 1, 2].map(() => browser.newContext({ baseURL, timezoneId: "Asia/Singapore" })));
  const [staff, coordinator, safety] = await Promise.all(contexts.map(c => c.newPage()));
  const reason = "Emergency electrical maintenance";
  try {
    await signIn(staff, EMAILS.staff);
    await staff.goto("/venues/availability");
    await staff.getByRole("combobox", { name: /^Venue/ }).selectOption(String(state.venue.id));
    const block = staff.getByRole("form", { name: "Block venue" });
    await block.getByLabel("Reason category").selectOption("MAINTENANCE");
    await block.getByLabel("Reason", { exact: true }).fill(reason);
    await block.getByLabel("Block start").fill(localInput(Date.parse(state.event.preferred_start)));
    await block.getByLabel("Block end").fill(localInput(Date.parse(state.event.preferred_end)));
    await block.getByRole("button", { name: "Save block" }).click();
    await expect(staff.getByRole("status")).toContainText("Block saved");
    await expect(staff.getByRole("region", { name: "Venue blocks" })).toContainText(state.event.name);

    const bookings = await json(await all.coordinator.api.get("/api/events/" + state.event.id + "/venue-bookings/"));
    expect(bookings.find((b: { id: number }) => b.id === state.booking.id).status).toBe("DISRUPTED");
    const event = await json(await all.coordinator.api.get("/api/events/" + state.event.id + "/"));
    expect(event.status).toBe("PLANNING");
    for (const actor of [all.organiser, all.coordinator]) {
      const notices = await notifications(actor, event.id);
      expect(notices.some((n: { kind: string; message: string }) => n.kind === "RESOURCE_UNAVAILABLE" && n.message.includes(state.venue.name) && n.message.includes("alternative arrangements are required"))).toBe(true);
    }

    await signIn(coordinator, EMAILS.coordinator);
    await coordinator.goto("/coordinator/events/" + event.id);
    await expect(coordinator.getByRole("region", { name: "Venue requests" })).toContainText("Disrupted");
    await expect(coordinator.getByRole("region", { name: "Operational safety check" })).toContainText("Superseded");
    await expect(coordinator.getByRole("button", { name: "Confirm event", exact: true })).toBeDisabled();
    const replacement = await json(await all.staff.post("/api/venues/", {
      name: "Replacement room " + crypto.randomUUID(), location: "Accessible test wing", capacity: 50,
      layouts: ["THEATRE"], facilities: [], wheelchair_access: true,
      opens_at: "08:00", closes_at: "22:00", operating_days: [0,1,2,3,4,5,6],
      emergency_access: "Two marked exits", known_restrictions: "No open flames",
    }), 201);
    // Staff added the replacement after this page loaded; read the updated catalogue.
    await coordinator.reload();
    const planner = coordinator.getByRole("region", { name: "Venue requests" });
    await planner.getByLabel("Venue", { exact: true }).selectOption(String(replacement.id));
    await planner.getByRole("button", { name: "Send request to Venue Staff" }).click();
    await expect(planner.getByRole("status")).toContainText("sent to Venue Staff");
    const after = await json(await all.coordinator.api.get("/api/events/" + event.id + "/venue-bookings/"));
    const pending = after.find((b: { status: string }) => b.status === "PENDING");
    expect(pending.replaces).toBe(state.booking.id);
    await staff.goto("/venues/requests");
    const row = staff.getByRole("row").filter({ hasText: replacement.name });
    await row.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(row).toHaveCount(0);

    await coordinator.reload();
    await expect(coordinator.getByRole("button", { name: "Confirm event", exact: true })).toBeDisabled();
    await coordinator.getByRole("button", { name: /Request (a new )?safety check/ }).click();
    await signIn(safety, EMAILS.safety);
    await safety.getByRole("link", { name: event.name, exact: true }).click();
    await expect(safety.getByRole("region", { name: "Venues", exact: true })).toContainText(replacement.name);
    await safety.getByRole("radio", { name: /^Approve/ }).check();
    await safety.getByRole("button", { name: "Record decision" }).click();
    await expect(safety.getByRole("region", { name: "Recorded decision" })).toContainText("Approved");
    await coordinator.reload();
    await coordinator.getByRole("button", { name: "Confirm event", exact: true }).click();
    await expect(coordinator.getByRole("region", { name: "Readiness" })).toContainText("Confirmed by Cora Coordinator");
    const final = await json(await all.organiser.api.get("/api/events/" + event.id + "/confirmed-arrangements/"));
    expect(JSON.stringify(final)).toContain(replacement.name);
    expect(JSON.stringify(final)).not.toContain(state.venue.name);
  } finally {
    await cancelEvent(all, state.event.id);
    await Promise.all(contexts.map(c => c.close()));
    await dispose(all);
  }
});
