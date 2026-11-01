import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listBookingInbox } from "../api/venueBookings";
import type { VenueBooking } from "../types";
import { VenueBookingInbox } from "./VenueBookingInbox";

vi.mock("../api/venueBookings", () => ({
  listBookingInbox: vi.fn(),
  approveBooking: vi.fn(),
  rejectBooking: vi.fn(),
}));

const REQUEST = {
  id: 1,
  event: 9,
  event_name: "Partner Summit",
  organisation_name: "Acme Pte Ltd",
  venue_name: "Harbour Hall",
  starts_at: "2027-03-01T02:00:00Z",
  ends_at: "2027-03-01T04:00:00Z",
  attendance: 60,
  layout_name: "Theatre",
  required_facilities: ["Video conferencing"],
  wheelchair_access_required: true,
  accessibility_notes: "Two wheelchair users.",
  status: "PENDING",
  status_label: "Pending",
  requested_by_name: "Cora Coordinator",
  requested_at: "2026-11-01T01:00:00Z",
} as unknown as VenueBooking;

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <VenueBookingInbox />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("VenueBookingInbox (SCRUM-11 AC4)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the pending requests with their requirements", async () => {
    vi.mocked(listBookingInbox).mockResolvedValue([REQUEST]);

    renderPage();

    expect(await screen.findByText("Harbour Hall")).toBeInTheDocument();
    expect(listBookingInbox).toHaveBeenCalledWith("PENDING");
    expect(screen.getByText("Partner Summit")).toBeInTheDocument();
    expect(screen.getByText("Acme Pte Ltd")).toBeInTheDocument();
    expect(screen.getByText(/60 people · Theatre/)).toBeInTheDocument();
    expect(screen.getByText("Wheelchair access required")).toBeInTheDocument();
    expect(screen.getByText("Cora Coordinator")).toBeInTheDocument();
    // SCRUM-72 - each pending request can be decided from the inbox.
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
  });

  it("can show every request, and has a clear empty state", async () => {
    vi.mocked(listBookingInbox).mockResolvedValue([]);
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("No booking requests to show.")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Show requests"), "");
    expect(listBookingInbox).toHaveBeenLastCalledWith(undefined);
  });
});
