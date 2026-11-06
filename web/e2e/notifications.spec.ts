import { expect, test } from "@playwright/test";
import { actors, dispose, EMAILS, futureDate, json, notifications, roleApi, signIn } from "./helpers";

// E2E-11 / SCRUM-79,82: real workflow notices, recipient isolation, read persistence and current access.
test("E2E-11 recipient-only notification read state and reassignment access", async ({ page, baseURL }) => {
  const all = await actors(baseURL!);
  const other = await roleApi(baseURL!, "coordinator2@connectsphere.example");
  const day = futureDate(90);
  const event = await json(await all.organiser.post("/api/events/", {
    name: "Notification journey " + crypto.randomUUID(), purpose: "Notification read and access",
    preferred_start: day + "T02:00:00Z", preferred_end: day + "T04:00:00Z", expected_attendance: 20,
  }), 201);
  try {
    await json(await all.organiser.post("/api/events/" + event.id + "/submit/"));
    const sent = await notifications(all.lead, event.id);
    expect(sent.filter((n: { kind: string }) => n.kind === "SUBMITTED")).toHaveLength(1);
    expect(await notifications(all.coordinator, event.id)).toHaveLength(0);
    expect(await notifications(all.attendee, event.id)).toHaveLength(0);
    const notice = sent[0];
    expect(notice.is_read).toBe(false);
    const unread = await json(await all.lead.api.get("/api/notifications/unread-count/"));

    await signIn(page, EMAILS.lead);
    await page.locator("summary", { hasText: "Notifications" }).click();
    expect((await notifications(all.lead, event.id))[0].is_read).toBe(false);
    await page.getByRole("list", { name: "Notifications" }).getByRole("button", {
      name: "Unread: " + notice.kind_label + " - " + event.name, exact: true,
    }).click();
    await expect(page).toHaveURL(new RegExp("/lead/events/" + event.id + "$"));
    await expect(page.getByRole("heading", { name: event.name, exact: true })).toBeVisible();
    expect((await notifications(all.lead, event.id))[0].is_read).toBe(true);
    expect((await json(await all.lead.api.get("/api/notifications/unread-count/"))).unread).toBe(unread.unread - 1);
    await page.reload();
    await page.locator("summary", { hasText: "Notifications" }).click();
    await expect(page.getByRole("list", { name: "Notifications" }).getByRole("button", {
      name: notice.kind_label + " - " + event.name, exact: true,
    })).toBeVisible();

    const who = await json(await all.coordinator.api.get("/api/auth/me/"));
    await json(await all.lead.post("/api/events/" + event.id + "/assign-coordinator/", {
      coordinator_id: who.id, expected_revision: 0,
    }));
    const assigned = (await notifications(all.coordinator, event.id)).find(
      (n: { destination: { path: string } | null }) => n.destination?.path === "/coordinator/events/" + event.id,
    );
    expect(assigned).toBeTruthy();
    await page.getByRole("button", { name: "Sign out" }).click();
    await signIn(page, EMAILS.coordinator);
    await page.locator("summary", { hasText: "Notifications" }).click();
    await page.getByRole("list", { name: "Notifications" }).getByRole("button", {
      name: "Unread: " + assigned.kind_label + " - " + event.name, exact: true,
    }).click();
    await expect(page).toHaveURL(new RegExp("/coordinator/events/" + event.id + "$"));

    const next = await json(await other.api.get("/api/auth/me/"));
    const current = await json(await all.lead.api.get("/api/events/" + event.id + "/"));
    await json(await all.lead.post("/api/events/" + event.id + "/assign-coordinator/", {
      coordinator_id: next.id, expected_revision: current.assignment_revision,
    }));
    await page.goto("/coordinator");
    await page.locator("summary", { hasText: "Notifications" }).click();
    await page.getByRole("list", { name: "Notifications" }).getByRole("button", {
      name: assigned.kind_label + " - " + event.name, exact: true,
    }).click();
    await expect(page.getByRole("status")).toContainText("You no longer have access to this event");
    await expect(page).toHaveURL(/\/coordinator$/);
    const oldNotice = (await notifications(all.coordinator, event.id)).find((n: { id: number }) => n.id === assigned.id);
    expect(oldNotice.destination).toBeNull();
  } finally {
    await other.api.dispose();
    await dispose(all);
  }
});
