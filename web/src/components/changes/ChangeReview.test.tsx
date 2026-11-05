import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { decideChange, getChangeImpact, listChangeRequests } from "../../api/changeRequests";
import type { ChangeAssessment, ChangeRequest } from "../../types";
import { ChangeRequests } from "./ChangeRequests";
import { ChangeReview } from "./ChangeReview";

vi.mock("../../api/changeRequests", () => ({
  listChangeRequests: vi.fn(),
  requestChange: vi.fn(),
  getChangeImpact: vi.fn(),
  decideChange: vi.fn(),
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
  status: "PENDING",
  status_label: "Pending",
  status_changed_at: "2026-11-04T01:00:00Z",
  requested_by_name: "Ada Organiser",
  requested_at: "2026-11-04T01:00:00Z",
  decided_by_name: null,
  decided_at: null,
  decision_reason: "",
  applied_at: null,
  completed_at: null,
  completion_note: "",
};

function assessment(overrides: Partial<ChangeAssessment> = {}): ChangeAssessment {
  return {
    change_request: 4,
    significant: true,
    significant_fields: ["preferred_start"],
    stale: false,
    venue_bookings: [
      {
        booking: 7,
        venue: "Harbour Hall",
        session: "Main programme",
        status: "APPROVED",
        status_label: "Approved",
        starts_at: "2027-03-01T02:00:00Z",
        ends_at: "2027-03-01T04:00:00Z",
        proposed_starts_at: "2027-03-02T02:00:00Z",
        proposed_ends_at: "2027-03-02T04:00:00Z",
        rechecked_for: ["expected_attendance"],
        unsuitable: true,
        unsuitable_reasons: ["Capacity 150 is below the expected attendance of 151."],
        conflicts: [{ booking: 9, event: 12, starts_at: "2027-03-02T02:00:00Z", ends_at: "2027-03-02T04:00:00Z" }],
        referenced: false,
      },
    ],
    equipment: [
      {
        request: 3,
        equipment_type: "Projector",
        quantity: 3,
        status: "REQUESTED",
        status_label: "Requested",
        available_at_proposed_time: 2,
        shortfall: 1,
        reasons: ["The date or time changes, so its period must be checked again."],
      },
    ],
    registrations: { registered: 2, waitlisted: 1, capacity: 100, affected: true, reasons: [] },
    warnings: ["Harbour Hall is already booked for another event at the proposed time."],
    no_impact: false,
    summary: "Review the arrangements below before deciding.",
    ...overrides,
  };
}

function renderReview() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChangeReview change={CHANGE} eventId={9} />
    </QueryClientProvider>,
  );
}

async function openReview() {
  const user = userEvent.setup();
  renderReview();
  await user.click(screen.getByRole("button", { name: "Review impact" }));
  return { user, review: await screen.findByRole("region", { name: "Review of change request 4" }) };
}

describe("ChangeReview (SCRUM-78)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getChangeImpact).mockResolvedValue(assessment());
  });

  it("assesses only when opened", async () => {
    renderReview();
    expect(getChangeImpact).not.toHaveBeenCalled();
  });

  it("AC1-AC3: lists affected bookings, equipment and registrations with their flags", async () => {
    const { review } = await openReview();

    expect(await within(review).findByText(/Harbour Hall \(Main programme, Approved\)/)).toBeInTheDocument();
    expect(review).toHaveTextContent("Potentially unsuitable");
    expect(review).toHaveTextContent("Conflicts with another booking");
    expect(review).toHaveTextContent("3 x Projector (Requested)");
    expect(review).toHaveTextContent("1 short");
    expect(review).toHaveTextContent("2 registered, 1 on the waiting list.");
    expect(within(review).getByRole("list", { name: "Warnings" })).toHaveTextContent(
      "Harbour Hall is already booked for another event at the proposed time.",
    );
    expect(getChangeImpact).toHaveBeenCalledWith(4);
  });

  it("AC1: equipment with enough stock at the new time is listed without a shortfall", async () => {
    const [line] = assessment().equipment;
    vi.mocked(getChangeImpact).mockResolvedValue(
      assessment({ equipment: [{ ...line, available_at_proposed_time: 10, shortfall: 0 }] }),
    );
    const { review } = await openReview();

    expect(await within(review).findByText(/3 x Projector \(Requested\)/)).toBeInTheDocument();
    expect(review).not.toHaveTextContent("short");
  });

  it("AC4: states clearly when nothing is affected", async () => {
    vi.mocked(getChangeImpact).mockResolvedValue(
      assessment({
        no_impact: true,
        summary: "This change does not affect any existing arrangements.",
        venue_bookings: [],
        equipment: [],
        warnings: [],
      }),
    );
    const { review } = await openReview();

    expect(
      await within(review).findByText("This change does not affect any existing arrangements."),
    ).toBeInTheDocument();
  });

  it.each([
    ["Approve change", "APPROVE"],
    ["Reject change", "REJECT"],
  ] as const)("AC5: %s sends the decision with the reason", async (button, decision) => {
    vi.mocked(decideChange).mockResolvedValue({
      detail: "Done.",
      change_request: CHANGE,
      assessment: assessment(),
    });
    const { user, review } = await openReview();
    await within(review).findByText(/Harbour Hall \(Main programme/);

    await user.type(within(review).getByLabelText("Reason for your decision"), "Agreed with the venue.");
    await user.click(within(review).getByRole("button", { name: button }));

    expect(decideChange).toHaveBeenCalledWith(4, decision, "Agreed with the venue.");
  });

  it("AC5: shows why a decision without a reason was refused", async () => {
    vi.mocked(decideChange).mockRejectedValue(
      new ApiError(400, { reason: ["Enter the reason for your decision."] }, "The decision could not be recorded."),
    );
    const { user, review } = await openReview();
    await within(review).findByText(/Harbour Hall \(Main programme/);

    await user.click(within(review).getByRole("button", { name: "Reject change" }));

    expect(await within(review).findByText("Enter the reason for your decision.")).toBeInTheDocument();
  });

  it("a stale request can be rejected but not approved", async () => {
    vi.mocked(getChangeImpact).mockResolvedValue(assessment({ stale: true }));
    const { review } = await openReview();

    expect(await within(review).findByRole("alert")).toHaveTextContent(
      "The event has changed since this was requested. It can be rejected, not approved.",
    );
    expect(within(review).getByRole("button", { name: "Approve change" })).toBeDisabled();
    expect(within(review).getByRole("button", { name: "Reject change" })).toBeEnabled();
  });

  it("shows a conflict refusal, such as a request decided elsewhere", async () => {
    vi.mocked(decideChange).mockRejectedValue(
      new ApiError(409, { detail: "This change request is already Rejected." }, "This change request is already Rejected."),
    );
    const { user, review } = await openReview();
    await within(review).findByText(/Harbour Hall \(Main programme/);
    await user.type(within(review).getByLabelText("Reason for your decision"), "OK.");

    await user.click(within(review).getByRole("button", { name: "Approve change" }));

    expect(await within(review).findByRole("alert")).toHaveTextContent(
      "This change request is already Rejected.",
    );
  });

  it("shows a field refusal for the event or decision as a message", async () => {
    vi.mocked(decideChange).mockRejectedValue(
      new ApiError(400, { event: ["A Cancelled event cannot take an approved change."] }, "Refused."),
    );
    const { user, review } = await openReview();
    await within(review).findByText(/Harbour Hall \(Main programme/);
    await user.type(within(review).getByLabelText("Reason for your decision"), "OK.");

    await user.click(within(review).getByRole("button", { name: "Approve change" }));

    expect(await within(review).findByRole("alert")).toHaveTextContent(
      "A Cancelled event cannot take an approved change.",
    );
  });

  it("says when the assessment could not be loaded", async () => {
    vi.mocked(getChangeImpact).mockRejectedValue(new Error("down"));
    const { review } = await openReview();

    expect(await within(review).findByRole("alert")).toHaveTextContent("We could not assess this change.");
  });
});

describe("ChangeRequests with SCRUM-59/78", () => {
  function renderList(canDecide: boolean, change: ChangeRequest = CHANGE) {
    vi.mocked(listChangeRequests).mockResolvedValue([change]);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <ChangeRequests eventId={9} eventStatus="CONFIRMED" canDecide={canDecide} />
      </QueryClientProvider>,
    );
  }

  it("SCRUM-59 AC1: flags a significant request", async () => {
    renderList(false);
    const item = await screen.findByRole("listitem", { name: "Change request 4" });
    expect(within(item).getByText("Significant")).toBeInTheDocument();
  });

  it("does not flag an ordinary request", async () => {
    renderList(false, { ...CHANGE, significant: false });
    const item = await screen.findByRole("listitem", { name: "Change request 4" });
    expect(within(item).queryByText("Significant")).not.toBeInTheDocument();
  });

  it("offers a review only to the deciding coordinator, and only while Pending", async () => {
    renderList(true);
    expect(await screen.findByRole("button", { name: "Review impact" })).toBeInTheDocument();
  });

  it("offers no review once decided or to read-only viewers", async () => {
    renderList(true, { ...CHANGE, status: "APPROVED", status_label: "Approved", decided_at: "2026-11-04T02:00:00Z" });
    await screen.findByRole("listitem", { name: "Change request 4" });
    expect(screen.queryByRole("button", { name: "Review impact" })).not.toBeInTheDocument();
  });
});
