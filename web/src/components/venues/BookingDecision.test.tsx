import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { approveBooking, rejectBooking } from "../../api/venueBookings";
import type { VenueBooking } from "../../types";
import { BookingDecision } from "./BookingDecision";

vi.mock("../../api/venueBookings", () => ({ approveBooking: vi.fn(), rejectBooking: vi.fn() }));

const PENDING = {
  id: 7,
  event: 9,
  status: "PENDING",
  decided_by_name: null,
  decided_at: null,
  decision_reason: "",
} as unknown as VenueBooking;

function renderDecision(booking: VenueBooking = PENDING, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(
    <QueryClientProvider client={client}>
      <BookingDecision booking={booking} />
    </QueryClientProvider>,
  );
}

describe("BookingDecision (SCRUM-72)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC2 - approves a pending request", async () => {
    vi.mocked(approveBooking).mockResolvedValue({ detail: "ok", booking: PENDING });
    const user = userEvent.setup();
    renderDecision();

    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(approveBooking).toHaveBeenCalledWith(7);
    expect(rejectBooking).not.toHaveBeenCalled();
  });

  it("G12: a staff decision invalidates cached discovery, shortlist and availability data", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const keys = [["venue-search", 2], ["venue-shortlist", 9, 2], ["venue-availability", 3]];
    keys.forEach(key => client.setQueryData<{ oldSnapshot: boolean }>(key, { oldSnapshot: true }));
    vi.mocked(approveBooking).mockResolvedValue({ detail: "ok", booking: PENDING });
    renderDecision(PENDING, client);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => keys.forEach(key => expect(client.getQueryState(key)?.isInvalidated).toBe(true)));
  });

  it.each([
    new Error("connection lost"), new ApiError(500, null, "Empty response"),
  ])("G12: uncertain decision responses refresh cached venue availability (%s)", async error => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const keys = [["venue-search", 2], ["venue-shortlist", 9, 2], ["venue-availability", 3]];
    keys.forEach(key => client.setQueryData<{ oldSnapshot: boolean }>(key, { oldSnapshot: true }));
    vi.mocked(approveBooking).mockRejectedValue(error);
    renderDecision(PENDING, client);
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The decision could not be recorded");
    await waitFor(() => keys.forEach(key => expect(client.getQueryState(key)?.isInvalidated).toBe(true)));
  });

  it.each([
    { body: { event: ["This event already has an approved venue."] }, expected: "This event already has an approved venue." },
    { body: { venue: ["The venue conflicts with event 42."] }, expected: "The venue conflicts with event 42." },
    { body: { unmet_requirements: [{ message: "Attendance exceeds current capacity." }] }, expected: "Attendance exceeds current capacity." },
  ])("shows a current server refusal without claiming approval: $expected", async ({ body, expected }) => {
    vi.mocked(approveBooking).mockRejectedValue(new ApiError(409, body, "Refused"));
    renderDecision();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(expected);
  });

  it("AC3/AC4 - rejection needs a reason before it can be confirmed", async () => {
    vi.mocked(rejectBooking).mockResolvedValue({ detail: "ok", booking: PENDING });
    const user = userEvent.setup();
    renderDecision();

    await user.click(screen.getByRole("button", { name: "Reject" }));
    const confirm = screen.getByRole("button", { name: "Confirm rejection" });
    expect(confirm).toBeDisabled();
    await user.type(screen.getByLabelText("Reason for rejection"), "   ");
    expect(confirm).toBeDisabled();
    expect(rejectBooking).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText("Reason for rejection"), "Hall is being renovated.");
    await user.click(confirm);

    expect(rejectBooking).toHaveBeenCalledWith(7, "Hall is being renovated.");
  });

  it("cancelling a rejection sends nothing", async () => {
    const user = userEvent.setup();
    renderDecision();

    await user.click(screen.getByRole("button", { name: "Reject" }));
    await user.type(screen.getByLabelText("Reason for rejection"), "Maybe not.");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(rejectBooking).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("AC5 - shows why the server refused a decision", async () => {
    vi.mocked(approveBooking).mockRejectedValue(
      new ApiError(
        409,
        {
          detail: "The venue is not available for that period.",
          reasons: ["The venue is out of service."],
        },
        "Conflict",
      ),
    );
    const user = userEvent.setup();
    renderDecision();

    await user.click(screen.getByRole("button", { name: "Approve" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The venue is not available for that period.");
    expect(alert).toHaveTextContent("The venue is out of service.");
  });

  it("AC6 - a decided request shows who decided, when and why, with no actions", () => {
    renderDecision({
      ...PENDING,
      status: "REJECTED",
      decided_by_name: "Vera Venue",
      decided_at: "2026-11-01T02:00:00Z",
      decision_reason: "Hall is being renovated.",
    });

    expect(screen.getByText(/Vera Venue/)).toBeInTheDocument();
    expect(screen.getByText("Reason: Hall is being renovated.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
