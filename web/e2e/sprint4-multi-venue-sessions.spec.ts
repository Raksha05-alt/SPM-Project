import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

const PASSWORD = "connectsphere-demo";
async function role(baseURL: string, email: string) {
  const api = await request.newContext({ baseURL });
  await api.get("/api/auth/csrf/");
  const token = async () => (await api.storageState()).cookies.find(c => c.name === "csrftoken")?.value ?? "";
  const post = async (path: string, data: object = {}) => api.post(path, { data, headers: { "X-CSRFToken": await token() } });
  expect((await post("/api/auth/login/", { email, password: PASSWORD })).status()).toBe(200);
  return { api, post };
}
async function signIn(page: Page, email: string) {
  await page.goto("/login"); await page.getByLabel("Email").fill(email); await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}
async function jsonOk(response: Awaited<ReturnType<APIRequestContext["post"]>>, code: number) {
  expect(response.status(), await response.text()).toBe(code); return response.json();
}

test("S4-SESSIONS: independent room decisions, complete Safety confirmation and public session display", async ({ browser, baseURL }) => {
  test.setTimeout(90_000);
  const clients = await Promise.all(["organiser@acme.example", "lead@connectsphere.example", "coordinator@connectsphere.example", "venue@connectsphere.example", "tech@connectsphere.example"].map(email => role(baseURL!, email)));
  const [organiser, lead, coordinator, staff, tech] = clients;
  const suffix = `${Date.now()}`;
  const event = await jsonOk(await organiser.post("/api/events/", { name: `Multi-session ${suffix}`, purpose: "Session acceptance journey",
    preferred_start: "2030-06-18T02:00:00Z", preferred_end: "2030-06-18T04:00:00Z", expected_attendance: 120 }), 201);
  const context = await browser.newContext({ baseURL, timezoneId: "Asia/Singapore" });
  const page = await context.newPage();
  try {
    await jsonOk(await organiser.post(`/api/events/${event.id}/submit/`), 200);
    const who = await (await coordinator.api.get("/api/auth/me/")).json();
    await jsonOk(await lead.post(`/api/events/${event.id}/assign-coordinator/`, { coordinator_id: who.id, expected_revision: 0 }), 200);
    await jsonOk(await coordinator.post(`/api/events/${event.id}/approve/`), 200);
    const rooms = [];
    for (const [name, capacity] of [[`Session Hall ${suffix}`, 120], [`Session Workshop ${suffix}`, 30]] as const) {
      rooms.push(await jsonOk(await staff.post("/api/venues/", { name, capacity, location: "Session wing", layouts: ["THEATRE"],
        facilities: [], wheelchair_access: true, opens_at: "08:00", closes_at: "22:00", operating_days: [0,1,2,3,4,5,6],
        emergency_access: "East exit to assembly point", known_restrictions: "No open flames" }), 201));
    }
    await signIn(page, "coordinator@connectsphere.example");
    await page.goto(`/coordinator/events/${event.id}`);
    const planner = page.getByRole("region", { name: "Venue requests" });
    await planner.getByLabel("Venue", { exact: true }).selectOption(String(rooms[0].id));
    await planner.getByRole("button", { name: "Send request to Venue Staff" }).click();
    await expect(planner.getByRole("status")).toContainText("sent to Venue Staff");
    await planner.getByLabel("Session", { exact: true }).selectOption("NEW");
    await planner.getByLabel("Session name").fill("Breakout A");
    await planner.getByLabel("Attendance").fill("30");
    await planner.getByLabel("Venue", { exact: true }).selectOption(String(rooms[1].id));
    const sent = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/venue-bookings/"));
    await planner.getByRole("button", { name: "Send request to Venue Staff" }).click();
    expect((await sent).status()).toBe(201);
    await expect(planner.getByRole("row", { name: /Breakout A/ })).toContainText("Pending");
    await page.getByRole("button", { name: "Sign out" }).click();
    await signIn(page, "venue@connectsphere.example"); await page.goto("/venues/requests");
    const mainRow = page.getByRole("row").filter({ hasText: rooms[0].name });
    await mainRow.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(mainRow).toHaveCount(0);
    const breakoutRow = page.getByRole("row").filter({ hasText: rooms[1].name });
    await expect(breakoutRow).toContainText("Breakout A");
    const pending = await (await coordinator.api.get(`/api/events/${event.id}/readiness/`)).json();
    expect(pending.missing.join(" ")).toContain("Breakout A");
    expect((await coordinator.post(`/api/events/${event.id}/confirm/`)).status()).toBe(409);
    await breakoutRow.getByRole("button", { name: "Approve", exact: true }).click();
    await expect(breakoutRow).toHaveCount(0);
    // Technical approval comes from real equipment reservation, never a database fixture.
    const types = await (await coordinator.api.get("/api/equipment/types/")).json();
    const item = await jsonOk(await coordinator.post(`/api/events/${event.id}/equipment-requests/`, {
      equipment_type: types.find((t: { code: string }) => t.code === "PROJECTOR").id, quantity: 1 }), 201);
    const plan = await (await tech.api.get(`/api/events/${event.id}/equipment-plan/`)).json();
    await jsonOk(await tech.post(`/api/equipment/requests/${item.request.id}/reserve/`, { expected_revision: plan.revision }), 200);
    await page.getByRole("button", { name: "Sign out" }).click();
    await signIn(page, "coordinator@connectsphere.example"); await page.goto(`/coordinator/events/${event.id}`);
    await page.getByRole("button", { name: /Request (a new )?safety check/ }).click();
    await expect(page.getByRole("region", { name: "Operational safety check" })).toContainText("Awaiting Safety Officer");
    await page.getByRole("button", { name: "Sign out" }).click();
    await signIn(page, "safety@connectsphere.example"); await page.goto("/safety");
    await page.getByRole("link", { name: event.name, exact: true }).click();
    const facts = page.getByRole("region", { name: "Venues", exact: true });
    await expect(facts).toContainText("Main programme"); await expect(facts).toContainText("Breakout A");
    await page.getByRole("radio", { name: /^Approve/ }).check();
    await page.getByRole("button", { name: "Record decision" }).click();
    await expect(page.getByRole("region", { name: "Recorded decision" })).toContainText("Approved");
    await page.getByRole("button", { name: "Sign out" }).click();
    await signIn(page, "coordinator@connectsphere.example"); await page.goto(`/coordinator/events/${event.id}`);
    await page.getByRole("button", { name: "Confirm event", exact: true }).click();
    await expect(page.getByRole("region", { name: "Readiness" })).toContainText("Confirmed by Cora Coordinator");
    await page.getByRole("button", { name: "Sign out" }).click();
    await signIn(page, "organiser@acme.example"); await page.goto(`/organiser/requests/${event.id}`);
    const arrangements = page.getByRole("region", { name: "Confirmed arrangements" });
    await expect(arrangements).toContainText(`Main programme: ${rooms[0].name}`);
    await expect(arrangements).toContainText(`Breakout A: ${rooms[1].name}`);
    await page.getByRole("button", { name: "Sign out" }).click();
    await signIn(page, "attendee@example.com"); await page.goto("/attendee");
    const publicEvent = page.getByRole("listitem").filter({ has: page.getByRole("heading", { name: event.name, exact: true }) });
    await expect(publicEvent).toContainText(`Main programme: ${rooms[0].name}`);
    await expect(publicEvent).toContainText(`Breakout A: ${rooms[1].name}`);
    expect((await page.request.get(`/api/events/${event.id}/venue-bookings/`)).status()).toBe(403);
  } finally {
    const response = await coordinator.api.get(`/api/events/${event.id}/cancellation-preview/`);
    if (response.ok()) await coordinator.post(`/api/events/${event.id}/cancel/`, { expected_version: (await response.json()).version, confirm_cancel: true, reason: "Browser test cleanup" });
    await context.close(); await Promise.all(clients.map(c => c.api.dispose()));
  }
});
