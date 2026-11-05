import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { approveBooking, rejectBooking, updateHoldExpiry } from "../../api/venueBookings";
import type { VenueBooking } from "../../types";
import { BookingDecision } from "./BookingDecision";

vi.mock("../../api/venueBookings", () => ({ approveBooking: vi.fn(), rejectBooking: vi.fn(), updateHoldExpiry: vi.fn() }));

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


it("SCRUM-85 warns about buffer hours while allowing staff approval", async () => {
  vi.mocked(approveBooking).mockClear();
  vi.mocked(approveBooking).mockResolvedValue({ detail: "ok", booking: PENDING });
  renderDecision({ ...PENDING, buffer_review: {
    occupied_starts_at: "2027-03-01T01:30:00Z", occupied_ends_at: "2027-03-01T04:45:00Z",
    warnings: ["Setup or turnaround extends outside operating hours. Venue Staff may still approve."],
  } });
  expect(screen.getByRole("alert")).toHaveTextContent("outside operating hours");
  await userEvent.click(screen.getByRole("button", { name: "Approve" }));
  expect(approveBooking).toHaveBeenCalledWith(7);
});


it.each([
  { status: "PENDING", open: "Approve as hold", submit: "Place hold", action: approveBooking },
  { status: "HELD", open: "Change expiry", submit: "Save expiry", action: updateHoldExpiry },
] as const)("SCRUM-88 sets a Singapore hold deadline when $status", async ({ status, open, submit, action }) => {
  const held = { ...PENDING, status: "HELD", hold_until: "2027-03-01T01:30:00Z" } as const;
  vi.mocked(action).mockResolvedValue({ detail: "Hold saved", booking: held });
  renderDecision({ ...held, status });
  if (status === "HELD") expect(screen.getByText(/Hold expires .* SGT/)).toBeInTheDocument();

  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: open }));
  const save = screen.getByRole("button", { name: submit });
  expect(save).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Hold expiry (Singapore time)"), {
    target: { value: "2027-03-01T09:45" },
  });
  await user.click(save);
  expect(action).toHaveBeenCalledWith(7, "2027-03-01T09:45+08:00");
});

it("US-73 sends an optional alternative with the rejection in Singapore time", async () => {
  const { listVenues } = await import("../../api/venues");
  const venueSpy = vi.spyOn(await import("../../api/venues"), "listVenues");
  venueSpy.mockResolvedValue([{ id: 8, name: "Workshop Room" }] as Awaited<ReturnType<typeof listVenues>>);
  vi.mocked(rejectBooking).mockResolvedValue({ detail: "ok", booking: PENDING });
  renderDecision({
    ...PENDING, venue: 3, venue_name: "Original hall",
    starts_at: "2030-06-18T02:00:00Z", ends_at: "2030-06-18T04:00:00Z",
  });
  await userEvent.click(screen.getByRole("button", { name: "Reject" }));
  await userEvent.type(screen.getByLabelText("Reason for rejection"), "Use the workshop instead");
  await userEvent.click(screen.getByLabelText("Suggest another venue or time"));
  await screen.findByRole("option", { name: "Workshop Room" });
  expect(screen.getByLabelText("Suggested start (Singapore time)")).toHaveValue("2030-06-18T10:00");
  await userEvent.selectOptions(screen.getByLabelText("Suggested venue"), "8");
  await userEvent.click(screen.getByRole("button", { name: "Confirm rejection" }));
  expect(rejectBooking).toHaveBeenCalledWith(7, "Use the workshop instead", {
    venue: 8, starts_at: "2030-06-18T10:00+08:00", ends_at: "2030-06-18T12:00+08:00",
  });
  venueSpy.mockRestore();
});
