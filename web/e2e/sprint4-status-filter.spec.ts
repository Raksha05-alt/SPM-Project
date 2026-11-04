import { expect, request, test } from "@playwright/test";

async function role(baseURL: string, email: string) {
  const api = await request.newContext({ baseURL });
  await api.get("/api/auth/csrf/");
  const token = async () => (await api.storageState()).cookies.find(c => c.name === "csrftoken")?.value ?? "";
  const post = async (path: string, data: object = {}) => api.post(path, { data, headers: { "X-CSRFToken": await token() } });
  expect((await post("/api/auth/login/", { email, password: "connectsphere-demo" })).status()).toBe(200);
  return { api, post };
}

test("SCRUM-57: real multi-status filters, empty state, clear and current-assignment permissions", async ({ page, baseURL }) => {
  const clients = await Promise.all(["organiser@acme.example", "lead@connectsphere.example", "coordinator@connectsphere.example", "coordinator2@connectsphere.example"].map(email => role(baseURL!, email)));
  const [organiser, lead, coordinator, other] = clients;
  const mine = await (await coordinator.api.get("/api/auth/me/")).json();
  const theirs = await (await other.api.get("/api/auth/me/")).json();
  // Clear only previous executions of this journey in the isolated browser database.
  for (const actor of [coordinator, other]) {
    const prior = await (await actor.api.get("/api/events/mine/")).json();
    for (const row of prior.filter((e: { name: string }) => /^(Approved|Planning|Private) filter /.test(e.name))) {
      const preview = await actor.api.get(`/api/events/${row.id}/cancellation-preview/`);
      if (preview.ok()) await actor.post(`/api/events/${row.id}/cancel/`, { expected_version: (await preview.json()).version, confirm_cancel: true, reason: "Filter acceptance cleanup" });
    }
  }
  const suffix = Date.now();
  const made: { id: number; name: string }[] = [];
  try {
    for (const [label, owner, actor] of [["Approved filter", mine.id, coordinator], ["Planning filter", mine.id, coordinator], ["Private filter", theirs.id, other]] as const) {
      const created = await organiser.post("/api/events/", { name: `${label} ${suffix}`, purpose: "Filter acceptance",
        preferred_start: "2031-06-18T02:00:00Z", preferred_end: "2031-06-18T04:00:00Z", expected_attendance: 20 });
      expect(created.status()).toBe(201); const event = await created.json(); made.push(event);
      expect((await organiser.post(`/api/events/${event.id}/submit/`)).status()).toBe(200);
      expect((await lead.post(`/api/events/${event.id}/assign-coordinator/`, { coordinator_id: owner, expected_revision: 0 })).status()).toBe(200);
      expect((await actor.post(`/api/events/${event.id}/approve/`)).status()).toBe(200);
    }
    const venues = await (await coordinator.api.get("/api/venues/")).json();
    const sent = await coordinator.post(`/api/events/${made[1].id}/venue-bookings/`, { venue: venues.find((v: { name: string }) => v.name === "Harbour Hall").id,
      starts_at: "2031-06-18T02:00:00Z", ends_at: "2031-06-18T04:00:00Z", attendance: 20 });
    expect(sent.status()).toBe(201); // actual request moves Approved to Planning
    await page.goto("/login"); await page.getByLabel("Email").fill("coordinator@connectsphere.example");
    await page.getByLabel("Password").fill("connectsphere-demo");
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
    await page.goto("/coordinator/mine");
    await expect(page.getByRole("link", { name: made[0].name, exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: made[1].name, exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: made[2].name, exact: true })).toHaveCount(0);
    const planning = page.getByRole("checkbox", { name: "Planning", exact: true });
    await planning.check();
    await expect(page.getByRole("link", { name: made[0].name, exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: made[1].name, exact: true })).toBeVisible();
    await page.getByRole("checkbox", { name: "Approved", exact: true }).check();
    await expect(page.getByRole("link", { name: made[0].name, exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: made[1].name, exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await page.getByRole("checkbox", { name: "Completed", exact: true }).check();
    await expect(page.getByText("No events match the selected statuses.")).toBeVisible();
    await page.getByRole("button", { name: "Clear filters" }).click();
    await expect(page.getByRole("link", { name: made[0].name, exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: made[1].name, exact: true })).toBeVisible();
    // A real Lead reassignment changes what the old coordinator may retrieve.
    const current = await (await lead.api.get(`/api/events/${made[1].id}/`)).json();
    expect((await lead.post(`/api/events/${made[1].id}/assign-coordinator/`, { coordinator_id: theirs.id, expected_revision: current.assignment_revision })).status()).toBe(200);
    await planning.check();
    // Other journeys may leave permitted Planning events; only the reassigned
    // and foreign records must disappear from this user's results.
    await expect(page.getByRole("link", { name: made[1].name, exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: made[2].name, exact: true })).toHaveCount(0);
    const filtered = await (await page.request.get("/api/events/?status=PLANNING&status=APPROVED")).json();
    expect(filtered.map((e: { id: number }) => e.id)).not.toContain(made[1].id);
    expect(filtered.map((e: { id: number }) => e.id)).not.toContain(made[2].id);
  } finally {
    for (const event of made) {
      for (const actor of [coordinator, other]) {
        const preview = await actor.api.get(`/api/events/${event.id}/cancellation-preview/`);
        if (preview.ok()) {
          await actor.post(`/api/events/${event.id}/cancel/`, { expected_version: (await preview.json()).version,
            confirm_cancel: true, reason: "Filter acceptance cleanup" });
          break;
        }
      }
    }
    await Promise.all(clients.map(client => client.api.dispose()));
  }
});
