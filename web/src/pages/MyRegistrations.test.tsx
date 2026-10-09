import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listMyRegistrations, withdrawRegistration, type MyRegistration } from "../api/attendee";
import { ApiError } from "../api/client";
import { MyRegistrations } from "./MyRegistrations";

vi.mock("../api/attendee", () => ({
  listMyRegistrations: vi.fn(),
  withdrawRegistration: vi.fn(),
}));

function mine(overrides: Partial<MyRegistration> = {}): MyRegistration {
  return {
    id: 9,
    event: 42,
    event_name: "Regional Partner Conference",
    event_start: "2026-10-20T01:00:00Z",
    event_end: "2026-10-20T07:00:00Z",
    event_status: "Confirmed",
    venues: [
      { name: "Harbour Hall", location: "Level 2", start: "2026-10-20T01:00:00Z", end: "2026-10-20T07:00:00Z" },
    ],
    full_name: "Ann Attendee",
    email: "ann@example.com",
    accessibility_needs: "",
    status: "REGISTERED",
    status_display: "Registered",
    registered_at: "2026-09-28T01:00:00Z",
    waitlisted_at: null,
    place_offered_at: null,
    withdrawn_at: null,
    ...overrides,
  };
}

const summaryError = new ApiError(
  409,
  {
    detail: "Confirm to withdraw.",
    summary: {
      event: "Regional Partner Conference",
      start: "2026-10-20T01:00:00Z",
      end: "2026-10-20T07:00:00Z",
      status: "Registered",
    },
  },
  "Confirm to withdraw.",
);

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MyRegistrations />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SCRUM-21 AC4 my registrations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC4: lists my registrations with status, date and time, and venue", async () => {
    vi.mocked(listMyRegistrations).mockResolvedValue([mine()]);
    renderPage();
    expect(await screen.findByText("Regional Partner Conference")).toBeInTheDocument();
    expect(screen.getByText("Registered")).toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(new Date("2026-10-20T01:00:00Z").toLocaleString("en-SG"))),
    ).toBeInTheDocument();
    expect(screen.getByText("Harbour Hall, Level 2")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    vi.mocked(listMyRegistrations).mockResolvedValue([]);
    renderPage();
    expect(
      await screen.findByText("You have not registered for any events yet."),
    ).toBeInTheDocument();
  });
});

describe("SCRUM-14 withdraw from an event", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1/AC2: shows the summary, then withdraws only after confirming", async () => {
    vi.mocked(listMyRegistrations).mockResolvedValue([mine()]);
    vi.mocked(withdrawRegistration)
      .mockRejectedValueOnce(summaryError)
      .mockResolvedValueOnce(mine({ status: "WITHDRAWN", status_display: "Withdrawn" }));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Withdraw" }));
    expect(withdrawRegistration).toHaveBeenCalledWith(9, false);
    expect(
      await screen.findByText("Withdraw from Regional Partner Conference?"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Current status: Registered/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm withdrawal" }));
    expect(withdrawRegistration).toHaveBeenLastCalledWith(9, true);
  });

  it("AC2: keeping my place sends nothing more", async () => {
    vi.mocked(listMyRegistrations).mockResolvedValue([mine()]);
    vi.mocked(withdrawRegistration).mockRejectedValueOnce(summaryError);
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Withdraw" }));
    await userEvent.click(await screen.findByRole("button", { name: "Keep my place" }));
    expect(withdrawRegistration).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Withdraw from/)).not.toBeInTheDocument();
  });

  it("AC4: shows the refusal when the event has already taken place", async () => {
    vi.mocked(listMyRegistrations).mockResolvedValue([mine()]);
    const detail = "This event has already taken place, so the registration cannot be withdrawn.";
    vi.mocked(withdrawRegistration).mockRejectedValue(new ApiError(409, { detail }, detail));
    renderPage();
    await userEvent.click(await screen.findByRole("button", { name: "Withdraw" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(detail);
  });

  it("does not offer to withdraw a withdrawn registration", async () => {
    vi.mocked(listMyRegistrations).mockResolvedValue([
      mine({ status: "WITHDRAWN", status_display: "Withdrawn" }),
    ]);
    renderPage();
    expect(await screen.findByText("Withdrawn")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Withdraw" })).not.toBeInTheDocument();
  });
});
