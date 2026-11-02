import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getEquipmentHolders } from "../../api/equipment";
import type { EquipmentHolders } from "../../types";
import { EquipmentHoldersPanel } from "./EquipmentHoldersPanel";

vi.mock("../../api/equipment", () => ({ getEquipmentHolders: vi.fn() }));

const PERIOD = { starts_at: "2026-12-01T02:00:00Z", ends_at: "2026-12-01T04:00:00Z" };

const BASE: EquipmentHolders = {
  period: PERIOD,
  availability: {
    equipment_type: 1,
    code: "PROJECTOR",
    name: "Projector",
    in_service: true,
    total_quantity: 10,
    unavailable_quantity: 1,
    unavailable: [
      {
        quantity: 1,
        cause: "MAINTENANCE",
        cause_label: "Under maintenance",
        reason: "Lamp replacement",
        expected_return_at: null,
      },
    ],
    reserved_for_other_events: 7,
    reserved_for_this_event: 0,
    available_quantity: 2,
    requested_quantity: 5,
    shortfall: 3,
    status: "PARTIAL",
  },
  holders: [
    {
      reservation: 11,
      quantity: 3,
      starts_at: "2026-12-01T01:00:00Z",
      ends_at: "2026-12-01T04:00:00Z",
      event: {
        id: 4,
        name: "Board Offsite",
        status: "PLANNING",
        status_label: "Planning",
        coordinator: { name: "Casey Coordinator", email: "casey@connectsphere.example" },
      },
    },
  ],
};

function renderPanel(onClose = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <EquipmentHoldersPanel eventId={9} equipmentTypeId={1} period={PERIOD} onClose={onClose} />
    </QueryClientProvider>,
  );
  return onClose;
}

describe("EquipmentHoldersPanel (SCRUM-76)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("AC1: Technical Support see each holding event, its dates and coordinator", async () => {
    vi.mocked(getEquipmentHolders).mockResolvedValue(BASE);
    renderPanel();

    expect(await screen.findByText("Board Offsite")).toBeInTheDocument();
    expect(screen.getByText(/Planning/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "casey@connectsphere.example" })).toHaveAttribute(
      "href",
      "mailto:casey@connectsphere.example",
    );
    expect(screen.getByText(/^3 held ·/)).toBeInTheDocument();
    expect(getEquipmentHolders).toHaveBeenCalledWith(9, 1, PERIOD);
  });

  it("AC3: a coordinator sees quantity and dates without the other event", async () => {
    const { event: _hidden, ...withoutEvent } = BASE.holders[0];
    vi.mocked(getEquipmentHolders).mockResolvedValue({ ...BASE, holders: [withoutEvent] });
    renderPanel();

    expect(await screen.findByText("Reserved by another event")).toBeInTheDocument();
    expect(screen.queryByText("Board Offsite")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("AC2: shows why stock is out of action and an unknown return date", async () => {
    vi.mocked(getEquipmentHolders).mockResolvedValue(BASE);
    renderPanel();

    expect(
      await screen.findByText(/1 under maintenance: Lamp replacement · return date not recorded/),
    ).toBeInTheDocument();
  });

  it("says when no other event holds it, and closes", async () => {
    vi.mocked(getEquipmentHolders).mockResolvedValue({ ...BASE, holders: [] });
    const onClose = renderPanel();

    expect(
      await screen.findByText("No other event has this equipment reserved for the period."),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });

  it("says so when the holders cannot be loaded", async () => {
    vi.mocked(getEquipmentHolders).mockRejectedValue(new Error("boom"));
    renderPanel();

    expect(await screen.findByRole("alert")).toHaveTextContent("We could not load");
  });
});
