import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { listChangeRequests, requestChange } from "../../api/changeRequests";
import type { ChangeRequest, EventStatus } from "../../types";
import { ChangeRequests, proposedValues } from "./ChangeRequests";

vi.mock("../../api/changeRequests", () => ({
  listChangeRequests: vi.fn(),
  requestChange: vi.fn(),
}));

const WHAT = "Move the conference to the following Monday.";
const WHY = "Our keynote speaker can only attend that day.";

function change(overrides: Partial<ChangeRequest> = {}): ChangeRequest {
  return {
    id: 4,
    event: 9,
    description: WHAT,
    reason: WHY,
    proposed_values: { expected_attendance: 150 },
    proposed_changes: [
      { field: "expected_attendance", label: "Expected attendance", current: "120", proposed: "150" },
    ],
    target_bookings: [],
    target_equipment_requests: [],
    revision: 1,
    significant: true,
    status: "PENDING",
    status_label: "Pending",
    status_changed_at: "2026-11-03T01:00:00Z",
    requested_by_name: "Ada Organiser",
    requested_at: "2026-11-03T01:00:00Z",
    decided_by_name: null,
    decided_at: null,
    decision_reason: "",
    ...overrides,
  };
}

function renderSection(eventStatus: EventStatus = "CONFIRMED", canRequest = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChangeRequests eventId={9} eventStatus={eventStatus} canRequest={canRequest} />
    </QueryClientProvider>,
  );
}

describe("ChangeRequests (SCRUM-20)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listChangeRequests).mockResolvedValue([]);
  });

  it("AC1/AC2: sends what and why with only the filled-in new details, and shows the receipt", async () => {
    vi.mocked(requestChange).mockResolvedValue({
      detail: "Your change request has been sent and is Pending review.",
      change_request: change(),
    });
    const user = userEvent.setup();
    renderSection();

    await user.type(await screen.findByLabelText("What do you want changed?"), WHAT);
    await user.type(screen.getByLabelText("Why is the change needed?"), WHY);
    await user.type(screen.getByLabelText("Proposed attendance"), "150");
    await user.selectOptions(screen.getByLabelText("Proposed layout"), "Theatre");
    await user.click(screen.getByRole("button", { name: "Send change request" }));

    expect(requestChange).toHaveBeenCalledWith(9, {
      description: WHAT,
      reason: WHY,
      proposed_values: { expected_attendance: 150, required_layout: "THEATRE" },
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Your change request has been sent and is Pending review.",
    );
    // The form is cleared for the next request.
    expect(screen.getByLabelText("What do you want changed?")).toHaveValue("");
  });

  it("AC3: shows why a request without a description was not sent", async () => {
    vi.mocked(requestChange).mockRejectedValue(
      new ApiError(
        400,
        {
          detail: "The change request could not be sent.",
          description: ["Enter a description of the change."],
        },
        "The change request could not be sent.",
      ),
    );
    const user = userEvent.setup();
    renderSection();

    await user.type(await screen.findByLabelText("Why is the change needed?"), WHY);
    await user.click(screen.getByRole("button", { name: "Send change request" }));

    expect(await screen.findByText("Enter a description of the change.")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows a refused proposed value beside its own field", async () => {
    vi.mocked(requestChange).mockRejectedValue(
      new ApiError(
        400,
        { "proposed_values.expected_attendance": ["Expected attendance must be at least one person."] },
        "The change request could not be sent.",
      ),
    );
    const user = userEvent.setup();
    renderSection();

    await user.type(await screen.findByLabelText("What do you want changed?"), WHAT);
    await user.type(screen.getByLabelText("Why is the change needed?"), WHY);
    await user.type(screen.getByLabelText("Proposed attendance"), "0");
    await user.click(screen.getByRole("button", { name: "Send change request" }));

    expect(
      await screen.findByText("Expected attendance must be at least one person."),
    ).toBeInTheDocument();
  });

  it("AC4: shows the refusal for an event that no longer accepts changes", async () => {
    vi.mocked(requestChange).mockRejectedValue(
      new ApiError(
        400,
        { event: ["A change cannot be requested for a Cancelled event."] },
        "The change request could not be sent.",
      ),
    );
    const user = userEvent.setup();
    renderSection();

    await user.type(await screen.findByLabelText("What do you want changed?"), WHAT);
    await user.type(screen.getByLabelText("Why is the change needed?"), WHY);
    await user.click(screen.getByRole("button", { name: "Send change request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A change cannot be requested for a Cancelled event.",
    );
  });

  it("sends every proposed detail the organiser fills in", async () => {
    vi.mocked(requestChange).mockResolvedValue({ detail: "Sent.", change_request: change() });
    const user = userEvent.setup();
    renderSection();

    await user.type(await screen.findByLabelText("What do you want changed?"), WHAT);
    await user.type(screen.getByLabelText("Why is the change needed?"), WHY);
    await user.type(screen.getByLabelText("Proposed start"), "2027-03-08T09:00");
    await user.type(screen.getByLabelText("Proposed end"), "2027-03-08T17:00");
    await user.type(screen.getByLabelText("Proposed accessibility arrangements"), "Step-free access");
    await user.type(screen.getByLabelText("Proposed equipment needs"), "Two projectors");
    await user.click(screen.getByRole("button", { name: "Send change request" }));

    const [, sent] = vi.mocked(requestChange).mock.calls[0];
    expect(Object.keys(sent.proposed_values).sort()).toEqual([
      "accessibility_needs",
      "equipment_notes",
      "preferred_end",
      "preferred_start",
    ]);
    expect(sent.proposed_values.accessibility_needs).toBe("Step-free access");
  });

  it("names an unknown proposed field in a general message", async () => {
    vi.mocked(requestChange).mockRejectedValue(
      new ApiError(
        400,
        { proposed_values: ["These cannot be changed through a change request: status."] },
        "The change request could not be sent.",
      ),
    );
    const user = userEvent.setup();
    renderSection();

    await user.type(await screen.findByLabelText("What do you want changed?"), WHAT);
    await user.type(screen.getByLabelText("Why is the change needed?"), WHY);
    await user.click(screen.getByRole("button", { name: "Send change request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "These cannot be changed through a change request: status.",
    );
  });

  it("shows the refusal when the event belongs to another organisation", async () => {
    vi.mocked(requestChange).mockRejectedValue(
      new ApiError(403, {}, "You can only request changes to your own events."),
    );
    const user = userEvent.setup();
    renderSection();

    await user.type(await screen.findByLabelText("What do you want changed?"), WHAT);
    await user.type(screen.getByLabelText("Why is the change needed?"), WHY);
    await user.click(screen.getByRole("button", { name: "Send change request" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You can only request changes to your own events.",
    );
  });

  it.each(["CANCELLED", "COMPLETED", "REJECTED"] as EventStatus[])(
    "AC4: offers no form for a %s event",
    async (status) => {
      renderSection(status);

      expect(
        await screen.findByText("Changes cannot be requested for this event in its current status."),
      ).toBeInTheDocument();
      expect(screen.queryByRole("form", { name: "Request a change" })).not.toBeInTheDocument();
    },
  );

  it("AC5: lists each request with its status, proposed values and requester", async () => {
    vi.mocked(listChangeRequests).mockResolvedValue([change()]);
    renderSection();

    const item = await screen.findByRole("listitem", { name: "Change request 4" });
    expect(item).toHaveTextContent(WHAT);
    expect(item).toHaveTextContent(`Why: ${WHY}`);
    expect(item).toHaveTextContent("Pending");
    expect(item).toHaveTextContent("Expected attendance: 120 → 150");
    expect(item).toHaveTextContent("Requested by Ada Organiser");
  });

  it("AC5: shows the decision once one has been made", async () => {
    vi.mocked(listChangeRequests).mockResolvedValue([
      change({
        status: "REJECTED",
        status_label: "Rejected",
        decided_by_name: "Cora Coordinator",
        decided_at: "2026-11-04T01:00:00Z",
        decision_reason: "The venue is unavailable that day.",
      }),
    ]);
    renderSection();

    const item = await screen.findByRole("listitem", { name: "Change request 4" });
    expect(within(item).getByText(/Rejected by Cora Coordinator/)).toHaveTextContent(
      ": The venue is unavailable that day.",
    );
  });

  it("staff see the requests read-only", async () => {
    vi.mocked(listChangeRequests).mockResolvedValue([change()]);
    renderSection("CONFIRMED", false);

    expect(await screen.findByRole("listitem", { name: "Change request 4" })).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Request a change" })).not.toBeInTheDocument();
    expect(
      screen.queryByText("Changes cannot be requested for this event in its current status."),
    ).not.toBeInTheDocument();
  });

  it("has a clear empty state and announces a load failure", async () => {
    renderSection();
    expect(await screen.findByText("No changes have been requested.")).toBeInTheDocument();

    vi.mocked(listChangeRequests).mockRejectedValue(new Error("down"));
    renderSection();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We could not load the change requests.",
    );
  });
});

describe("proposedValues", () => {
  it("sends only the details that were filled in, typed", () => {
    expect(
      proposedValues({
        description: WHAT,
        reason: WHY,
        preferred_start: "",
        preferred_end: "",
        expected_attendance: "",
        required_layout: "",
        accessibility_needs: "   ",
        equipment_notes: "",
      }),
    ).toEqual({});
    const values = proposedValues({
      description: WHAT,
      reason: WHY,
      preferred_start: "2027-03-08T09:00",
      preferred_end: "2027-03-08T17:00",
      expected_attendance: "0",
      required_layout: "BANQUET",
      accessibility_needs: "Step-free access",
      equipment_notes: "Two projectors",
    });
    expect(values).toMatchObject({
      expected_attendance: 0,
      required_layout: "BANQUET",
      accessibility_needs: "Step-free access",
      equipment_notes: "Two projectors",
    });
    expect(new Date(values.preferred_start as string).getTime()).toBe(
      new Date("2027-03-08T09:00").getTime(),
    );
    expect(typeof values.preferred_end).toBe("string");
  });
});
