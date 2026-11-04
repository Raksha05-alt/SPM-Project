import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getVenueReviews, type VenueReview } from "../../api/venueReviews";
import { VenueReviews } from "./VenueReviews";

vi.mock("../../api/venueReviews", () => ({ getVenueReviews: vi.fn() }));

function review(overrides: Partial<VenueReview> = {}): VenueReview {
  return {
    id: 1,
    booking: 4,
    venue: "Harbour Hall",
    booking_status: "APPROVED",
    reasons: [
      {
        requirement: "CAPACITY",
        message: "Expected attendance of 201 exceeds the venue's maximum capacity of 200.",
      },
    ],
    changed_fields: ["expected_attendance"],
    source: "EVENT_EDIT",
    raised_by_name: "Cora Coordinator",
    raised_at: "2026-11-04T02:00:00Z",
    is_open: true,
    resolved_at: null,
    resolution: "",
    ...overrides,
  };
}

function renderReviews() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <VenueReviews eventId={9} />
    </QueryClientProvider>,
  );
}

describe("SCRUM-66 venue review", () => {
  beforeEach(() => vi.mocked(getVenueReviews).mockReset());

  it("AC3: shows each flagged venue with the reason, what changed, who and when", async () => {
    vi.mocked(getVenueReviews).mockResolvedValue({ event: 9, open: [review()], history: [] });
    renderReviews();

    const venue = await screen.findByRole("listitem", { name: "Harbour Hall" });
    expect(getVenueReviews).toHaveBeenCalledWith(9);
    expect(
      within(venue).getByText(
        "Expected attendance of 201 exceeds the venue's maximum capacity of 200.",
      ),
    ).toBeInTheDocument();
    expect(within(venue).getByText(/expected attendance changed \(by Cora Coordinator\)/)).toBeInTheDocument();
    expect(venue.querySelector("time")).toHaveAttribute("datetime", "2026-11-04T02:00:00Z");
    expect(venue.querySelector("time")).toHaveTextContent("04 Nov 2026, 10:00 SGT");
    expect(screen.getByText(/cannot be confirmed until the required venue reviews are resolved/)).toBeInTheDocument();
  });

  it("SCRUM-70 shows the proposed period and conflicting event without claiming staff approval", async () => {
    const message = "Proposed period 02 Mar 2027, 10:00 to 02 Mar 2027, 12:00 SGT conflicts with event 12 (booking 8). The current booking is retained. Venue Staff must review the new period.";
    vi.mocked(getVenueReviews).mockResolvedValue({
      event: 9,
      open: [review({ changed_fields: ["preferred_start", "preferred_end"], reasons: [{ requirement: "PERIOD", message }] })],
      history: [],
    });
    renderReviews();
    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.getByText(/start time and end time changed/)).toBeInTheDocument();
  });

  it("names several changed requirements and unknown fields readably", async () => {
    vi.mocked(getVenueReviews).mockResolvedValue({
      event: 9,
      open: [review({ changed_fields: ["required_layout", "other_field"], raised_by_name: null })],
      history: [],
    });
    renderReviews();

    expect(await screen.findByText(/required layout and other_field changed ·/)).toBeInTheDocument();
  });

  it("AC4: shows nothing when no venue needs review, even with resolved history", async () => {
    vi.mocked(getVenueReviews).mockResolvedValue({
      event: 9,
      open: [],
      history: [review({ is_open: false, resolved_at: "2026-11-04T03:00:00Z" })],
    });
    const { container } = renderReviews();

    await vi.waitFor(() => expect(getVenueReviews).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("says so when the check cannot be loaded", async () => {
    vi.mocked(getVenueReviews)
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue({ event: 9, open: [], history: [] });
    renderReviews();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We could not check whether the booked venues still suit this event.",
    );
  });
});
