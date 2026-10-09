import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  approveBooking,
  listBookings,
  listVenues,
  rejectBooking,
  reviewBooking,
} from "../../api/venues";
import type { Venue, VenueBooking } from "../../api/venues";
import { VenueBookingInbox } from "./VenueBookingInbox";

vi.mock("../../api/venues", () => ({
  listBookings: vi.fn(),
  listVenues: vi.fn(),
  approveBooking: vi.fn(),
  rejectBooking: vi.fn(),
  reviewBooking: vi.fn(),
}));

function booking(overrides: Partial<VenueBooking> = {}): VenueBooking {
  return {
    id: 5,
    event: 9,
    event_name: "Partner Summit",
    event_status: "PLANNING",
    venue: 3,
    venue_name: "Harbour Hall",
    start: "2026-10-20T01:00:00Z",
    end: "2026-10-20T07:00:00Z",
    attendance: 120,
    layout: "THEATRE",
    layout_label: "Theatre",
    facilities: ["Projector"],
    accessibility_needs: "Wheelchair access",
    notes: "Stage needed",
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
    reviewed_by_name: null,
    reviewed_at: null,
    review_outcome: "",
    conflicts: [],
    created_at: "2026-10-01T01:00:00Z",
    ...overrides,
  };
}

const garden = { id: 4, name: "Garden Room" } as Venue;
const fmt = (value: string) => new Date(value).toLocaleString("en-SG");

function setup(pending: VenueBooking[], approved: VenueBooking[] = []) {
  vi.mocked(listBookings).mockImplementation(async (status) =>
    status === "PENDING" ? pending : approved,
  );
  vi.mocked(listVenues).mockResolvedValue([garden]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <VenueBookingInbox />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function openReject() {
  await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
  return screen.getByRole("region", { name: "Reject booking request" });
}

beforeEach(() => vi.clearAllMocks());

describe("SCRUM-72 respond to a booking request", () => {
  it("AC1: lists pending requests with the event, period and requirements", async () => {
    setup([booking()]);

    expect(await screen.findByRole("heading", { name: "Partner Summit" })).toBeInTheDocument();
    expect(listBookings).toHaveBeenCalledWith("PENDING");
    expect(
      screen.getByText(`Harbour Hall · ${fmt("2026-10-20T01:00:00Z")} – ${fmt("2026-10-20T07:00:00Z")}`),
    ).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText("Theatre")).toBeInTheDocument();
    expect(screen.getByText("Projector")).toBeInTheDocument();
    expect(screen.getByText("Wheelchair access")).toBeInTheDocument();
    expect(screen.getByText("Stage needed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Venues" })).toBeInTheDocument();
  });

  it("AC2: approves a request and shows who decided and when", async () => {
    setup([booking()]);
    vi.mocked(approveBooking).mockResolvedValue(
      booking({
        status: "APPROVED",
        status_display: "Approved",
        decided_by_name: "Vera Venue",
        decided_at: "2026-10-09T02:00:00Z",
      }),
    );

    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));

    expect(approveBooking).toHaveBeenCalledWith(5);
    expect(await screen.findByRole("status")).toHaveTextContent(
      `Approved by Vera Venue on ${fmt("2026-10-09T02:00:00Z")}`,
    );
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("AC3: rejects with a reason", async () => {
    setup([booking()]);
    vi.mocked(rejectBooking).mockResolvedValue(
      booking({
        status: "REJECTED",
        status_display: "Rejected",
        decided_by_name: "Vera Venue",
        decided_at: "2026-10-09T02:00:00Z",
        rejection_reason: "Hall closed for works.",
      }),
    );

    const form = await openReject();
    await userEvent.type(within(form).getByLabelText("Reason for rejection"), "Hall closed for works.");
    await userEvent.click(within(form).getByRole("button", { name: "Confirm rejection" }));

    expect(rejectBooking).toHaveBeenCalledWith(5, {
      reason: "Hall closed for works.",
      suggested_venue: null,
      suggested_start: null,
      suggested_end: null,
      suggestion_note: "",
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Rejected by Vera Venue on " + fmt("2026-10-09T02:00:00Z") + ". Reason: Hall closed for works.",
    );
  });

  it("AC4: a rejection without a reason is blocked", async () => {
    setup([booking()]);

    const form = await openReject();
    await userEvent.type(within(form).getByLabelText("Reason for rejection"), "   ");
    await userEvent.click(within(form).getByRole("button", { name: "Confirm rejection" }));

    expect(screen.getByText("Enter a reason for the rejection.")).toBeInTheDocument();
    expect(rejectBooking).not.toHaveBeenCalled();
  });

  it("AC5: shows the API's refusal of a decision", async () => {
    setup([booking()]);
    vi.mocked(rejectBooking).mockRejectedValue(
      new ApiError(409, { detail: "This booking request has already been withdrawn." }, "This booking request has already been withdrawn."),
    );

    const form = await openReject();
    await userEvent.type(within(form).getByLabelText("Reason for rejection"), "No.");
    await userEvent.click(within(form).getByRole("button", { name: "Confirm rejection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This booking request has already been withdrawn.",
    );
  });
});

describe("SCRUM-73 suggest an alternative", () => {
  it("AC1: sends a suggested venue, time and note with the rejection", async () => {
    setup([booking()]);
    vi.mocked(rejectBooking).mockResolvedValue(
      booking({ status: "REJECTED", status_display: "Rejected", suggested_venue_name: "Garden Room" }),
    );

    const form = await openReject();
    await userEvent.type(within(form).getByLabelText("Reason for rejection"), "Too small.");
    await userEvent.selectOptions(
      await within(form).findByLabelText("Suggested venue (optional)"),
      await within(form).findByRole("option", { name: "Garden Room" }),
    );
    fireEvent.change(within(form).getByLabelText("Suggested start (optional)"), {
      target: { value: "2026-10-21T09:00" },
    });
    fireEvent.change(within(form).getByLabelText("Suggested end (optional)"), {
      target: { value: "2026-10-21T15:00" },
    });
    await userEvent.type(within(form).getByLabelText("Suggestion note (optional)"), "Next day");
    await userEvent.click(within(form).getByRole("button", { name: "Confirm rejection" }));

    expect(rejectBooking).toHaveBeenCalledWith(5, {
      reason: "Too small.",
      suggested_venue: 4,
      suggested_start: new Date("2026-10-21T09:00").toISOString(),
      suggested_end: new Date("2026-10-21T15:00").toISOString(),
      suggestion_note: "Next day",
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Suggested: Garden Room");
  });

  it("AC4: warns when the suggested venue is taken and lets staff send anyway", async () => {
    setup([booking()]);
    vi.mocked(rejectBooking)
      .mockRejectedValueOnce(
        new ApiError(
          409,
          { detail: "Garden Room is already booked or blocked for that period. Send the suggestion anyway?", warning: true },
          "Garden Room is already booked or blocked for that period. Send the suggestion anyway?",
        ),
      )
      .mockResolvedValueOnce(booking({ status: "REJECTED", status_display: "Rejected" }));

    const form = await openReject();
    await userEvent.type(within(form).getByLabelText("Reason for rejection"), "Too small.");
    await userEvent.selectOptions(
      within(form).getByLabelText("Suggested venue (optional)"),
      await within(form).findByRole("option", { name: "Garden Room" }),
    );
    await userEvent.click(within(form).getByRole("button", { name: "Confirm rejection" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Garden Room is already booked or blocked for that period.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send anyway" }));

    expect(rejectBooking).toHaveBeenLastCalledWith(
      5,
      expect.objectContaining({ suggested_venue: 4, acknowledge_warning: true }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Rejected by");
  });
});

describe("SCRUM-69 booking conflicts", () => {
  const conflict = {
    booking: 7,
    event: 12,
    event_name: "Board Dinner",
    start: "2026-10-20T03:00:00Z",
    end: "2026-10-20T09:00:00Z",
  };

  it("AC1: names the events a request conflicts with", async () => {
    setup([booking({ conflicts: [conflict] })]);

    expect(await screen.findByText("Conflicts with confirmed bookings:")).toBeInTheDocument();
    expect(screen.getByText(/Board Dinner/)).toBeInTheDocument();
  });

  it("AC2: shows why approval is refused and the conflicting bookings", async () => {
    setup([booking()]);
    vi.mocked(approveBooking).mockRejectedValue(
      new ApiError(
        409,
        {
          detail: "This request overlaps a confirmed booking and cannot be approved.",
          conflicts: [conflict],
        },
        "This request overlaps a confirmed booking and cannot be approved.",
      ),
    );

    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This request overlaps a confirmed booking and cannot be approved.");
    expect(alert).toHaveTextContent("Board Dinner");
  });
});

describe("SCRUM-80 staff review of affected bookings", () => {
  const flagged = booking({
    id: 6,
    event_name: "Gala Night",
    status: "APPROVED",
    status_display: "Approved",
    review_required: true,
    review_reason: "The event moved to a later time.",
    review_start: "2026-10-20T03:00:00Z",
    review_end: "2026-10-20T09:00:00Z",
  });
  const unflagged = booking({ id: 8, event_name: "Quiet Lunch", status: "APPROVED" });

  it("AC1: lists only confirmed bookings that need review, with the reason and period", async () => {
    setup([], [flagged, unflagged]);

    const section = await screen.findByRole("region", { name: "Needs review" });
    expect(await within(section).findByText("Gala Night")).toBeInTheDocument();
    expect(within(section).queryByText("Quiet Lunch")).not.toBeInTheDocument();
    expect(within(section).getByText("The event moved to a later time.")).toBeInTheDocument();
    expect(
      within(section).getByText(`${fmt("2026-10-20T03:00:00Z")} – ${fmt("2026-10-20T09:00:00Z")}`),
    ).toBeInTheDocument();
    expect(listBookings).toHaveBeenCalledWith("APPROVED");
  });

  it("AC2: accommodates the change with a revised period", async () => {
    setup([], [flagged]);
    vi.mocked(reviewBooking).mockResolvedValue(
      booking({
        ...flagged,
        review_required: false,
        reviewed_by_name: "Vera Venue",
        reviewed_at: "2026-10-09T02:00:00Z",
        review_outcome: "Revised to 20 Oct 2026 12:00 to 20 Oct 2026 18:00.",
      }),
    );

    const section = await screen.findByRole("region", { name: "Needs review" });
    await within(section).findByText("Gala Night");
    fireEvent.change(within(section).getByLabelText("Revised start (optional)"), {
      target: { value: "2026-10-20T12:00" },
    });
    fireEvent.change(within(section).getByLabelText("Revised end (optional)"), {
      target: { value: "2026-10-20T18:00" },
    });
    await userEvent.click(within(section).getByRole("button", { name: "Accommodate" }));

    expect(reviewBooking).toHaveBeenCalledWith(6, {
      accommodated: true,
      note: "",
      start: new Date("2026-10-20T12:00").toISOString(),
      end: new Date("2026-10-20T18:00").toISOString(),
    });
    expect(await within(section).findByRole("status")).toHaveTextContent(
      "Reviewed by Vera Venue",
    );
  });

  it("AC3: cannot accommodate requires a note", async () => {
    setup([], [flagged]);

    const section = await screen.findByRole("region", { name: "Needs review" });
    await within(section).findByText("Gala Night");
    await userEvent.click(within(section).getByRole("button", { name: "Cannot accommodate" }));

    expect(screen.getByText("Explain why the change cannot be accommodated.")).toBeInTheDocument();
    expect(reviewBooking).not.toHaveBeenCalled();
  });

  it("AC3: records that the change cannot be accommodated", async () => {
    setup([], [flagged]);
    vi.mocked(reviewBooking).mockResolvedValue(
      booking({ ...flagged, review_required: false, review_outcome: "Could not accommodate the change: Hall booked." }),
    );

    const section = await screen.findByRole("region", { name: "Needs review" });
    await within(section).findByText("Gala Night");
    await userEvent.type(within(section).getByLabelText("Note"), "Hall booked.");
    await userEvent.click(within(section).getByRole("button", { name: "Cannot accommodate" }));

    expect(reviewBooking).toHaveBeenCalledWith(6, {
      accommodated: false,
      note: "Hall booked.",
      start: null,
      end: null,
    });
    expect(await within(section).findByRole("status")).toHaveTextContent(
      "Could not accommodate the change: Hall booked.",
    );
  });

  it("AC2: shows the API's refusal when the revised period is not free", async () => {
    setup([], [flagged]);
    vi.mocked(reviewBooking).mockRejectedValue(
      new ApiError(409, { detail: "The revised period is not free at this venue.", conflicts: [] }, "The revised period is not free at this venue."),
    );

    const section = await screen.findByRole("region", { name: "Needs review" });
    await within(section).findByText("Gala Night");
    await userEvent.click(within(section).getByRole("button", { name: "Accommodate" }));

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "The revised period is not free at this venue.",
    );
  });
});
