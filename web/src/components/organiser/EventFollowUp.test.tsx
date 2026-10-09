import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  cancelEvent,
  createChangeRequest,
  getEventRegistrations,
  listChangeRequests,
  type ChangeRequest,
  type OrganiserEvent,
} from "../../api/organiser";
import { EventFollowUp, type FollowUpEvent } from "./EventFollowUp";

vi.mock("../../api/organiser", () => ({
  cancelEvent: vi.fn(),
  createChangeRequest: vi.fn(),
  getEventRegistrations: vi.fn(),
  listChangeRequests: vi.fn(),
}));

function event(overrides: Partial<FollowUpEvent> = {}): FollowUpEvent {
  return { id: 4, status: "PLANNING", registration_required: false, ...overrides };
}

function change(overrides: Partial<ChangeRequest> = {}): ChangeRequest {
  return {
    id: 1,
    event: 4,
    description: "Move to the afternoon",
    reason: "Speaker clash",
    proposed_start: null,
    proposed_end: null,
    proposed_attendance: null,
    proposed_layout: "",
    proposed_accessibility_needs: "",
    proposed_equipment_notes: "",
    status: "PENDING",
    status_display: "Pending",
    requested_by_name: "Ada Organiser",
    created_at: "2026-09-28T01:00:00Z",
    decided_by_name: null,
    decided_at: null,
    decision_reason: "",
    ...overrides,
  };
}

function renderPanel(e: FollowUpEvent) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EventFollowUp event={e} />
    </QueryClientProvider>,
  );
}

describe("SCRUM-58 confirmed arrangements", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listChangeRequests).mockResolvedValue([]);
  });

  it("AC5: a confirmed event shows the confirmed venues and equipment", async () => {
    renderPanel(
      event({
        status: "CONFIRMED",
        confirmed_arrangements: {
          venues: [
            {
              venue: "Harbour Hall",
              location: "Level 2",
              start: "2026-10-20T01:00:00Z",
              end: "2026-10-20T07:00:00Z",
            },
          ],
          equipment: [{ equipment: "Projector", quantity: 2 }],
        },
      }),
    );
    const section = screen.getByRole("region", { name: "Confirmed arrangements" });
    expect(within(section).getByText(/Harbour Hall, Level 2/)).toBeInTheDocument();
    expect(within(section).getByText("2 x Projector")).toBeInTheDocument();
  });

  it("AC5: nothing is shown before the event is confirmed", () => {
    renderPanel(event({ confirmed_arrangements: null }));
    expect(screen.queryByText("Confirmed arrangements")).not.toBeInTheDocument();
  });
});

describe("SCRUM-56 cancel a submitted event", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listChangeRequests).mockResolvedValue([]);
  });

  it("AC1/AC2: asks for confirmation and sends the optional reason", async () => {
    vi.mocked(cancelEvent).mockResolvedValue({ id: 4, status: "CANCELLED" } as OrganiserEvent);
    renderPanel(event());
    await userEvent.click(screen.getByRole("button", { name: "Cancel event" }));
    expect(cancelEvent).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Reason for cancelling (optional)"), "Budget cut");
    await userEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }));
    expect(cancelEvent).toHaveBeenCalledWith(4, "Budget cut");
  });

  it("AC2: the reason is optional", async () => {
    vi.mocked(cancelEvent).mockResolvedValue({ id: 4, status: "CANCELLED" } as OrganiserEvent);
    renderPanel(event());
    await userEvent.click(screen.getByRole("button", { name: "Cancel event" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }));
    expect(cancelEvent).toHaveBeenCalledWith(4, "");
  });

  it("AC3: shows the refusal when the API will not cancel", async () => {
    vi.mocked(cancelEvent).mockRejectedValue(
      new ApiError(409, { detail: "This event cannot be cancelled." }, "This event cannot be cancelled."),
    );
    renderPanel(event());
    await userEvent.click(screen.getByRole("button", { name: "Cancel event" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This event cannot be cancelled.");
  });

  it("AC4: a cancelled event shows its reason and cannot be cancelled again", () => {
    renderPanel(event({ status: "CANCELLED", cancellation_reason: "Budget cut" }));
    expect(screen.getByText("Reason: Budget cut")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel event" })).not.toBeInTheDocument();
  });
});

describe("SCRUM-20 change requests", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: raises a change request with the proposed values", async () => {
    vi.mocked(listChangeRequests).mockResolvedValue([]);
    vi.mocked(createChangeRequest).mockResolvedValue(change());
    renderPanel(event());
    await userEvent.type(screen.getByLabelText("What should change?"), "More seats");
    await userEvent.type(screen.getByLabelText("Why (optional)"), "Popular");
    await userEvent.type(screen.getByLabelText("New expected attendance"), "150");
    await userEvent.click(screen.getByRole("button", { name: "Send change request" }));
    expect(createChangeRequest).toHaveBeenCalledWith(
      4,
      expect.objectContaining({ description: "More seats", reason: "Popular", proposed_attendance: 150 }),
    );
    expect(await screen.findByRole("status")).toHaveTextContent("Your change request has been sent");
  });

  it("AC2: a description is required before anything is sent", async () => {
    vi.mocked(listChangeRequests).mockResolvedValue([]);
    renderPanel(event());
    await userEvent.click(screen.getByRole("button", { name: "Send change request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Describe the change you want.");
    expect(createChangeRequest).not.toHaveBeenCalled();
  });

  it("AC2: shows field errors returned by the API", async () => {
    vi.mocked(listChangeRequests).mockResolvedValue([]);
    vi.mocked(createChangeRequest).mockRejectedValue(
      new ApiError(400, { proposed_start: ["The new start cannot be in the past."] }, "Something went wrong."),
    );
    renderPanel(event());
    await userEvent.type(screen.getByLabelText("What should change?"), "Earlier");
    await userEvent.click(screen.getByRole("button", { name: "Send change request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The new start cannot be in the past.");
  });

  it("AC4: shows the refusal when the event can no longer change", async () => {
    vi.mocked(listChangeRequests).mockResolvedValue([]);
    vi.mocked(createChangeRequest).mockRejectedValue(
      new ApiError(409, { detail: "This event can no longer be changed." }, "This event can no longer be changed."),
    );
    renderPanel(event());
    await userEvent.type(screen.getByLabelText("What should change?"), "Earlier");
    await userEvent.click(screen.getByRole("button", { name: "Send change request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This event can no longer be changed.");
  });

  it("AC4: hides the form for cancelled, completed and rejected events", async () => {
    vi.mocked(listChangeRequests).mockResolvedValue([]);
    for (const status of ["CANCELLED", "COMPLETED", "REJECTED"] as const) {
      const { unmount } = renderPanel(event({ status }));
      expect(await screen.findByText("No changes have been requested.")).toBeInTheDocument();
      expect(screen.queryByLabelText("What should change?")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("AC5: lists change requests with their status and decision", async () => {
    vi.mocked(listChangeRequests).mockResolvedValue([
      change(),
      change({
        id: 2,
        description: "Add a microphone",
        status: "REJECTED",
        status_display: "Rejected",
        decided_by_name: "Cora Coordinator",
        decided_at: "2026-09-29T01:00:00Z",
        decision_reason: "None available",
      }),
    ]);
    renderPanel(event());
    const list = await screen.findByRole("list", { name: "Change requests" });
    expect(within(list).getByText("Move to the afternoon")).toBeInTheDocument();
    expect(within(list).getByText("Pending")).toBeInTheDocument();
    expect(within(list).getByText(/by Cora Coordinator · Reason: None available/)).toBeInTheDocument();
  });
});

describe("SCRUM-14 / SCRUM-19 registrations for the organiser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listChangeRequests).mockResolvedValue([]);
  });

  it("SCRUM-14 AC5 / SCRUM-19 AC4: shows counts and each registration's status", async () => {
    vi.mocked(getEventRegistrations).mockResolvedValue({
      capacity: 100,
      registered_count: 1,
      waitlist_count: 1,
      places_left: 99,
      registrations: [
        {
          id: 1,
          full_name: "Ann Attendee",
          email: "ann@example.com",
          accessibility_needs: "",
          status: "REGISTERED",
          status_display: "Registered",
          registered_at: "2026-09-28T01:00:00Z",
          waitlisted_at: null,
          withdrawn_at: null,
        },
        {
          id: 2,
          full_name: "Ben Waiting",
          email: "ben@example.com",
          accessibility_needs: "Wheelchair",
          status: "WAITLISTED",
          status_display: "On waiting list",
          registered_at: null,
          waitlisted_at: "2026-09-28T02:00:00Z",
          withdrawn_at: null,
        },
      ],
    });
    renderPanel(event({ status: "CONFIRMED", registration_required: true }));
    expect(
      await screen.findByText("1 registered of 100 places · 1 on the waiting list · 99 places left"),
    ).toBeInTheDocument();
    expect(screen.getByText("Ann Attendee")).toBeInTheDocument();
    expect(screen.getByText("On waiting list")).toBeInTheDocument();
  });

  it("does not ask for registrations when the event takes none", () => {
    renderPanel(event());
    expect(getEventRegistrations).not.toHaveBeenCalled();
  });
});
