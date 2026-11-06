import { expect, test } from "@playwright/test";
import { actors, cancelEvent, confirmedEvent, dispose, EMAILS, json, localInput, notifications, signIn } from "./helpers";

// E2E-07 / SCRUM-21,81,14,19: independent attendees, capacity, FIFO notices and fresh registration.
test("E2E-07 full event, FIFO waiting list, cancelled withdrawal and fresh registration", async ({ browser, baseURL }) => {
  test.setTimeout(90_000);
  const all = await actors(baseURL!);
  const { event } = await confirmedEvent(all, "Registration FIFO", 80, 10);
  const contexts = await Promise.all([0, 1, 2, 3].map(() => browser.newContext({ baseURL, timezoneId: "Asia/Singapore" })));
  const [organiser, first, second, third] = await Promise.all(contexts.map(c => c.newPage()));
  const card = (page: typeof first) => page.getByRole("listitem").filter({
    has: page.getByRole("heading", { name: event.name, exact: true }),
  });
  try {
    await signIn(organiser, EMAILS.organiser);
    await organiser.goto("/organiser/requests/" + event.id);
    const policy = organiser.getByRole("region", { name: "Registration", exact: true });
    await policy.getByLabel("Allow attendees to register").check();
    await policy.getByLabel("Registration opens").fill(localInput(Date.now() - 3_600_000));
    await policy.getByLabel("Registration closes").fill(localInput(Date.now() + 7 * 86_400_000));
    await policy.getByLabel("Registration capacity").fill("1");
    await policy.getByLabel("Offer a waiting list when the event is full").check();
    await policy.getByRole("button", { name: "Save registration settings" }).click();
    await expect(policy.getByRole("status")).toContainText("Registration settings saved");

    await signIn(first, EMAILS.attendee);
    await card(first).getByRole("button", { name: "Register", exact: true }).click();
    await card(first).getByLabel("Full name").fill("");
    await card(first).getByRole("button", { name: "Confirm registration" }).click();
    await expect(card(first).getByRole("alert")).toContainText("Full name");
    await card(first).getByLabel("Full name").fill("Andy Attendee");
    await card(first).getByRole("button", { name: "Confirm registration" }).click();
    await expect(card(first).getByRole("status")).toContainText("registered");
    await first.reload();
    await expect(card(first).getByRole("button", { name: "Register", exact: true })).toHaveCount(0);
    const summary = await json(await all.attendee.api.get("/api/events/" + event.id + "/registration/"));
    const registrationId = summary.my_registration;

    for (const [page, email, position] of [[second, EMAILS.second, 1], [third, EMAILS.third, 2]] as const) {
      await signIn(page, email);
      await expect(card(page)).toContainText("This event is full");
      await card(page).getByRole("button", { name: "Join the waiting list", exact: true }).click();
      await card(page).getByRole("button", { name: "Join waiting list", exact: true }).click();
      await expect(card(page).getByRole("status")).toContainText("number " + position);
    }
    const before = await json(await all.organiser.api.get("/api/events/" + event.id + "/registrations/"));
    expect(before.registered).toBe(1);
    expect(before.waiting).toBe(2);
    // Another attendee cannot withdraw Andy's place; denial is not a CSRF failure.
    const refused = await all.second.post("/api/registrations/" + registrationId + "/withdraw/", { confirm: true });
    expect(refused.status()).toBe(403);
    expect((await refused.json()).detail).toContain("own registration");

    // Real browser network loss: the summary must fail visibly, retry safely
    // after connectivity returns, and preserve the existing registration.
    await first.context().setOffline(true);
    await card(first).getByRole("button", { name: "Withdraw", exact: true }).click();
    await expect(card(first).getByRole("alert")).toContainText("offline", { timeout: 15_000 });
    await first.context().setOffline(false);
    await expect(card(first).getByText("Your place will be released for someone else.")).toBeVisible();
    await card(first).getByRole("button", { name: "Keep my place" }).click();
    expect((await json(await all.organiser.api.get("/api/events/" + event.id + "/registrations/"))).registered).toBe(1);
    await card(first).getByRole("button", { name: "Withdraw", exact: true }).click();
    await card(first).getByRole("button", { name: "Confirm withdrawal" }).click();
    await expect(card(first).getByRole("button", { name: "Register", exact: true })).toBeVisible();

    // Notify-only FIFO: no automatic enrolment and no reserved seat.
    const opened = await json(await all.organiser.api.get("/api/events/" + event.id + "/registrations/"));
    expect(opened.registered).toBe(0);
    expect(opened.waiting).toBe(2);
    const firstNotices = await notifications(all.second, event.id);
    const laterNotices = await notifications(all.third, event.id);
    expect(firstNotices.some((n: { kind: string }) => n.kind === "PLACE_AVAILABLE")).toBe(true);
    expect(laterNotices.some((n: { kind: string }) => n.kind === "PLACE_AVAILABLE")).toBe(false);
    await second.reload();
    await card(second).getByRole("button", { name: "Register", exact: true }).click();
    await card(second).getByRole("button", { name: "Confirm registration" }).click();
    await expect(card(second).getByRole("status")).toContainText("registered");
    const final = await json(await all.organiser.api.get("/api/events/" + event.id + "/registrations/"));
    expect(final.registered).toBe(1);
    expect(final.waiting).toBe(1);
    await third.reload();
    await expect(card(third)).toContainText("number 1 on the waiting list");
    await expect(card(third).getByRole("button", { name: "Register", exact: true })).toHaveCount(0);
  } finally {
    await cancelEvent(all, event.id);
    await Promise.all(contexts.map(c => c.close()));
    await dispose(all);
  }
});
