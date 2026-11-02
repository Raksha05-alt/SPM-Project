import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { getEquipmentAvailability, listEquipmentInbox } from "../api/equipment";
import { fetchMyEvents } from "../api/events";
import type { EquipmentAvailability } from "../types";
import { EquipmentAvailabilityPage, toLocalInput } from "./EquipmentAvailability";

vi.mock("../api/equipment", () => ({
  getEquipmentAvailability: vi.fn(),
  listEquipmentInbox: vi.fn(),
}));
vi.mock("../api/events", () => ({ fetchMyEvents: vi.fn() }));
const auth = { user: { id: 2, role: "TECH_SUPPORT" } };
vi.mock("../auth/AuthContext", () => ({ useAuth: () => auth }));

const RESULT: EquipmentAvailability = {
  event: {
    id: 9,
    name: "Partner Summit",
    preferred_start: "2026-12-01T02:00:00Z",
    preferred_end: "2026-12-01T04:00:00Z",
  },
  period: { starts_at: "2026-12-01T02:00:00Z", ends_at: "2026-12-01T04:00:00Z" },
  equipment: [
    {
      equipment_type: 1,
      code: "PROJECTOR",
      name: "Projector",
      in_service: true,
      total_quantity: 10,
      unavailable_quantity: 2,
      unavailable: [
        {
          quantity: 1,
          cause: "DAMAGED",
          cause_label: "Damaged",
          reason: "Lens cracked",
          expected_return_at: null,
        },
        {
          quantity: 1,
          cause: "MAINTENANCE",
          cause_label: "Under maintenance",
          reason: "Lamp replacement",
          expected_return_at: "2026-12-20T01:00:00Z",
        },
      ],
      reserved_for_other_events: 5,
      reserved_for_this_event: 0,
      available_quantity: 3,
      requested_quantity: 4,
      shortfall: 1,
      status: "PARTIAL",
    },
    {
      equipment_type: 2,
      code: "MIC",
      name: "Microphone",
      in_service: true,
      total_quantity: 4,
      unavailable_quantity: 0,
      unavailable: [],
      reserved_for_other_events: 4,
      reserved_for_this_event: 2,
      available_quantity: 0,
      requested_quantity: null,
      shortfall: 0,
      status: "UNAVAILABLE",
    },
  ],
  shortfalls: [{ name: "Projector", requested: 4, short_by: 1 }],
};

function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/equipment/availability" element={<EquipmentAvailabilityPage />} />
          <Route path="/equipment/availability/:id" element={<EquipmentAvailabilityPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EquipmentAvailability (SCRUM-12)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    auth.user.role = "TECH_SUPPORT";
  });

  it("AC1: Technical Support choose an event from their inbox", async () => {
    const user = userEvent.setup();
    vi.mocked(listEquipmentInbox).mockResolvedValue([
      { id: 9, name: "Partner Summit" } as never,
    ]);
    vi.mocked(getEquipmentAvailability).mockResolvedValue(RESULT);
    renderAt("/equipment/availability");

    await user.selectOptions(await screen.findByLabelText("Event"), "9");

    expect(await screen.findByText("Partner Summit")).toBeInTheDocument();
    expect(getEquipmentAvailability).toHaveBeenCalledWith(9, undefined);
    expect(fetchMyEvents).not.toHaveBeenCalled();
  });

  it("AC1: a coordinator chooses from their own events", async () => {
    auth.user.role = "COORDINATOR";
    vi.mocked(fetchMyEvents).mockResolvedValue([{ id: 4, name: "Board offsite" } as never]);
    renderAt("/equipment/availability");

    expect(await screen.findByRole("option", { name: "Board offsite" })).toBeInTheDocument();
    expect(listEquipmentInbox).not.toHaveBeenCalled();
  });

  it("AC2-AC4: shows each type's available quantity and what is out of action", async () => {
    vi.mocked(getEquipmentAvailability).mockResolvedValue(RESULT);
    renderAt("/equipment/availability/9");

    const projector = await screen.findByRole("row", { name: "Projector" });
    const cells = within(projector).getAllByRole("cell").map((c) => c.textContent);
    expect(cells.slice(1, 5)).toEqual(["10", "2", "5", "3"]);
    expect(within(projector).getByText(/1 damaged: Lens cracked · return date not recorded/))
      .toBeInTheDocument();
    expect(within(projector).getByText(/1 under maintenance: Lamp replacement · expected back/))
      .toBeInTheDocument();

    const mic = screen.getByRole("row", { name: "Microphone" });
    expect(within(mic).getByText("Unavailable")).toBeInTheDocument();
    expect(within(mic).getByText("2 already reserved for this event")).toBeInTheDocument();
  });

  it("AC5: the shortfall is clearly indicated", async () => {
    vi.mocked(getEquipmentAvailability).mockResolvedValue(RESULT);
    renderAt("/equipment/availability/9");

    const shortfalls = await screen.findByRole("region", { name: "Shortfalls" });
    expect(shortfalls).toHaveTextContent("Projector: requested 4, short by 1");
    expect(
      within(screen.getByRole("row", { name: "Projector" })).getByText("Short by 1"),
    ).toBeInTheDocument();
  });

  it("AC1: checks a chosen period, sent as instants", async () => {
    const user = userEvent.setup();
    vi.mocked(getEquipmentAvailability).mockResolvedValue(RESULT);
    renderAt("/equipment/availability/9");
    const from = await screen.findByLabelText("From");
    expect(from).toHaveValue(toLocalInput(RESULT.period.starts_at));

    fireEvent.change(from, { target: { value: "2026-12-02T10:00" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-12-02T12:00" } });
    await user.click(screen.getByRole("button", { name: "Check availability" }));

    expect(getEquipmentAvailability).toHaveBeenLastCalledWith(9, {
      starts_at: new Date("2026-12-02T10:00").toISOString(),
      ends_at: new Date("2026-12-02T12:00").toISOString(),
    });
  });

  it("shows the API's reason when a period is refused", async () => {
    vi.mocked(getEquipmentAvailability).mockRejectedValue(
      new ApiError(400, { period: ["End must be after start."] }, "Bad request"),
    );
    renderAt("/equipment/availability/9");

    expect(await screen.findByRole("alert")).toHaveTextContent("End must be after start.");
  });

  it("AC6: a refusal is shown, with nothing else about the event", async () => {
    vi.mocked(getEquipmentAvailability).mockRejectedValue(
      new ApiError(403, { detail: "Only Technical Support or the event's coordinator can check its equipment." }, "Only Technical Support or the event's coordinator can check its equipment."),
    );
    renderAt("/equipment/availability/9");

    expect(await screen.findByRole("alert")).toHaveTextContent("Only Technical Support");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
