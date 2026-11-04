import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getRegistrationSummary,
  getWithdrawalSummary,
  joinWaitlist,
  registerForEvent,
  withdrawRegistration,
  type RegistrationSummary,
  type WithdrawalSummary,
} from "../../api/registrations";
import { RegisterPanel } from "./RegisterPanel";

vi.mock("../../api/registrations", () => ({
  getRegistrationSummary: vi.fn(),
  registerForEvent: vi.fn(),
  joinWaitlist: vi.fn(),
  getWithdrawalSummary: vi.fn(),
  withdrawRegistration: vi.fn(),
}));

vi.mock("../../auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 7, email: "andy@example.com", first_name: "Andy", last_name: "Attendee" },
  }),
}));

const BASE: RegistrationSummary = {
  enabled: true,
  open: true,
  reason: "",
  reason_code: "",
  opens_at: null,
  closes_at: null,
  capacity: 2,
  remaining: 1,
  my_status: null,
  my_registration: null,
  waitlist_offered: false,
  waitlist_position: null,
  waiting: 0,
};

const FULL: RegistrationSummary = {
  ...BASE,
  open: false,
  reason: "This event is full.",
  reason_code: "full",
  remaining: 0,
  waitlist_offered: true,
  waiting: 2,
};

const REGISTERED: RegistrationSummary = { ...BASE, my_status: "REGISTERED", my_registration: 9 };

const SUMMARY: WithdrawalSummary = {
  registration: 9,
  event: 3,
  event_name: "Harbour Gala",
  starts_at: "2026-12-12T01:00:00Z",
  ends_at: "2026-12-12T07:00:00Z",
  status: "REGISTERED",
  releases_place: true,
  can_withdraw: true,
  reason: "",
};

function wrap(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

describe("Withdrawing (SCRUM-14)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1 - shows a summary, and only the confirmation withdraws", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue(REGISTERED);
    vi.mocked(getWithdrawalSummary).mockResolvedValue(SUMMARY);
    vi.mocked(withdrawRegistration).mockResolvedValue({
      detail: "You have withdrawn.",
    } as Awaited<ReturnType<typeof withdrawRegistration>>);
    const user = userEvent.setup();
    wrap(<RegisterPanel eventId={3} />);

    await user.click(await screen.findByRole("button", { name: "Withdraw" }));
    expect(await screen.findByText(/Your place will be released/)).toBeInTheDocument();
    expect(withdrawRegistration).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm withdrawal" }));

    expect(withdrawRegistration).toHaveBeenCalledWith(9);
  });

  it("AC4 - an event that has taken place shows the reason and no confirm button", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue(REGISTERED);
    vi.mocked(getWithdrawalSummary).mockResolvedValue({
      ...SUMMARY,
      can_withdraw: false,
      reason: "This event has already taken place, so you cannot withdraw.",
    });
    const user = userEvent.setup();
    wrap(<RegisterPanel eventId={3} />);

    await user.click(await screen.findByRole("button", { name: "Withdraw" }));

    expect(await screen.findByText(/already taken place/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm withdrawal" })).not.toBeInTheDocument();
  });

  it("keeping the place sends nothing", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue(REGISTERED);
    vi.mocked(getWithdrawalSummary).mockResolvedValue(SUMMARY);
    const user = userEvent.setup();
    wrap(<RegisterPanel eventId={3} />);

    await user.click(await screen.findByRole("button", { name: "Withdraw" }));
    await user.click(await screen.findByRole("button", { name: "Keep my place" }));

    expect(withdrawRegistration).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Withdraw" })).toBeInTheDocument();
  });
});

describe("Waiting list (SCRUM-19)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1 - a full event offers the waiting list and joins it", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue(FULL);
    vi.mocked(joinWaitlist).mockResolvedValue({
      detail: "You are number 3 on the waiting list.",
    } as Awaited<ReturnType<typeof joinWaitlist>>);
    const user = userEvent.setup();
    wrap(<RegisterPanel eventId={3} />);

    expect(await screen.findByText(/2 people are/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Join the waiting list" }));
    await user.click(screen.getByRole("button", { name: "Join waiting list" }));

    expect(joinWaitlist).toHaveBeenCalledWith(3, {
      full_name: "Andy Attendee",
      email: "andy@example.com",
      accessibility_requirements: "",
    });
    expect(registerForEvent).not.toHaveBeenCalled();
  });

  it("AC2 - with places available, only Register is offered", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue(BASE);
    wrap(<RegisterPanel eventId={3} />);

    expect(await screen.findByRole("button", { name: "Register" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /waiting list/ })).not.toBeInTheDocument();
  });

  it("AC3 - shows my position on the waiting list and lets me leave it", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue({
      ...FULL,
      waitlist_offered: false,
      my_status: "WAITLISTED",
      my_registration: 12,
      waitlist_position: 2,
    });
    wrap(<RegisterPanel eventId={3} />);

    expect(await screen.findByText(/number 2 on the waiting list/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave the waiting list" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Join the waiting list" })).not.toBeInTheDocument();
  });

  it("AC5 - once a place opens, a waiting attendee can register", async () => {
    vi.mocked(getRegistrationSummary).mockResolvedValue({
      ...BASE,
      my_status: "WAITLISTED",
      my_registration: 12,
      waitlist_position: 1,
    });
    wrap(<RegisterPanel eventId={3} />);

    expect(await screen.findByRole("button", { name: "Register" })).toBeInTheDocument();
    expect(screen.getByText(/number 1 on the waiting list/)).toBeInTheDocument();
  });
});
