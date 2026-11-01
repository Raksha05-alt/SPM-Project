import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { listEquipmentTypes, listEventEquipment, requestEquipment } from "../../api/equipment";
import type { EquipmentRequest, EventRequest } from "../../types";
import { EquipmentRequests } from "./EquipmentRequests";

vi.mock("../../api/equipment", () => ({
  listEquipmentTypes: vi.fn(),
  listEventEquipment: vi.fn(),
  requestEquipment: vi.fn(),
}));

const EVENT = { id: 9, name: "Partner Summit", status: "APPROVED" } as unknown as EventRequest;
const NOTE = "HDMI and USB-C inputs; mount at the back";

function line(overrides: Partial<EquipmentRequest> = {}): EquipmentRequest {
  return {
    id: 1,
    event: 9,
    equipment_type: 4,
    equipment_type_name: "Projector",
    quantity: 3,
    technical_requirements: NOTE,
    status: "REQUESTED",
    status_label: "Requested",
    requested_by_name: "Cora Coordinator",
    requested_at: "2026-11-01T01:00:00Z",
    ...overrides,
  };
}

function renderSection(event: EventRequest = EVENT) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <EquipmentRequests event={event} />
    </QueryClientProvider>,
  );
}

describe("EquipmentRequests (SCRUM-74)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listEventEquipment).mockResolvedValue([]);
    vi.mocked(listEquipmentTypes).mockResolvedValue([
      { id: 4, code: "PROJECTOR", name: "Projector", description: "" },
      { id: 5, code: "MIC", name: "Wireless microphone", description: "" },
    ]);
  });

  it("AC1/AC4: sends the type, quantity and technical requirements and confirms", async () => {
    vi.mocked(requestEquipment).mockResolvedValue({
      detail: "Your request for 3 x Projector has been sent to Technical Support.",
      request: line(),
    });
    const user = userEvent.setup();
    renderSection();

    await user.selectOptions(await screen.findByLabelText("Equipment"), "Projector");
    await user.clear(screen.getByLabelText("Quantity"));
    await user.type(screen.getByLabelText("Quantity"), "3");
    await user.type(screen.getByLabelText(/Technical requirements/), NOTE);
    await user.click(screen.getByRole("button", { name: "Send request to Technical Support" }));

    expect(requestEquipment).toHaveBeenCalledWith(9, {
      equipment_type: 4,
      quantity: 3,
      technical_requirements: NOTE,
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Your request for 3 x Projector has been sent to Technical Support.",
    );
  });

  it("AC2: shows why a quantity of zero or less was refused, beside the field", async () => {
    vi.mocked(requestEquipment).mockRejectedValue(
      new ApiError(
        400,
        {
          detail: "The equipment request could not be saved.",
          quantity: ["The quantity must be a whole number of 1 or more."],
        },
        "The equipment request could not be saved.",
      ),
    );
    const user = userEvent.setup();
    renderSection();

    await user.selectOptions(await screen.findByLabelText("Equipment"), "Projector");
    await user.clear(screen.getByLabelText("Quantity"));
    await user.type(screen.getByLabelText("Quantity"), "0");
    await user.click(screen.getByRole("button", { name: "Send request to Technical Support" }));

    expect(requestEquipment).toHaveBeenCalledWith(9, expect.objectContaining({ quantity: 0 }));
    expect(
      await screen.findByText("The quantity must be a whole number of 1 or more."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("AC2: an empty quantity is sent as missing so the API can name it", async () => {
    vi.mocked(requestEquipment).mockRejectedValue(
      new ApiError(400, { quantity: ["Enter the quantity required."] }, "Bad request"),
    );
    const user = userEvent.setup();
    renderSection();

    await user.clear(await screen.findByLabelText("Quantity"));
    await user.click(screen.getByRole("button", { name: "Send request to Technical Support" }));

    expect(requestEquipment).toHaveBeenCalledWith(9, {
      equipment_type: null,
      quantity: null,
      technical_requirements: "",
    });
    expect(await screen.findByText("Enter the quantity required.")).toBeInTheDocument();
  });

  it("AC5: shows the refusal when the user is not the assigned coordinator", async () => {
    vi.mocked(requestEquipment).mockRejectedValue(
      new ApiError(403, {}, "Only the coordinator assigned to this event can request equipment."),
    );
    const user = userEvent.setup();
    renderSection();

    await user.selectOptions(await screen.findByLabelText("Equipment"), "Projector");
    await user.click(screen.getByRole("button", { name: "Send request to Technical Support" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only the coordinator assigned to this event can request equipment.",
    );
  });

  it("AC3/AC4: lists each request with quantity, requirements, who and when", async () => {
    vi.mocked(listEventEquipment).mockResolvedValue([line()]);
    renderSection();

    const row = await screen.findByRole("row", { name: /Projector/ });
    expect(row).toHaveTextContent("3");
    expect(row).toHaveTextContent(NOTE);
    expect(row).toHaveTextContent("Requested");
    expect(row).toHaveTextContent("by Cora Coordinator");
  });

  it("offers no form before the event is approved", async () => {
    renderSection({ ...EVENT, status: "SUBMITTED" } as EventRequest);

    expect(
      await screen.findByText("Equipment can be requested once this event has been approved."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "Request equipment" })).not.toBeInTheDocument();
    expect(listEquipmentTypes).not.toHaveBeenCalled();
  });
});
