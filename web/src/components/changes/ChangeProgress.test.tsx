import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { applyChange, getChangeHistory, keepOriginal } from "../../api/changeRequests";
import type { ChangeHistory, ChangeRequest } from "../../types";
import { ChangeProgress } from "./ChangeProgress";

vi.mock("../../api/changeRequests", () => ({
  applyChange: vi.fn(),
  getChangeHistory: vi.fn(),
  keepOriginal: vi.fn(),
}));

const CHANGE: ChangeRequest = {
  id: 4,
  event: 9,
  description: "Move the gala to the next day.",
  reason: "Speaker availability.",
  proposed_values: {},
  proposed_changes: [],
  target_bookings: [],
  target_equipment_requests: [],
  revision: 1,
  significant: true,
  status: "APPROVED",
  status_label: "Approved",
  status_changed_at: "2026-11-05T01:00:00Z",
  requested_by_name: "Ada Organiser",
  requested_at: "2026-11-05T01:00:00Z",
  decided_by_name: "Cora Coordinator",
  decided_at: "2026-11-05T02:00:00Z",
  decision_reason: "Agreed.",
  applied_at: null,
  completed_at: null,
  completion_note: "",
};

function history(overrides: Partial<ChangeHistory> = {}): ChangeHistory {
  return {
    change_request: 4,
    description: CHANGE.description,
    reason: CHANGE.reason,
    requested_by: "Ada Organiser",
    requested_at: CHANGE.requested_at,
    status: "IN_REVIEW",
    status_label: "In staff review",
    decision: { decided_by: "Cora Coordinator", decided_at: CHANGE.decided_at, reason: "Agreed." },
    applied_by: "Cora Coordinator",
    applied_at: "2026-11-05T03:00:00Z",
    completed_at: null,
    completion_note: "",
    arrangements: [
      {
        id: 1,
        kind: "VENUE",
        kind_label: "Venue booking",
        name: "Harbour Hall",
        before: { starts_at: "2027-03-01T02:00:00Z", ends_at: "2027-03-01T04:00:00Z", attendance: 120 },
        proposed: { starts_at: "2027-03-02T02:00:00Z", ends_at: "2027-03-02T04:00:00Z", attendance: 120 },
        reasons: [],
        outcome: "NOT_ACCOMMODATED",
        outcome_label: "Cannot be accommodated",
        reviewed_by: "Vera Venue",
        reviewed_at: "2026-11-05T04:00:00Z",
        review_reason: "Closed for maintenance.",
      },
      {
        id: 2,
        kind: "EQUIPMENT",
        kind_label: "Equipment",
        name: "Projector",
        before: { quantity: 3 },
        proposed: { quantity: 3 },
        reasons: [],
        outcome: "PENDING",
        outcome_label: "Awaiting staff review",
        reviewed_by: null,
        reviewed_at: null,
        review_reason: "",
      },
    ],
    field_changes: [],
    ...overrides,
  };
}

function renderProgress(change: ChangeRequest = CHANGE, canDecide = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChangeProgress change={change} eventId={9} canDecide={canDecide} />
    </QueryClientProvider>,
  );
}

describe("ChangeProgress (SCRUM-80)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getChangeHistory).mockResolvedValue(history());
  });

  it("AC1: the coordinator applies an approved change and sees the receipt", async () => {
    vi.mocked(applyChange).mockResolvedValue({
      detail: "2 arrangement(s) sent to staff for review.",
      change_request: { ...CHANGE, status: "IN_REVIEW" },
      history: history(),
    });
    const user = userEvent.setup();
    renderProgress();

    await user.click(screen.getByRole("button", { name: "Apply change" }));

    expect(applyChange).toHaveBeenCalledWith(4);
    expect(await screen.findByRole("status")).toHaveTextContent("2 arrangement(s) sent to staff for review.");
  });

  it("shows why applying was refused, with any problems", async () => {
    vi.mocked(applyChange).mockRejectedValue(
      new ApiError(409, { problems: ["Harbour Hall is already booked."] }, "Cannot apply."),
    );
    const user = userEvent.setup();
    renderProgress();

    await user.click(screen.getByRole("button", { name: "Apply change" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Cannot apply. Harbour Hall is already booked.");
  });

  it("offers no apply button or history to read-only viewers of an approved change", () => {
    renderProgress(CHANGE, false);

    expect(screen.queryByRole("button", { name: "Apply change" })).not.toBeInTheDocument();
    expect(getChangeHistory).not.toHaveBeenCalled();
  });

  it("AC5: shows the decision, each arrangement outcome and who recorded it", async () => {
    renderProgress({ ...CHANGE, status: "IN_REVIEW" }, false);

    const panel = await screen.findByRole("region", { name: "History of change request 4" });
    expect(panel).toHaveTextContent("Approved by Cora Coordinator: Agreed.");
    expect(panel).toHaveTextContent("Sent for staff review by Cora Coordinator.");
    const outcomes = within(panel).getByRole("list", { name: "Arrangement outcomes" });
    expect(outcomes).toHaveTextContent("Harbour Hall (Venue booking)");
    expect(outcomes).toHaveTextContent("Cannot be accommodated by Vera Venue: Closed for maintenance.");
    expect(outcomes).toHaveTextContent("Projector (Equipment): Awaiting staff review");
    // Read-only viewers do not get the keep-original action.
    expect(screen.queryByRole("button", { name: "Keep the original arrangement" })).not.toBeInTheDocument();
  });

  it("AC3: after a refusal the coordinator records that the original is kept", async () => {
    vi.mocked(keepOriginal).mockResolvedValue({
      detail: "The original arrangement is kept.",
      change_request: { ...CHANGE, status: "ORIGINAL_KEPT" },
    });
    const user = userEvent.setup();
    renderProgress({ ...CHANGE, status: "IN_REVIEW" });

    await user.type(
      await screen.findByLabelText("What was agreed with the organiser"),
      "Keep the original date.",
    );
    await user.click(screen.getByRole("button", { name: "Keep the original arrangement" }));

    expect(keepOriginal).toHaveBeenCalledWith(4, "Keep the original date.");
  });

  it("AC3: names a missing agreement", async () => {
    vi.mocked(keepOriginal).mockRejectedValue(
      new ApiError(400, { reason: ["Enter what was agreed with the organiser."] }, "Refused."),
    );
    const user = userEvent.setup();
    renderProgress({ ...CHANGE, status: "IN_REVIEW" });

    await user.click(await screen.findByRole("button", { name: "Keep the original arrangement" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Enter what was agreed with the organiser.");
  });

  it("offers no keep-original action while every review is still possible", async () => {
    vi.mocked(getChangeHistory).mockResolvedValue(
      history({ arrangements: history().arrangements.filter((a) => a.outcome === "PENDING") }),
    );
    renderProgress({ ...CHANGE, status: "IN_REVIEW" });

    await screen.findByRole("list", { name: "Arrangement outcomes" });
    expect(screen.queryByRole("button", { name: "Keep the original arrangement" })).not.toBeInTheDocument();
  });

  it("shows how an applied change ended", async () => {
    vi.mocked(getChangeHistory).mockResolvedValue(
      history({
        status: "APPLIED",
        status_label: "Applied",
        completion_note: "Every affected arrangement was accommodated.",
        arrangements: [],
      }),
    );
    renderProgress({ ...CHANGE, status: "APPLIED" });

    expect(await screen.findByText("Every affected arrangement was accommodated.")).toBeInTheDocument();
  });

  it("says when the history could not be loaded", async () => {
    vi.mocked(getChangeHistory).mockRejectedValue(new Error("down"));
    renderProgress({ ...CHANGE, status: "APPLIED" });

    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load the history.");
  });
});
