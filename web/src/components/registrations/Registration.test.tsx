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
    vi.mocked(getRegistrationSummary).mockResolvedValue({ ...OPEN, my_status: "REGISTERED" });
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
    });
    expect(
      await screen.findByText("2 people are already registered; the capacity cannot be lower."),
    ).toBeInTheDocument();
  });
});
