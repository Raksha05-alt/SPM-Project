import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  joinWaitlist,
  listOpenEvents,
  registerForEvent,
  type AttendeeEventRow,
  type MyRegistration,
} from "../api/attendee";
import { ApiError } from "../api/client";
import { AuthContext } from "../auth/AuthContext";
import { AttendeeEvents } from "./AttendeeEvents";

vi.mock("../api/attendee", () => ({
  listOpenEvents: vi.fn(),
  registerForEvent: vi.fn(),
  joinWaitlist: vi.fn(),
}));

function eventRow(overrides: Partial<AttendeeEventRow> = {}): AttendeeEventRow {
  return {
    id: 42,
    name: "Regional Partner Conference",
    description: "A public partner conference.",
    preferred_start: "2026-10-20T01:00:00Z",
    preferred_end: "2026-10-20T07:00:00Z",
    accessibility_needs: "Step-free access",
    registration_required: true,
    registration_capacity: 100,
    registration_opens_at: null,
    registration_closes_at: null,
    places_left: 12,
    registration_message: null,
    waitlist_offered: false,
    my_registration: null,
    venues: [
      { name: "Harbour Hall", location: "Level 2", start: "2026-10-20T01:00:00Z", end: "2026-10-20T07:00:00Z" },
    ],
    status: "CONFIRMED",
    status_label: "Confirmed",
    status_description: "All essential arrangements are in place.",
    status_changed_at: "2026-09-22T02:00:00Z",
    ...overrides,
  };
}

const registration = {
  id: 9,
  event: 42,
  status: "REGISTERED",
  status_display: "Registered",
} as MyRegistration;

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthContext.Provider
        value={{
          user: {
            id: 5,
            email: "ann@example.com",
            first_name: "Ann",
            last_name: "Attendee",
            role: "ATTENDEE",
            role_label: "Attendee",
            organisation: null,
            organisation_name: null,
            landing_path: "/events",
          },
          loading: false,
          signIn: vi.fn(),
          signOut: vi.fn(),
        }}
      >
        <MemoryRouter>
          <AttendeeEvents />
        </MemoryRouter>
      </AuthContext.Provider>
    </QueryClientProvider>,
  );
}

describe("AttendeeEvents", () => {
  beforeEach(() => vi.clearAllMocks());

  it("US-06.1 AC2-AC4: shows only the attendee-safe status details returned by the API", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([eventRow()]);
    renderPage();
    expect(await screen.findByText("Regional Partner Conference")).toBeInTheDocument();
    expect(screen.getByText("Confirmed")).toHaveAttribute(
      "title",
      "All essential arrangements are in place.",
    );
    expect(screen.getByText("All essential arrangements are in place.")).toBeInTheDocument();
    expect(screen.getByText(/Status updated/)).toBeInTheDocument();
  });
});

describe("SCRUM-21 register for an event", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: shows places left and the venue", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([eventRow()]);
    renderPage();
    expect(await screen.findByText("12 places left")).toBeInTheDocument();
    expect(screen.getByText("Harbour Hall, Level 2")).toBeInTheDocument();
  });

  it("AC2/AC3: registers with details prefilled from the signed-in user", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([eventRow()]);
    vi.mocked(registerForEvent).mockResolvedValue(registration);
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Register" }));
    expect(screen.getByLabelText("Full name")).toHaveValue("Ann Attendee");
    expect(screen.getByLabelText("Email")).toHaveValue("ann@example.com");
    await userEvent.type(screen.getByLabelText("Accessibility needs (optional)"), "Hearing loop");
    await userEvent.click(screen.getByRole("button", { name: "Confirm registration" }));
    expect(registerForEvent).toHaveBeenCalledWith(42, {
      full_name: "Ann Attendee",
      email: "ann@example.com",
      accessibility_needs: "Hearing loop",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Your status: Registered.");
  });

  it("AC2: full name and email are required before anything is sent", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([eventRow()]);
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Register" }));
    await userEvent.clear(screen.getByLabelText("Full name"));
    await userEvent.clear(screen.getByLabelText("Email"));
    await userEvent.click(screen.getByRole("button", { name: "Confirm registration" }));
    expect(screen.getByText("Enter your full name.")).toBeInTheDocument();
    expect(screen.getByText("Enter your email address.")).toBeInTheDocument();
    expect(registerForEvent).not.toHaveBeenCalled();
  });

  it("AC2: shows field errors from the API", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([eventRow()]);
    vi.mocked(registerForEvent).mockRejectedValue(
      new ApiError(400, { email: ["Enter a valid email address."] }, "Something went wrong."),
    );
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Register" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm registration" }));
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
  });

  it("AC5 / SCRUM-81: shows why registration is closed and offers no form", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([
      eventRow({ registration_message: "Registration for this event has closed." }),
    ]);
    renderPage();
    expect(await screen.findByText("Registration for this event has closed.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
  });

  it("SCRUM-81: shows the API refusal when the event is already full", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([eventRow({ places_left: 1 })]);
    vi.mocked(registerForEvent).mockRejectedValue(
      new ApiError(409, { detail: "This event is full.", full: true, waitlist_offered: true }, "This event is full."),
    );
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Register" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm registration" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This event is full.");
    expect(screen.getByRole("button", { name: "Join waiting list instead" })).toBeInTheDocument();
  });

  it("SCRUM-81: shows the API refusal when already registered", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([eventRow()]);
    vi.mocked(registerForEvent).mockRejectedValue(
      new ApiError(409, { detail: "You are already registered for this event.", existing: 9 }, "You are already registered for this event."),
    );
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Register" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm registration" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("You are already registered for this event.");
  });
});

describe("SCRUM-19 waiting list", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1/AC2: offers the waiting list only when the API does", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([
      eventRow({ id: 1, name: "Full event", places_left: 0, waitlist_offered: true }),
      eventRow({ id: 2, name: "Full, no list", places_left: 0, waitlist_offered: false }),
    ]);
    vi.mocked(joinWaitlist).mockResolvedValue({
      ...registration,
      status: "WAITLISTED",
      status_display: "On waiting list",
    });
    renderPage();
    const buttons = await screen.findAllByRole("button", { name: "Join waiting list" });
    expect(buttons).toHaveLength(1);
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
    await userEvent.click(buttons[0]);
    await userEvent.click(screen.getByRole("button", { name: "Join waiting list" }));
    expect(joinWaitlist).toHaveBeenCalledWith(1, expect.objectContaining({ email: "ann@example.com" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Your status: On waiting list.");
  });

  it("AC3: shows my registration status instead of the form", async () => {
    vi.mocked(listOpenEvents).mockResolvedValue([
      eventRow({ my_registration: { id: 9, status: "WAITLISTED", status_display: "On waiting list" } }),
    ]);
    renderPage();
    expect(await screen.findByText("Your status: On waiting list")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
  });
});
