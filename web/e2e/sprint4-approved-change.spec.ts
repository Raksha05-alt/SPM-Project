import { expect, request, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";

/**
 * Sprint 4 journeys S4-J3 (approved change) and S4-J4 (unable to accommodate):
 * SCRUM-80, applying an approved change through staff review.
 *
 * Real API and database: the event is made, booked, reserved, Safety-approved
 * and confirmed through the real actions (as in the Sprint 3 J4/J5 journey);
 * the organiser's change request and the coordinator's approval use the real
 * SCRUM-20/78 endpoints. Applying, staff review, fresh Safety and
 * reconfirmation run in the browser.
 */

const PASSWORD = "connectsphere-demo";

async function token(api: APIRequestContext) {
  return (await api.storageState()).cookies.find((c) => c.name === "csrftoken")?.value ?? "";
}

async function roleApi(baseURL: string, email: string) {
  const api = await request.newContext({ baseURL });
  await api.get("/api/auth/csrf/");
  const login = await api.post("/api/auth/login/", {
    data: { email, password: PASSWORD },
    headers: { "X-CSRFToken": await token(api) },
  });
  expect(login.status()).toBe(200);
  return {
    api,
    post: async (path: string, data: unknown = {}) =>
      api.post(path, { data, headers: { "X-CSRFToken": await token(api) } }),
  };
}

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

/** A confirmed event with an approved venue and reserved, approved equipment. */
async function confirmedEvent(baseURL: string, browser: Browser, day: string) {
  const emails = [
    "organiser@acme.example",
    "lead@connectsphere.example",
    "coordinator@connectsphere.example",
    "venue@connectsphere.example",
    "tech@connectsphere.example",
  ];
  const clients = await Promise.all(emails.map((email) => roleApi(baseURL, email)));
  const [organiser, lead, coordinator, staff, tech] = clients;
  const eventName = `S4 approved change ${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const created = await organiser.post("/api/events/", {
    name: eventName,
    purpose: "Approved change journey",
    preferred_start: `${day}T02:00:00Z`,
    preferred_end: `${day}T04:00:00Z`,
    expected_attendance: 60,
  });
  expect(created.status()).toBe(201);
  const event = await created.json();
  expect((await organiser.post(`/api/events/${event.id}/submit/`)).status()).toBe(200);
  const who = await (await coordinator.api.get("/api/auth/me/")).json();
  expect(
    (
      await lead.post(`/api/events/${event.id}/assign-coordinator/`, {
        coordinator_id: who.id,
        expected_revision: 0,
      })
    ).status(),
  ).toBe(200);
  expect((await coordinator.post(`/api/events/${event.id}/approve/`)).status()).toBe(200);
  const catalogue = await (await coordinator.api.get("/api/venues/")).json();
  const venue = catalogue.find(
    (v: { in_service: boolean; capacity: number; layouts: string[] }) =>
      v.in_service && v.capacity >= 60 && v.layouts.includes("THEATRE"),
  );
  const requested = await coordinator.post(`/api/events/${event.id}/venue-bookings/`, {
    venue: venue.id,
    starts_at: event.preferred_start,
    ends_at: event.preferred_end,
    attendance: 60,
    layout: "THEATRE",
    required_facilities: [],
    wheelchair_access_required: false,
    accessibility_notes: "",
  });
  expect(requested.status()).toBe(201);
  const booking = (await requested.json()).booking;
  expect((await staff.post(`/api/venue-bookings/${booking.id}/approve/`)).status()).toBe(200);
  const types = await (await coordinator.api.get("/api/equipment/types/")).json();
  const projector = types.find((t: { code: string }) => t.code === "PROJECTOR");
  const equipment = await coordinator.post(`/api/events/${event.id}/equipment-requests/`, {
    equipment_type: projector.id,
    quantity: 2,
    technical_requirements: "HDMI at the stage",
  });
  expect(equipment.status()).toBe(201);
  const item = (await equipment.json()).request;
  const plan = await (await tech.api.get(`/api/events/${event.id}/equipment-plan/`)).json();
  expect(
    (await tech.post(`/api/equipment/requests/${item.id}/reserve/`, { expected_revision: plan.revision })).status(),
  ).toBe(200);

  const contexts = await Promise.all(
    [0, 1, 2].map(() => browser.newContext({ baseURL, timezoneId: "Asia/Singapore" })),
  );
  const [coPage, officerPage, staffPage] = await Promise.all(contexts.map((c) => c.newPage()));
  await signIn(coPage, "coordinator@connectsphere.example");
  await signIn(officerPage, "safety@connectsphere.example");
  const state = { event, eventName, venue, clients, organiser, coordinator, staff, tech, contexts, coPage, officerPage, staffPage };
  await safetyAndConfirm(state);
  return state;
}

type State = Awaited<ReturnType<typeof confirmedEvent>>;

/** Request a Safety check, the officer approves it, the coordinator confirms. */
async function safetyAndConfirm(state: Omit<State, never> | Record<string, never>) {
  const s = state as State;
  await s.coPage.goto(`/coordinator/events/${s.event.id}`);
  await s.coPage.getByRole("button", { name: /Request (a new )?safety check/ }).click();
  await expect(s.coPage.getByRole("region", { name: "Operational safety check" })).toContainText(
    "Awaiting Safety Officer",
  );
  await s.officerPage.goto("/safety");
  await s.officerPage.getByRole("link", { name: s.eventName, exact: true }).click();
  await s.officerPage.getByRole("radio", { name: /^Approve/ }).check();
  await s.officerPage.getByRole("button", { name: "Record decision" }).click();
  await expect(s.officerPage.getByRole("region", { name: "Recorded decision" })).toContainText("Approved");
  await s.coPage.reload();
  await s.coPage.getByRole("button", { name: "Confirm event", exact: true }).click();
  await expect(s.coPage.getByRole("region", { name: "Readiness" })).toContainText(
    "Confirmed by Cora Coordinator",
  );
}

/** The organiser asks to move the event a day later; the coordinator approves it (SCRUM-20/78). */
async function approvedMove(state: State, day: string) {
  const asked = await state.organiser.post(`/api/events/${state.event.id}/change-requests/`, {
    description: "Move the event one day later.",
    reason: "The keynote speaker can only attend then.",
    proposed_values: { preferred_start: `${day}T02:00:00Z`, preferred_end: `${day}T04:00:00Z` },
  });
  expect(asked.status()).toBe(201);
  const change = (await asked.json()).change_request;
  const decided = await state.coordinator.post(`/api/change-requests/${change.id}/decide/`, {
    decision: "APPROVE",
    reason: "The venue team will check the new date.",
  });
  expect(decided.status()).toBe(200);
  return change;
}

async function applyInBrowser(state: State) {
  await state.coPage.goto(`/coordinator/events/${state.event.id}`);
  const item = state.coPage
    .getByRole("region", { name: "Change requests" })
    .getByRole("listitem")
    .filter({ hasText: "Move the event one day later." });
  await item.getByRole("button", { name: "Apply change" }).click();
  await expect(item.getByRole("status")).toContainText("2 arrangement(s) sent to staff for review.");
  // AC6 - the Safety check no longer applies and the event is back in Planning.
  await state.coPage.reload();
  await expect(state.coPage.getByRole("region", { name: "Operational safety check" })).toContainText(
    "Superseded",
  );
  await expect(state.coPage.getByRole("button", { name: "Confirm event", exact: true })).toBeDisabled();
  return item;
}

async function staffOutcome(page: Page, path: string, name: string, button: string, reason: string) {
  await page.goto(path);
  const review = page
    .getByRole("region", { name: "Approved changes to review" })
    .getByRole("listitem", { name: new RegExp(`Review of ${name}`) })
    .first();
  await review.getByLabel("Reason for your outcome").fill(reason);
  await review.getByRole("button", { name: button }).click();
  await expect(
    page.getByRole("region", { name: "Approved changes to review" }).getByRole("status"),
  ).toBeVisible();
}

async function cleanup(state: State) {
  const summary = await state.coordinator.api.get(`/api/events/${state.event.id}/cancellation-preview/`);
  if (summary.status() === 200) {
    await state.coordinator.post(`/api/events/${state.event.id}/cancel/`, {
      expected_version: (await summary.json()).version,
      confirm_cancel: true,
      reason: "Journey clean-up",
    });
  }
  await Promise.all([...state.contexts.map((c) => c.close()), ...state.clients.map((c) => c.api.dispose())]);
}

test("S4-J3: an approved change goes through staff review and a fresh Safety check before reconfirmation", async ({
  browser,
  baseURL,
}) => {
  test.setTimeout(150_000);
  const state = await confirmedEvent(baseURL!, browser, "2027-09-07");
  try {
    await approvedMove(state, "2027-09-08");
    const item = await applyInBrowser(state);

    // AC1/AC2 - Venue Staff and Technical Support each accommodate their arrangement.
    await signIn(state.staffPage, "venue@connectsphere.example");
    await staffOutcome(state.staffPage, "/venues/requests", state.venue.name, "Can accommodate", "The hall is free that day.");
    await state.staffPage.getByRole("button", { name: "Sign out" }).click();
    await signIn(state.staffPage, "tech@connectsphere.example");
    await staffOutcome(state.staffPage, "/equipment", "Projector", "Can accommodate", "Projectors are available.");

    // AC4/AC5 - the change is applied; its history shows each outcome and who.
    await state.coPage.reload();
    const applied = state.coPage
      .getByRole("region", { name: "Change requests" })
      .getByRole("listitem")
      .filter({ hasText: "Move the event one day later." });
    // The coordinator page loads several sections; allow it time on a busy machine.
    await expect(applied).toContainText("Applied", { timeout: 15_000 });
    const history = applied.getByRole("region", { name: /History of change request/ });
    await expect(history).toContainText("Can be accommodated by Vera Venue: The hall is free that day.", {
      timeout: 15_000,
    });
    await expect(history).toContainText("Every affected arrangement was accommodated.");

    // AC6 - only the affected equipment goes back through Technical Support approval...
    const plan = await (await state.tech.api.get(`/api/events/${state.event.id}/equipment-plan/`)).json();
    expect(
      (await state.tech.post(`/api/events/${state.event.id}/approve-revised-equipment/`, { expected_revision: plan.revision })).status(),
    ).toBe(200);
    // ...and the event needs a fresh Safety check before it is confirmed again.
    await safetyAndConfirm(state);
  } finally {
    await cleanup(state);
  }
});

test("S4-J4: when staff cannot accommodate a change, the original arrangement stays", async ({ browser, baseURL }) => {
  test.setTimeout(150_000);
  const state = await confirmedEvent(baseURL!, browser, "2027-09-14");
  try {
    const change = await approvedMove(state, "2027-09-15");
    await applyInBrowser(state);

    // AC3 - Venue Staff cannot accommodate the new date; nothing is moved.
    await signIn(state.staffPage, "venue@connectsphere.example");
    await staffOutcome(state.staffPage, "/venues/requests", state.venue.name, "Cannot accommodate", "The hall is closed that day.");
    const booking = (await (await state.coordinator.api.get(`/api/events/${state.event.id}/venue-bookings/`)).json())[0];
    expect(Date.parse(booking.starts_at)).toBe(Date.parse("2027-09-14T02:00:00Z"));
    expect(booking.status).toBe("APPROVED");

    // The coordinator records what was agreed with the organiser.
    await state.coPage.reload();
    const item = state.coPage
      .getByRole("region", { name: "Change requests" })
      .getByRole("listitem")
      .filter({ hasText: "Move the event one day later." });
    await expect(item).toContainText("Cannot be accommodated by Vera Venue: The hall is closed that day.", {
      timeout: 15_000,
    });
    await item.getByLabel("What was agreed with the organiser").fill("Keep the original date.");
    await item.getByRole("button", { name: "Keep the original arrangement" }).click();
    await expect(item).toContainText("Original arrangement kept");

    const history = await (await state.organiser.api.get(`/api/change-requests/${change.id}/history/`)).json();
    expect(history.status).toBe("ORIGINAL_KEPT");
    expect(history.completion_note).toBe("Keep the original date.");
    // The original booking and date are unchanged; the event can be confirmed again.
    const event = await (await state.coordinator.api.get(`/api/events/${state.event.id}/`)).json();
    expect(Date.parse(event.preferred_start)).toBe(Date.parse("2027-09-14T02:00:00Z"));
    await safetyAndConfirm(state);
  } finally {
    await cleanup(state);
  }
});
