import { expect, request, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";

// J4/J5: real API/database setup, then coordinator and officer browser actions.
// No held bookings or other Sprint 4 features are prerequisites for this journey.
const PASSWORD = "connectsphere-demo";
async function token(api: APIRequestContext) {
  return (await api.storageState()).cookies.find((c) => c.name === "csrftoken")?.value ?? "";
}
async function roleApi(baseURL: string, email: string) {
  const api = await request.newContext({ baseURL });
  await api.get("/api/auth/csrf/");
  expect((await api.post("/api/auth/login/", { data: { email, password: PASSWORD }, headers: { "X-CSRFToken": await token(api) } })).status()).toBe(200);
  return { api, post: async (path: string, data: unknown = {}) => api.post(path, { data, headers: { "X-CSRFToken": await token(api) } }) };
}
async function signIn(page: Page, email: string) {
  await page.goto("/login"); await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}
async function prepare(baseURL: string, browser: Browser) {
  const clients = await Promise.all(["organiser@acme.example", "lead@connectsphere.example", "coordinator@connectsphere.example", "venue@connectsphere.example", "tech@connectsphere.example"].map((email) => roleApi(baseURL, email)));
  const [organiser, lead, coordinator, staff, tech] = clients;
  const eventName = `Sprint 3 acceptance ${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
  const created = await organiser.post("/api/events/", { name: eventName, purpose: "Safety and confirmation acceptance", preferred_start: "2027-08-17T02:00:00Z", preferred_end: "2027-08-17T04:00:00Z", expected_attendance: 60 });
  expect(created.status()).toBe(201); const event = await created.json();
  expect((await organiser.post(`/api/events/${event.id}/submit/`)).status()).toBe(200);
  const who = await (await coordinator.api.get("/api/auth/me/")).json();
  expect((await lead.post(`/api/events/${event.id}/assign-coordinator/`, { coordinator_id: who.id, expected_revision: 0 })).status()).toBe(200);
  expect((await coordinator.post(`/api/events/${event.id}/approve/`)).status()).toBe(200);
  const catalogue = await (await coordinator.api.get("/api/venues/")).json();
  const venue = catalogue.find((v: { in_service: boolean; capacity: number; layouts: string[] }) => v.in_service && v.capacity >= 60 && v.layouts.includes("THEATRE"));
  expect(venue).toBeTruthy();
  const requested = await coordinator.post(`/api/events/${event.id}/venue-bookings/`, { venue: venue.id, starts_at: event.preferred_start, ends_at: event.preferred_end, attendance: 60, layout: "THEATRE", required_facilities: [], wheelchair_access_required: false, accessibility_notes: "" });
  expect(requested.status()).toBe(201); const booking = (await requested.json()).booking;
  expect((await staff.post(`/api/venue-bookings/${booking.id}/approve/`)).status()).toBe(200);
  const types = await (await coordinator.api.get("/api/equipment/types/")).json();
  const type = types.find((t: { code: string }) => t.code === "PROJECTOR");
  const equipment = await coordinator.post(`/api/events/${event.id}/equipment-requests/`, { equipment_type: type.id, quantity: 2, technical_requirements: "HDMI at the stage" });
  expect(equipment.status()).toBe(201); const item = (await equipment.json()).request;
  const plan = await (await tech.api.get(`/api/events/${event.id}/equipment-plan/`)).json();
  expect((await tech.post(`/api/equipment/requests/${item.id}/reserve/`, { expected_revision: plan.revision })).status()).toBe(200);
  const coContext = await browser.newContext({ baseURL, timezoneId: "Asia/Singapore" });
  const officerContext = await browser.newContext({ baseURL, timezoneId: "Asia/Singapore" });
  const coPage = await coContext.newPage(); const officerPage = await officerContext.newPage();
  await signIn(coPage, "coordinator@connectsphere.example"); await signIn(officerPage, "safety@connectsphere.example");
  return { event, eventName, venue, item, clients, organiser, coordinator, tech, coContext, officerContext, coPage, officerPage };
}
async function requestReview(state: Awaited<ReturnType<typeof prepare>>) {
  await state.coPage.goto(`/coordinator/events/${state.event.id}`);
  await expect(state.coPage.getByRole("button", { name: "Confirm event", exact: true })).toBeDisabled();
  await state.coPage.getByRole("button", { name: /Request (a new )?safety check/ }).click();
  await expect(state.coPage.getByRole("region", { name: "Operational safety check" })).toContainText("Awaiting Safety Officer");
  await state.officerPage.goto("/safety");
  await state.officerPage.getByRole("link", { name: state.eventName, exact: true }).click();
  await expect(state.officerPage.getByRole("region", { name: "Equipment", exact: true })).toContainText("2 of 2 reserved");
  await expect(state.officerPage.getByRole("region", { name: "Venues", exact: true })).toContainText(state.venue.name);
}
async function approveAndConfirm(state: Awaited<ReturnType<typeof prepare>>) {
  await state.officerPage.getByRole("radio", { name: /^Approve/ }).check();
  await state.officerPage.getByRole("button", { name: "Record decision" }).click();
  await expect(state.officerPage.getByRole("region", { name: "Recorded decision" })).toContainText("Approved");
  await state.coPage.reload();
  await state.coPage.getByRole("button", { name: "Confirm event", exact: true }).click();
  await expect(state.coPage.getByRole("region", { name: "Readiness" })).toContainText("Confirmed by Cora Coordinator");
}
async function cleanup(state: Awaited<ReturnType<typeof prepare>>) {
  const summary = await state.coordinator.api.get(`/api/events/${state.event.id}/cancellation-preview/`);
  if (summary.status() === 200) await state.coordinator.post(`/api/events/${state.event.id}/cancel/`, { expected_version: (await summary.json()).version, confirm_cancel: true, reason: "Acceptance test cleanup" });
  await Promise.all([state.coContext.close(), state.officerContext.close(), ...state.clients.map((c) => c.api.dispose())]);
}

test("J4: Safety requests changes, actual technical revision is reapproved, and the organiser sees confirmed arrangements", async ({ browser, baseURL }) => {
  test.setTimeout(90_000); const state = await prepare(baseURL!, browser);
  try {
    await requestReview(state);
    await state.officerPage.getByRole("radio", { name: /^Request changes/ }).check();
    await state.officerPage.getByRole("button", { name: "Record decision" }).click();
    await expect(state.officerPage.getByRole("alert")).toContainText("Add a comment");
    await state.officerPage.getByLabel(/Comment/).fill("Route cables along the wall.");
    await state.officerPage.getByRole("button", { name: "Record decision" }).click();
    await expect(state.officerPage.getByRole("region", { name: "Recorded decision" })).toContainText("Route cables along the wall.");
    let plan = await (await state.tech.api.get(`/api/events/${state.event.id}/equipment-plan/`)).json();
    expect((await state.coordinator.post(`/api/equipment/requests/${state.item.id}/amend/`, { expected_revision: plan.revision, quantity: 2, technical_requirements: "Route HDMI along the wall" })).status()).toBe(200);
    plan = await (await state.tech.api.get(`/api/events/${state.event.id}/equipment-plan/`)).json();
    const active = plan.reservations.find((r: { status: string }) => r.status === "ACTIVE");
    expect((await state.tech.post(`/api/equipment/reservations/${active.id}/release/`, { expected_revision: plan.revision, reason: "Technical review of revised routing" })).status()).toBe(200);
    plan = await (await state.tech.api.get(`/api/events/${state.event.id}/equipment-plan/`)).json();
    expect((await state.tech.post(`/api/equipment/requests/${state.item.id}/reserve/`, { expected_revision: plan.revision })).status()).toBe(200);
    await requestReview(state); await approveAndConfirm(state);
    const organiserPage = await state.coContext.newPage();
    await state.coPage.getByRole("button", { name: "Sign out" }).click();
    await signIn(organiserPage, "organiser@acme.example");
    await organiserPage.goto(`/organiser/requests/${state.event.id}`);
    const arrangements = organiserPage.getByRole("region", { name: "Confirmed arrangements" });
    await expect(arrangements).toContainText(state.venue.name); await expect(arrangements).toContainText("2 × Projector");
    expect((await state.organiser.api.get("/api/safety-checks/")).status()).toBe(403);
  } finally { await cleanup(state); }
});

test("J5: releasing a confirmed resource returns to Planning and requires a fresh Safety approval before reconfirmation", async ({ browser, baseURL }) => {
  test.setTimeout(90_000); const state = await prepare(baseURL!, browser);
  try {
    await requestReview(state); await approveAndConfirm(state);
    let plan = await (await state.tech.api.get(`/api/events/${state.event.id}/equipment-plan/`)).json();
    const active = plan.reservations.find((r: { status: string }) => r.status === "ACTIVE");
    expect((await state.tech.post(`/api/equipment/reservations/${active.id}/release/`, { expected_revision: plan.revision, reason: "Arrangement changed after confirmation" })).status()).toBe(200);
    await state.coPage.reload();
    await expect(state.coPage.getByRole("region", { name: "Operational safety check" })).toContainText("Superseded");
    await expect(state.coPage.getByRole("button", { name: "Confirm event", exact: true })).toBeDisabled();
    const refused = await state.coordinator.post(`/api/events/${state.event.id}/confirm/`);
    expect(refused.status()).toBe(409); expect((await refused.json()).missing.join(" ")).toContain("Operational safety check");
    plan = await (await state.tech.api.get(`/api/events/${state.event.id}/equipment-plan/`)).json();
    expect((await state.tech.post(`/api/equipment/requests/${state.item.id}/reserve/`, { expected_revision: plan.revision })).status()).toBe(200);
    await requestReview(state); await approveAndConfirm(state);
  } finally { await cleanup(state); }
});
