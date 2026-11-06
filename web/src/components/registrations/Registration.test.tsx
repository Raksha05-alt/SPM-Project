import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  getRegistrationPolicy,
  getRegistrationSummary,
  listMyRegistrations,
  registerForEvent,
  updateRegistrationPolicy,
  type RegistrationSummary,
} from "../../api/registrations";
import { MyRegistrations } from "./MyRegistrations";
import { RegisterPanel } from "./RegisterPanel";
import { RegistrationPolicyForm } from "./RegistrationPolicyForm";

vi.mock("../../api/registrations", () => ({
  getRegistrationSummary: vi.fn(),
  joinWaitlist: vi.fn(),
  getWithdrawalSummary: vi.fn(),
  withdrawRegistration: vi.fn(),
  registerForEvent: vi.fn(),
  listMyRegistrations: vi.fn(),
  getRegistrationPolicy: vi.fn(),
  updateRegistrationPolicy: vi.fn(),
}));

vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, email: "andy@example.com", first_name: "Andy", last_name: "Attendee" },
  }),
}));

const OPEN: RegistrationSummary = {
  enabled: true,
  open: true,
  reason: "",
  reason_code: "",
  opens_at: null,
  closes_at: null,
  capacity: 50,
  remaining: 12,
  my_status: null,
  my_registration: null,
  waitlist_offered: false,
  waitlist_position: null,
  waiting: 0,
};

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

describe("RegisterPanel (SCRUM-21/81)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("SCRUM-21 AC1 - registers with details prefilled from the account", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue(OPEN);
    vi.mocked(registerForEvent).mockResolvedValue({
      detail: 'You are registered for "Harbour Gala".',
    } as Awaited<ReturnType<typeof registerForEvent>>);
    const user = userEvent.setup();
    wrap(<RegisterPanel eventId={3} />);

    expect(await screen.findByText("12 places left")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Register" }));
    expect(screen.getByLabelText("Full name")).toHaveValue("Andy Attendee");
    await user.type(screen.getByLabelText(/Accessibility requirements/), "Wheelchair space");
    await user.click(screen.getByRole("button", { name: "Confirm registration" }));

    expect(registerForEvent).toHaveBeenCalledWith(3, {
      full_name: "Andy Attendee",
      email: "andy@example.com",
      accessibility_requirements: "Wheelchair space",
    });
  });

  it("SCRUM-21 AC2 - names each missing item the server reports", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue(OPEN);
    vi.mocked(registerForEvent).mockRejectedValue(
      new ApiError(
        400,
        { detail: "Some registration information is missing.", missing: ["full_name", "email"] },
        "Bad Request",
      ),
    );
    const user = userEvent.setup();
    wrap(<RegisterPanel eventId={3} />);

    await user.click(await screen.findByRole("button", { name: "Register" }));
    await user.clear(screen.getByLabelText("Full name"));
    await user.click(screen.getByRole("button", { name: "Confirm registration" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Some registration information is missing.");
    expect(alert).toHaveTextContent("Full name");
    expect(alert).toHaveTextContent("Email address");
  });

  it("SCRUM-21 AC3 - an existing registration is shown instead of the form", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue({
      ...OPEN,
      my_status: "REGISTERED",
      my_registration: 9,
    });
    wrap(<RegisterPanel eventId={3} />);

    expect(await screen.findByText("You are registered for this event.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
  });

  it.each([
    ["full", "This event is full."],
    ["not_open", "Registration opens on 10 Dec 2026 09:00."],
    ["closed", "Registration closed on 01 Dec 2026 09:00."],
  ])("SCRUM-81 - %s registration shows why and offers no Register button", async (code, reason) => {
    vi.mocked(getRegistrationSummary).mockResolvedValue({
      ...OPEN,
      open: false,
      reason,
      reason_code: code,
    });
    wrap(<RegisterPanel eventId={3} />);

    expect(await screen.findByText(reason)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
  });
});

describe("MyRegistrations (SCRUM-21 AC4)", () => {
  it("shows each registration with its status and confirmed date, time and venue", async () => {
    vi.mocked(listMyRegistrations).mockResolvedValue([
      {
        id: 1,
        event: 3,
        event_name: "Harbour Gala",
        status: "REGISTERED",
        status_label: "Registered",
        full_name: "Andy Attendee",
        email: "andy@example.com",
        accessibility_requirements: "",
        registered_at: "2026-11-03T01:00:00Z",
        withdrawn_at: null,
        event_details: {
          id: 3,
          name: "Harbour Gala",
          status: "CONFIRMED",
          status_label: "Confirmed",
          starts_at: "2026-12-12T01:00:00Z",
          ends_at: "2026-12-12T07:00:00Z",
          venues: [
            {
              venue: "Harbour Hall",
              location: "Level 2, Marina Wing",
              starts_at: "2026-12-12T01:00:00Z",
              ends_at: "2026-12-12T07:00:00Z",
            },
          ],
        },
      },
    ]);
    wrap(<MyRegistrations />);

    expect(await screen.findByText("Harbour Gala")).toBeInTheDocument();
    expect(screen.getByText("Registered · Confirmed")).toBeInTheDocument();
    expect(screen.getByText("Harbour Hall, Level 2, Marina Wing")).toBeInTheDocument();
    const start = new Date("2026-12-12T01:00:00Z").toLocaleString("en-SG");
    expect(screen.getByText(new RegExp(start.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument();
  });

  it("has an empty state", async () => {
    vi.mocked(listMyRegistrations).mockResolvedValue([]);
    wrap(<MyRegistrations />);

    expect(
      await screen.findByText("You have not registered for any events yet."),
    ).toBeInTheDocument();
  });
});

describe("RegistrationPolicyForm (SCRUM-81)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("saves the organiser's capacity and shows the server's refusal", async () => {
    vi.mocked(getRegistrationPolicy).mockResolvedValue({
      event: 3,
      enabled: false,
      opens_at: null,
      closes_at: null,
      manually_closed: false,
      capacity: null,
      registered: 2,
      remaining: null,
      full: false,
      open: false,
      waitlist_enabled: false,
      waiting: 0,
    });
    vi.mocked(updateRegistrationPolicy).mockRejectedValue(
      new ApiError(
        400,
        { capacity: ["2 people are already registered; the capacity cannot be lower."] },
        "Bad Request",
      ),
    );
    const user = userEvent.setup();
    wrap(<RegistrationPolicyForm eventId={3} />);

    expect(await screen.findByText(/2 registered/)).toBeInTheDocument();
    await user.click(screen.getByLabelText("Allow attendees to register"));
    await user.type(screen.getByLabelText("Registration capacity"), "1");
    await user.click(screen.getByRole("button", { name: "Save registration settings" }));

    expect(updateRegistrationPolicy).toHaveBeenCalledWith(3, {
      enabled: true,
      opens_at: null,
      closes_at: null,
      capacity: 1,
      manually_closed: false,
      waitlist_enabled: false,
    });
    expect(
      await screen.findByText("2 people are already registered; the capacity cannot be lower."),
    ).toBeInTheDocument();
  });
});

it("SCRUM-87 AC6: my registrations retain both session names and their independent periods", async () => {
  vi.mocked(listMyRegistrations).mockResolvedValue([{ id: 87, event: 87, event_name: "Parallel conference",
    status: "REGISTERED", status_label: "Registered", full_name: "Andy", email: "andy@example.com",
    accessibility_requirements: "", registered_at: "2026-11-04T01:00:00Z", withdrawn_at: null,
    event_details: { id: 87, name: "Parallel conference", status: "CONFIRMED", status_label: "Confirmed",
      starts_at: "2027-06-08T02:00:00Z", ends_at: "2027-06-08T04:00:00Z", venues: [
        { session_name: "Main programme", venue: "Main Hall", location: "Level 1", starts_at: "2027-06-08T02:00:00Z", ends_at: "2027-06-08T04:00:00Z" },
        { session_name: "Breakout A", venue: "Workshop", location: "Level 2", starts_at: "2027-06-08T03:00:00Z", ends_at: "2027-06-08T04:00:00Z" },
      ] },
  }]);
  wrap(<MyRegistrations />);
  expect(await screen.findByText("Main programme:")).toBeVisible();
  expect(screen.getByText("Breakout A:")).toBeVisible();
  expect(screen.getByText("Main Hall, Level 1")).toBeVisible();
  expect(screen.getByText("Workshop, Level 2")).toBeVisible();
});

const AUDIT_POLICY = {
  event: 3, enabled: false, opens_at: "2027-01-04T01:00:00Z",
  closes_at: "2027-01-04T03:00:00Z", manually_closed: false,
  capacity: 2, registered: 2, remaining: 0, full: true, open: false,
  waitlist_enabled: false, waiting: 2,
};

describe("SCRUM-81 registration settings regression gaps", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getRegistrationPolicy).mockResolvedValue(AUDIT_POLICY);
  });

  it("saves the window, capacity, manual close and waiting-list settings and persists the server response", async () => {
    const user = userEvent.setup();
    const opens = "2027-01-04T09:30";
    const closes = "2027-01-04T11:30";
    vi.mocked(updateRegistrationPolicy).mockResolvedValue({
      ...AUDIT_POLICY, enabled: true, manually_closed: true, waitlist_enabled: true,
      opens_at: new Date(opens).toISOString(), closes_at: new Date(closes).toISOString(),
      capacity: 12, full: false, remaining: 10,
    });
    wrap(<RegistrationPolicyForm eventId={3} />);
    expect(await screen.findByText(/2 on the waiting list/)).toHaveTextContent("Full");
    expect(new Date((screen.getByLabelText("Registration opens") as HTMLInputElement).value).getTime()).toBe(Date.parse(AUDIT_POLICY.opens_at));
    await user.click(screen.getByLabelText("Allow attendees to register"));
    await user.clear(screen.getByLabelText("Registration capacity"));
    await user.type(screen.getByLabelText("Registration capacity"), "12");
    await user.click(screen.getByLabelText("Close registration now"));
    await user.click(screen.getByLabelText("Offer a waiting list when the event is full"));
    await user.clear(screen.getByLabelText("Registration opens"));
    await user.type(screen.getByLabelText("Registration opens"), opens);
    await user.clear(screen.getByLabelText("Registration closes"));
    await user.type(screen.getByLabelText("Registration closes"), closes);
    await user.click(screen.getByRole("button", { name: "Save registration settings" }));
    expect(updateRegistrationPolicy).toHaveBeenCalledWith(3, {
      enabled: true, opens_at: new Date(opens).toISOString(),
      closes_at: new Date(closes).toISOString(), capacity: 12,
      manually_closed: true, waitlist_enabled: true,
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Registration settings saved.");
    expect(screen.getByLabelText("Registration capacity")).toHaveValue(12);
    expect(screen.getByText(/2 registered/)).toHaveTextContent("of 12");
  });

  it.each([
    ["opening time", new ApiError(400, { opens_at: ["Registration must open before it closes."] }, "Bad request"), "Registration must open before it closes."],
    ["closing time", new ApiError(400, { closes_at: ["Close registration before the event starts."] }, "Bad request"), "Close registration before the event starts."],
    ["server refusal", new ApiError(409, { detail: "The event has been cancelled." }, "The event has been cancelled."), "The event has been cancelled."],
    ["network failure", new Error("connection lost"), "The settings could not be saved."],
  ])("shows the %s reason without claiming settings were saved", async (_label, error, message) => {
    vi.mocked(updateRegistrationPolicy).mockRejectedValue(error);
    wrap(<RegistrationPolicyForm eventId={3} />);
    await screen.findByLabelText("Allow attendees to register");
    await userEvent.click(screen.getByRole("button", { name: "Save registration settings" }));
    expect(await screen.findByText(String(message))).toBeVisible();
    expect(screen.queryByText("Registration settings saved.")).not.toBeInTheDocument();
  });

  it("shows a failed policy load and lets the organiser retry", async () => {
    vi.mocked(getRegistrationPolicy).mockRejectedValueOnce(new Error("temporary outage"));
    wrap(<RegistrationPolicyForm eventId={3} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("could not load");
    expect(screen.queryByRole("button", { name: "Save registration settings" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByLabelText("Allow attendees to register")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
