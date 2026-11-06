import { expect, request, type APIRequestContext, type APIResponse, type Page } from "@playwright/test";

export const PASSWORD = "connectsphere-demo";
export const EMAILS = {
  organiser: "organiser@acme.example", lead: "lead@connectsphere.example",
  coordinator: "coordinator@connectsphere.example", staff: "venue@connectsphere.example",
  tech: "tech@connectsphere.example", safety: "safety@connectsphere.example",
  attendee: "attendee@example.com", second: "attendee2@example.com", third: "attendee3@example.com",
};

export function futureDate(days = 45) {
  const day = new Date();
  // Count working days so adjacent offsets never collapse onto the same
  // Monday when a suite runs at the weekend.
  for (let count = 0; count < days;) {
    day.setUTCDate(day.getUTCDate() + 1);
    if (day.getUTCDay() !== 0 && day.getUTCDay() !== 6) count++;
  }
  return day.toISOString().slice(0, 10);
}

export function localInput(instant: number) {
  return new Date(instant + 8 * 3_600_000).toISOString().slice(0, 16);
}

export async function signIn(page: Page, email: string, password = PASSWORD) {
  await page.goto("/login");
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

export async function json(response: APIResponse, expected = 200) {
  expect(response.status(), await response.text()).toBe(expected);
  return response.json();
}

export async function roleApi(baseURL: string, email: string) {
  const api = await request.newContext({ baseURL });
  await api.get("/api/auth/csrf/");
  const headers = async () => ({
    "X-CSRFToken": (await api.storageState()).cookies.find(c => c.name === "csrftoken")?.value ?? "",
  });
  const post = async (path: string, data: object = {}) => api.post(path, { data, headers: await headers() });
  const put = async (path: string, data: object) => api.put(path, { data, headers: await headers() });
  const patch = async (path: string, data: object) => api.patch(path, { data, headers: await headers() });
  await json(await post("/api/auth/login/", { email, password: PASSWORD }));
  return { api, post, put, patch };
}

export type Actor = Awaited<ReturnType<typeof roleApi>>;
export type Actors = Record<keyof typeof EMAILS, Actor>;
export async function actors(baseURL: string): Promise<Actors> {
  const entries = await Promise.all(Object.entries(EMAILS).map(async ([name, email]) =>
    [name, await roleApi(baseURL, email)] as const));
  return Object.fromEntries(entries) as Actors;
}

export async function dispose(all: Actors) {
  await Promise.all(Object.values(all).map(a => a.api.dispose()));
}

/** Real API setup only; the journey's behaviour is exercised in the browser. */
export async function confirmedEvent(all: Actors, label: string, days: number, attendance = 20) {
  const day = futureDate(days);
  const name = label + " " + crypto.randomUUID();
  const event = await json(await all.organiser.post("/api/events/", {
    name, purpose: label, preferred_start: day + "T02:00:00Z",
    preferred_end: day + "T04:00:00Z", expected_attendance: attendance,
  }), 201);
  await json(await all.organiser.post("/api/events/" + event.id + "/submit/"));
  const who = await json(await all.coordinator.api.get("/api/auth/me/"));
  await json(await all.lead.post("/api/events/" + event.id + "/assign-coordinator/", {
    coordinator_id: who.id, expected_revision: 0,
  }));
  await json(await all.coordinator.post("/api/events/" + event.id + "/approve/"));
  const venue = await json(await all.staff.post("/api/venues/", {
    name: label + " room " + crypto.randomUUID(), capacity: attendance + 10, location: "E2E test wing",
    layouts: ["THEATRE"], facilities: [], wheelchair_access: true,
    opens_at: "08:00", closes_at: "22:00", operating_days: [0, 1, 2, 3, 4, 5, 6],
    emergency_access: "Two marked exits", known_restrictions: "No open flames",
  }), 201);
  const { booking } = await json(await all.coordinator.post("/api/events/" + event.id + "/venue-bookings/", {
    venue: venue.id, starts_at: event.preferred_start, ends_at: event.preferred_end,
    attendance, layout: "THEATRE", required_facilities: [],
  }), 201);
  await json(await all.staff.post("/api/venue-bookings/" + booking.id + "/approve/"));
  const types = await json(await all.coordinator.api.get("/api/equipment/types/"));
  const projector = types.find((t: { code: string }) => t.code === "PROJECTOR");
  expect(projector).toBeTruthy();
  const item = await json(await all.coordinator.post("/api/events/" + event.id + "/equipment-requests/", {
    equipment_type: projector.id, quantity: 1,
  }), 201);
  const plan = await json(await all.tech.api.get("/api/events/" + event.id + "/equipment-plan/"));
  await json(await all.tech.post("/api/equipment/requests/" + item.request.id + "/reserve/", {
    expected_revision: plan.revision,
  }));
  const check = await json(await all.coordinator.post("/api/events/" + event.id + "/safety-checks/"), 201);
  await json(await all.safety.post("/api/safety-checks/" + check.id + "/decide/", { decision: "APPROVED" }));
  await json(await all.coordinator.post("/api/events/" + event.id + "/confirm/"));
  return { event, venue, booking };
}

export async function cancelEvent(all: Actors, id: number) {
  const preview = await json(await all.coordinator.api.get("/api/events/" + id + "/cancellation-preview/"));
  await json(await all.coordinator.post("/api/events/" + id + "/cancel/", {
    expected_version: preview.version, confirm_cancel: true, reason: "E2E cleanup",
  }));
}

export async function notifications(actor: Actor, eventId: number) {
  const rows = await json(await actor.api.get("/api/notifications/"));
  return rows.filter((n: { event: number }) => n.event === eventId);
}
