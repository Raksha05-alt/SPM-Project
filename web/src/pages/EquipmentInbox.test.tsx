import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listEquipmentInbox } from "../api/equipment";
import type { TechnicalEvent } from "../types";
import { EquipmentInbox } from "./EquipmentInbox";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api/changeRequests", () => ({ listArrangementReviews: async () => [], decideArrangement: async () => ({}) }));
vi.mock("../api/equipment", () => ({ listEquipmentInbox: vi.fn() }));

const GALA: TechnicalEvent = {
  id: 9,
  name: "Annual Gala",
  status: "PLANNING",
  status_label: "Planning",
  preferred_start: "2027-03-01T02:00:00Z",
  preferred_end: "2027-03-01T04:00:00Z",
  expected_attendance: 60,
  coordinator_name: "Cora Coordinator",
  equipment_requests: [
    {
      id: 1,
      event: 9,
      equipment_type: 4,
      equipment_type_name: "Projector",
      quantity: 3,
      technical_requirements: "HDMI input",
      status: "REQUESTED",
      status_label: "Requested",
      requested_by_name: "Cora Coordinator",
      requested_at: "2026-11-01T01:00:00Z",
    },
    {
      id: 2,
      event: 9,
      equipment_type: 5,
      equipment_type_name: "Wireless microphone",
      quantity: 4,
      technical_requirements: "",
      status: "REQUESTED",
      status_label: "Requested",
      requested_by_name: "Cora Coordinator",
      requested_at: "2026-11-01T01:05:00Z",
    },
  ],
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <EquipmentInbox />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("EquipmentInbox (SCRUM-74 AC3)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows each event with every requested item, quantity and requirements", async () => {
    vi.mocked(listEquipmentInbox).mockResolvedValue([GALA]);
    renderPage();

    const event = await screen.findByRole("region", { name: "Annual Gala" });
    expect(event).toHaveTextContent("60 people");
    expect(event).toHaveTextContent("Coordinator: Cora Coordinator");
    const projector = within(event).getByRole("row", { name: /Projector/ });
    expect(projector).toHaveTextContent("3");
    expect(projector).toHaveTextContent("HDMI input");
    const microphone = within(event).getByRole("row", { name: /Wireless microphone/ });
    expect(microphone).toHaveTextContent("4");
    expect(microphone).toHaveTextContent("—");
  });

  it("has a clear empty state", async () => {
    vi.mocked(listEquipmentInbox).mockResolvedValue([]);
    renderPage();

    expect(
      await screen.findByText("No equipment has been requested for any event."),
    ).toBeInTheDocument();
  });

  it("says when the list could not be loaded", async () => {
    vi.mocked(listEquipmentInbox).mockRejectedValue(new Error("down"));
    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "We could not load the equipment requests.",
    );
  });
});
