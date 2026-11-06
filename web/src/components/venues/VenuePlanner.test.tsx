import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { confirmVenueHold, listEventBookings, requestVenue, withdrawVenue } from "../../api/venueBookings";
import { listVenues } from "../../api/venues";
import type { EventRequest, Venue, VenueBooking } from "../../types";
import { VenuePlanner } from "./VenuePlanner";

vi.mock("../../api/venueBookings", () => ({
  confirmVenueHold: vi.fn(),
  listEventBookings: vi.fn(),
  requestVenue: vi.fn(),
  withdrawVenue: vi.fn(),
}));
vi.mock("../../api/venues", () => ({ listVenues: vi.fn() }));

const EVENT = {
  id: 9,
  name: "Partner Summit",
  status: "APPROVED",
  preferred_start: "2027-03-01T02:00:00Z",
  preferred_end: "2027-03-01T04:00:00Z",
  expected_attendance: 60,
  required_layout: "THEATRE",
  accessibility_needs: "Two wheelchair users.",
} as unknown as EventRequest;

const HALL = { id: 3, name: "Harbour Hall", capacity: 60 } as Venue;

function booking(overrides: Partial<VenueBooking> = {}): VenueBooking {
  return {
    id: 1,
    event: 9,
    event_name: "Partner Summit",
    organisation_name: "Acme Pte Ltd",
    venue: 3,
    venue_name: "Harbour Hall",
    starts_at: "2027-03-01T02:00:00Z",
    ends_at: "2027-03-01T04:00:00Z",
    attendance: 60,
    layout: "THEATRE",
    layout_name: "Theatre",
    required_facilities: [],
    wheelchair_access_required: true,
    accessibility_notes: "",
    status: "PENDING",
    status_label: "Pending",
    status_changed_at: "2026-11-01T01:00:00Z",
    requested_by_name: "Cora Coordinator",
    requested_at: "2026-11-01T01:00:00Z",
    decided_by_name: null,
    decided_at: null,
    decision_reason: "",
    ...overrides,
  };
}

function renderPlanner(event: EventRequest = EVENT) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VenuePlanner event={event} />
    </QueryClientProvider>,
  );
}

describe("VenuePlanner (SCRUM-11)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listEventBookings).mockResolvedValue([]);
    vi.mocked(listVenues).mockResolvedValue([HALL]);
  });

  it("AC1/AC2: sends the venue, timing and requirements, pre-filled from the event", async () => {
    vi.mocked(requestVenue).mockResolvedValue({
      detail: "Your request for Harbour Hall has been sent to Venue Staff.",
      booking: booking(),
    });
    const user = userEvent.setup();
    renderPlanner();

    await screen.findByRole("option", { name: "Harbour Hall (capacity 60)" });
    await user.selectOptions(screen.getByLabelText("Venue"), "3");
    fireEvent.change(screen.getByLabelText("Starts"), { target: { value: "2030-06-18T09:30" } });
    fireEvent.change(screen.getByLabelText("Ends"), { target: { value: "2030-06-18T11:30" } });
    await user.selectOptions(screen.getByLabelText("Room layout"), "CLASSROOM");
    await user.clear(screen.getByLabelText("Accessibility needs"));
    await user.type(screen.getByLabelText("Accessibility needs"), "Ramp at entrance.");
    await user.type(
      screen.getByLabelText("Required facilities"),
      "Video conferencing, Hearing loop",
    );
    await user.click(screen.getByLabelText("Wheelchair access required"));
    await user.click(screen.getByRole("button", { name: "Send request to Venue Staff" }));

    expect(requestVenue).toHaveBeenCalledWith(9, {
      venue: 3,
      starts_at: new Date("2030-06-18T09:30").toISOString(),
      ends_at: new Date("2030-06-18T11:30").toISOString(),
      attendance: 60,
      layout: "CLASSROOM",
      required_facilities: ["Video conferencing", "Hearing loop"],
      wheelchair_access_required: true,
      accessibility_notes: "Ramp at entrance.",
    });
    // AC4 - confirmation that it reached Venue Staff.
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Your request for Harbour Hall has been sent to Venue Staff.",
    );
  });

  it("AC3: names each missing item beside its field", async () => {
    vi.mocked(requestVenue).mockRejectedValue(
      new ApiError(
        400,
        {
          detail: "Missing information.",
          venue: ["Choose a venue."],
          attendance: ["Enter the expected attendance."],
        },
        "Missing information.",
      ),
    );
    const user = userEvent.setup();
    renderPlanner();

    await user.click(await screen.findByRole("button", { name: "Send request to Venue Staff" }));

    expect(await screen.findByText("Choose a venue.")).toBeInTheDocument();
    expect(screen.getByText("Enter the expected attendance.")).toBeInTheDocument();
  });

  it("SCRUM-71 AC4: lists every requirement an unsuitable venue does not meet", async () => {
    vi.mocked(requestVenue).mockRejectedValue(
      new ApiError(
        400,
        {
          detail: "Harbour Hall does not meet this event's requirements.",
          unmet_requirements: [
            { requirement: "CAPACITY", message: "Attendance 70 is more than the capacity of 60." },
            { requirement: "LAYOUT", message: "Boardroom is not a supported layout." },
          ],
        },
        "Harbour Hall does not meet this event's requirements.",
      ),
    );
    const user = userEvent.setup();
    renderPlanner();

    await user.click(await screen.findByRole("button", { name: "Send request to Venue Staff" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Harbour Hall does not meet this event's requirements.");
    expect(alert).toHaveTextContent("Attendance 70 is more than the capacity of 60.");
    expect(alert).toHaveTextContent("Boardroom is not a supported layout.");
  });

  it("explains when the venue is blocked or already booked", async () => {
    vi.mocked(requestVenue).mockRejectedValue(
      new ApiError(
        409,
        {
          detail: "The venue is not available for that period.",
          reasons: ["The venue is out of service."],
        },
        "The venue is not available for that period.",
      ),
    );
    const user = userEvent.setup();
    renderPlanner();

    await user.click(await screen.findByRole("button", { name: "Send request to Venue Staff" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The venue is out of service.");
  });

  it("AC5: shows each request's current status and decision", async () => {
    vi.mocked(listEventBookings).mockResolvedValue([
      booking({
        status: "REJECTED",
        status_label: "Rejected",
        decided_by_name: "Vera Venue",
        decision_reason: "Under renovation.",
      }),
    ]);

    renderPlanner();

    expect(await screen.findByText("Rejected")).toBeInTheDocument();
    expect(screen.getByText("by Vera Venue")).toBeInTheDocument();
    expect(screen.getByText("Under renovation.")).toBeInTheDocument();
  });

  it("offers no request form before the event is approved", async () => {
    renderPlanner({ ...EVENT, status: "SUBMITTED" } as EventRequest);

    expect(
      await screen.findByText("A venue can be requested once this event has been approved."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Send request to Venue Staff" }),
    ).not.toBeInTheDocument();
  });
});


describe("SCRUM-67 withdrawal", () => {
  it("offers withdrawal during the project's Awaiting Clarification status", async () => {
    vi.mocked(listEventBookings).mockResolvedValue([booking()]);
    renderPlanner({ ...EVENT, status: "UNDER_REVIEW" } as EventRequest);
    expect(await screen.findByRole("button", { name: "Withdraw Harbour Hall" })).toBeEnabled();
  });

  it("requires approved confirmation and cancelling sends no mutation", async () => {
    vi.mocked(listEventBookings).mockResolvedValue([booking({ status: "APPROVED", status_label: "Approved" })]);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    renderPlanner();
    await user.click(await screen.findByRole("button", { name: "Withdraw Harbour Hall" }));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining("release a confirmed venue arrangement"));
    expect(withdrawVenue).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    vi.mocked(withdrawVenue).mockResolvedValue({ detail: "Withdrawn", booking: booking({ status: "WITHDRAWN" }) });
    await user.click(screen.getByRole("button", { name: "Withdraw Harbour Hall" }));
    expect(withdrawVenue).toHaveBeenCalledWith(9, expect.objectContaining({ id: 1, status: "APPROVED" }), true);
    confirm.mockRestore();
  });
});


it("SCRUM-88 confirms an active hold and refreshes the booking", async () => {
  const approved = booking({ status: "APPROVED", status_label: "Approved" });
  vi.mocked(listEventBookings).mockResolvedValueOnce([
    booking({ status: "HELD", status_label: "Held", hold_until: "2027-03-01T01:30:00Z" }),
  ]).mockResolvedValue([approved]);
  vi.mocked(confirmVenueHold).mockResolvedValue({ detail: "Venue hold confirmed.", booking: approved });
  renderPlanner();

  await userEvent.click(await screen.findByRole("button", { name: "Confirm hold" }));
  expect(confirmVenueHold).toHaveBeenCalledWith(1);
  expect(await screen.findByText("Approved", { exact: true })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirm hold" })).not.toBeInTheDocument();
});

it("SCRUM-88 shows expired holds without a confirmation action", async () => {
  vi.mocked(listEventBookings).mockResolvedValue([booking({ status: "EXPIRED", status_label: "Expired" })]);
  renderPlanner();
  expect(await screen.findByText("Expired", { exact: true })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Confirm hold" })).not.toBeInTheDocument();
});

describe("SCRUM-88 hold confirmation refusals", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listEventBookings).mockResolvedValue([
      booking({ status: "HELD", status_label: "Held", hold_until: "2027-03-01T01:30:00Z" }),
    ]);
    vi.mocked(listVenues).mockResolvedValue([HALL]);
  });

  it.each([
    ["expired state", new ApiError(400, { status: ["The hold expired."] }, "Cannot confirm"), "The hold expired."],
    ["new conflict", new ApiError(409, { reasons: ["Another booking now overlaps."] }, "Venue unavailable"), "Another booking now overlaps."],
    ["changed assignment", new ApiError(403, { detail: "Only the assigned coordinator can confirm." }, "Only the assigned coordinator can confirm."), "Only the assigned coordinator can confirm."],
    ["network failure", new Error("offline"), "We could not send the request."],
  ])("shows %s and reloads current bookings without claiming confirmation", async (_label, error, message) => {
    vi.mocked(confirmVenueHold).mockRejectedValue(error);
    renderPlanner();
    await userEvent.click(await screen.findByRole("button", { name: "Confirm hold" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(String(message));
    expect(screen.queryByText("Venue hold confirmed.")).not.toBeInTheDocument();
    await waitFor(() => expect(listEventBookings).toHaveBeenCalledTimes(2));
  });
});
