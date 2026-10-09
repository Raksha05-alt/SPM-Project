import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  cancelEvent,
  completeEvent,
  confirmEvent,
  listCoordinators,
  reassignEvent,
} from "../../api/planning";
import { EventActions } from "./EventActions";
import { planningEvent } from "./fixtures";

vi.mock("../../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/planning")>()),
  confirmEvent: vi.fn(),
  cancelEvent: vi.fn(),
  completeEvent: vi.fn(),
  reassignEvent: vi.fn(),
  listCoordinators: vi.fn(),
  updateEvent: vi.fn(),
}));

function renderActions(event = planningEvent()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EventActions event={event} />
    </QueryClientProvider>,
  );
}

describe("SCRUM-58 confirm an event", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: the assigned coordinator confirms a planned event", async () => {
    vi.mocked(confirmEvent).mockResolvedValue(planningEvent({ status: "CONFIRMED" }));

    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Confirm event" }));

    expect(confirmEvent).toHaveBeenCalledWith(9);
  });

  it("AC2: shows each missing arrangement when confirmation is refused", async () => {
    vi.mocked(confirmEvent).mockRejectedValue(
      new ApiError(
        409,
        {
          detail: "The event cannot be confirmed until every essential arrangement is in place.",
          missing: [
            { arrangement: "Venue", detail: "No venue booking has been approved." },
            { arrangement: "Equipment", detail: "2 x Projector is awaiting reservation." },
          ],
        },
        "The event cannot be confirmed until every essential arrangement is in place.",
      ),
    );

    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Confirm event" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("cannot be confirmed");
    expect(alert).toHaveTextContent("Venue: No venue booking has been approved.");
    expect(alert).toHaveTextContent("Equipment: 2 x Projector is awaiting reservation.");
  });

  it("offers no Confirm button outside Planning", async () => {
    renderActions(planningEvent({ status: "APPROVED" }));

    expect(screen.queryByRole("button", { name: "Confirm event" })).not.toBeInTheDocument();
  });
});

describe("SCRUM-56 cancel and complete", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: cancelling asks for confirmation and sends the optional reason", async () => {
    vi.mocked(cancelEvent).mockResolvedValue(planningEvent({ status: "CANCELLED" }));

    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Cancel event" }));
    expect(cancelEvent).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Reason (optional)"), "Client withdrew");
    await userEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }));

    expect(cancelEvent).toHaveBeenCalledWith(9, "Client withdrew");
  });

  it("AC1: a cancellation without a reason is allowed", async () => {
    vi.mocked(cancelEvent).mockResolvedValue(planningEvent({ status: "CANCELLED" }));

    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Cancel event" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm cancellation" }));

    expect(cancelEvent).toHaveBeenCalledWith(9, "");
  });

  it("AC2: backing out of the confirm step does not cancel", async () => {
    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Cancel event" }));
    await userEvent.click(screen.getByRole("button", { name: "Keep event" }));

    expect(cancelEvent).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Cancel event" })).toBeInTheDocument();
  });

  it("AC3: marks a confirmed event completed, and shows a refusal", async () => {
    vi.mocked(completeEvent).mockRejectedValue(
      new ApiError(409, null, "An event can only be marked completed after it has taken place."),
    );

    renderActions(planningEvent({ status: "CONFIRMED" }));
    await userEvent.click(screen.getByRole("button", { name: "Mark completed" }));

    expect(completeEvent).toHaveBeenCalledWith(9);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An event can only be marked completed after it has taken place.",
    );
  });

  it("AC4: offers no actions on a closed event", () => {
    renderActions(planningEvent({ status: "COMPLETED" }));

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("SCRUM-53 reassign an event", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: picks another coordinator from the list", async () => {
    vi.mocked(listCoordinators).mockResolvedValue([
      { id: 2, name: "Cora Coordinator", email: "cora@example.com", available: true },
      { id: 5, name: "Dan Delegate", email: "dan@example.com", available: true },
    ]);
    vi.mocked(reassignEvent).mockResolvedValue(planningEvent({ coordinator: 5 }));

    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Reassign" }));
    await screen.findByRole("option", { name: "Dan Delegate" });
    expect(screen.queryByRole("option", { name: "Cora Coordinator" })).not.toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("New coordinator"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Confirm reassignment" }));

    expect(reassignEvent).toHaveBeenCalledWith(9, 5);
  });

  it("AC2: a coordinator must be chosen", async () => {
    vi.mocked(listCoordinators).mockResolvedValue([]);

    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Reassign" }));
    await userEvent.click(screen.getByRole("button", { name: "Confirm reassignment" }));

    expect(screen.getByText("Choose a coordinator.")).toBeInTheDocument();
    expect(reassignEvent).not.toHaveBeenCalled();
  });

  it("AC3: shows the API's refusal", async () => {
    vi.mocked(listCoordinators).mockResolvedValue([
      { id: 5, name: "Dan Delegate", email: "dan@example.com", available: true },
    ]);
    vi.mocked(reassignEvent).mockRejectedValue(
      new ApiError(400, { coordinator: ["Choose an active Event Coordinator."] }, "Choose an active Event Coordinator."),
    );

    renderActions();
    await userEvent.click(screen.getByRole("button", { name: "Reassign" }));
    await screen.findByRole("option", { name: "Dan Delegate" });
    await userEvent.selectOptions(screen.getByLabelText("New coordinator"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Confirm reassignment" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Choose an active Event Coordinator.",
    );
  });
});
