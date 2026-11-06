import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import type { EventRequest, Role, User } from "./types";

// These are frontend integration tests: App, auth, route guards, pages and
// HTTP clients are real. Only the HTTP server boundary is replaced.
vi.unmock("./api/layouts");

const roleCases: { role: Role; landing: string; heading: string; endpoint: string }[] = [
  { role: "ORGANISER", landing: "/organiser", heading: "Your event requests", endpoint: "/api/events/?group=drafts" },
  { role: "COORDINATOR", landing: "/coordinator", heading: "Incoming event requests", endpoint: "/api/events/queue/" },
  { role: "COORDINATOR_LEAD", landing: "/lead", heading: "Coordinator assignments", endpoint: "/api/events/unassigned/" },
  { role: "VENUE_STAFF", landing: "/venues", heading: "Venues", endpoint: "/api/venues/" },
  { role: "TECH_SUPPORT", landing: "/equipment", heading: "Equipment requests", endpoint: "/api/equipment/requests/" },
  { role: "SAFETY_OFFICER", landing: "/safety", heading: "Operational safety checks", endpoint: "/api/safety-checks/?status=PENDING" },
  { role: "ATTENDEE", landing: "/events", heading: "Events", endpoint: "/api/events/" },
];

function account(role: Role): User {
  return {
    id: 7, email: "member@example.com", first_name: "Team", last_name: "Member",
    role, role_label: role, organisation: role === "ORGANISER" ? 3 : null,
    organisation_name: role === "ORGANISER" ? "Acme" : null,
    landing_path: roleCases.find((entry) => entry.role === role)!.landing,
  };
}

function eventRecord(changes: Partial<EventRequest> = {}): EventRequest {
  return {
    id: 42, name: "", purpose: "", description: "", preferred_start: null,
    preferred_end: null, expected_attendance: null, required_layout: "",
    accessibility_needs: "", equipment_notes: "", registration_required: false,
    status: "DRAFT", status_label: "Draft", status_description: "Not submitted",
    status_changed_at: null, submitted_at: null, organisation_name: "Acme",
    created_by_name: "Team Member", coordinator: null, coordinator_name: null,
    coordinator_email: null, assignment_requires_attention: false,
    rejection_reason: "", rejected_at: null, clarifications: [],
    missing_mandatory_fields: [], is_editable: true,
    created_at: "2030-06-01T01:00:00Z", updated_at: "2030-06-01T01:00:00Z",
    ...changes,
  };
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});

type Handler = (path: string, method: string, body: unknown) => Response | Promise<Response> | undefined;
const unexpected: string[] = [];
const clients: QueryClient[] = [];

function installServer(initial: User | null, extra?: Handler) {
  let signedIn = initial;
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const method = init?.method ?? "GET";
    const body = typeof init?.body === "string" ? JSON.parse(init.body) as unknown : undefined;
    const override = extra?.(path, method, body);
    if (override !== undefined) return override;
    if (path === "/api/auth/csrf/") {
      document.cookie = "csrftoken=integration-token; path=/";
      return json({});
    }
    if (path === "/api/auth/me/") return signedIn ? json(signedIn) : json({ detail: "Sign in required." }, 401);
    if (path === "/api/auth/logout/" && method === "POST") {
      signedIn = null;
      return new Response(null, { status: 204 });
    }
    if (path === "/api/notifications/unread-count/") return json({ unread: 0 });
    if (path === "/api/layouts/") return json([{
      code: "THEATRE", name: "Theatre", description: "Rows of seats", is_active: true,
      sort_order: 1, created_at: "2030-01-01T00:00:00Z",
      updated_at: "2030-01-01T00:00:00Z", updated_by_name: null,
    }]);
    if ([
      "/api/notifications/", "/api/events/?group=drafts", "/api/events/?group=submitted",
      "/api/events/queue/", "/api/events/unassigned/", "/api/venues/",
      "/api/equipment/requests/", "/api/arrangement-reviews/?status=PENDING", "/api/safety-checks/?status=PENDING", "/api/events/",
      "/api/registrations/mine/",
    ].includes(path)) return json([]);
    unexpected.push(method + " " + path);
    return json({ detail: "Unexpected test request: " + path }, 500);
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function Location() {
  return <output aria-label="Current route">{useLocation().pathname}</output>;
}

function mount(path = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  clients.push(client);
  render(<QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[path]}><App /><Location /></MemoryRouter>
  </QueryClientProvider>);
  return client;
}

afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.unstubAllGlobals();
  document.cookie = "csrftoken=; Max-Age=0; path=/";
  expect(unexpected.splice(0)).toEqual([]);
});

describe("US-6/US-1 application route integration", () => {
  it.each(roleCases)("lands a restored $role session on its API-selected screen", async ({ role, landing, heading, endpoint }) => {
    const fetch = installServer(account(role));
    mount();
    expect(await screen.findByRole("heading", { name: heading, level: 1 })).toBeVisible();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(endpoint, expect.objectContaining({ credentials: "same-origin" })));
    expect(screen.getByLabelText("Current route")).toHaveTextContent(landing);
    expect(screen.getByRole("button", { name: "Sign out" })).toBeEnabled();
  });

  it("redirects an expired deep-link session before loading private event data", async () => {
    const fetch = installServer(null);
    mount("/coordinator/events/42");
    expect(await screen.findByRole("heading", { name: "Sign in to ConnectSphere" })).toBeVisible();
    expect(screen.getByLabelText("Current route")).toHaveTextContent("/login");
    expect(fetch.mock.calls.some(([path]) => path === "/api/events/42/")).toBe(false);
  });

  it("refuses a venue-maintenance route to an attendee without requesting the catalogue", async () => {
    const fetch = installServer(account("ATTENDEE"));
    mount("/venues/layouts");
    expect(await screen.findByRole("heading", { name: "Events", level: 1 })).toBeVisible();
    expect(screen.getByLabelText("Current route")).toHaveTextContent("/events");
    expect(fetch.mock.calls.some(([path]) => path === "/api/layouts/")).toBe(false);
  });

  it("resolves an unknown URL through the signed-in user's home screen", async () => {
    installServer(account("ORGANISER"));
    mount("/missing-page");
    expect(await screen.findByRole("heading", { name: "Your event requests" })).toBeVisible();
    expect(screen.getByLabelText("Current route")).toHaveTextContent("/organiser");
  });

  it("shows the home loading state until session restoration completes", async () => {
    let resolve!: (value: Response) => void;
    const pending = new Promise<Response>((done) => { resolve = done; });
    const fetch = installServer(null, (path) => path === "/api/auth/me/" ? pending : undefined);
    mount();
    await waitFor(() => expect(fetch.mock.calls.some(([path]) => path === "/api/auth/me/")).toBe(true));
    expect(screen.getByText("Loading…")).toBeVisible();
    expect(fetch.mock.calls.some(([path]) => path === "/api/events/")).toBe(false);
    resolve(json(account("ATTENDEE")));
    expect(await screen.findByRole("heading", { name: "Events", level: 1 })).toBeVisible();
  });

  it("signs out through the real client and removes the protected screen", async () => {
    const fetch = installServer(account("ORGANISER"));
    mount("/organiser");
    await screen.findByRole("heading", { name: "Your event requests" });
    await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in to ConnectSphere" })).toBeVisible();
    expect(fetch).toHaveBeenCalledWith("/api/auth/logout/", expect.objectContaining({
      method: "POST", credentials: "same-origin",
      headers: expect.objectContaining({ "X-CSRFToken": "integration-token" }),
    }));
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
  });
});

it("US-7/8/15 edits, saves, reopens and submits one request through the real router and HTTP clients", async () => {
  let stored = eventRecord();
  const writes: { method: string; body: unknown }[] = [];
  installServer(account("ORGANISER"), (path, method, body) => {
    if (path === "/api/events/" && method === "POST") {
      writes.push({ method, body });
      stored = eventRecord(body as Partial<EventRequest>);
      return json(stored, 201);
    }
    if (path === "/api/events/42/" && method === "GET") return json(stored);
    if (path === "/api/events/42/" && method === "PATCH") {
      writes.push({ method, body });
      stored = { ...stored, ...body as Partial<EventRequest> };
      return json(stored);
    }
    if (path === "/api/events/42/submit/" && method === "POST") {
      stored = { ...stored, status: "SUBMITTED", status_label: "Submitted", is_editable: false };
      return json(stored);
    }
    if (path === "/api/events/?group=submitted") return json(stored.status === "SUBMITTED" ? [stored] : []);
    return undefined;
  });
  mount("/organiser/requests/new");
  await screen.findByRole("option", { name: "Theatre" });
  await userEvent.type(screen.getByLabelText("Event name"), "Partner Summit");
  await userEvent.type(screen.getByLabelText("Purpose"), "Annual partner briefing");
  await userEvent.type(screen.getByLabelText("Description"), "Product demonstrations");
  fireEvent.change(screen.getByLabelText("Preferred start"), { target: { value: "2030-06-18T10:00" } });
  fireEvent.change(screen.getByLabelText("Preferred end"), { target: { value: "2030-06-18T12:00" } });
  await userEvent.type(screen.getByLabelText("Expected attendance"), "45");
  await userEvent.selectOptions(screen.getByLabelText("Required room layout"), "THEATRE");
  await userEvent.type(screen.getByLabelText("Accessibility needs"), "Step-free access");
  await userEvent.type(screen.getByLabelText("Equipment and technical requirements"), "Two microphones");
  await userEvent.click(screen.getByLabelText("Attendees will need to register for this event"));
  await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(screen.getByLabelText("Current route")).toHaveTextContent("/organiser/requests/42"));
  expect(writes[0]).toEqual({ method: "POST", body: expect.objectContaining({
    name: "Partner Summit", purpose: "Annual partner briefing", description: "Product demonstrations",
    preferred_start: new Date("2030-06-18T10:00").toISOString(),
    preferred_end: new Date("2030-06-18T12:00").toISOString(),
    expected_attendance: 45, required_layout: "THEATRE", accessibility_needs: "Step-free access",
    equipment_notes: "Two microphones", registration_required: true,
  }) });
  await screen.findByDisplayValue("Partner Summit");
  await userEvent.clear(screen.getByLabelText("Expected attendance"));
  fireEvent.change(screen.getByLabelText("Preferred end"), { target: { value: "" } });
  await userEvent.click(screen.getByRole("button", { name: "Save draft" }));
  await waitFor(() => expect(writes[writes.length - 1]).toMatchObject({ method: "PATCH", body: {
    expected_attendance: null, preferred_end: null, equipment_notes: "Two microphones",
  } }));
  await userEvent.type(screen.getByLabelText("Expected attendance"), "45");
  fireEvent.change(screen.getByLabelText("Preferred end"), { target: { value: "2030-06-18T12:00" } });
  await userEvent.click(screen.getByRole("button", { name: "Send to ConnectSphere" }));
  expect(await screen.findByRole("heading", { name: "Your event requests" })).toBeVisible();
  expect(await screen.findByRole("link", { name: "Partner Summit" })).toBeVisible();
  expect(stored.status).toBe("SUBMITTED");
  expect(stored.expected_attendance).toBe(45);
});

it("US-6 rejects invalid credentials, then lands a successful retry on the server-selected role", async () => {
  const fetch = installServer(null, (path, method, body) => {
    if (path === "/api/auth/login/" && method === "POST") {
      return (body as { password: string }).password === "wrong"
        ? json({ detail: "Invalid credentials." }, 401)
        : json(account("COORDINATOR"));
    }
    return undefined;
  });
  mount();
  await userEvent.type(await screen.findByLabelText("Email"), "member@example.com");
  await userEvent.type(screen.getByLabelText("Password"), "wrong");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Those sign-in details were not recognised.");
  expect(fetch.mock.calls.some(([path]) => path === "/api/events/queue/")).toBe(false);
  await userEvent.clear(screen.getByLabelText("Password"));
  await userEvent.type(screen.getByLabelText("Password"), "connectsphere-demo");
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("heading", { name: "Incoming event requests" })).toBeVisible();
  expect(fetch).toHaveBeenCalledWith("/api/auth/login/", expect.objectContaining({
    method: "POST", credentials: "same-origin",
    headers: expect.objectContaining({ "X-CSRFToken": "integration-token" }),
    body: JSON.stringify({ email: "member@example.com", password: "connectsphere-demo" }),
  }));
});

it("US-91 preserves an in-use layout, offers retirement and manages a separate new layout through real HTTP clients", async () => {
  let catalogue = [{
    code: "THEATRE", name: "Theatre", description: "Rows of seats", is_active: true,
    sort_order: 1, created_at: "2030-01-01T00:00:00Z",
    updated_at: "2030-01-01T00:00:00Z", updated_by_name: null,
  }];
  const fetch = installServer(account("VENUE_STAFF"), (path, method, body) => {
    if (path === "/api/layouts/" && method === "GET") return json(catalogue);
    if (path === "/api/layouts/" && method === "POST") {
      const layout = { ...catalogue[0], ...body as { code: string; name: string; description: string } };
      catalogue = [...catalogue, layout];
      return json(layout, 201);
    }
    const match = path.match(/^\/api\/layouts\/([^/]+)\/(retire\/|reinstate\/)?$/);
    if (!match) return undefined;
    const code = decodeURIComponent(match[1]);
    const layout = catalogue.find((entry) => entry.code === code)!;
    if (method === "PATCH") {
      if ((body as { name: string }).name === "Duplicate") return json({ name: ["This name is already used."] }, 400);
      Object.assign(layout, body);
      return json(layout);
    }
    if (method === "DELETE") {
      if (code === "THEATRE") return json({
        detail: "Existing records use this layout.",
        usage: { venues: 2, event_requests: 0, venue_bookings: 1 },
      }, 409);
      catalogue = catalogue.filter((entry) => entry.code !== code);
      return new Response(null, { status: 204 });
    }
    if (method === "POST") {
      layout.is_active = match[2] === "reinstate/";
      return json(layout);
    }
    return undefined;
  });
  mount("/venues/layouts");
  await screen.findByRole("heading", { name: "Room layouts" });
  await userEvent.type(screen.getByLabelText("Code"), "CABARET");
  await userEvent.type(screen.getByLabelText("Name"), "Cabaret");
  await userEvent.type(screen.getByLabelText("Description"), "Tables with stage view");
  await userEvent.click(screen.getByRole("button", { name: "Add layout" }));
  expect(await screen.findByRole("status", { name: "" })).toHaveTextContent("Added Cabaret.");
  await userEvent.click(await screen.findByRole("button", { name: "Edit Cabaret" }));
  await userEvent.clear(screen.getByLabelText("Name for CABARET"));
  await userEvent.type(screen.getByLabelText("Name for CABARET"), "Duplicate");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("This name is already used.");
  expect(catalogue.find((entry) => entry.code === "CABARET")?.name).toBe("Cabaret");
  await userEvent.clear(screen.getByLabelText("Name for CABARET"));
  await userEvent.type(screen.getByLabelText("Name for CABARET"), "Cabaret revised");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("status", { name: "" })).toHaveTextContent("Saved Cabaret revised.");
  await userEvent.click(await screen.findByRole("button", { name: "Retire Cabaret revised" }));
  expect(await screen.findByRole("status", { name: "" })).toHaveTextContent("Retired Cabaret revised.");
  await userEvent.click(await screen.findByRole("button", { name: "Reinstate Cabaret revised" }));
  expect(await screen.findByRole("status", { name: "" })).toHaveTextContent("Cabaret revised can be chosen again.");
  await userEvent.click(screen.getByRole("button", { name: "Edit Cabaret revised" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByLabelText("Name for CABARET")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Delete Cabaret revised" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
  expect(await screen.findByRole("status", { name: "" })).toHaveTextContent("Deleted Cabaret revised.");
  expect(catalogue.map((entry) => entry.code)).toEqual(["THEATRE"]);
  await userEvent.click(screen.getByRole("button", { name: "Delete Theatre" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Used by 2 venues, 1 venue booking.");
  await userEvent.click(screen.getByRole("button", { name: "Retire Theatre instead" }));
  expect(await screen.findByRole("status", { name: "" })).toHaveTextContent("Retired Theatre.");
  expect(catalogue[0].is_active).toBe(false);
  expect(fetch.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(2);
});

it("US-81 loads and saves registration settings through real clients and shows a rejected window beside its field", async () => {
  const current = eventRecord({ status: "APPROVED", status_label: "Approved", is_editable: false });
  let policy = {
    event: 42, enabled: false, opens_at: null as string | null, closes_at: null as string | null,
    manually_closed: false, capacity: null as number | null, registered: 0, remaining: null,
    full: false, open: false, waitlist_enabled: false, waiting: 0,
  };
  let rejectWindow = true;
  const fetch = installServer(account("ORGANISER"), (path, method, body) => {
    if (path === "/api/events/42/") return json(current);
    if (path === "/api/events/42/change-requests/") return json([]);
    if (path === "/api/events/42/registration-policy/") {
      if (method === "GET") return json(policy);
      if (rejectWindow) {
        rejectWindow = false;
        return json({ opens_at: ["Registration must open before it closes."] }, 400);
      }
      policy = { ...policy, ...body as Partial<typeof policy> };
      return json(policy);
    }
    return undefined;
  });
  mount("/organiser/requests/42");
  await userEvent.click(await screen.findByLabelText("Allow attendees to register"));
  fireEvent.change(screen.getByLabelText(/^Registration opens/), { target: { value: "2030-06-18T10:00" } });
  fireEvent.change(screen.getByLabelText("Registration closes"), { target: { value: "2030-06-18T09:00" } });
  await userEvent.click(screen.getByRole("button", { name: "Save registration settings" }));
  expect(await screen.findByText("Registration must open before it closes.")).toBeVisible();
  expect(screen.queryByText("Registration settings saved.")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(/^Registration opens/), { target: { value: "2030-06-17T10:00" } });
  await userEvent.click(screen.getByLabelText("Offer a waiting list when the event is full"));
  await userEvent.click(screen.getByRole("button", { name: "Save registration settings" }));
  expect(await screen.findByText("Registration settings saved.")).toBeVisible();
  expect(policy).toMatchObject({
    enabled: true, capacity: null, waitlist_enabled: true,
    opens_at: new Date("2030-06-17T10:00").toISOString(),
    closes_at: new Date("2030-06-18T09:00").toISOString(),
  });
  const saved = fetch.mock.calls.filter(([path, init]) =>
    path === "/api/events/42/registration-policy/" && init?.method === "PUT");
  expect(saved).toHaveLength(2);
  expect(JSON.parse(String(saved[1][1]?.body))).not.toHaveProperty("registered");
});

it("US-21/14 sends edited attendee contact details, refreshes the registration and confirms withdrawal", async () => {
  let state: "REGISTERED" | "WITHDRAWN" | null = null;
  const publicEvent = { id: 42, name: "Partner Summit", status: "CONFIRMED", status_label: "Confirmed",
    starts_at: "2030-06-18T02:00:00Z", ends_at: "2030-06-18T04:00:00Z", venues: [] };
  const registration = () => ({
    id: 8, event: 42, event_name: "Partner Summit", status: state, status_label: state === "REGISTERED" ? "Registered" : "Withdrawn",
    full_name: "Attendee Contact", email: "attendee@example.com", accessibility_requirements: "Step-free access",
    registered_at: "2030-06-01T00:00:00Z", withdrawn_at: null, event_details: publicEvent,
  });
  const fetch = installServer(account("ATTENDEE"), (path, method) => {
    if (path === "/api/events/") return json([{
      ...eventRecord(), name: "Partner Summit", status: "CONFIRMED", status_label: "Confirmed",
      preferred_start: publicEvent.starts_at, preferred_end: publicEvent.ends_at, registration_required: true,
    }]);
    if (path === "/api/registrations/mine/") return json(state ? [registration()] : []);
    if (path === "/api/events/42/registration/") {
      if (method === "POST") {
        state = "REGISTERED";
        return json({ detail: "Registration confirmed.", registration: registration(), event: publicEvent }, 201);
      }
      return json({
        enabled: true, open: state !== "REGISTERED", reason: "", reason_code: "", opens_at: null, closes_at: null,
        capacity: 1, remaining: state === "REGISTERED" ? 0 : 1, my_status: state, my_registration: state ? 8 : null,
        waitlist_offered: false, waitlist_position: null, waiting: 0,
      });
    }
    if (path === "/api/registrations/8/withdraw/") {
      if (method === "POST") {
        state = "WITHDRAWN";
        return json({ detail: "Registration withdrawn.", registration: registration() });
      }
      return json({ registration: 8, event: 42, event_name: "Partner Summit",
        starts_at: publicEvent.starts_at, ends_at: publicEvent.ends_at,
        status: state, releases_place: true, can_withdraw: true, reason: "" });
    }
    return undefined;
  });
  mount("/events");
  await userEvent.click(await screen.findByRole("button", { name: "Register" }));
  await userEvent.clear(screen.getByLabelText("Full name"));
  await userEvent.type(screen.getByLabelText("Full name"), "Attendee Contact");
  await userEvent.clear(screen.getByLabelText("Email address"));
  await userEvent.type(screen.getByLabelText("Email address"), "attendee@example.com");
  await userEvent.type(screen.getByLabelText("Accessibility requirements (optional)"), "Step-free access");
  await userEvent.click(screen.getByRole("button", { name: "Confirm registration" }));
  expect(await screen.findByRole("button", { name: "Withdraw" })).toBeVisible();
  expect(within(screen.getByRole("region", { name: "My registrations" })).getByText("Registered · Confirmed")).toBeVisible();
  expect(fetch).toHaveBeenCalledWith("/api/events/42/registration/", expect.objectContaining({
    method: "POST", body: JSON.stringify({
      full_name: "Attendee Contact", email: "attendee@example.com", accessibility_requirements: "Step-free access",
    }),
  }));
  await userEvent.click(screen.getByRole("button", { name: "Withdraw" }));
  expect(await screen.findByText("Your place will be released for someone else.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Confirm withdrawal" }));
  expect(await screen.findByRole("button", { name: "Register" })).toBeVisible();
  await waitFor(() => expect(screen.getByRole("region", { name: "My registrations" })).toHaveTextContent("Withdrawn · Confirmed"));
  expect(fetch).toHaveBeenCalledWith("/api/registrations/8/withdraw/", expect.objectContaining({
    method: "POST", body: JSON.stringify({ confirm: true }),
    headers: expect.objectContaining({ "X-CSRFToken": "integration-token" }),
  }));
});

it("US-19 joins a full event's waiting list and retains the returned queue position", async () => {
  let joined = false;
  const fetch = installServer(account("ATTENDEE"), (path, method) => {
    if (path === "/api/events/") return json([{ ...eventRecord(), name: "Full Event",
      status: "CONFIRMED", status_label: "Confirmed", registration_required: true }]);
    if (path === "/api/events/42/registration/") return json({
      enabled: true, open: false, reason: "Event full", reason_code: "FULL", opens_at: null, closes_at: null,
      capacity: 1, remaining: 0, my_status: joined ? "WAITLISTED" : null,
      my_registration: joined ? 9 : null, waitlist_offered: !joined, waitlist_position: joined ? 3 : null, waiting: joined ? 3 : 2,
    });
    if (path === "/api/events/42/waitlist/" && method === "POST") {
      joined = true;
      return json({ detail: "You joined the waiting list at position 3.", position: 3, registration: { id: 9, status: "WAITLISTED" } }, 201);
    }
    return undefined;
  });
  mount("/events");
  await userEvent.click(await screen.findByRole("button", { name: "Join the waiting list" }));
  await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(fetch.mock.calls.some(([path]) => path === "/api/events/42/waitlist/")).toBe(false);
  await userEvent.click(screen.getByRole("button", { name: "Join the waiting list" }));
  await userEvent.click(screen.getByRole("button", { name: "Join waiting list" }));
  expect(await screen.findByText("You joined the waiting list at position 3.")).toBeVisible();
  expect(await screen.findByRole("button", { name: "Leave the waiting list" })).toBeVisible();
  expect(fetch).toHaveBeenCalledWith("/api/events/42/waitlist/", expect.objectContaining({
    method: "POST", body: JSON.stringify({
      full_name: "Team Member", email: "member@example.com", accessibility_requirements: "",
    }),
  }));
});
