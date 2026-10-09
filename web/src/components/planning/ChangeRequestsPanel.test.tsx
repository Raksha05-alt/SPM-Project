import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  approveChangeRequest,
  fetchChangeRequest,
  fetchChangeRequests,
  rejectChangeRequest,
  type ChangeRequest,
} from "../../api/planning";
import { ChangeRequestsPanel } from "./ChangeRequestsPanel";

vi.mock("../../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/planning")>()),
  fetchChangeRequests: vi.fn(),
  fetchChangeRequest: vi.fn(),
  approveChangeRequest: vi.fn(),
  rejectChangeRequest: vi.fn(),
}));

function change(overrides: Partial<ChangeRequest> = {}): ChangeRequest {
  return {
    id: 31,
    event: 9,
    description: "Move to the afternoon",
    reason: "Speaker delayed",
    proposed_start: "2026-11-20T05:00:00Z",
    proposed_end: "2026-11-20T09:00:00Z",
    proposed_attendance: 150,
    proposed_layout: "",
    proposed_accessibility_needs: "",
    proposed_equipment_notes: "",
    status: "PENDING",
    status_display: "Pending",
    requested_by_name: "Ada Organiser",
    created_at: "2026-10-01T01:00:00Z",
    decided_by_name: null,
    decided_at: null,
    decision_reason: "",
    ...overrides,
  };
}

function renderPanel(canDecide = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChangeRequestsPanel eventId={9} canDecide={canDecide} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchChangeRequests).mockResolvedValue([change()]);
});

describe("SCRUM-78 review a change request's impact", () => {
  it("AC1: lists the change requests with what is proposed", async () => {
    vi.mocked(fetchChangeRequests).mockResolvedValue([
      change(),
      change({
        id: 32,
        description: "Add a microphone",
        proposed_attendance: null,
        status: "REJECTED",
        status_display: "Rejected",
        decided_by_name: "Cora Coordinator",
        decided_at: "2026-10-02T01:00:00Z",
        decision_reason: "None available",
      }),
    ]);

    renderPanel();

    expect(await screen.findByText("Move to the afternoon")).toBeInTheDocument();
    expect(fetchChangeRequests).toHaveBeenCalledWith(9);
    expect(screen.getByText("Attendance: 150")).toBeInTheDocument();
    expect(screen.getByText(/Rejected by Cora Coordinator .*None available/)).toBeInTheDocument();
  });

  it("AC2/AC3: shows affected bookings, equipment and registrations", async () => {
    vi.mocked(fetchChangeRequest).mockResolvedValue(
      change({
        impact: {
          changed_fields: ["expected attendance", "start time"],
          venue_bookings: [
            {
              booking: 11,
              venue: "Hall A",
              status: "Approved",
              current_start: "2026-11-20T01:00:00Z",
              current_end: "2026-11-20T07:00:00Z",
              new_start: "2026-11-20T05:00:00Z",
              new_end: "2026-11-20T11:00:00Z",
              potentially_unsuitable: true,
              issues: ["Expected attendance of 150 exceeds the venue's capacity of 120."],
              conflicts: [
                {
                  event: 40,
                  event_name: "Board Meeting",
                  start: "2026-11-20T08:00:00Z",
                  end: "2026-11-20T10:00:00Z",
                },
              ],
            },
          ],
          equipment: [
            {
              request: 21,
              equipment: "Projector",
              quantity: 2,
              reserved_quantity: 2,
              available_in_new_period: 1,
              issues: ["Only 1 available in the new period; 2 needed."],
            },
          ],
          registrations: { registered: 30, waitlisted: 2, issues: [] },
          has_impact: true,
          message: null,
        },
      }),
    );

    renderPanel();
    await userEvent.click(
      await screen.findByRole("button", { name: "Review impact of Move to the afternoon" }),
    );

    expect(await screen.findByText(/Hall A \(Approved\)/)).toBeInTheDocument();
    expect(fetchChangeRequest).toHaveBeenCalledWith(31);
    expect(screen.getByText("Potentially unsuitable")).toBeInTheDocument();
    expect(
      screen.getByText("Expected attendance of 150 exceeds the venue's capacity of 120."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Conflicts with Board Meeting/)).toBeInTheDocument();
    expect(screen.getByText("Only 1 available in the new period; 2 needed.")).toBeInTheDocument();
    expect(screen.getByText("30 registered, 2 on the waiting list")).toBeInTheDocument();
  });

  it("AC4: says when the change affects no arrangements", async () => {
    vi.mocked(fetchChangeRequest).mockResolvedValue(
      change({
        impact: {
          changed_fields: ["start time"],
          venue_bookings: [],
          equipment: [],
          registrations: null,
          has_impact: false,
          message: "This change does not affect any existing arrangements.",
        },
      }),
    );

    renderPanel();
    await userEvent.click(
      await screen.findByRole("button", { name: "Review impact of Move to the afternoon" }),
    );

    expect(
      await screen.findByText("This change does not affect any existing arrangements."),
    ).toBeInTheDocument();
  });
});

describe("SCRUM-78 AC5 decide on a change request", () => {
  beforeEach(() => {
    vi.mocked(fetchChangeRequest).mockResolvedValue(
      change({
        impact: {
          changed_fields: [],
          venue_bookings: [],
          equipment: [],
          registrations: null,
          has_impact: false,
          message: "This change does not affect any existing arrangements.",
        },
      }),
    );
  });

  async function open() {
    await userEvent.click(
      await screen.findByRole("button", { name: "Review impact of Move to the afternoon" }),
    );
    await screen.findByText("This change does not affect any existing arrangements.");
  }

  it("approves with a reason", async () => {
    vi.mocked(approveChangeRequest).mockResolvedValue(change({ status: "APPROVED" }));

    renderPanel();
    await open();
    await userEvent.type(screen.getByLabelText("Reason for your decision"), "Venue is free");
    await userEvent.click(screen.getByRole("button", { name: "Approve change" }));

    expect(approveChangeRequest).toHaveBeenCalledWith(31, "Venue is free");
  });

  it("rejects with a reason", async () => {
    vi.mocked(rejectChangeRequest).mockResolvedValue(change({ status: "REJECTED" }));

    renderPanel();
    await open();
    await userEvent.type(screen.getByLabelText("Reason for your decision"), "Hall is taken");
    await userEvent.click(screen.getByRole("button", { name: "Reject change" }));

    expect(rejectChangeRequest).toHaveBeenCalledWith(31, "Hall is taken");
  });

  it("a decision without a reason is blocked", async () => {
    renderPanel();
    await open();
    await userEvent.click(screen.getByRole("button", { name: "Reject change" }));

    expect(screen.getByText("Enter a reason for your decision.")).toBeInTheDocument();
    expect(rejectChangeRequest).not.toHaveBeenCalled();
  });

  it("shows the API's refusal", async () => {
    vi.mocked(approveChangeRequest).mockRejectedValue(
      new ApiError(409, null, "This change request has already been approved."),
    );

    renderPanel();
    await open();
    await userEvent.type(screen.getByLabelText("Reason for your decision"), "OK");
    await userEvent.click(screen.getByRole("button", { name: "Approve change" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This change request has already been approved.",
    );
  });

  it("a coordinator who is not assigned can view the impact but not decide", async () => {
    renderPanel(false);
    await open();

    expect(screen.queryByRole("button", { name: "Approve change" })).not.toBeInTheDocument();
  });
});
