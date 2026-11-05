import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { decideArrangement, listArrangementReviews } from "../../api/changeRequests";
import type { ArrangementReviewItem } from "../../types";
import { ArrangementReviews } from "./ArrangementReviews";

vi.mock("../../api/changeRequests", () => ({
  listArrangementReviews: vi.fn(),
  decideArrangement: vi.fn(),
}));

const VENUE: ArrangementReviewItem = {
  id: 7,
  change_request: 4,
  event: 9,
  event_name: "Annual Gala",
  change_description: "Move the gala to the next day.",
  change_status: "IN_REVIEW",
  kind: "VENUE",
  name: "Harbour Hall",
  quantity: null,
  before: { starts_at: "2027-03-01T02:00:00Z", ends_at: "2027-03-01T04:00:00Z", attendance: 120 },
  proposed: { starts_at: "2027-03-02T02:00:00Z", ends_at: "2027-03-02T04:00:00Z", attendance: 120 },
  reasons: ["Another booking already holds the venue at the proposed time."],
  outcome: "PENDING",
  outcome_label: "Awaiting staff review",
  reviewed_by_name: null,
  reviewed_at: null,
  review_reason: "",
};

const EQUIPMENT: ArrangementReviewItem = {
  ...VENUE,
  id: 8,
  kind: "EQUIPMENT",
  name: "Projector",
  quantity: 3,
  before: { quantity: 3, reserved: true, starts_at: null, ends_at: null },
  proposed: { quantity: 3, starts_at: null, ends_at: null },
  reasons: [],
};

function renderReviews() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ArrangementReviews />
    </QueryClientProvider>,
  );
}

describe("ArrangementReviews (SCRUM-80)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listArrangementReviews).mockResolvedValue([VENUE]);
  });

  it("AC1: lists each arrangement awaiting review with current and proposed values", async () => {
    renderReviews();

    const item = await screen.findByRole("listitem", { name: "Review of Harbour Hall for Annual Gala" });
    expect(item).toHaveTextContent("Approved change: Move the gala to the next day.");
    expect(item).toHaveTextContent("120 people");
    expect(item).toHaveTextContent("Another booking already holds the venue at the proposed time.");
    expect(listArrangementReviews).toHaveBeenCalledWith("PENDING");
  });

  it("shows equipment with its quantity and an unchanged period", async () => {
    vi.mocked(listArrangementReviews).mockResolvedValue([EQUIPMENT]);
    renderReviews();

    const item = await screen.findByRole("listitem", { name: "Review of Projector for Annual Gala" });
    expect(item).toHaveTextContent("Projector (3) – Annual Gala");
    expect(item).toHaveTextContent("Current: Same period");
  });

  it.each([
    ["Can accommodate", "ACCOMMODATED"],
    ["Cannot accommodate", "NOT_ACCOMMODATED"],
  ] as const)("AC2/AC3: %s records the outcome with the reason", async (button, outcome) => {
    vi.mocked(decideArrangement).mockResolvedValue({ detail: "Your outcome has been recorded.", review: VENUE });
    const user = userEvent.setup();
    renderReviews();
    const item = await screen.findByRole("listitem", { name: /Harbour Hall/ });

    await user.type(within(item).getByLabelText("Reason for your outcome"), "Checked the calendar.");
    await user.click(within(item).getByRole("button", { name: button }));

    expect(decideArrangement).toHaveBeenCalledWith(7, outcome, "Checked the calendar.");
    expect(await screen.findByRole("status")).toHaveTextContent("Your outcome has been recorded.");
  });

  it("shows why an accommodation was refused, with the current problems", async () => {
    vi.mocked(decideArrangement).mockRejectedValue(
      new ApiError(
        409,
        { problems: ["Harbour Hall is already booked at the proposed time."] },
        "The change can no longer be accommodated as proposed.",
      ),
    );
    const user = userEvent.setup();
    renderReviews();
    const item = await screen.findByRole("listitem", { name: /Harbour Hall/ });

    await user.click(within(item).getByRole("button", { name: "Can accommodate" }));

    expect(await within(item).findByRole("alert")).toHaveTextContent(
      "The change can no longer be accommodated as proposed. Harbour Hall is already booked at the proposed time.",
    );
  });

  it.each([
    [{ reason: ["Enter the reason for your outcome."] }, "Enter the reason for your outcome."],
    [{ outcome: ["Choose whether the change can be accommodated."] }, "Choose whether the change can be accommodated."],
  ])("names a missing reason or outcome", async (body, text) => {
    vi.mocked(decideArrangement).mockRejectedValue(new ApiError(400, body, "Refused."));
    const user = userEvent.setup();
    renderReviews();
    const item = await screen.findByRole("listitem", { name: /Harbour Hall/ });

    await user.click(within(item).getByRole("button", { name: "Cannot accommodate" }));

    expect(await within(item).findByRole("alert")).toHaveTextContent(text);
  });

  it("has a clear empty state and announces a load failure", async () => {
    vi.mocked(listArrangementReviews).mockResolvedValue([]);
    renderReviews();
    expect(await screen.findByText("No approved changes are waiting for your review.")).toBeInTheDocument();

    vi.mocked(listArrangementReviews).mockRejectedValue(new Error("down"));
    renderReviews();
    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load the changes to review.");
  });
});
