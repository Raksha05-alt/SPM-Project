import { expect, test } from "@playwright/test";
import { EMAILS, PASSWORD, json, roleApi, signIn } from "./helpers";

// E2E-01: each role exercises a distinct landing/guard policy (SCRUM-6 AC1/3; SCRUM-1 AC3).
for (const [email, landing, forbidden, apiPath] of [
  [EMAILS.organiser, "/organiser", "/lead", "/api/safety-checks/"],
  [EMAILS.lead, "/lead", "/organiser", "/api/registrations/mine/"],
  [EMAILS.coordinator, "/coordinator", "/organiser", "/api/registrations/mine/"],
  [EMAILS.staff, "/venues", "/lead", "/api/safety-checks/"],
  [EMAILS.tech, "/equipment", "/lead", "/api/safety-checks/"],
  [EMAILS.safety, "/safety", "/lead", "/api/registrations/mine/"],
  [EMAILS.attendee, "/events", "/lead", "/api/safety-checks/"],
]) {
  test("E2E-01 role access and logout: " + email, async ({ page }) => {
    await signIn(page, email);
    await expect(page).toHaveURL(new RegExp(landing + "$"));
    await page.goto(forbidden);
    await expect(page).toHaveURL(new RegExp(landing + "$"));
    const denied = await page.request.get(apiPath);
    expect(denied.status()).toBe(403);
    expect((await denied.json()).detail).toBeTruthy();
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.goto("/account");
    await expect(page).toHaveURL(/\/login$/);
    expect((await page.request.get("/api/auth/me/")).status()).toBe(403);
    await expect(page.getByRole("heading", { name: "Your account" })).toHaveCount(0);
  });
}

test("E2E-01 invalid credentials do not open a session", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAILS.attendee);
  await page.getByLabel("Password").fill("incorrect-test-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveText("Those sign-in details were not recognised.");
  await expect(page).toHaveURL(/\/login$/);
  expect((await page.request.get("/api/auth/me/")).status()).toBe(403);
});

// SCRUM-2 AC2/3/4: validation, persistence, privilege refusal and changed sign-in identity.
test("E2E-01 account edits persist without changing permissions", async ({ page, baseURL }) => {
  const original = await roleApi(baseURL!, EMAILS.third);
  const previous = await json(await original.api.get("/api/auth/me/"));
  const newEmail = "account-" + crypto.randomUUID() + "@example.com";
  try {
    await signIn(page, EMAILS.third);
    await page.goto("/account");
    const form = page.getByRole("form", { name: "Contact details" });
    await form.getByLabel("Email address", { exact: true }).fill("invalid");
    await form.getByRole("button", { name: "Save details" }).click();
    await expect(form.getByText("Enter a valid email address.", { exact: true })).toBeVisible();
    expect((await json(await page.request.get("/api/auth/me/"))).email).toBe(EMAILS.third);

    await form.getByLabel("First name", { exact: true }).fill("Updated");
    await form.getByLabel("Email address", { exact: true }).fill(newEmail);
    await form.getByRole("button", { name: "Save details" }).click();
    await expect(page.getByRole("status")).toContainText("Sign in with your new email");
    await page.reload();
    await expect(form.getByLabel("First name", { exact: true })).toHaveValue("Updated");
    await expect(form.getByLabel("Email address", { exact: true })).toHaveValue(newEmail);
    const csrf = (await page.context().cookies()).find(c => c.name === "csrftoken")!.value;
    const escalated = await page.request.patch("/api/auth/me/", {
      data: { role: "COORDINATOR_LEAD", first_name: "Must not save" }, headers: { "X-CSRFToken": csrf },
    });
    expect(escalated.status()).toBe(403);
    const unchanged = await json(await page.request.get("/api/auth/me/"));
    expect(unchanged.role).toBe("ATTENDEE");
    expect(unchanged.first_name).toBe("Updated");

    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByLabel("Email").fill(EMAILS.third);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("alert")).toBeVisible();
    await signIn(page, newEmail);
    await expect(page).toHaveURL(/\/events$/);
  } finally {
    // The original API session remains valid after changing its own email.
    await json(await original.patch("/api/auth/me/", {
      first_name: previous.first_name, last_name: previous.last_name, email: previous.email,
    }));
    await original.api.dispose();
  }
});
