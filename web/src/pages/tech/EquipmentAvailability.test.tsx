import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import {
  fetchAvailability,
  fetchHolders,
  listEquipmentRequests,
  type AvailabilityRow,
  type EquipmentRequest,
} from "../../api/equipment";
import { EquipmentAvailability } from "./EquipmentAvailability";

vi.mock("../../api/equipment", () => ({
  fetchAvailability: vi.fn(),
  fetchHolders: vi.fn(),
  listEquipmentRequests: vi.fn(),
  reserveEquipment: vi.fn(),
  markUnavailable: vi.fn(),
  reviewEquipmentRequest: vi.fn(),
  releaseReservation: vi.fn(),
}));

const START = "2026-10-20T01:00:00Z";
const END = "2026-10-20T07:00:00Z";

function row(overrides: Partial<AvailabilityRow> = {}): AvailabilityRow {
  return {
    equipment: 3,
    name: "Projector",
    category: "AV",
    total_quantity: 5,
    out_of_service_quantity: 0,
    out_of_service_reason: "",
    expected_return: null,
    reserved_for_other_events: 0,
    available_quantity: 5,
    status: "Available",
    ...overrides,
  };
}

const summitRequest = { id: 1, event: 9, event_name: "Partner Summit" } as EquipmentRequest;

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <EquipmentAvailability />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SCRUM-12 equipment availability", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listEquipmentRequests).mockResolvedValue([summitRequest]);
  });

  it("AC1: checks availability for an event and shows the shortfall", async () => {
    vi.mocked(fetchAvailability).mockResolvedValue({
      event: 9,
      start: START,
      end: END,
      results: [
        row({ requested_quantity: 2, reserved_for_this_event: 0, shortfall: 0 }),
        row({
          equipment: 4,
          name: "Microphone",
          total_quantity: 4,
          out_of_service_quantity: 1,
          reserved_for_other_events: 2,
          available_quantity: 1,
          requested_quantity: 3,
          reserved_for_this_event: 0,
          shortfall: 2,
          status: "Short by 2",
        }),
      ],
    });

    renderPage();
    await screen.findByRole("option", { name: "Partner Summit" });
    await userEvent.selectOptions(screen.getByLabelText("Event"), "9");
    await userEvent.click(screen.getByRole("button", { name: "Check availability" }));

    expect(fetchAvailability).toHaveBeenCalledWith({ event: 9 });
    const mic = (await screen.findByText("Microphone")).closest("tr")!;
    const cells = within(mic)
      .getAllByRole("cell")
      .map((c) => c.textContent);
    // name, total, out of service, reserved elsewhere, available, requested, shortfall, status
    expect(cells.slice(1, 8)).toEqual(["4", "1", "2", "1", "3", "2", "Short by 2"]);
    expect(within(mic).getByText("Short by 2")).toHaveClass("text-rose-700");
    const projector = screen.getByText("Projector").closest("tr")!;
    expect(within(projector).getByText("Available")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Equipment requests" })).toHaveAttribute(
      "href",
      "/equipment",
    );
  });

  it("AC6: checks a chosen period and shows unavailable equipment", async () => {
    vi.mocked(fetchAvailability).mockResolvedValue({
      event: null,
      start: START,
      end: END,
      results: [
        row({ reserved_for_other_events: 5, available_quantity: 0, status: "Unavailable" }),
      ],
    });

    renderPage();
    await userEvent.click(screen.getByLabelText("A period"));
    await userEvent.type(screen.getByLabelText("Start"), "2026-10-20T09:00");
    await userEvent.type(screen.getByLabelText("End"), "2026-10-20T15:00");
    await userEvent.click(screen.getByRole("button", { name: "Check availability" }));

    expect(fetchAvailability).toHaveBeenCalledWith({
      start: new Date("2026-10-20T09:00").toISOString(),
      end: new Date("2026-10-20T15:00").toISOString(),
    });
    expect(await screen.findByText("Unavailable")).toHaveClass("text-rose-700");
    expect(screen.queryByRole("columnheader", { name: "Shortfall" })).not.toBeInTheDocument();
  });

  it("AC1: validates the choice before asking the API", async () => {
    renderPage();
    await userEvent.click(screen.getByRole("button", { name: "Check availability" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Choose an event.");

    await userEvent.click(screen.getByLabelText("A period"));
    await userEvent.type(screen.getByLabelText("Start"), "2026-10-20T15:00");
    await userEvent.type(screen.getByLabelText("End"), "2026-10-20T09:00");
    await userEvent.click(screen.getByRole("button", { name: "Check availability" }));
    expect(screen.getByRole("alert")).toHaveTextContent("The end must be after the start.");
    expect(fetchAvailability).not.toHaveBeenCalled();
  });

  it("AC1: shows the API refusal", async () => {
    vi.mocked(fetchAvailability).mockRejectedValue(
      new ApiError(
        400,
        { detail: "The event has no date and time yet." },
        "The event has no date and time yet.",
      ),
    );

    renderPage();
    await screen.findByRole("option", { name: "Partner Summit" });
    await userEvent.selectOptions(screen.getByLabelText("Event"), "9");
    await userEvent.click(screen.getByRole("button", { name: "Check availability" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The event has no date and time yet.",
    );
  });
});

describe("SCRUM-76 who holds unavailable equipment", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listEquipmentRequests).mockResolvedValue([summitRequest]);
    vi.mocked(fetchAvailability).mockResolvedValue({
      event: 9,
      start: START,
      end: END,
      results: [
        row({
          out_of_service_quantity: 2,
          out_of_service_reason: "Lamp replacement",
          expected_return: "2026-10-25",
          reserved_for_other_events: 3,
          available_quantity: 0,
          requested_quantity: 2,
          reserved_for_this_event: 0,
          shortfall: 2,
          status: "Short by 2",
        }),
        row({ equipment: 4, name: "Speaker", requested_quantity: 0, shortfall: 0 }),
      ],
    });
  });

  async function checkSummit() {
    renderPage();
    await screen.findByRole("option", { name: "Partner Summit" });
    await userEvent.selectOptions(screen.getByLabelText("Event"), "9");
    await userEvent.click(screen.getByRole("button", { name: "Check availability" }));
  }

  it("AC1/AC2: lists the events holding it with dates, and the out-of-service reason and return", async () => {
    vi.mocked(fetchHolders).mockResolvedValue({
      equipment: 3,
      name: "Projector",
      out_of_service_quantity: 2,
      out_of_service_reason: "Lamp replacement",
      expected_return: "2026-10-25",
      holding_events: [
        {
          event: 12,
          event_name: "Board Meeting",
          event_status: "Approved",
          start: START,
          end: END,
          quantity: 3,
          coordinator_name: "Cora Coordinator",
        },
      ],
    });

    await checkSummit();
    expect(screen.queryByRole("button", { name: "Who holds Speaker?" })).not.toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Who holds Projector?" }));

    expect(fetchHolders).toHaveBeenCalledWith(3, { event: 9 });
    const holders = await screen.findByLabelText("Holders of Projector");
    const period = `${new Date(START).toLocaleString("en-SG")} – ${new Date(END).toLocaleString("en-SG")}`;
    expect(within(holders).getByText("Board Meeting").closest("li")).toHaveTextContent(
      `Board Meeting (Approved) holds 3, ${period} · coordinator Cora Coordinator`,
    );
    expect(holders).toHaveTextContent(
      `2 out of service: Lamp replacement · expected back ${new Date("2026-10-25").toLocaleDateString("en-SG")}`,
    );
  });

  it("AC1: shows the API refusal when holders cannot be loaded", async () => {
    vi.mocked(fetchHolders).mockRejectedValue(
      new ApiError(403, null, "Only Technical Support Staff can do this."),
    );

    await checkSummit();
    await userEvent.click(await screen.findByRole("button", { name: "Who holds Projector?" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Only Technical Support Staff can do this.",
    );
  });
});
