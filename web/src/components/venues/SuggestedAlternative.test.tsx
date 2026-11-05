import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { acceptVenueSuggestion } from "../../api/venueBookings";
import type { VenueBooking } from "../../types";
import { SuggestedAlternative } from "./SuggestedAlternative";

vi.mock("../../api/venueBookings", () => ({ acceptVenueSuggestion: vi.fn() }));
const rejected = {
  id: 7, event: 9, status: "REJECTED",
  suggestion: { venue: 8, venue_name: "Workshop Room", starts_at: "2030-06-18T02:00:00Z",
    ends_at: "2030-06-18T04:00:00Z", booking: null },
} as VenueBooking;

function show(booking = rejected, canAccept = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <SuggestedAlternative booking={booking} canAccept={canAccept} />
  </QueryClientProvider>);
  return client;
}

beforeEach(() => vi.resetAllMocks());

it("US-73 accepts the staff proposal as a new request and refreshes the event", async () => {
  vi.mocked(acceptVenueSuggestion).mockResolvedValue({ detail: "Alternative requested.", booking: { ...rejected, id: 11, status: "PENDING" } });
  const client = show();
  const refresh = vi.spyOn(client, "invalidateQueries");
  expect(screen.getByText(/Suggested alternative.*Workshop Room/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Accept and request alternative" }));
  expect(acceptVenueSuggestion).toHaveBeenCalledWith(7);
  expect(await screen.findByRole("status")).toHaveTextContent("Alternative requested.");
  expect(refresh).toHaveBeenCalled();
});

it.each([
  new ApiError(409, { detail: "Room unavailable", reasons: ["An active hold overlaps."] }, "Room unavailable"),
  new ApiError(400, { detail: "Requirements changed", unmet_requirements: [{ message: "Capacity is now 10." }] }, "Requirements changed"),
  new ApiError(400, { detail: "Invalid suggestion", suggestion: ["The time has passed."], status: ["A newer request exists."] }, "Invalid suggestion"),
  new Error("Disconnected"),
])("US-73 shows a refused or uncertain acceptance without claiming success", async (error) => {
  vi.mocked(acceptVenueSuggestion).mockRejectedValue(error);
  const client = show();
  const refresh = vi.spyOn(client, "invalidateQueries");
  await userEvent.click(screen.getByRole("button", { name: "Accept and request alternative" }));
  const message = await screen.findByRole("alert");
  expect(message).not.toBeEmptyDOMElement();
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  await waitFor(() => expect(refresh).toHaveBeenCalledWith({ queryKey: ["venue-bookings", 9] }));
});

it.each([false, true])("US-73 preserves the accepted suggestion without offering another request (%s)", canAccept => {
  show({ ...rejected, suggestion: { ...rejected.suggestion!, booking: 11 } }, canAccept);
  expect(screen.getByText(/Requested as booking #11/)).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("US-73 keeps staff and closed events read-only", () => {
  show(rejected, false);
  expect(screen.getByText(/Workshop Room/)).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("US-73 does not add a proposal to legacy requests", () => {
  show({ ...rejected, suggestion: undefined });
  expect(screen.queryByText(/Suggested alternative/)).not.toBeInTheDocument();
});
