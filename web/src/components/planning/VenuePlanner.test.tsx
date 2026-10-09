import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  acceptSuggestion,
  addToShortlist,
  compareAvailability,
  fetchBookings,
  fetchShortlist,
  fetchSuitability,
  removeFromShortlist,
  requestBooking,
  searchVenues,
  withdrawBooking,
  type VenueBooking,
} from "../../api/planning";
import { planningEvent } from "./fixtures";
import { VenuePlanner } from "./VenuePlanner";

vi.mock("../../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/planning")>()),
  searchVenues: vi.fn(),
  fetchSuitability: vi.fn(),
  compareAvailability: vi.fn(),
  fetchShortlist: vi.fn(),
  addToShortlist: vi.fn(),
  removeFromShortlist: vi.fn(),
  fetchBookings: vi.fn(),
  requestBooking: vi.fn(),
  withdrawBooking: vi.fn(),
  acceptSuggestion: vi.fn(),
}));

const hallA = {
  id: 3,
  name: "Hall A",
  location: "Level 2",
  capacity: 200,
  facilities: ["Projector"],
  layout_labels: ["Theatre"],
  wheelchair_access: true,
  checks: [{ criterion: "Capacity", matches: true }],
};

function booking(overrides: Partial<VenueBooking> = {}): VenueBooking {
  return {
    id: 11,
    event: 9,
    event_name: "Partner Summit",
    venue: 3,
    venue_name: "Hall A",
    start: "2026-11-20T01:00:00Z",
    end: "2026-11-20T07:00:00Z",
    attendance: 120,
    layout: "THEATRE",
    layout_label: "Theatre",
    facilities: [],
    accessibility_needs: "",
    notes: "",
    status: "PENDING",
    status_display: "Pending review",
    requested_by_name: "Cora Coordinator",
    decided_by_name: null,
    decided_at: null,
    rejection_reason: "",
    suggested_venue: null,
    suggested_venue_name: null,
    suggested_start: null,
    suggested_end: null,
    suggestion_note: "",
    withdrawn_by_name: null,
    withdrawn_at: null,
    review_required: false,
    review_reason: "",
    review_start: null,
    review_end: null,
    review_outcome: "",
    conflicts: [],
    created_at: "2026-10-01T01:00:00Z",
    ...overrides,
  };
}

function renderPlanner() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VenuePlanner event={planningEvent()} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchShortlist).mockResolvedValue([]);
  vi.mocked(fetchBookings).mockResolvedValue([]);
});

describe("SCRUM-64 search venues against the event's needs", () => {
  it("AC1: searches with the event's needs and period prefilled", async () => {
    vi.mocked(searchVenues).mockResolvedValue({ results: [hallA], message: "" });

    renderPlanner();
    expect(screen.getByLabelText("Attendance")).toHaveValue(120);
    expect(screen.getByLabelText("Wheelchair access")).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));

    expect(searchVenues).toHaveBeenCalledWith(
      expect.objectContaining({
        attendance: 120,
        layout: "THEATRE",
        wheelchair_access: true,
        start: "2026-11-20T01:00:00Z",
        end: "2026-11-20T07:00:00Z",
      }),
    );
    expect(await screen.findByText("Hall A")).toBeInTheDocument();
  });

  it("AC3: says when no venue matches", async () => {
    vi.mocked(searchVenues).mockResolvedValue({
      results: [],
      message: "No venue matched every requirement you entered.",
    });

    renderPlanner();
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));

    expect(
      await screen.findByText("No venue matched every requirement you entered."),
    ).toBeInTheDocument();
  });

  it("AC4: shows the API's validation error", async () => {
    vi.mocked(searchVenues).mockRejectedValue(
      new ApiError(400, { attendance: ["Enter a whole number of people."] }, "Something went wrong."),
    );

    renderPlanner();
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));

    expect(await screen.findByText("Enter a whole number of people.")).toBeInTheDocument();
  });
});

describe("SCRUM-71 venue suitability", () => {
  it("AC2: shows why a venue is unsuitable", async () => {
    vi.mocked(searchVenues).mockResolvedValue({ results: [hallA], message: "" });
    vi.mocked(fetchSuitability).mockResolvedValue({
      venue: 3,
      venue_name: "Hall A",
      event: 9,
      suitable: false,
      checks: [],
      warnings: ["Expected attendance of 120 exceeds the venue's capacity of 100."],
    });

    renderPlanner();
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    await userEvent.click(await screen.findByRole("button", { name: "Check suitability of Hall A" }));

    expect(fetchSuitability).toHaveBeenCalledWith(3, 9);
    expect(
      await screen.findByText("Expected attendance of 120 exceeds the venue's capacity of 100."),
    ).toBeInTheDocument();
  });

  it("AC1: confirms a suitable venue", async () => {
    vi.mocked(searchVenues).mockResolvedValue({ results: [hallA], message: "" });
    vi.mocked(fetchSuitability).mockResolvedValue({
      venue: 3,
      venue_name: "Hall A",
      event: 9,
      suitable: true,
      checks: [],
      warnings: [],
    });

    renderPlanner();
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    await userEvent.click(await screen.findByRole("button", { name: "Check suitability of Hall A" }));

    expect(await screen.findByText("Suitable for this event.")).toBeInTheDocument();
  });
});

describe("SCRUM-62 compare venue availability for the event period", () => {
  it("AC1: compares every venue for the event's period", async () => {
    vi.mocked(compareAvailability).mockResolvedValue({
      start: "2026-11-20T01:00:00Z",
      end: "2026-11-20T07:00:00Z",
      none_available: false,
      message: "",
      venues: [
        {
          venue: 3,
          venue_name: "Hall A",
          capacity: 200,
          overall: "AVAILABLE",
          overall_label: "Available for the whole period",
          segments: [],
        },
        {
          venue: 4,
          venue_name: "Room B",
          capacity: 40,
          overall: "PARTIAL",
          overall_label: "Partly available",
          segments: [
            {
              start: "2026-11-20T01:00:00Z",
              end: "2026-11-20T03:00:00Z",
              status: "CONFIRMED",
              label: "Confirmed",
              detail: "Confirmed booking",
              event: 1,
              event_name: "Other",
            },
          ],
        },
      ],
    });

    renderPlanner();
    await userEvent.click(screen.getByRole("button", { name: "Compare availability" }));

    expect(compareAvailability).toHaveBeenCalledWith(
      "2026-11-20T01:00:00Z",
      "2026-11-20T07:00:00Z",
    );
    expect(await screen.findByText("Available for the whole period")).toBeInTheDocument();
    expect(screen.getByText("Partly available")).toBeInTheDocument();
    expect(screen.getByText(/Confirmed \(Confirmed booking\)/)).toBeInTheDocument();
  });

  it("AC3: says when no venue is available", async () => {
    vi.mocked(compareAvailability).mockResolvedValue({
      start: "",
      end: "",
      none_available: true,
      message: "No venue is available at any time in this period.",
      venues: [],
    });

    renderPlanner();
    await userEvent.click(screen.getByRole("button", { name: "Compare availability" }));

    expect(
      await screen.findByText("No venue is available at any time in this period."),
    ).toBeInTheDocument();
  });
});

describe("SCRUM-68 shortlist venues", () => {
  it("AC1: adds a search result to the shortlist", async () => {
    vi.mocked(searchVenues).mockResolvedValue({ results: [hallA], message: "" });
    vi.mocked(addToShortlist).mockResolvedValue({} as never);

    renderPlanner();
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    await userEvent.click(await screen.findByRole("button", { name: "Shortlist Hall A" }));

    expect(addToShortlist).toHaveBeenCalledWith(9, 3);
    expect(fetchShortlist).toHaveBeenCalledTimes(2);
  });

  it("AC3/AC4: shows satisfied and unsatisfied criteria and 'no longer available'", async () => {
    vi.mocked(fetchShortlist).mockResolvedValue([
      {
        venue: 4,
        venue_name: "Room B",
        capacity: 40,
        location: "Level 1",
        satisfied: ["Operational status", "Room layout"],
        not_satisfied: [
          {
            criterion: "Capacity",
            reason: "Expected attendance of 120 exceeds the venue's capacity of 40.",
          },
        ],
        no_longer_available: true,
        added_at: "2026-10-01T01:00:00Z",
      },
    ]);
    vi.mocked(removeFromShortlist).mockResolvedValue(undefined);

    renderPlanner();

    expect(await screen.findByText("No longer available")).toBeInTheDocument();
    expect(screen.getByText("Satisfied: Operational status, Room layout")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Not satisfied – Capacity: Expected attendance of 120 exceeds the venue's capacity of 40.",
      ),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Remove Room B from shortlist" }));
    expect(removeFromShortlist).toHaveBeenCalledWith(9, 4);
  });

  it("AC5: shows the API's refusal", async () => {
    vi.mocked(searchVenues).mockResolvedValue({ results: [hallA], message: "" });
    vi.mocked(addToShortlist).mockRejectedValue(
      new ApiError(403, null, "Only the coordinator assigned to this event can do this."),
    );

    renderPlanner();
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    await userEvent.click(await screen.findByRole("button", { name: "Shortlist Hall A" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only the coordinator assigned to this event can do this.",
    );
  });
});

describe("SCRUM-11 request a venue booking", () => {
  async function openForm() {
    vi.mocked(searchVenues).mockResolvedValue({ results: [hallA], message: "" });
    renderPlanner();
    await userEvent.click(screen.getByRole("button", { name: "Search venues" }));
    await userEvent.click(await screen.findByRole("button", { name: "Request Hall A" }));
  }

  it("AC1: sends a request prefilled from the event", async () => {
    vi.mocked(requestBooking).mockResolvedValue(booking());

    await openForm();
    expect(screen.getByLabelText("Booking start")).not.toHaveValue("");
    await userEvent.type(screen.getByLabelText("Notes for Venue Staff"), "Early access");
    await userEvent.click(screen.getByRole("button", { name: "Send booking request" }));

    expect(requestBooking).toHaveBeenCalledWith({
      event: 9,
      venue: 3,
      start: "2026-11-20T01:00:00.000Z",
      end: "2026-11-20T07:00:00.000Z",
      attendance: 120,
      layout: "THEATRE",
      facilities: [],
      accessibility_needs: "Wheelchair access",
      notes: "Early access",
    });
    expect(fetchBookings).toHaveBeenCalledTimes(2);
  });

  it("AC2: missing or invalid items are shown and not sent", async () => {
    await openForm();
    await userEvent.clear(screen.getByLabelText("Attendance", { selector: "#booking-attendance" }));
    await userEvent.clear(screen.getByLabelText("Booking end"));
    await userEvent.click(screen.getByRole("button", { name: "Send booking request" }));

    expect(screen.getByText("Enter the expected attendance.")).toBeInTheDocument();
    expect(screen.getByText("Enter the date and end time.")).toBeInTheDocument();
    expect(requestBooking).not.toHaveBeenCalled();
  });

  it("AC3: shows each unmet requirement when the venue does not suit", async () => {
    vi.mocked(requestBooking).mockRejectedValue(
      new ApiError(
        400,
        {
          detail: "Hall A does not meet this event's requirements.",
          unmet: ["The venue does not support the Theatre layout."],
        },
        "Hall A does not meet this event's requirements.",
      ),
    );

    await openForm();
    await userEvent.click(screen.getByRole("button", { name: "Send booking request" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Hall A does not meet this event's requirements.");
    expect(alert).toHaveTextContent("The venue does not support the Theatre layout.");
  });

  it("AC4: shows the API's field errors and a blocked venue", async () => {
    vi.mocked(requestBooking).mockRejectedValueOnce(
      new ApiError(400, { start: ["The booking must start in the future."] }, "Something went wrong."),
    );
    vi.mocked(requestBooking).mockRejectedValueOnce(
      new ApiError(409, { detail: "Hall A is blocked during this period: Renovation." }, "Hall A is blocked during this period: Renovation."),
    );

    await openForm();
    await userEvent.click(screen.getByRole("button", { name: "Send booking request" }));
    expect(await screen.findByText("The booking must start in the future.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Send booking request" }));
    expect(
      await screen.findByText("Hall A is blocked during this period: Renovation."),
    ).toBeInTheDocument();
  });
});

describe("SCRUM-69 / 73 / 66 / 70 bookings with conflicts, review and suggestions", () => {
  it("shows status, conflicts and the review flag with its reason and period", async () => {
    vi.mocked(fetchBookings).mockResolvedValue([
      booking({
        conflicts: [
          {
            booking: 20,
            event: 30,
            event_name: "Board Meeting",
            start: "2026-11-20T02:00:00Z",
            end: "2026-11-20T03:00:00Z",
          },
        ],
      }),
      booking({
        id: 12,
        venue_name: "Room B",
        status: "APPROVED",
        status_display: "Approved",
        review_required: true,
        review_reason: "The event's start time changed.",
        review_start: "2026-11-21T01:00:00Z",
        review_end: "2026-11-21T07:00:00Z",
      }),
    ]);

    renderPlanner();

    expect(await screen.findByText(/Pending review/)).toBeInTheDocument();
    expect(screen.getByText(/Board Meeting/)).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("The event's start time changed.")).toBeInTheDocument();
    expect(screen.getByText(/Review period:/)).toBeInTheDocument();
  });

  it("SCRUM-73: shows the rejection reason and accepts the suggestion", async () => {
    vi.mocked(fetchBookings).mockResolvedValue([
      booking({
        status: "REJECTED",
        status_display: "Rejected",
        rejection_reason: "Hall A is under maintenance.",
        suggested_venue: 4,
        suggested_venue_name: "Room C",
        suggestion_note: "Same floor",
      }),
    ]);
    vi.mocked(acceptSuggestion).mockResolvedValue(booking({ id: 13 }));

    renderPlanner();

    expect(await screen.findByText("Reason: Hall A is under maintenance.")).toBeInTheDocument();
    expect(screen.getByText(/Suggested: Room C/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept suggestion" }));
    expect(acceptSuggestion).toHaveBeenCalledWith(11);
  });

  it("SCRUM-67: withdraws a pending booking directly", async () => {
    vi.mocked(fetchBookings).mockResolvedValue([booking()]);
    vi.mocked(withdrawBooking).mockResolvedValue(booking({ status: "WITHDRAWN" }));

    renderPlanner();
    await userEvent.click(await screen.findByRole("button", { name: "Withdraw Hall A" }));

    expect(withdrawBooking).toHaveBeenCalledWith(11, false);
  });

  it("SCRUM-67: an approved booking needs a confirm step before withdrawal", async () => {
    vi.mocked(fetchBookings).mockResolvedValue([
      booking({ status: "APPROVED", status_display: "Approved" }),
    ]);
    vi.mocked(withdrawBooking)
      .mockRejectedValueOnce(
        new ApiError(
          409,
          { detail: "Hall A is confirmed for this event. Confirm to continue.", warning: true },
          "Hall A is confirmed for this event. Confirm to continue.",
        ),
      )
      .mockResolvedValueOnce(booking({ status: "WITHDRAWN" }));

    renderPlanner();
    await userEvent.click(await screen.findByRole("button", { name: "Withdraw Hall A" }));

    const warning = await screen.findByRole("alert");
    expect(warning).toHaveTextContent("Hall A is confirmed for this event.");
    await userEvent.click(within(warning).getByRole("button", { name: "Confirm withdrawal" }));

    expect(withdrawBooking).toHaveBeenLastCalledWith(11, true);
  });

  it("SCRUM-67: shows a refusal", async () => {
    vi.mocked(fetchBookings).mockResolvedValue([booking()]);
    vi.mocked(withdrawBooking).mockRejectedValue(
      new ApiError(403, null, "Only the coordinator assigned to this event can do this."),
    );

    renderPlanner();
    await userEvent.click(await screen.findByRole("button", { name: "Withdraw Hall A" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only the coordinator assigned to this event can do this.",
    );
  });
});
