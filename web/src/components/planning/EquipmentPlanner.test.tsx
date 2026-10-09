import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  amendEquipmentRequest,
  createEquipmentRequest,
  fetchEquipmentAvailability,
  fetchEquipmentRequests,
  listEquipmentTypes,
  withdrawEquipmentRequest,
  type EquipmentRequest,
} from "../../api/planning";
import { EquipmentPlanner } from "./EquipmentPlanner";
import { planningEvent } from "./fixtures";

vi.mock("../../api/planning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../api/planning")>()),
  listEquipmentTypes: vi.fn(),
  fetchEquipmentRequests: vi.fn(),
  createEquipmentRequest: vi.fn(),
  amendEquipmentRequest: vi.fn(),
  withdrawEquipmentRequest: vi.fn(),
  fetchEquipmentAvailability: vi.fn(),
}));

function item(overrides: Partial<EquipmentRequest> = {}): EquipmentRequest {
  return {
    id: 21,
    event: 9,
    equipment_type: 1,
    equipment_name: "Projector",
    quantity: 2,
    technical_requirements: "HDMI",
    status: "RESERVED",
    status_display: "Reserved",
    reserved_quantity: 2,
    requested_by_name: "Cora Coordinator",
    created_at: "2026-10-01T01:00:00Z",
    unavailable_reason: "",
    review_required: false,
    review_reason: "",
    changes: [],
    ...overrides,
  };
}

function renderPlanner(event = planningEvent()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EquipmentPlanner event={event} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listEquipmentTypes).mockResolvedValue([
    { id: 1, name: "Projector", category: "AV", total_quantity: 5 },
    { id: 2, name: "Microphone", category: "AV", total_quantity: 10 },
  ]);
  vi.mocked(fetchEquipmentRequests).mockResolvedValue([]);
  vi.mocked(fetchEquipmentAvailability).mockResolvedValue({
    event: 9,
    start: "2026-11-20T01:00:00Z",
    end: "2026-11-20T07:00:00Z",
    results: [],
  });
});

describe("SCRUM-74 record equipment requirements", () => {
  it("AC1: adds an equipment request for the event", async () => {
    vi.mocked(createEquipmentRequest).mockResolvedValue(item());

    renderPlanner();
    await screen.findByRole("option", { name: "Microphone" });
    await userEvent.selectOptions(screen.getByLabelText("Equipment type"), "2");
    const quantity = screen.getByLabelText("Quantity");
    await userEvent.clear(quantity);
    await userEvent.type(quantity, "4");
    await userEvent.type(screen.getByLabelText("Technical requirements"), "Wireless");
    await userEvent.click(screen.getByRole("button", { name: "Add equipment request" }));

    expect(createEquipmentRequest).toHaveBeenCalledWith({
      event: 9,
      equipment_type: 2,
      quantity: 4,
      technical_requirements: "Wireless",
    });
    expect(fetchEquipmentRequests).toHaveBeenCalledTimes(2);
  });

  it("AC2: a quantity below 1 is blocked before sending", async () => {
    renderPlanner();
    await screen.findByRole("option", { name: "Projector" });
    await userEvent.selectOptions(screen.getByLabelText("Equipment type"), "1");
    const quantity = screen.getByLabelText("Quantity");
    await userEvent.clear(quantity);
    await userEvent.type(quantity, "0");
    await userEvent.click(screen.getByRole("button", { name: "Add equipment request" }));

    expect(screen.getByText("The quantity must be at least 1.")).toBeInTheDocument();
    expect(createEquipmentRequest).not.toHaveBeenCalled();
  });

  it("AC2: shows the API's field errors and refusals", async () => {
    vi.mocked(createEquipmentRequest)
      .mockRejectedValueOnce(
        new ApiError(400, { quantity: ["The quantity must be a whole number."] }, "Something went wrong."),
      )
      .mockRejectedValueOnce(
        new ApiError(409, { detail: "Equipment can be requested once the event is approved; it is Submitted." }, "Equipment can be requested once the event is approved; it is Submitted."),
      );

    renderPlanner();
    await screen.findByRole("option", { name: "Projector" });
    await userEvent.selectOptions(screen.getByLabelText("Equipment type"), "1");
    await userEvent.click(screen.getByRole("button", { name: "Add equipment request" }));
    expect(await screen.findByText("The quantity must be a whole number.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Add equipment request" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Equipment can be requested once the event is approved",
    );
  });

  it("AC3: shows each request's status, reserved quantity and change history", async () => {
    vi.mocked(fetchEquipmentRequests).mockResolvedValue([
      item({
        status: "REQUESTED",
        status_display: "Requested",
        quantity: 3,
        reserved_quantity: 1,
        changes: [
          {
            description: "Quantity changed from 2 to 3.",
            changed_by_name: "Cora Coordinator",
            changed_at: "2026-10-02T01:00:00Z",
          },
        ],
      }),
    ]);

    renderPlanner();

    expect(await screen.findByText(/3 x Projector/)).toBeInTheDocument();
    expect(screen.getByText(/· Requested/)).toBeInTheDocument();
    expect(screen.getByText(/Reserved 1 of 3/)).toBeInTheDocument();
    expect(screen.getByText(/Quantity changed from 2 to 3\./)).toBeInTheDocument();
  });
});

describe("SCRUM-75 amend or withdraw equipment", () => {
  it("AC1: amends the quantity and requirements", async () => {
    vi.mocked(fetchEquipmentRequests).mockResolvedValue([item()]);
    vi.mocked(amendEquipmentRequest).mockResolvedValue(item({ quantity: 3 }));

    renderPlanner();
    await userEvent.click(await screen.findByRole("button", { name: "Amend Projector" }));
    const quantity = screen.getByLabelText("Quantity", { selector: "#amend-quantity-21" });
    await userEvent.clear(quantity);
    await userEvent.type(quantity, "3");
    await userEvent.click(screen.getByRole("button", { name: "Save amendment" }));

    expect(amendEquipmentRequest).toHaveBeenCalledWith(21, {
      quantity: 3,
      technical_requirements: "HDMI",
    });
  });

  it("AC2: an amended quantity below 1 is blocked", async () => {
    vi.mocked(fetchEquipmentRequests).mockResolvedValue([item()]);

    renderPlanner();
    await userEvent.click(await screen.findByRole("button", { name: "Amend Projector" }));
    const quantity = screen.getByLabelText("Quantity", { selector: "#amend-quantity-21" });
    await userEvent.clear(quantity);
    await userEvent.type(quantity, "0");
    await userEvent.click(screen.getByRole("button", { name: "Save amendment" }));

    expect(screen.getByText("The quantity must be at least 1.")).toBeInTheDocument();
    expect(amendEquipmentRequest).not.toHaveBeenCalled();
  });

  it("AC3: withdraws a request, and shows a refusal", async () => {
    vi.mocked(fetchEquipmentRequests).mockResolvedValue([item()]);
    vi.mocked(withdrawEquipmentRequest).mockRejectedValue(
      new ApiError(409, null, "This equipment request has already been withdrawn."),
    );

    renderPlanner();
    await userEvent.click(await screen.findByRole("button", { name: "Withdraw Projector" }));

    expect(withdrawEquipmentRequest).toHaveBeenCalledWith(21);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This equipment request has already been withdrawn.",
    );
  });

  it("offers no actions on a withdrawn request", async () => {
    vi.mocked(fetchEquipmentRequests).mockResolvedValue([
      item({ status: "WITHDRAWN", status_display: "Withdrawn" }),
    ]);

    renderPlanner();

    expect(await screen.findByText(/· Withdrawn/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Amend Projector" })).not.toBeInTheDocument();
  });
});

describe("SCRUM-12 equipment availability for the event", () => {
  it("AC2/AC3: shows the quantity available and any shortfall", async () => {
    vi.mocked(fetchEquipmentAvailability).mockResolvedValue({
      event: 9,
      start: "2026-11-20T01:00:00Z",
      end: "2026-11-20T07:00:00Z",
      results: [
        {
          equipment: 1,
          name: "Projector",
          available_quantity: 1,
          requested_quantity: 3,
          reserved_for_this_event: 0,
          shortfall: 2,
          status: "Short by 2",
        },
      ],
    });

    renderPlanner();

    expect(await screen.findByText("Short by 2")).toBeInTheDocument();
    expect(fetchEquipmentAvailability).toHaveBeenCalledWith(9);
  });

  it("does not check availability for an event without a date", async () => {
    renderPlanner(planningEvent({ preferred_start: null, preferred_end: null }));

    expect(await screen.findByText("The event has no date and time yet.")).toBeInTheDocument();
    expect(fetchEquipmentAvailability).not.toHaveBeenCalled();
  });
});
